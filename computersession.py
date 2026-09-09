"""Task-owned stdio browser session and durable, lineage-bound action state.

The server is owner-reviewed executable code, not a network containment layer.
Acknowledged input remains DISPATCHED until scoped evidence or finalization.
"""
import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
import time
from contextlib import nullcontext

import computeruse as C
import fileauth
import locks
import mcp
import computerprocess

TERMINAL = frozenset({'VERIFIED','REFUSED','FAILED_WITH_KNOWN_NO_EFFECT','UNKNOWN'})

def _digest(value):
    return hashlib.sha256(C._canonical(value)).hexdigest()

def _artifact_anchor(path):
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_CLOEXEC',0)
    if os.name!='nt':
        return os.open(path,flags|getattr(os,'O_NOFOLLOW',0))
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    create=kernel32.CreateFileW
    create.argtypes=(wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                     wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,
                     wintypes.HANDLE)
    create.restype=wintypes.HANDLE
    close=kernel32.CloseHandle
    close.argtypes=(wintypes.HANDLE,)
    close.restype=wintypes.BOOL
    full=os.path.abspath(path)
    if not full.startswith('\\\\?\\'):
        full='\\\\?\\UNC\\'+full[2:] if full.startswith('\\\\') else '\\\\?\\'+full
    handle=create(full,0x80000000,0x00000001,None,3,0x00200000,None)
    if handle==wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(
            handle,flags|getattr(os,'O_NOINHERIT',0))
    except BaseException:
        close(handle)
        raise

def _read_bounded(fd,limit):
    chunks=[]
    while limit:
        chunk=os.read(fd,limit)
        if not chunk:
            break
        chunks.append(chunk)
        limit-=len(chunk)
    return b''.join(chunks)

class ComputerSession:
    def __init__(self, root, task, server_name, policy_revision):
        self.root = os.path.abspath(root)
        self.task = task
        self.task_id = str(task['id'])
        self.lineage = str(task.get('lineage') or self.task_id)
        self.role = task['role']
        self.server_name = server_name
        self.policy_revision = policy_revision
        self.state = 'created'
        self.server = None
        self.epoch = secrets.token_hex(16)
        self._key = secrets.token_bytes(32)
        self._serial = threading.RLock()
        self._lease = None
        self._spec = self._configuration()
        self._spec_digest = _digest(self._spec)
        self.origin = C._origin(self._spec['computer_policy']['allowed_origin'], configured=True)
        self.authority = C.BrowserAuthority(self.origin, session_id=self.epoch)
        self._context = {'task_id':self.task_id, 'lineage':self.lineage}
        self._rel = 'effects/computer/'+_digest([self.lineage,server_name])+'.json'
        self._owner_rel='effects/computer/server-'+_digest(server_name)+'.json'
        path = fileauth.resolve(self.root, self._rel, 'write', 'harness')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lease_rel = 'effects/computer/'+_digest(server_name)+'.lease'
        self._lease_path = fileauth.resolve(self.root,lease_rel,'write','harness')
        self._lease = locks.advisory_holding(self._lease_path,timeout=0)
        try:
            self._lease.__enter__()
        except TimeoutError as error:
            self._lease = None
            raise C.Refused('browser session lease belongs to another task') from error
        try:
            self._recover()
        except BaseException:
            # No usable instance escapes construction. Durable quarantine,
            # not an in-memory context manager, must exclude later lineages.
            self.state='tainted'
            self._lease.__exit__(None,None,None); self._lease=None
            raise

    def _configuration(self):
        servers,source=mcp.config_snapshot(self.root)
        if hasattr(self,'_source') and source!=self._source:
            raise C.Refused('owner MCP configuration source changed')
        self._source=source
        spec = servers.get(self.server_name)
        if not isinstance(spec,dict) or not mcp._role_allowed(spec,self.role):
            raise C.Refused('owner server is missing or role is denied')
        policy = spec.get('computer_policy')
        if (not isinstance(policy,dict) or set(policy)!={'revision','allowed_origin'}
                or not isinstance(policy['revision'],str) or not policy['revision']
                or policy['revision']!=self.policy_revision):
            raise C.Refused('owner computer policy revision is missing or changed')
        C._origin(policy['allowed_origin'],configured=True)
        C._locator_opt_in(spec)
        if spec.get('atomic_browser_adapter') is not True:
            raise C.Refused('owner bounded adapter opt-in required')
        try: mcp.validate_identity(spec)
        except ValueError as error: raise C.Refused(str(error)) from error
        # This increment cannot establish ownership of an attached browser or
        # persistent external profile. Such servers need a later lease contract.
        arguments = [str(a).lower() for a in spec.get('args',[])]
        external = ('--cdp-endpoint','--endpoint','--user-data-dir','--extension',
                    '--connect','--browser-endpoint','--storage-state')
        if any(a==flag or a.startswith(flag+'=') for a in arguments for flag in external):
            raise C.Refused('attached browsers and persistent external profiles are unsupported')
        if any('playwright' in a for a in arguments) and not any('--isolated' in a.split() for a in arguments):
            raise C.Refused('task-owned Playwright requires an isolated browser profile')
        computerprocess.validate_configuration(spec)
        return spec

    def _boundary(self, mutation=False):
        if self.state in ('closed','closing','tainted'):
            raise C.Refused('computer session is '+self.state)
        if (str(self.task.get('id'))!=self.task_id or self.task.get('role')!=self.role
                or str(self.task.get('lineage') or self.task_id)!=self.lineage):
            self.close('task ownership changed')
            raise C.Refused('computer task ownership changed')
        # A queued task cancellation may arrive while a model call is in flight.
        path = fileauth.resolve(self.root,'state.json','read','harness')
        if os.path.exists(path):
            with open(path,encoding='utf-8-sig') as f: state=json.load(f)
            found = next((t for t in state.get('tasks',[]) if t.get('id')==self.task_id),None)
            if found and found.get('status') in ('cancelled','canceled','done','failed'):
                self.close('external task '+found['status'])
                raise C.Refused('task is externally terminal')
        if self.task.get('status') in ('cancelled','canceled','done','failed'):
            self.close('task terminal')
            raise C.Refused('task is terminal')
        try:
            if _digest(self._configuration())!=self._spec_digest:
                raise C.Refused('owner computer policy changed')
        except (ValueError,OSError) as error:
            self.close('owner policy revoked')
            raise C.Refused('owner computer policy revoked or changed') from error
        if self.server is not None and (self.server.proc.poll() is not None or self.server._terminal_error):
            self.close('browser died')
            raise C.Unresolved('browser connection died')
        if mutation and any(a['state']=='UNKNOWN' and not self._resolved(a) for a in self.actions()):
            raise C.Refused('UNKNOWN action in task lineage requires owner reconciliation')

    def _load(self):
        path = fileauth.resolve(self.root,self._rel,'read','harness')
        if not os.path.exists(path): return {'actions':[]}
        with open(path,encoding='utf-8') as f: data=json.load(f)
        if not isinstance(data,dict) or not isinstance(data.get('actions'),list):
            raise C.Refused('invalid computer action ledger')
        return data

    def _save(self,data):
        # File Authority writes unique temp, flushes/fsyncs, then atomically replaces.
        fileauth.write_json(self.root,self._rel,data,actor='harness',durable=True)

    def actions(self):
        with self._serial: return self._load()['actions']

    @staticmethod
    def _resolved(action):
        return bool(action.get('reconciliations'))

    def _recover(self):
        owner_path=fileauth.resolve(self.root,self._owner_rel,'read','harness')
        if os.path.exists(owner_path):
            owner=computerprocess.read(self.root,self._owner_rel)
        else:
            # Pre-server-record runtime state cannot safely be assigned to a
            # different lineage. Do not guess who owns legacy environments.
            directory=os.path.dirname(owner_path)
            owners=[]; legacy=[]
            for name in os.listdir(directory):
                if not name.endswith('.json') or name.startswith('process-'): continue
                record=computerprocess.read(self.root,'effects/computer/'+name)
                (owners if name.startswith('server-') else legacy).append(record)
            bound={o.get('environment') for o in owners}
            unbound=any(x.get('environment') and x['environment'] not in bound for x in legacy
                        if x.get('environment') and computerprocess.read(self.root,x['environment']).get('state')!='closed')
            owner={'server':self.server_name,'state':'quarantined' if unbound else 'closed',
                   'environment':None,'ledger':self._rel,'unattributed':unbound}
            self._save_owner(owner)
        if owner.get('server')!=self.server_name or owner.get('unattributed'):
            raise C.Refused('server ownership unavailable; independent owner cleanup required')
        environment=owner.get('environment')
        if environment:
            try:
                computerprocess.cleanup(self.root,environment)
                self._terminalize(owner['ledger'])
            except BaseException as error:
                self._quarantine(error)
                raise
            owner.update(state='closed',environment=None)
            self._save_owner(owner)
        self._terminalize(self._rel)

    def _save_owner(self,owner):
        fileauth.write_json(self.root,self._owner_rel,owner,actor='harness',durable=True)

    def _quarantine(self,original):
        try:
            owner=computerprocess.read(self.root,self._owner_rel)
            owner['state']='quarantined'; self._save_owner(owner)
        except BaseException as persistence_error:
            # The pre-spawn durable environment still requires cleanup for
            # every claimant. Preserve system interruption even if disk fails.
            original.add_note('Quarantine refresh failed: '+type(persistence_error).__name__)

    def _terminalize(self,relative):
        if not relative.startswith('effects/computer/') or not relative.endswith('.json'):
            raise C.Refused('invalid owned action ledger')
        path=fileauth.resolve(self.root,relative,'read','harness')
        if not os.path.exists(path): return
        data=computerprocess.read(self.root,relative)
        for action in data['actions']:
            if action['state']=='PREPARED':
                action.update(state='FAILED_WITH_KNOWN_NO_EFFECT',reason='owner terminated before dispatch')
            elif action['state']=='DISPATCHED':
                action.update(state='UNKNOWN',reason='owner terminated before independent verification')
        fileauth.write_json(self.root,relative,data,actor='harness',durable=True)

    def _prepare(self, operation, intent):
        self._boundary(mutation=True)
        data=self._load(); key=_digest([self.lineage,self.server_name,operation,intent])
        for action in data['actions']:
            if action['intent_key']==key and action['state'] not in ('REFUSED','FAILED_WITH_KNOWN_NO_EFFECT','VERIFIED'):
                resolution=(action.get('reconciliations') or [{}])[-1]
                if resolution.get('decision') not in ('authorize_retry','confirmed_no_effect'):
                    raise C.Refused('same computer intent already dispatched; do not retry')
        action={'id':secrets.token_hex(16),'intent_key':key,'operation':operation,
                'intent':intent,'task':self.task_id,'lineage':self.lineage,
                'epoch':self.epoch,'state':'PREPARED','prepared_at':time.time(),
                'dispatch_acknowledged':False,'workflow_verified':False}
        data['actions'].append(action); self._save(data)
        return action['id']

    def _update(self,identity,**fields):
        data=self._load(); action=next(a for a in data['actions'] if a['id']==identity)
        if action['state'] in TERMINAL:
            raise C.Refused('terminal computer action is immutable')
        action.update(fields); self._save(data)

    def _dispatch(self,identity):
        self._boundary(mutation=True)
        self._update(identity,state='DISPATCHED',dispatched_at=time.time())

    def _failure(self,identity,error):
        action=next(a for a in self.actions() if a['id']==identity)
        if action['state'] in TERMINAL:
            return
        if isinstance(error,C.Refused) and (action['state']=='PREPARED' or
                (action['operation']=='click' and not action['dispatch_acknowledged'])): terminal='REFUSED'
        elif action['state']=='PREPARED': terminal='FAILED_WITH_KNOWN_NO_EFFECT'
        else: terminal='UNKNOWN'
        self._update(identity,state=terminal,reason=str(error)[:300])
        if terminal=='UNKNOWN':
            self.state='tainted'
            if self.server is not None: self.server.close()

    def _connect(self):
        if self.server is None:
            environment='effects/computer/process-'+self.epoch+'.json'
            fileauth.write_json(self.root,environment,{'state':'created','token':self.epoch,
                'job':'Local\\agent-computer-'+self.epoch},actor='harness')
            self._save_owner({'server':self.server_name,'state':'owned','environment':environment,
                              'ledger':self._rel,'task':self.task_id,'lineage':self.lineage,'epoch':self.epoch})
            data=self._load(); data['environment']=environment; self._save(data)
            try:
                self.server=mcp.connect(self.root,self.server_name,role=self.role,
                                        owned_process=(self.root,environment))
            except BaseException as error:
                self.state='tainted'
                self._quarantine(error)
                raise
            self.state='active'

    def _seal(self,state,artifacts=None):
        raw=state.get('view_context') or {}
        viewport=raw.get('viewport'); scale=raw.get('device_scale')
        if viewport is not None and (not isinstance(viewport,dict) or set(viewport)!={'width','height'}
                or any(type(x) is not int or x<=0 for x in viewport.values())
                or raw.get('viewport_source')!='playwright_host'):
            raise C.Refused('invalid host viewport observation')
        if scale is not None and (type(scale) not in (int,float) or not C.math.isfinite(scale)
                or scale<=0 or raw.get('device_scale_source')!='page_untrusted'):
            raise C.Refused('invalid untrusted scale observation')
        view={'viewport':viewport,'viewport_source':'playwright_host' if viewport else 'unavailable',
              'device_scale':scale,'device_scale_source':'page_untrusted' if scale else 'unavailable',
              'coordinate_mode':'css_locator','screenshot_coordinates_authorized':False}
        receipt=self.authority.observe({k:v for k,v in state.items() if k!='view_context'})
        envelope={'task':self.task_id,'epoch':self.epoch,'policy_revision':self.policy_revision,
                  'observation':receipt,'artifacts':artifacts or [],'view_context':view}
        envelope['mac']=hmac.new(self._key,C._canonical(envelope),hashlib.sha256).hexdigest()
        # State is also supplied at top level for typed-tool consumers.
        return dict(envelope,state=receipt['state'])

    def _unseal(self,receipt):
        if not isinstance(receipt,dict) or set(receipt)!={'task','epoch','policy_revision','observation','artifacts','view_context','mac','state'}:
            raise C.Refused('invalid task observation receipt')
        body={k:v for k,v in receipt.items() if k not in ('mac','state')}
        signature=hmac.new(self._key,C._canonical(body),hashlib.sha256).hexdigest()
        if (not isinstance(receipt['mac'],str) or not hmac.compare_digest(signature,receipt['mac'])
                or receipt['task']!=self.task_id or receipt['epoch']!=self.epoch
                or receipt['policy_revision']!=self.policy_revision
                or receipt['state']!=receipt['observation']['state']):
            raise C.Refused('foreign, expired epoch or tampered task receipt')
        for artifact in receipt['artifacts']: self._artifact(artifact)
        return receipt['observation']

    def _artifact(self,meta,allow_zones=None):
        try:
            return self._artifact_checked(meta,allow_zones=allow_zones)
        except C.Refused:
            raise
        except (fileauth.Denied,OSError,ValueError) as error:
            raise C.Refused('artifact secure read refused') from error

    def _artifact_checked(self,meta,allow_zones=None):
        path=fileauth.resolve(self.root,meta['path'],'read','harness',
                              allow_zones=allow_zones)
        anchor_fd=_artifact_anchor(path)
        try:
            anchor=os.fstat(anchor_fd)
            before=C._no_links(path)
            if ((before.st_dev,before.st_ino)!=(anchor.st_dev,anchor.st_ino)
                    or not stat.S_ISREG(anchor.st_mode) or anchor.st_nlink!=1
                    or getattr(anchor,'st_file_attributes',0)
                       & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0)):
                raise C.Refused('artifact identity changed before read')
            if anchor.st_size!=meta['bytes']:
                raise C.Refused('artifact size changed')
            raw=_read_bounded(anchor_fd,meta['bytes']+1)
            if hashlib.sha256(raw).hexdigest()!=meta['sha256']:
                raise C.Refused('artifact bytes changed')
            if fileauth.resolve(self.root,meta['path'],'read','harness',
                                allow_zones=allow_zones)!=path:
                raise C.Refused('artifact path changed')
            after=C._no_links(path)
            if (after.st_dev,after.st_ino)!=(anchor.st_dev,anchor.st_ino):
                raise C.Refused('artifact path changed')
            anchor_after=os.fstat(anchor_fd)
            if ((anchor_after.st_dev,anchor_after.st_ino)!=(anchor.st_dev,anchor.st_ino)
                    or not stat.S_ISREG(anchor_after.st_mode)
                    or anchor_after.st_nlink!=1
                    or anchor_after.st_size!=meta['bytes']
                    or getattr(anchor_after,'st_file_attributes',0)
                       & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0)):
                raise C.Refused('artifact identity or size changed after read')
            return raw
        finally:
            os.close(anchor_fd)

    def open(self,url):
        with self._serial:
            self._boundary(mutation=True)
            if C._origin(url)!=self.origin: raise C.Refused('navigation origin denied')
            self._connect()
            identity=self._prepare('open',{'url':url})
            try:
                result,how=mcp.computer_guarded_call(self.server,'browser_navigate',{'url':url},
                    root=self.root,fresh=True,task_context=self._context,before_send=lambda:self._dispatch(identity))
                if how in ('denied','approval_required'): raise C.Refused('navigation '+how)
                if how!='live' or result.get('isError'): raise C.Unresolved('navigation outcome unknown')
                receipt=self.observe()
                if receipt['state']['url']!=url: raise C.Unresolved('navigation URL not confirmed')
                self._update(identity,state='VERIFIED',dispatch_acknowledged=True,
                             verification_scope='navigation_url',verifier_kind='fresh_observation')
                return {'status':'VERIFIED','verification_scope':'navigation_url',
                        'workflow_verified':False,'action_id':identity,'observation':receipt}
            except Exception as error:
                self._failure(identity,error); raise

    def observe(self):
        with self._serial:
            self._boundary(); self._connect()
            artifacts=[]
            try:
                state=C.playwright_observe(self.server,self.root,task_context=self._context,artifacts=artifacts)
                for artifact in artifacts: self._artifact(artifact)
                return self._seal(state,artifacts)
            except C.Unresolved:
                self.state='tainted'; self.server.close(); raise

    def click(self,receipt,target_id):
        with self._serial:
            self._boundary(mutation=True)
            observation=self._unseal(receipt)
            links=[x for x in observation['state']['links'] if x['id']==target_id]
            if len(links)!=1: raise C.Refused('target absent')
            identity=self._prepare('click',{'page':observation['state']['url'],
                                          'target_id':target_id,'href':links[0]['href']})
            artifacts=[]
            post_view=[]
            def dispatch(p):
                answer=C.playwright_atomic_click(self.server,self.root,dict(p,view_context=receipt['view_context']),
                    task_context=self._context,before_send=lambda:self._dispatch(identity),artifacts=artifacts)
                post_view.append(answer.get('post_observation',{}).pop('view_context',None))
                return answer
            try:
                result=self.authority.execute_click(observation,target_id,
                    observation['observed_at']+self.authority.max_age,
                    dispatch)
                self._update(identity,dispatch_acknowledged=True)
                for artifact in artifacts: self._artifact(artifact)
                post=dict(result['post_observation'],view_context=post_view[-1])
                result.update(action_id=identity,dispatch_acknowledged=True,
                              observation=self._seal(post,artifacts))
                return result
            except Exception as error:
                self._failure(identity,error); raise

    def close(self,reason):
        with self._serial:
            if self.state=='closed': return
            self.state='closing'
            try:
                if self.server is not None: self.server.close()
                if self._lease is not None: self._recover()
            except BaseException as error:
                self.state='tainted'
                self._quarantine(error)
                raise
            else:
                if self._lease is not None:
                    self._lease.__exit__(None,None,None); self._lease=None
                self.state='closed'

    def reconcile(self,action_id,decision,scope,evidence):
        """Owner attestation only; never a model tool or automatic verifier."""
        import controlplane
        controlplane.owner_only('reconcile computer action')
        if decision not in ('confirmed_effect','confirmed_no_effect','authorize_retry'):
            raise C.Refused('unknown owner reconciliation decision')
        if not isinstance(scope,str) or not scope.strip():
            raise C.Refused('owner reconciliation requires explicit scope')
        if (not isinstance(evidence,dict) or set(evidence)!={'path','sha256','bytes'}
                or not isinstance(evidence['path'],str)
                or not isinstance(evidence['bytes'],int) or isinstance(evidence['bytes'],bool)
                or not 0 < evidence['bytes'] <= 25_000_000):
            raise C.Refused('owner evidence requires bounded path, digest and byte count')
        with self._serial, (nullcontext() if self._lease is not None else
                           locks.advisory_holding(self._lease_path,timeout=0)):
            try:
                fileauth.resolve(
                    self.root,evidence['path'],'read','harness',
                    allow_zones={fileauth.ZONE_CONTROL,fileauth.ZONE_RUNTIME})
                self._artifact(evidence,allow_zones={
                    fileauth.ZONE_CONTROL,fileauth.ZONE_RUNTIME})
            except fileauth.Denied as error:
                raise C.Refused(
                    'owner evidence must be CONTROL or RUNTIME, not worker output alone') from error
            data=self._load()
            action=next((a for a in data['actions'] if a['id']==action_id),None)
            if action is None or action['state'] not in ('DISPATCHED','UNKNOWN'):
                raise C.Refused('action is not pending reconciliation')
            action.setdefault('reconciliations',[]).append({
                'decision':decision,'scope':scope,'evidence':dict(evidence),
                'verifier_kind':'owner_attestation','recorded_at':time.time(),
                'workflow_verified':False})
            self._save(data)
            return action['reconciliations'][-1]
