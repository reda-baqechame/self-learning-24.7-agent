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
import computerverify

TERMINAL = frozenset({'VERIFIED','REFUSED','FAILED_WITH_KNOWN_NO_EFFECT',
                      'FAILED_POSTCONDITION','UNKNOWN'})

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
        self._index_lease = None
        self._output_leases = {}
        self._output_claims = {}
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
            self._index_lease=locks.advisory_holding(
                computerverify.index_lease_path(self.root,self.lineage),timeout=0)
            self._index_lease.__enter__()
            self._register_ledger()
            self._recover()
        except BaseException:
            # No usable instance escapes construction. Durable quarantine,
            # not an in-memory context manager, must exclude later lineages.
            self.state='tainted'
            if self._index_lease is not None:
                self._index_lease.__exit__(None,None,None); self._index_lease=None
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
        binding={'lineage':self.lineage,'server':self.server_name}
        if not os.path.exists(path):
            return {'binding':binding,'actions':[],'workflows':[],
                    'next_environment_incarnation':0}
        with open(path,encoding='utf-8') as f: data=json.load(f)
        if not isinstance(data,dict) or not isinstance(data.get('actions'),list):
            raise C.Refused('invalid computer action ledger')
        stored=data.get('binding')
        if stored is None:
            if any(str(action.get('task'))!=self.task_id
                   or str(action.get('lineage'))!=self.lineage
                   for action in data['actions'] if isinstance(action,dict)):
                raise C.Refused('legacy computer action ledger binding differs')
            data['binding']=binding
        elif stored!=binding:
            raise C.Refused('computer action ledger binding differs')
        data.setdefault('workflows',[])
        data.setdefault('next_environment_incarnation',0)
        if (not isinstance(data['workflows'],list)
                or type(data['next_environment_incarnation']) is not int
                or data['next_environment_incarnation']<0):
            raise C.Refused('invalid computer workflow ledger')
        return data

    def _save(self,data):
        # File Authority writes unique temp, flushes/fsyncs, then atomically replaces.
        fileauth.write_json(self.root,self._rel,data,actor='harness',durable=True)

    def _index(self):
        path=computerverify.index_path(self.root,self.lineage)
        if not os.path.exists(path):
            return {'schema':computerverify.INDEX_SCHEMA,'state':'COMMITTED',
                    'first_task':self.task_id,'lineage':self.lineage,'revision':0,
                    'ledgers':{},'workflows':{}}
        return computerprocess.read(self.root,computerverify.index_rel(self.lineage))

    def _save_index(self,value):
        fileauth.write_json(self.root,computerverify.index_rel(self.lineage),
                            value,actor='harness',durable=True)

    def _recover_index(self,index):
        if index.get('state')!='PREPARED': return index
        pending=index.get('pending') or {}
        try:
            ledger=computerprocess.read(self.root,pending['ledger'])
            if pending['kind']=='register':
                if ledger.get('binding')!=pending['binding']: raise ValueError
                index['ledgers'][pending['ledger']]=pending['binding']
            elif pending['kind']=='workflow':
                rows=[w for w in ledger.get('workflows',[])
                      if w.get('id')==pending['workflow_id']
                      and w.get('contract_sha256')==pending['contract_sha256']]
                if len(rows)!=1: raise ValueError
                index['workflows'][pending['workflow_id']]={
                    'ledger':pending['ledger'],
                    'contract_sha256':pending['contract_sha256']}
            else: raise ValueError
        except (KeyError,ValueError,OSError,TypeError):
            index['state']='ABORTED'; index['abort_reason']='incomplete index transaction'
            index.pop('pending',None); self._save_index(index)
            raise C.Refused('computer lineage index transaction is incomplete')
        index['state']='COMMITTED'; index.pop('pending',None); self._save_index(index)
        return index

    def _register_ledger(self):
        index=self._index()
        if (not isinstance(index,dict) or index.get('schema')!=computerverify.INDEX_SCHEMA
                or index.get('lineage')!=self.lineage
                or index.get('state')=='ABORTED'):
            raise C.Refused('computer lineage index binding is unavailable')
        index=self._recover_index(index)
        if index.get('state')!='COMMITTED' or not isinstance(index.get('ledgers'),dict) \
                or not isinstance(index.get('workflows'),dict):
            raise C.Refused('computer lineage index is malformed')
        binding={'lineage':self.lineage,'server':self.server_name}
        if index['ledgers'].get(self._rel)==binding:
            self._save(self._load())
            return
        if self._rel in index['ledgers']:
            raise C.Refused('computer lineage ledger registration differs')
        prepared=dict(index,state='PREPARED',revision=int(index.get('revision',0))+1,
                      pending={'kind':'register','ledger':self._rel,'binding':binding})
        self._save_index(prepared)
        self._save(self._load())
        prepared['ledgers']=dict(prepared['ledgers'],**{self._rel:binding})
        prepared['state']='COMMITTED'; prepared.pop('pending',None)
        self._save_index(prepared)

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
                self._terminalize(owner['ledger'],environment)
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

    def _cleanup_receipt(self,environment):
        metadata=computerprocess.read(self.root,environment)
        if metadata.get('state')!='closed':
            raise C.Refused('owned environment closure is unconfirmed')
        return {'environment':environment,'state':'closed',
                'metadata_sha256':_digest(metadata),'confirmed_at':time.time()}

    def _terminalize(self,relative,environment=None):
        if not relative.startswith('effects/computer/') or not relative.endswith('.json'):
            raise C.Refused('invalid owned action ledger')
        path=fileauth.resolve(self.root,relative,'read','harness')
        if not os.path.exists(path): return
        data=computerprocess.read(self.root,relative)
        cleanup=self._cleanup_receipt(environment) if environment else None
        for action in data['actions']:
            if action['state']=='PREPARED':
                action.update(state='FAILED_WITH_KNOWN_NO_EFFECT',reason='owner terminated before dispatch')
            elif action['state']=='DISPATCHED':
                action.update(state='UNKNOWN',reason='owner terminated before independent verification')
                if cleanup is not None and action.get('environment')==environment:
                    action['cleanup_receipt']=cleanup
        fileauth.write_json(self.root,relative,data,actor='harness',durable=True)

    def _prepare(self, operation, intent, workflow_id=None):
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
        if workflow_id is not None:
            workflows=[w for w in data['workflows'] if w.get('id')==workflow_id]
            if len(workflows)!=1: raise C.Refused('frozen invoice workflow is unavailable')
            workflow=workflows[0]; contract=computerverify.validate_contract(workflow['contract'])
            position=len(workflow.get('action_ids') or [])
            if position>=len(contract['intents']):
                raise C.Refused('frozen invoice workflow has no remaining intent')
            expected=contract['intents'][position]
            if (operation!='click' or intent.get('target_id')!=expected['target_id']
                    or intent.get('href')!=expected['destination']):
                raise C.Refused('click differs from next frozen invoice intent')
            prior=[]
            for identity in workflow.get('action_ids') or []:
                item=next((d for d in data['actions'] if d.get('id')==identity),None)
                if item is None: raise C.Refused('invoice workflow action history is missing')
                prior.append(item)
            if any(computerverify.effective_action_status(self.root,item,workflow,contract)
                   not in ('VERIFIED','VERIFIED_BY_POSTCONDITION') for item in prior):
                raise C.Refused('prior invoice action lacks independent verification')
            action.update(workflow_id=workflow_id,
                          contract_sha256=workflow['contract_sha256'],
                          intent_index=position,required_for_task=True)
        data['actions'].append(action); self._save(data)
        return action['id']

    def _hold_output_path(self,output_dir,claimant):
        binding=computerverify.output_binding(self.root,output_dir)
        key=computerverify.output_lease_rel(binding)
        owner=self._output_claims.get(key)
        if owner is not None and owner!=claimant:
            raise C.Refused('invoice output authority belongs to another workflow')
        if key not in self._output_leases:
            path=fileauth.resolve(self.root,key,'write','harness')
            context=locks.advisory_holding(path,timeout=0)
            try: context.__enter__()
            except TimeoutError as error:
                raise C.Refused('invoice output authority belongs to another workflow') from error
            self._output_leases[key]=context
        self._output_claims[key]=claimant
        return binding,key

    def _hold_output_lease(self,contract,workflow_id):
        binding,key=self._hold_output_path(contract['output_dir'],workflow_id)
        if binding!=contract['output_identity'] or key!=contract['output_lease']:
            raise C.Refused('invoice output authority identity changed')
        if not computerverify.output_claim_matches(
                self.root,binding,workflow_id,computerverify.canonical_digest(contract),self._rel):
            raise C.Refused('durable invoice output claim differs')

    def freeze_invoice_workflow(self,output_dir,manifest,expectation_source,
                                account,intents,deadline_seconds=30):
        """Trusted controller API. It is deliberately absent from model tools."""
        with self._serial:
            self._boundary(mutation=True)
            for intent in intents if isinstance(intents,list) else []:
                if C._origin(intent.get('destination'))!=self.origin:
                    raise C.Refused('frozen invoice destination origin denied')
            output_binding=computerverify.output_binding(self.root,output_dir)
            output_key=computerverify.output_lease_rel(output_binding)
            if output_key in self._output_claims:
                raise C.Refused('invoice output authority already belongs to another workflow')
            already_held=output_key in self._output_leases
            held_binding,held_key=self._hold_output_path(output_dir,'FREEZE_PENDING')
            prior_claim=computerverify.recover_output_claim(self.root,held_binding)
            if prior_claim is not None and prior_claim['state']!='ABORTED':
                context=self._output_leases.pop(output_key,None)
                self._output_claims.pop(output_key,None)
                if context is not None: context.__exit__(None,None,None)
                raise C.Refused('invoice output authority has a durable workflow claim')
            try:
                contract=computerverify.build_contract(
                    self.root,self.task_id,self.lineage,self.epoch,
                    self.policy_revision,self.server_name,self.origin,output_dir,
                    manifest,expectation_source,account,intents,deadline_seconds,
                    expected_output_binding=held_binding)
            except BaseException:
                if not already_held:
                    context=self._output_leases.pop(output_key,None)
                    if context is not None: context.__exit__(None,None,None)
                self._output_claims.pop(output_key,None)
                raise
            digest=computerverify.canonical_digest(contract)
            workflow_id=digest[:32]
            claim={'schema':computerverify.CLAIM_SCHEMA,'state':'PREPARED',
                   'output_identity':held_binding,'workflow_id':workflow_id,
                   'contract_sha256':digest,'ledger':self._rel,
                   'task':self.task_id,'lineage':self.lineage,'server':self.server_name,
                   'revision':(prior_claim['revision']+1 if prior_claim else 1),
                   'prior_claim_sha256':(computerverify.canonical_digest(prior_claim)
                                         if prior_claim else None)}
            computerverify.write_output_claim(self.root,claim)
            data=self._load()
            existing=[w for w in data['workflows'] if w.get('id')==workflow_id]
            if existing:
                if len(existing)!=1 or existing[0].get('contract_sha256')!=digest:
                    raise C.Refused('invoice workflow identity collision')
                return {'workflow_id':workflow_id,'contract_sha256':digest}
            index=self._recover_index(self._index())
            if index.get('state')!='COMMITTED' or index['ledgers'].get(self._rel)!=data['binding']:
                raise C.Refused('computer lineage index is not committed')
            prepared=dict(index,state='PREPARED',revision=int(index.get('revision',0))+1,
                          pending={'kind':'workflow','ledger':self._rel,
                                   'workflow_id':workflow_id,
                                   'contract_sha256':digest})
            self._save_index(prepared)
            data['workflows'].append({'id':workflow_id,'contract_sha256':digest,
                                      'contract':contract,'action_ids':[],
                                      'verification_attempts':[]})
            self._save(data)
            prepared['workflows']=dict(prepared['workflows'])
            prepared['workflows'][workflow_id]={'ledger':self._rel,
                                                 'contract_sha256':digest}
            prepared['state']='COMMITTED'; prepared.pop('pending',None)
            self._save_index(prepared)
            computerverify.commit_output_claim(self.root,claim)
            self._output_claims[output_key]=workflow_id
            return {'workflow_id':workflow_id,'contract_sha256':digest}

    def verify_invoice_action(self,action_id,workflow_id):
        """Quiesce executor and independently terminalize one frozen intent."""
        with self._serial:
            self._boundary()
            data=self._load()
            workflows=[w for w in data['workflows'] if w.get('id')==workflow_id]
            action=next((a for a in data['actions'] if a.get('id')==action_id),None)
            if len(workflows)!=1 or action is None or action.get('workflow_id')!=workflow_id:
                raise C.Refused('invoice action/workflow binding is unavailable')
            workflow=workflows[0]
            contract=computerverify.validate_contract(workflow['contract'])
            if (computerverify.canonical_digest(contract)!=workflow['contract_sha256']
                    or action.get('contract_sha256')!=workflow['contract_sha256']):
                raise C.Refused('invoice action contract binding changed')
            effective=computerverify.effective_action_status(self.root,action,workflow,contract)
            if effective in ('VERIFIED','VERIFIED_BY_POSTCONDITION'):
                if effective=='VERIFIED': return action['postcondition_receipt']
                return action['postcondition_resolutions'][-1]['receipt']
            if action.get('state') in ('VERIFIED','UNKNOWN') and \
                    (action.get('postcondition_receipt') or action.get('postcondition_resolutions')):
                raise C.Refused('stored independent postcondition receipt is invalid')
            if action.get('state')=='DISPATCHED':
                self._quiesce(action_id); data=self._load()
                workflow=next(w for w in data['workflows'] if w['id']==workflow_id)
                action=next(a for a in data['actions'] if a['id']==action_id)
            elif action.get('state')!='UNKNOWN':
                raise C.Refused('invoice action is not pending independent verification')
            if not isinstance(action.get('cleanup_receipt'),dict):
                raise C.Refused('owned environment cleanup receipt is unavailable')
            self._hold_output_lease(contract,workflow_id)
            attempts=action.setdefault('verification_attempts',[])
            for attempt in attempts:
                if attempt.get('result')=='STARTED':
                    attempt.update(result='INTERRUPTED',finished_at=time.time(),
                                   reason='incomplete prior verification attempt')
            sequence=len(attempts)+1
            started={'sequence':sequence,'result':'STARTED','started_at':time.time(),
                     'deadline_at':contract['deadline_at'],'verifier':dict(computerverify.VERIFIER),
                     'action_id':action_id,'workflow_id':workflow_id,
                     'contract_sha256':workflow['contract_sha256']}
            attempts.append(started); self._save(data)
            try:
                readbacks=computerverify.verify_prefix(
                    self.root,contract,action['intent_index']+1)
            except BaseException as error:
                data=self._load(); current=next(a for a in data['actions'] if a['id']==action_id)
                attempt=current['verification_attempts'][-1]
                attempt.update(result=('INTERRUPTED' if isinstance(error,(KeyboardInterrupt,SystemExit))
                                       else 'REFUSED' if isinstance(error,computerverify.PredicateMismatch)
                                       else 'UNAVAILABLE'),
                               finished_at=time.time(),reason=str(error)[:300])
                if isinstance(error,computerverify.PredicateMismatch) \
                        and current.get('state')=='DISPATCHED':
                    current.update(state='FAILED_POSTCONDITION',
                                   reason=str(error)[:300],
                                   verification_scope='invoice_exact_prefix',
                                   workflow_verified=False)
                self._save(data)
                if isinstance(error,(KeyboardInterrupt,SystemExit)): raise
                if isinstance(error,C.Refused): raise
                raise C.Refused('independent invoice verifier unavailable') from error
            data=self._load(); workflow=next(w for w in data['workflows'] if w['id']==workflow_id)
            action=next(a for a in data['actions'] if a['id']==action_id)
            if action.get('state') not in ('DISPATCHED','UNKNOWN'):
                raise C.Refused('invoice action changed before terminalization')
            position=action['intent_index']; prior=[]
            for identity in workflow['action_ids'][:position]:
                item=next(a for a in data['actions'] if a['id']==identity)
                if computerverify.effective_action_status(self.root,item,workflow,contract) not in ('VERIFIED','VERIFIED_BY_POSTCONDITION'):
                    raise C.Refused('verified invoice prefix history changed')
                prior.append(contract['intents'][item['intent_index']]['invoice_id'])
            body={'schema':computerverify.RECEIPT_SCHEMA,'result':'VERIFIED',
                  'action_id':action_id,'intent_key':action['intent_key'],
                  'workflow_id':workflow_id,'contract_sha256':workflow['contract_sha256'],
                  'task':self.task_id,'lineage':self.lineage,'epoch':action['epoch'],
                  'policy_revision':contract['policy_revision'],
                  'verifier':dict(computerverify.VERIFIER),
                  'expectation_source':contract['expectation_source'],
                  'account':contract['account'],'sequence':sequence,
                  'verified_at':time.time(),'prior_verified_ids':prior,
                  'readbacks':readbacks,'cleanup_receipt':action['cleanup_receipt'],
                  'workflow_verified':position+1==len(contract['intents'])}
            receipt_id=computerverify.canonical_digest(body)
            receipt=dict(body,receipt_id=receipt_id,receipt_sha256=receipt_id)
            attempt=action['verification_attempts'][-1]
            if attempt.get('result')!='STARTED' or attempt.get('sequence')!=sequence:
                raise C.Refused('verification attempt changed before terminalization')
            attempt.update(result='VERIFIED',finished_at=time.time(),
                           receipt_id=receipt_id,receipt_sha256=receipt_id)
            if action['state']=='UNKNOWN':
                action.setdefault('postcondition_resolutions',[]).append({
                    'kind':'independent_postcondition','recorded_at':time.time(),
                    'receipt':receipt})
            else:
                action.update(state='VERIFIED',postcondition_receipt=receipt,
                              verification_scope='invoice_exact_prefix')
            action['workflow_verified']=receipt['workflow_verified']
            workflow['verified_prefix']=position+1
            self._save(data)
            if receipt['workflow_verified']:
                if self._output_claims.get(contract['output_lease'])!=workflow_id:
                    raise C.Refused('invoice output authority release owner changed')
                context=self._output_leases.pop(contract['output_lease'],None)
                self._output_claims.pop(contract['output_lease'],None)
                if context is not None: context.__exit__(None,None,None)
            return receipt

    def _update(self,identity,**fields):
        data=self._load(); action=next(a for a in data['actions'] if a['id']==identity)
        if action['state'] in TERMINAL:
            raise C.Refused('terminal computer action is immutable')
        action.update(fields); self._save(data)

    def _dispatch(self,identity):
        self._boundary(mutation=True)
        data=self._load(); environment=data.get('environment')
        action=next(a for a in data['actions'] if a['id']==identity)
        if action['state'] in TERMINAL: raise C.Refused('terminal computer action is immutable')
        workflow_id=action.get('workflow_id')
        if workflow_id is not None:
            workflows=[w for w in data['workflows'] if w.get('id')==workflow_id]
            if len(workflows)!=1: raise C.Refused('frozen workflow disappeared before dispatch')
            action_ids=workflows[0].setdefault('action_ids',[])
            if action.get('intent_index')!=len(action_ids):
                raise C.Refused('frozen workflow dispatch order changed')
            action_ids.append(identity)
        action.update(state='DISPATCHED',dispatched_at=time.time(),environment=environment)
        self._save(data)

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
            data=self._load()
            incarnation=data['next_environment_incarnation']+1
            environment=('effects/computer/process-'+self.epoch+'-'+
                         str(incarnation)+'.json')
            data['next_environment_incarnation']=incarnation
            data['environment']=environment
            data.setdefault('environment_history',[]).append(environment)
            self._save(data)
            fileauth.write_json(self.root,environment,{'state':'created','token':self.epoch,
                'incarnation':incarnation,
                'job':'Local\\agent-computer-'+self.epoch+'-'+str(incarnation)},actor='harness')
            self._save_owner({'server':self.server_name,'state':'owned','environment':environment,
                              'ledger':self._rel,'task':self.task_id,'lineage':self.lineage,'epoch':self.epoch})
            try:
                self.server=mcp.connect(self.root,self.server_name,role=self.role,
                                        owned_process=(self.root,environment))
            except BaseException as error:
                self.state='tainted'
                self._quarantine(error)
                raise
            self.state='active'

    def _quiesce(self,action_id):
        action=next((a for a in self.actions() if a.get('id')==action_id),None)
        if action is None or action.get('state')!='DISPATCHED':
            raise C.Refused('only a dispatched action can enter quiescent verification')
        environment=action.get('environment')
        if not environment: raise C.Refused('dispatched action lacks environment incarnation')
        self.state='quiescing'
        try:
            if self.server is not None:
                self.server.close(); self.server=None
            computerprocess.cleanup(self.root,environment)
            cleanup=self._cleanup_receipt(environment)
            owner=computerprocess.read(self.root,self._owner_rel)
            if owner.get('environment') not in (None,environment):
                raise C.Refused('owned environment incarnation changed during quiescence')
            owner.update(state='closed',environment=None); self._save_owner(owner)
            data=self._load(); current=next(a for a in data['actions'] if a['id']==action_id)
            if current.get('state')!='DISPATCHED' or current.get('environment')!=environment:
                raise C.Refused('dispatched action changed during quiescence')
            current['cleanup_receipt']=cleanup; data.pop('environment',None); self._save(data)
            self.state='quiescent'
            return cleanup
        except BaseException as error:
            self.state='tainted'
            try: self._failure(action_id,error)
            except BaseException: pass
            self._quarantine(error)
            raise

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

    def click(self,receipt,target_id,workflow_id=None):
        with self._serial:
            self._boundary(mutation=True)
            observation=self._unseal(receipt)
            links=[x for x in observation['state']['links'] if x['id']==target_id]
            if len(links)!=1: raise C.Refused('target absent')
            identity=self._prepare('click',{'page':observation['state']['url'],
                                           'target_id':target_id,'href':links[0]['href']},
                                   workflow_id=workflow_id)
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
                for context in list(self._output_leases.values()):
                    context.__exit__(None,None,None)
                self._output_leases.clear()
                self._output_claims.clear()
                if self._index_lease is not None:
                    self._index_lease.__exit__(None,None,None); self._index_lease=None
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
