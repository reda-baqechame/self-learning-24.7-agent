"""Task-owned lifecycle and durable intent tests using a real stdio child."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest
import zipfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import mcp
import computeruse as C

def wait_file(path):
    deadline = time.monotonic()+10
    while time.monotonic()<deadline:
        if path.exists():
            return
        time.sleep(.02)
    raise AssertionError('owned fixture did not reach boundary: '+str(path))

class Sessions(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('computersession'),
                             'task-owned ComputerSession module is absent')
        import computersession
        self.CS = computersession
        self.temp = tempfile.TemporaryDirectory(prefix='cs-', dir=os.getenv('AGENT_TEST_TMP'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {'id':'task-one','lineage':'lineage-one','role':'worker','status':'running'}
        self.spec = {'cmd':sys.executable,'args':[str(Path(__file__).with_name('computer_session_fixture.py')),str(self.root)],
                     'atomic_browser_adapter':True,'computer_locator_tool':'browser_run_code_unsafe',
                     'approval':'none','allow_roles':['worker'],
                     'computer_policy':{'revision':'r1','allowed_origin':'https://example.com'}}
        self.spec['trust_identity'] = mcp.server_identity(self.spec)
        self.config()
    def config(self):
        (self.root/'mcp.json').write_text(json.dumps({'servers':{'fixture':self.spec}}))
    def session(self, task=None):
        s = self.CS.ComputerSession(str(self.root), task or self.task, 'fixture','r1')
        self.addCleanup(s.close,'test cleanup')
        return s
    def test_reuse_pause_lease_restart_epoch_and_cleanup(self):
        s = self.session(); opened = s.open('https://example.com/')
        proc = s.server.proc
        first = opened['observation']; epoch = s.epoch
        self.task['status'] = 'blocked'
        with self.assertRaises(C.Refused):
            self.session(dict(self.task,id='other'))
        self.task.update(status='running',provider='model-failover')
        second = s.observe()
        self.assertEqual(first['state']['binding']['tab'],second['state']['binding']['tab'])
        self.assertIs(s.server.proc,proc)
        s.close('completed'); self.assertIsNotNone(proc.poll())
        restarted = self.session(); restarted.open('https://example.com/')
        self.assertNotEqual(epoch,restarted.epoch)
        with self.assertRaises(C.Refused):
            restarted.click(first,'one')
        print('[session-lifecycle] real process and tab reused through pause and model failover; exclusive lease, new epoch and child cleanup')
    def test_ack_is_pending_not_verified_and_same_intent_is_blocked(self):
        s = self.session(); receipt = s.open('https://example.com/')['observation']
        result = s.click(receipt,'one')
        self.assertEqual(result['status'],'ACTION_DISPATCHED')
        self.assertFalse(result['workflow_verified'])
        self.assertEqual(s.actions()[-1]['state'],'DISPATCHED')
        with self.assertRaises(C.Refused):
            s.click(s.observe(),'one')
        s.click(s.observe(),'two')
        s.close('completed')
        clicks = [a for a in s.actions() if a['operation']=='click']
        self.assertEqual([a['state'] for a in clicks],['UNKNOWN','UNKNOWN'])
        self.assertTrue(all(a['dispatch_acknowledged'] for a in clicks))
        print('[pending-effects] acknowledgment permits another intent, never verifies or repeats the same unresolved business action')
    def test_unknown_blocks_retry_lineage_even_with_new_observation(self):
        s = self.session(); receipt = s.open('https://example.com/')['observation']
        (self.root/'hold-response').touch(); s.server.timeout=.15
        with self.assertRaises(C.Unresolved):
            s.click(receipt,'one')
        self.assertEqual(s.state,'tainted')
        s.close('failure')
        retry = self.session(dict(self.task,id='retry',provider='fallback'))
        with self.assertRaises(C.Refused):
            retry.open('https://example.com/')
        self.assertEqual((self.root/'effect-seen').read_text(),'one')
        print('[unknown-lineage] lost response taints and survives retry task identity and model failover')
    def test_role_origin_revocation_and_explicit_effect_attribution(self):
        with self.assertRaises(C.Refused):
            self.session(dict(self.task,role='reader'))
        s = self.session()
        with self.assertRaises(C.Refused):
            s.open('https://outside.example/')
        with patch.dict(os.environ,{'AGENT_TASK_ID':'wrong','AGENT_TASK_LINEAGE':'wrong'}):
            s.open('https://example.com/')
        rows = [json.loads(x) for x in (self.root/'logs/effects.jsonl').read_text().splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(r['task']=='task-one' and r['key'].startswith('lineage-one|') for r in rows))
        self.spec['deny_tools']=['browser_run_code_unsafe']; self.config()
        with self.assertRaises(C.Refused): s.observe()
        self.assertIsNotNone(s.server.proc.poll())
        print('[session-policy] role and origin refuse; live owner revocation closes; effects use explicit task identity')

    def agent(self):
        import loop
        (self.root/'settings.toml').write_text('[agent]\n[roles.worker]\ntools=["computer_open","computer_observe","computer_click"]\n[roles.reader]\ntools=["read_file"]\n')
        agent = loop.Agent(str(self.root))
        for handler in list(agent.log.handlers):
            self.addCleanup(handler.close)
            self.addCleanup(agent.log.removeHandler,handler)
        self.addCleanup(agent.close_computers, 'test cleanup')
        return agent

    def test_agent_public_tools_role_reuse_and_terminal_cleanup(self):
        agent = self.agent()
        args = {'server_name':'fixture','policy_revision':'r1','url':'https://example.com/'}
        denied = agent.exec_tool(dict(self.task,role='reader'),'computer_open',args)
        self.assertTrue(denied.startswith('ERROR:'), denied)
        opened = json.loads(agent.exec_tool(self.task,'computer_open',args))
        proc = agent._computer_sessions[self.task['id']].server.proc
        self.task['status']='blocked'; agent.commit_task(self.task)
        self.assertIsNone(proc.poll())
        self.task['status']='running'
        self.assertIn('observation',opened)
        for _ in range(2):
            self.assertIn('state',json.loads(agent.exec_tool(self.task,'computer_observe',{})))
            self.assertIs(agent._computer_sessions[self.task['id']].server.proc,proc)
        raw=agent.exec_tool(self.task,'browser_evaluate',{'function':'()=>1'})
        self.assertNotIn('VERIFIED',raw)
        self.task['status']='done'; agent.commit_task(self.task)
        self.assertIsNotNone(proc.poll())
        self.assertFalse(agent._computer_sessions)
        print('[agent-tools] direct role denial, typed observations, one process across turns, blocked lease retained, completion closes')

    def test_agent_external_cancel_and_process_finally_cleanup(self):
        for terminal in ('cancelled','failed'):
            agent=self.agent()
            self.task['status']='running'
            (self.root/'state.json').unlink(missing_ok=True)
            agent.exec_tool(self.task,'computer_open',{'server_name':'fixture','policy_revision':'r1','url':'https://example.com/'})
            proc=agent._computer_sessions[self.task['id']].server.proc
            (self.root/'state.json').write_text(json.dumps({'tasks':[dict(self.task,status=terminal)]}))
            result=agent.exec_tool(self.task,'computer_observe',{})
            self.assertTrue(result.startswith('ERROR:'),result)
            self.assertIsNotNone(proc.poll())
            agent.close_computers('test')
        (self.root/'state.json').unlink()
        agent=self.agent()
        agent.exec_tool(self.task,'computer_open',{'server_name':'fixture','policy_revision':'r1','url':'https://example.com/'})
        proc=agent._computer_sessions[self.task['id']].server.proc
        with patch.object(agent,'_run',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): agent.run()
        self.assertIsNotNone(proc.poll())
        print('[agent-finally] external cancellation/failure refuses next action and closes; interrupted runtime finally closes child')

    def test_owner_reconciliation_evidence_and_worker_denial(self):
        s=self.session(); receipt=s.open('https://example.com/')['observation']
        action_id=s.click(receipt,'one')['action_id']; s.close('pending')
        original=s.actions()[-1].copy()
        evidence_path=self.root/'effects'/'owner-evidence.txt'
        evidence_path.write_bytes(b'owner inspected external receipt')
        meta={'path':'effects/owner-evidence.txt','sha256':hashlib.sha256(evidence_path.read_bytes()).hexdigest(),'bytes':len(evidence_path.read_bytes())}
        for var in ('AGENT_TASK_ID','AGENT_ROLE'):
            with patch.dict(os.environ,{var:'worker'}):
                with self.assertRaises(SystemExit): s.reconcile(action_id,'authorize_retry','invoice_review',meta)
        (self.root/'worker.txt').write_bytes(evidence_path.read_bytes())
        with self.assertRaises(C.Refused): s.reconcile(action_id,'authorize_retry','invoice_review',dict(meta,path='worker.txt'))
        with self.assertRaises(C.Refused):
            s.reconcile(action_id,'authorize_retry','invoice_review',
                        dict(meta,path='effects/../worker.txt'))
        for invalid in ('effects/missing.txt','effects/\x00bad.txt'):
            with self.assertRaises(C.Refused,msg=repr(invalid)):
                s.reconcile(action_id,'authorize_retry','invoice_review',
                            dict(meta,path=invalid))
        with self.assertRaises(C.Refused): s.reconcile(action_id,'confirmed_effect','invoice_review',dict(meta,sha256='0'*64))
        original_root=s.root
        alias=None
        if os.name=='nt':
            import ctypes
            buffer=ctypes.create_unicode_buffer(32768)
            size=ctypes.windll.kernel32.GetShortPathNameW(
                os.fspath(self.root),buffer,len(buffer))
            if (0 < size < len(buffer)
                    and os.path.normcase(buffer.value)
                    != os.path.normcase(os.fspath(self.root))):
                alias=buffer.value
        else:
            alias_path=self.root/'canonical-root-alias'
            alias_path.symlink_to(self.root,target_is_directory=True)
            alias=os.fspath(alias_path)
        if alias is not None:
            s.root=alias
        allowed={self.CS.fileauth.ZONE_CONTROL,
                 self.CS.fileauth.ZONE_RUNTIME}
        with patch.object(self.CS.fileauth,'resolve',
                          wraps=self.CS.fileauth.resolve) as authority:
            s.reconcile(action_id,'authorize_retry','invoice_review',meta)
        evidence_call=next(call for call in authority.call_args_list
                           if len(call.args)>1 and call.args[1]==meta['path'])
        self.assertEqual(evidence_call.kwargs.get('allow_zones'),allowed)
        s.root=original_root
        resolved=s.actions()[-1]
        for key,value in original.items(): self.assertEqual(resolved[key],value)
        self.assertEqual(resolved['reconciliations'][-1]['verifier_kind'],'owner_attestation')
        self.assertFalse(resolved['workflow_verified'])
        restarted=self.session(); restarted.open('https://example.com/')
        restarted.click(restarted.observe(),'one')
        print('[owner-intervention] worker entry and worker-only evidence denied; physical digest checked; UNKNOWN history retained with owner attestation')

    def test_file_authority_path_identity_matrix(self):
        F=self.CS.fileauth
        for name in ('effects','logs','out','keys'):
            (self.root/name).mkdir(exist_ok=True)
        (self.root/'effects'/'control.txt').write_bytes(b'control')
        (self.root/'logs'/'runtime.txt').write_bytes(b'runtime')
        (self.root/'out'/'workspace.txt').write_bytes(b'workspace')
        (self.root/'root.txt').write_bytes(b'root')
        allowed={F.ZONE_CONTROL,F.ZONE_RUNTIME}
        for rel in ('effects/control.txt','logs/runtime.txt',
                    'effects\\control.txt'):
            self.assertTrue(Path(F.resolve(
                self.root,rel,'read','harness',allow_zones=allowed)).exists())
        for rel in ('root.txt','out/workspace.txt','effects/../root.txt',
                    'effects\\..\\root.txt','./effects/control.txt',
                    'logs/./runtime.txt',
                    '../sibling-root-prefix.txt',str(self.root/'root.txt'),
                    'C:drive-relative.txt','//server/share/file.txt',
                    '//?/C:/device-path.txt','effects/\x00bad.txt'):
            with self.assertRaises(F.Denied,msg=rel):
                F.resolve(self.root,rel,'read','harness',
                          allow_zones=allowed)
        if os.name=='nt':
            for rel in ('out/file:stream','out/trailing.','out/trailing ',
                        'out/CON','out/LPT1.txt'):
                with self.assertRaises(F.Denied,msg=rel):
                    F.resolve(self.root,rel,'read','harness')
        else:
            # POSIX names are case-sensitive and ':' is not an ADS marker.
            self.assertTrue(F.resolve(
                self.root,'out/Case:literal','write','harness').endswith(
                    'Case:literal'))

        alias=None
        if os.name=='nt':
            import ctypes
            buffer=ctypes.create_unicode_buffer(32768)
            size=ctypes.windll.kernel32.GetShortPathNameW(
                os.fspath(self.root),buffer,len(buffer))
            if (0 < size < len(buffer)
                    and os.path.normcase(buffer.value)
                    != os.path.normcase(os.fspath(self.root))):
                alias=buffer.value
        else:
            alias_path=self.root.parent/(self.root.name+'-alias')
            alias_path.symlink_to(self.root,target_is_directory=True)
            self.addCleanup(alias_path.unlink)
            alias=os.fspath(alias_path)
        if alias is not None:
            resolved=F.resolve(alias,'effects/control.txt','read','harness',
                               allow_zones=allowed)
            self.assertTrue(os.path.samefile(
                resolved,self.root/'effects'/'control.txt'))
        elif os.name=='nt':
            print('[path-identity] Windows 8.3 alias is unavailable on this volume; native alias case not run')

        def directory_link(link,target):
            if os.name=='nt':
                made=subprocess.run(['cmd','/c','mklink','/J',str(link),
                                     str(target)],capture_output=True,text=True)
                if made.returncode:
                    self.skipTest('cannot create a Windows junction here')
                self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
            else:
                link.symlink_to(target,target_is_directory=True)
                self.addCleanup(link.unlink)

        cross=self.root/'effects'/'workspace-alias'
        directory_link(cross,self.root/'out')
        for rel in ('effects/workspace-alias/workspace.txt',
                    'effects/workspace-alias/new.txt'):
            with self.assertRaises(F.Denied,msg=rel):
                F.resolve(self.root,rel,'read','harness',
                          allow_zones=allowed)

        outside=tempfile.TemporaryDirectory(prefix='cs-outside-',
                                            dir=os.getenv('AGENT_TEST_TMP'))
        self.addCleanup(outside.cleanup)
        outside_path=Path(outside.name); (outside_path/'x.txt').write_bytes(b'x')
        escape=self.root/'out'/'escape'
        directory_link(escape,outside_path)
        with self.assertRaises(F.Denied):
            F.resolve(self.root,'out/escape/x.txt','read','harness')

        secret=self.root/'keys'/'owner.key'
        secret.write_bytes(b'sk-aaaaaaaaaaaaaaaaaaaa1234')
        with self.assertRaises(F.Denied):
            F.resolve(self.root,'keys/owner.key','read','harness')
        hardlink=self.root/'effects'/'owner-evidence.txt'
        os.link(secret,hardlink)
        meta={'path':'effects/owner-evidence.txt',
              'sha256':hashlib.sha256(secret.read_bytes()).hexdigest(),
              'bytes':len(secret.read_bytes())}
        with self.assertRaises(C.Refused):
            self.session()._artifact(meta,allow_zones=allowed)

        created=F.write_text(self.root,'out/ordinary.txt','ordinary')
        self.assertEqual(Path(created).read_text(),'ordinary')
        print('[path-identity] actual platform alias, typed zones, ambiguous spellings, cross-zone/outside links, secret hardlink and ordinary writes follow one authority contract')

    def test_artifact_inode_replacement_before_and_after_open_refuses(self):
        F=self.CS.fileauth
        (self.root/'effects').mkdir(exist_ok=True)
        target=self.root/'effects'/'stable.txt'; raw=b'stable evidence'
        target.write_bytes(raw)
        meta={'path':'effects/stable.txt',
              'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        allowed={F.ZONE_CONTROL,F.ZONE_RUNTIME}
        s=self.session()

        def replace_inode(suffix):
            old=target.with_suffix(suffix)
            os.replace(target,old)
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL)
            try:
                os.write(fd,raw)
            finally:
                os.close(fd)
            return old

        real_open=open; swapped=[]
        def racing_open(path,*args,**kwargs):
            if os.path.normcase(os.fspath(path))==os.path.normcase(str(target)) \
                    and args and args[0]=='rb' and not swapped:
                swapped.append(replace_inode('.before'))
            return real_open(path,*args,**kwargs)
        # Credential classification has its own alias/hard-link coverage above.
        # Isolate it here so the first binary open after `_no_links` is the
        # artifact descriptor whose pre-open identity binding we are testing.
        with patch('credentials.is_secret',return_value=False), \
                patch('builtins.open',side_effect=racing_open):
            with self.assertRaises(C.Refused):
                s._artifact(meta,allow_zones=allowed)
        target.unlink(); os.replace(swapped[0],target)

        real_resolve=F.resolve; calls=0; replaced=[]
        def racing_resolve(root,rel,*args,**kwargs):
            nonlocal calls
            result=real_resolve(root,rel,*args,**kwargs)
            if rel==meta['path']:
                calls+=1
                if calls==2:
                    replaced.append(replace_inode('.after'))
            return result
        with patch.object(F,'resolve',side_effect=racing_resolve):
            with self.assertRaises(C.Refused):
                s._artifact(meta,allow_zones=allowed)
        print('[artifact-race] same-size/same-digest inode replacement before open and after read both refuse before reconciliation state can change')

    def test_persistent_lease_health_never_recommends_deletion(self):
        import harness, locks
        s=self.session()
        lease=next((self.root/'effects'/'computer').glob('*.lock'))
        old=time.time()-1000
        os.utime(lease,(old,old))
        legacy=self.root/'legacy.lock'; legacy.write_text('dead'); os.utime(legacy,(old,old))
        provider=str(self.root/'settings.toml.update')
        with locks.advisory_holding(provider):
            os.utime(provider+'.lock',(old,old))
            problems=harness.integrity(str(self.root))['problems']
            self.assertFalse(any('stale lock:' in p and ('effects/computer' in p or 'settings.toml.update' in p) for p in problems),problems)
            self.assertTrue(any('stale lock: legacy.lock' in p for p in problems),problems)
            with self.assertRaises(C.Refused): self.session(dict(self.task,id='other'))
        self.assertTrue(lease.exists())
        print('[persistent-lock-health] old advisory locks never called safe-to-delete; legacy stale diagnosis and live exclusion remain')

    def test_package_excludes_root_session_private_state(self):
        import package
        (self.root/'effects'/'computer').mkdir(parents=True)
        (self.root/'effects'/'computer'/'ledger.json').write_text('private task URL')
        (self.root/'.superpowers').mkdir()
        (self.root/'.superpowers'/'report.md').write_text('private debug evidence')
        (self.root/'computersession.py').write_text('public module')
        target=self.root/'result.zip'
        with patch.object(package,'HERE',str(self.root)), patch.object(sys,'argv',['package.py','--out',str(target)]): package.main()
        with zipfile.ZipFile(target) as z:
            self.assertIn('computersession.py',z.namelist())
            self.assertNotIn('effects/computer/ledger.json',z.namelist())
            self.assertNotIn('.superpowers/report.md',z.namelist())
        print('[session-package] root runtime ledger and debug evidence excluded from real archive; module ships')

    def test_owned_grandchild_stops_when_session_closes_or_owner_dies(self):
        for mode in ('close','crash','blocked'):
            (self.root/'spawn-grandchild').touch()
            marker=self.root/'grandchild-ticks'
            marker.unlink(missing_ok=True)
            (self.root/'ready').unlink(missing_ok=True)
            if mode=='close':
                s=self.session(); s.open('https://example.com/')
                wait_file(marker); s.close('complete')
            else:
                proc=subprocess.Popen([sys.executable,str(Path(__file__)),'--owner',str(self.root),'blocked' if mode=='blocked' else 'prepared'],cwd=HERE)
                try:
                    wait_file(self.root/'ready'); wait_file(marker)
                    if mode=='blocked': time.sleep(.3)
                    proc.kill(); proc.wait(timeout=5)
                finally:
                    if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
            time.sleep(.6)
            size=marker.stat().st_size
            time.sleep(.3)
            self.assertEqual(marker.stat().st_size,size,'owned grandchild retained execution after close/death')
        print('[owned-process-tree] real grandchild loses execution on close and abrupt owner death, including a child that stopped reading stdin')

    def test_pinned_docker_session_and_container_cleanup(self):
        if os.getenv('AGENT_COMPUTER_LIVE')!='1':
            print('[owned-chromium] NOT_RUN: set AGENT_COMPUTER_LIVE=1 for network-none pinned Docker fixture')
            return
        from test_computeruse_live import DOCKER, IMAGE, ORIGIN
        import org
        org.create(str(self.root),'Session fixture','owner@example.invalid')
        org.set_policy(str(self.root),'owner@example.invalid','agents_may_reach_internal_network',True)
        self.spec.update(cmd=DOCKER,args=['run','-i','--rm','--init','--pull=never',
            '--network=none','--read-only','--tmpfs=/tmp:rw,nosuid,nodev,size=256m',
            '--tmpfs=/home/node:rw,nosuid,nodev,size=64m,uid=1000,gid=1000',
            '--memory=1g','--pids-limit=256','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--mount',f'type=bind,source={Path(__file__).parent/"computer-click-fixture"},target=/fixture,readonly',
            '--entrypoint=sh',IMAGE,'-c','node /fixture/server.cjs & exec node /app/cli.js --headless --browser chromium --no-sandbox --isolated --snapshot-mode=none --timeout-action=1000 --timeout-navigation=3000'],
            computer_policy={'revision':'r1','allowed_origin':ORIGIN})
        self.spec['trust_identity']=mcp.server_identity(self.spec); self.config()
        s=self.session(); first=s.open(ORIGIN+'/')['observation']; proc=s.server.proc
        second=s.observe(); self.assertIs(s.server.proc,proc)
        self.assertEqual(first['state']['binding']['tab'],second['state']['binding']['tab'])
        view=second['view_context']; self.assertEqual(view['viewport_source'],'playwright_host')
        self.assertGreater(view['viewport']['width'],0)
        self.assertIn(view['device_scale_source'],('page_untrusted','unavailable'))
        changed=dict(view['viewport'],width=view['viewport']['width']+1)
        mcp.computer_guarded_call(s.server,'browser_run_code_unsafe',{'code':'async page => {await page.setViewportSize('+json.dumps(changed)+');}'},root=str(self.root),fresh=True,task_context=s._context)
        with self.assertRaises(C.Refused): s.click(second,'INV-0')
        second=s.observe()
        result=s.click(second,'INV-0'); self.assertFalse(result['workflow_verified'])
        environment=s._load()['environment']
        metadata=self.CS.computerprocess.read(str(self.root),environment)
        cid=(self.root/metadata['docker']['cidfile']).read_text().strip()
        s.close('finished local fixture')
        actual=subprocess.run([DOCKER,'container','ls','-a','--no-trunc','--filter','id='+cid,'--format','{{.ID}}'],capture_output=True,text=True,check=True,timeout=15,env=mcp.server_environment({}))
        self.assertFalse(actual.stdout.strip(),'owned Docker environment still exists')
        self.assertEqual(s.actions()[-1]['state'],'UNKNOWN')
        print('[owned-chromium] pinned real browser reused through ComputerSession; click acknowledgment stays pending; exact container removal independently read back')

    def test_prepared_and_dispatched_are_fsynced_before_input(self):
        s=self.session(); receipt=s.open('https://example.com/')['observation']
        syncs=[]; original=os.fsync
        def synced(fd):
            original(fd); syncs.append(os.fstat(fd).st_size)
        with patch.object(os,'fsync',side_effect=synced):
            identity=s._prepare('click',{'manual':'durable-boundary'})
            self.assertTrue(syncs,'PREPARED was not fsynced')
            syncs.clear(); s._dispatch(identity)
            self.assertTrue(syncs,'DISPATCHED was not fsynced')
        self.assertEqual(s.actions()[-1]['state'],'DISPATCHED')
        print('[durable-boundary] actual fsync completes for PREPARED and DISPATCHED before adapter may send input')

    def test_post_click_artifacts_bound_and_physical_bytes_rechecked(self):
        (self.root/'emit-image').touch()
        s=self.session(); receipt=s.open('https://example.com/')['observation']
        self.assertTrue(receipt['artifacts'])
        post=s.click(receipt,'one')['observation']
        self.assertTrue(post['artifacts'],'post-click image metadata was dropped')
        meta=post['artifacts'][0]; (self.root/meta['path']).write_bytes(b'changed')
        with self.assertRaises(C.Refused): s.click(post,'two')
        self.assertEqual((self.root/'effect-seen').read_text(),'one')
        print('[artifact-receipts] initial and post-click receipts bind image metadata; altered physical bytes refuse before next input')

    def test_replacement_task_cannot_inherit_other_role_session(self):
        agent=self.agent()
        agent.exec_tool(self.task,'computer_open',{'server_name':'fixture','policy_revision':'r1','url':'https://example.com/'})
        replacement=dict(self.task,lineage='foreign-lineage')
        result=agent.exec_tool(replacement,'computer_observe',{})
        self.assertTrue(result.startswith('ERROR:'),result)
        print('[current-task-identity] replacement task object cannot silently inherit another lineage session')

    def test_unproven_cleanup_keeps_taint_and_exclusion(self):
        s=self.session(); s.open('https://example.com/')
        with patch.object(self.CS.computerprocess,'cleanup',side_effect=RuntimeError('cleanup unproven')):
            with self.assertRaises(RuntimeError): s.close('stop')
        self.assertEqual(s.state,'tainted')
        with self.assertRaises(C.Refused): self.session(dict(self.task,id='other'))
        s.close('verified retry cleanup')
        print('[cleanup-failclosed] unproven environment cleanup retains taint and exclusive lease')

    def test_off_origin_redirect_after_navigation_is_unknown(self):
        (self.root/'redirect-outside').touch()
        s=self.session()
        with self.assertRaises((C.Refused,C.Unresolved)): s.open('https://example.com/')
        self.assertEqual(s.actions()[-1]['state'],'UNKNOWN','navigation already dispatched before off-origin observation')
        self.assertEqual(s.state,'tainted')
        print('[navigation-scope] off-origin post-navigation observation cannot be labeled known-no-effect refusal')

    def test_empty_role_tool_allowlist_denies_computer_entry(self):
        agent=self.agent(); (self.root/'settings.toml').write_text('[agent]\n[roles.worker]\ntools=[]\n')
        result=agent.exec_tool(self.task,'computer_open',{'server_name':'fixture','policy_revision':'r1','url':'https://example.com/'})
        self.assertTrue(result.startswith('ERROR:'),result)
        self.assertFalse(agent._computer_sessions)
        print('[empty-role-allowlist] explicit empty tool allowlist denies direct computer tool entry')

    def test_view_context_is_sealed_and_changed_viewport_refuses(self):
        s=self.session(); receipt=s.open('https://example.com/')['observation']
        view=receipt['view_context']
        self.assertEqual(view['viewport'],{'width':800,'height':600})
        self.assertEqual(view['viewport_source'],'playwright_host')
        self.assertEqual(view['device_scale_source'],'page_untrusted')
        self.assertEqual(view['coordinate_mode'],'css_locator')
        self.assertFalse(view['screenshot_coordinates_authorized'])
        for key,value in [('viewport',{'width':1,'height':2}),('device_scale',2),
                          ('device_scale_source','trusted'),('screenshot_coordinates_authorized',True)]:
            altered=json.loads(json.dumps(receipt)); altered['view_context'][key]=value
            with self.assertRaises(C.Refused): s.click(altered,'one')
        (self.root/'viewport-width').write_text('801')
        with self.assertRaises(C.Refused): s.click(receipt,'one')
        self.assertFalse((self.root/'effect-seen').exists())
        s.click(s.observe(),'one')
        print('[view-context] sealed provenance cannot be altered; changed host viewport refuses before CSS-locator input')

    def test_unavailable_view_context_is_explicit(self):
        (self.root/'omit-view-context').touch()
        receipt=self.session().open('https://example.com/')['observation']
        view=receipt['view_context']
        self.assertIsNone(view['viewport']); self.assertIsNone(view['device_scale'])
        self.assertEqual(view['viewport_source'],'unavailable')
        self.assertEqual(view['device_scale_source'],'unavailable')
        self.assertFalse(view['screenshot_coordinates_authorized'])
        print('[unavailable-view-context] missing measurements remain null, never fabricated screenshot-coordinate authority')

    def test_agent_cleanup_attempts_all_owned_sessions_after_failure(self):
        agent=self.agent()
        (self.root/'mcp.json').write_text(json.dumps({'servers':{'fixture':self.spec,'fixture-two':self.spec}}))
        first=self.session(); first.open('https://example.com/')
        other=dict(self.task,id='task-two',lineage='lineage-two')
        second=self.CS.ComputerSession(str(self.root),other,'fixture-two','r1')
        self.addCleanup(second.close,'test cleanup'); second.open('https://example.com/')
        agent._computer_sessions={self.task['id']:first,other['id']:second}
        original=self.CS.computerprocess.cleanup; first_env=first._load()['environment']
        def cleanup(root,relative,*args,**kwargs):
            if relative==first_env: raise RuntimeError('first environment unproven')
            return original(root,relative,*args,**kwargs)
        with patch.object(self.CS.computerprocess,'cleanup',side_effect=cleanup):
            with self.assertRaises(Exception): agent.close_computers('stop all')
        self.assertEqual(first.state,'tainted'); self.assertEqual(second.state,'closed')
        self.assertIsNotNone(second.server.proc.poll())
        self.assertEqual(set(agent._computer_sessions),{self.task['id']})
        with self.assertRaises(C.Refused): self.session(dict(self.task,id='third'))
        print('[cleanup-all] first failure retains its tainted lease while every other owned environment is still closed')

    def test_process_death_prepared_and_dispatched_recover_differently(self):
        for stage, expected in [('prepared','FAILED_WITH_KNOWN_NO_EFFECT'),('dispatched','UNKNOWN')]:
            with self.subTest(stage=stage):
                for name in ('ready','fixture-exited','effect-seen'):
                    (self.root/name).unlink(missing_ok=True)
                if stage=='dispatched': (self.root/'hold-response').touch()
                proc = subprocess.Popen([sys.executable,str(Path(__file__)), '--owner',str(self.root),stage],cwd=HERE)
                try:
                    wait_file(self.root/('ready' if stage=='prepared' else 'effect-seen'))
                    proc.kill(); proc.wait(timeout=5)
                    recovered = self.session()
                    environment=recovered._load()['environment']
                    self.assertEqual(self.CS.computerprocess.read(str(self.root),environment)['state'],'closed')
                    clicks = [a for a in recovered.actions() if a['operation']=='click']
                    self.assertEqual(clicks[-1]['state'],expected)
                    recovered.close('test')
                finally:
                    if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
        print('[crash-boundaries] killed real owners recover PREPARED as no-effect and DISPATCHED as UNKNOWN; owned environment closure confirmed')

    def test_failed_recovery_quarantines_server_across_lineages(self):
        proc=subprocess.Popen([sys.executable,str(Path(__file__)),'--owner',str(self.root),'prepared'],cwd=HERE)
        try:
            wait_file(self.root/'ready'); proc.kill(); proc.wait(timeout=5)
        finally:
            if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
        with patch.object(self.CS.computerprocess,'cleanup',side_effect=RuntimeError('closure unavailable')):
            with self.assertRaises(RuntimeError): self.session()
            with self.assertRaises(RuntimeError): self.session(dict(self.task,id='foreign',lineage='foreign'))
        # The failed constructor has no usable instance. A later claimant must
        # independently prove closure before its different lineage can proceed.
        recovered=self.session(dict(self.task,id='foreign',lineage='foreign'))
        recovered.open('https://example.com/'); recovered.close('test')
        old=self.session()
        self.assertEqual([a['state'] for a in old.actions() if a['operation']=='click'],['FAILED_WITH_KNOWN_NO_EFFECT'])
        print('[server-quarantine] failed construction persists server ownership across lineage changes until independent cleanup succeeds')

    def test_public_role_revocation_reloads_actual_settings(self):
        agent=self.agent()
        agent.exec_tool(self.task,'computer_open',{'server_name':'fixture','policy_revision':'r1','url':'https://example.com/'})
        session=agent._computer_sessions[self.task['id']]
        (self.root/'settings.toml').write_text('[agent]\n[roles.worker]\ntools=[]\n')
        result=agent.exec_tool(self.task,'computer_observe',{})
        self.assertTrue(result.startswith('ERROR:'),result)
        self.assertEqual(session.state,'closed')
        self.assertIsNotNone(session.server.proc.poll())
        print('[fresh-role-policy] changing the owner settings file revokes the next direct public call and closes its session')

    def test_mcp_source_disappearance_cannot_inherit_identical_fallback(self):
        fleet=self.root; self.root=fleet/'experts'/'task'; self.root.mkdir(parents=True)
        self.spec['args'][-1]=str(self.root); self.spec['trust_identity']=mcp.server_identity(self.spec)
        self.config(); (fleet/'mcp.json').write_bytes((self.root/'mcp.json').read_bytes())
        s=self.session(); s.open('https://example.com/')
        (self.root/'mcp.json').unlink()
        with self.assertRaises(C.Refused): s.observe()
        self.assertIsNotNone(s.server.proc.poll())
        print('[configuration-source] deleting pinned local config refuses identical-content fleet fallback')

    def test_system_interruption_still_closes_other_sessions(self):
        agent=self.agent()
        (self.root/'mcp.json').write_text(json.dumps({'servers':{'fixture':self.spec,'fixture-two':self.spec}}))
        first=self.session(); first.open('https://example.com/')
        second=self.CS.ComputerSession(str(self.root),dict(self.task,id='second',lineage='second'),'fixture-two','r1')
        self.addCleanup(second.close,'test'); second.open('https://example.com/')
        agent._computer_sessions={self.task['id']:first,'second':second}
        original=self.CS.computerprocess.cleanup; environment=first._load()['environment']
        interruption=KeyboardInterrupt('owner interrupt')
        def interrupted(root,rel):
            if rel==environment: raise interruption
            return original(root,rel)
        with patch.object(self.CS.computerprocess,'cleanup',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt) as raised: agent.close_computers('stop')
        self.assertIs(raised.exception,interruption)
        self.assertEqual(first.state,'tainted'); self.assertEqual(second.state,'closed')
        print('[system-interruption-cleanup] KeyboardInterrupt is preserved only after every later owned session is attempted')

    def test_quarantine_write_failure_does_not_mask_system_interruption(self):
        s=self.session(); s.open('https://example.com/')
        interruption=KeyboardInterrupt('owner interrupt')
        with patch.object(self.CS.computerprocess,'cleanup',side_effect=interruption), patch.object(s,'_save_owner',side_effect=OSError('storage unavailable')):
            with self.assertRaises(KeyboardInterrupt) as raised: s.close('stop')
        self.assertIs(raised.exception,interruption)
        self.assertEqual(s.state,'tainted')
        self.assertTrue(self.CS.computerprocess.read(str(self.root),s._owner_rel)['environment'])
        print('[interrupt-primary] failure to refresh quarantine cannot mask system interruption; prior durable environment still excludes new claimants')

    def test_run_main_exception_survives_cleanup_failure(self):
        for primary in (KeyboardInterrupt('cancel main'),SystemExit(17),ValueError('main failed')):
            with self.subTest(primary=type(primary).__name__):
                agent=self.agent()
                (self.root/'mcp.json').write_text(json.dumps({'servers':{'fixture':self.spec,'fixture-two':self.spec}}))
                first=self.session(); first.open('https://example.com/')
                second=self.CS.ComputerSession(str(self.root),dict(self.task,id='second',lineage='second'),'fixture-two','r1')
                self.addCleanup(second.close,'test'); second.open('https://example.com/')
                agent._computer_sessions={self.task['id']:first,'second':second}
                original=self.CS.computerprocess.cleanup; environment=first._load()['environment']
                cause=RuntimeError('original cause'); primary.__cause__=cause
                def cleanup(root,rel):
                    if rel==environment: raise RuntimeError('cleanup unproven')
                    return original(root,rel)
                caught=None
                with patch.object(agent,'_run',side_effect=primary), patch.object(self.CS.computerprocess,'cleanup',side_effect=cleanup):
                    try: agent.run()
                    except BaseException as error: caught=error
                self.assertEqual(first.state,'tainted'); self.assertEqual(second.state,'closed')
                self.assertIsNotNone(second.server.proc.poll())
                agent.close_computers('verified test cleanup')
                self.assertIs(caught,primary,'run main exception was replaced by cleanup failure')
                self.assertIs(caught.__cause__,cause,'original cause was overwritten')
                self.assertTrue(any('cleanup unproven' in note for note in caught.__notes__))
                if isinstance(primary,SystemExit): self.assertEqual(caught.code,17)
        print('[run-primary-exception] public run preserves cancellation, exit code and ordinary failure while every session cleanup is attempted and diagnosed')

    def test_run_success_still_reports_cleanup_failure(self):
        agent=self.agent(); s=self.session(); s.open('https://example.com/')
        agent._computer_sessions={self.task['id']:s}
        with patch.object(agent,'_run',return_value='main result'), patch.object(self.CS.computerprocess,'cleanup',side_effect=RuntimeError('cleanup unproven')):
            with self.assertRaises(ExceptionGroup) as raised: agent.run()
        self.assertEqual(str(raised.exception.exceptions[0]),'cleanup unproven')
        self.assertEqual(s.state,'tainted')
        agent.close_computers('verified test cleanup')
        with patch.object(agent,'_run',return_value='main result'):
            self.assertEqual(agent.run(),'main result')
        print('[run-success-cleanup] successful main cannot suppress cleanup failure; verified clean finalization preserves its return value')

    def test_docker_endpoint_environment_refuses_before_spawn(self):
        for selector in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','DOCKER_TLS_VERIFY'):
            with self.subTest(selector=selector):
                self.root=Path(self.temp.name)/selector; self.root.mkdir()
                self.spec.update(cmd='docker',args=['run','--rm','--network=none','fixture'],env={selector:'unsupported'})
                self.spec['trust_identity']=mcp.server_identity(self.spec); self.config()
                started=[]
                def launch(*args,**kwargs): started.append(True); raise RuntimeError('unexpected spawn')
                with patch.object(subprocess,'Popen',side_effect=launch):
                    with self.assertRaises(ValueError): self.session()
                self.assertFalse(started,'endpoint selector reached process launch')
        print('[docker-endpoint-policy] forwarded endpoint/context/config/TLS selectors refuse before any subprocess launch')

    def test_posix_cleanup_contract_preserves_identity_and_requires_absence(self):
        process=self.CS.computerprocess
        self.assertTrue(callable(getattr(process,'_posix_stop',None)),'POSIX group closure primitive missing')
        calls=[]
        class Child:
            pid=12345
            def wait(inner,timeout):
                self.assertEqual(calls[0],(12345,process.signal.SIGKILL),'leader reaped before group termination')
        def signal_group(group,sig):
            calls.append((group,sig))
            if sig==0: raise ProcessLookupError()
        with patch.object(process.os,'killpg',side_effect=signal_group,create=True), patch.object(process.signal,'SIGKILL',9,create=True):
            process._posix_stop(Child())
        self.assertIn((12345,0),calls,'no independent group absence readback')
        with patch.object(process.os,'killpg',return_value=None,create=True), patch.object(process.time,'monotonic',side_effect=[0,10]), patch.object(process.signal,'SIGKILL',9,create=True):
            with self.assertRaises(RuntimeError): process._posix_stop(Child())
        print('[posix-contract-only] simulated syscall boundary preserves leader until kill and refuses lingering group; not native POSIX proof')

    def test_posix_exit_observation_does_not_reap_leader(self):
        process=self.CS.computerprocess
        self.assertTrue(callable(getattr(process,'_posix_exited',None)),'non-reaping POSIX observation missing')
        class Child:
            pid=12345
            def poll(inner): self.fail('poll reaped leader before group signal')
        with patch.object(process.os,'waitid',return_value=None,create=True) as observe:
            with patch.multiple(process.os,P_PID=1,WEXITED=2,WNOHANG=4,WNOWAIT=8,create=True):
                self.assertFalse(process._posix_exited(Child()))
                self.assertEqual(observe.call_args.args,(1,12345,14))
        print('[posix-wait-contract-only] exit observation requests WNOWAIT and never invokes reaping poll')

    def test_docker_cleanup_is_bound_to_launch_daemon(self):
        import shutil
        process=self.CS.computerprocess
        endpoint='npipe:////./pipe/docker_engine' if os.name=='nt' else 'unix:///var/run/docker.sock'
        for changed_identity in (False,True):
            with self.subTest(changed_identity=changed_identity):
                cid='a'*64; containers={'A':{cid},'B':set()}; default=['A']; identities={'A':'daemon-A','B':'daemon-B'}
                def docker(argv,**kwargs):
                    daemon='A' if '--host' in argv and argv[argv.index('--host')+1]==endpoint else default[0]
                    if 'context' in argv and 'inspect' in argv: out=json.dumps(endpoint)
                    elif 'info' in argv: out=identities[daemon]
                    elif 'rm' in argv:
                        containers[daemon].discard(argv[-1]); out=''
                    elif 'container' in argv and 'ls' in argv: out='\n'.join(containers[daemon])
                    else: raise AssertionError('unexpected fake daemon request '+repr(argv))
                    return subprocess.CompletedProcess(argv,0,out,'')
                relative='effects/computer/process-daemon-'+str(changed_identity)+'.json'
                path=self.root/relative; path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps({'state':'created','token':'daemon-test','job':'unused-fixture'}))
                spec={'cmd':'docker','args':['run','--rm','--network=none','fixture']}
                with patch.object(subprocess,'run',side_effect=docker), patch.object(shutil,'which',return_value=sys.executable), patch.object(process,'_job_stop'):
                    process.command(spec,str(self.root),relative)
                    metadata=json.loads(path.read_text()); metadata['state']='process_closed'; path.write_text(json.dumps(metadata))
                    (self.root/metadata['docker']['cidfile']).write_text(cid)
                    if changed_identity:
                        identities['A']='replacement-daemon'
                        with self.assertRaises(RuntimeError): process.cleanup(str(self.root),relative)
                        self.assertEqual(containers['A'],{cid},'mismatched daemon received destructive cleanup')
                        self.assertNotEqual(json.loads(path.read_text())['state'],'closed')
                    else:
                        default[0]='B'
                        process.cleanup(str(self.root),relative)
                        self.assertFalse(containers['A'],'absence on default daemon B was incorrectly called closure of A')
        print('[daemon-binding-contract] simulated daemon switch cannot redirect cleanup; changed daemon ID refuses before removal, not live daemon-failover proof')

    @unittest.skipIf(os.name=='nt','native POSIX process-group qualification requires POSIX host')
    def test_native_posix_exited_leader_and_descendant_cleanup(self):
        process=self.CS.computerprocess; marker=self.root/'posix-descendant'
        descendant='import pathlib,time,sys; p=pathlib.Path(sys.argv[1]); [(p.open("ab").write(b"x"),time.sleep(.05)) for _ in range(100)]'
        leader='import subprocess,sys; subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]])'
        child=subprocess.Popen([sys.executable,'-c',leader,descendant,str(marker)],start_new_session=True)
        try:
            wait_file(marker)
            deadline=time.monotonic()+3
            while not process._posix_exited(child):
                if time.monotonic()>deadline: self.fail('leader did not exit')
                time.sleep(.02)
            self.assertIsNone(child.returncode,'leader was reaped before cleanup')
            process._posix_stop(child)
            with self.assertRaises(ProcessLookupError): os.killpg(child.pid,0)
            size=marker.stat().st_size; time.sleep(.2); self.assertEqual(marker.stat().st_size,size)
        finally:
            # Signal only while the leader is still our unreaped child. Never
            # target a stale group ID after the tested cleanup has reaped it.
            if child.returncode is None:
                try: os.killpg(child.pid,process.signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait(timeout=3)
        print('[native-posix-closure] exited leader identity retained until termination; independent group absence and descendant stop confirmed')

def owner(root, stage):
    import computersession
    task = {'id':'task-one','lineage':'lineage-one','role':'worker','status':'running'}
    s = computersession.ComputerSession(root,task,'fixture','r1')
    receipt = s.open('https://example.com/')['observation']
    if stage=='prepared':
        original = s.server.call
        def held(*args,**kwargs):
            Path(root,'ready').touch()
            while True: time.sleep(.05)
        s.server.call = held
    if stage=='blocked':
        threading.Thread(target=lambda:s.server.call('stop_reading',{}),daemon=True).start()
        wait_file(Path(root,'ready'))
        s.server.call('blocked_write',{'payload':'x'*2_000_000})
        return
    s.click(receipt,'one')

if __name__=='__main__':
    if '--owner' in sys.argv: owner(sys.argv[2],sys.argv[3])
    else: unittest.main()
