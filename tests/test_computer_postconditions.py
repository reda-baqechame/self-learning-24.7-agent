"""CU-1 witnesses: executor dispatch cannot certify an invoice outcome."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import computersession
import computeruse as C
import computerverify
import fileauth
import loop
import mcp


class Postconditions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cu1-',dir=os.getenv('AGENT_TEST_TMP'))
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.task={'id':'invoice-task','lineage':'invoice-lineage','role':'worker','status':'running'}
        self.spec={'cmd':sys.executable,
                   'args':[str(Path(__file__).with_name('computer_session_fixture.py')),str(self.root)],
                   'atomic_browser_adapter':True,
                   'computer_locator_tool':'browser_run_code_unsafe','approval':'none',
                   'allow_roles':['worker'],
                   'computer_policy':{'revision':'r1','allowed_origin':'https://example.com'}}
        self.spec['trust_identity']=mcp.server_identity(self.spec)
        (self.root/'mcp.json').write_text(json.dumps({'servers':{'fixture':self.spec}}))
        (self.root/'settings.toml').write_text(
            '[agent]\n[roles.worker]\ntools=["computer_open","computer_observe","computer_click"]\n')
        self.output_rel='effects/computer/artifacts'
        (self.root/self.output_rel).mkdir(parents=True)
        self.manifest=self._manifest()
        self.source={'identity':'owner.synthetic.invoice-manifest',
                     'version':'2026-08-v1',
                     'sha256':computerverify.canonical_digest(self.manifest)}
        self.intents=[
            {'target_id':'one','invoice_id':'INV-0','destination':'https://example.com/one'},
            {'target_id':'two','invoice_id':'INV-1','destination':'https://example.com/two'}]
        work={'output_dir':self.output_rel,'targets':{
            'one':{'file':'INV-0.json','content':self._content(0)},
            'two':{'file':'INV-1.json','content':self._content(1)}}}
        (self.root/'invoice-work.json').write_text(json.dumps(work),encoding='utf-8')

    def _content(self,index):
        return {'id':'INV-'+str(index),'month':'2026-08',
                'account':'fixture-owner@example.invalid','total_cents':1200+index}

    def _manifest(self):
        rows=[]
        for index in range(2):
            raw=json.dumps(self._content(index),separators=(',',':')).encode()
            rows.append({'id':'INV-'+str(index),'file':'INV-'+str(index)+'.json',
                         'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                         'total_cents':1200+index})
        return {'month':'2026-08','account':'fixture-owner@example.invalid','invoices':rows}

    def session(self):
        value=computersession.ComputerSession(str(self.root),self.task,'fixture','r1')
        self.addCleanup(value.close,'test cleanup')
        return value

    def freeze(self,session,intents=None):
        selected=intents or self.intents
        ids={intent['invoice_id'] for intent in selected}
        manifest=dict(self.manifest,invoices=[row for row in self.manifest['invoices']
                                              if row['id'] in ids])
        source=dict(self.source,sha256=computerverify.canonical_digest(manifest))
        return session.freeze_invoice_workflow(
            self.output_rel,manifest,source,
            'fixture-owner@example.invalid',selected,
            deadline_seconds=20)

    def click(self,session,workflow,target):
        opened=session.open('https://example.com/')
        return session.click(opened['observation'],target,
                             workflow_id=workflow['workflow_id'])

    def test_index_precedes_dispatch_and_deleted_index_with_history_fails_done(self):
        session=self.session()
        index=Path(computerverify.index_path(str(self.root),self.task['lineage']))
        self.assertTrue(index.exists())
        receipt=session.open('https://example.com/')['observation']
        session.click(receipt,'one')
        index.unlink()
        agent=loop.Agent(str(self.root))
        self.addCleanup(lambda:[(handler.close(),agent.log.removeHandler(handler))
                                for handler in list(agent.log.handlers)])
        passed,evidence=agent.check_done(self.task)
        self.assertFalse(passed); self.assertIn('index',evidence.lower())

    def test_no_index_passes_only_with_authenticated_empty_lineage_census(self):
        empty=self.root/'empty'; empty.mkdir()
        self.assertEqual(computerverify.completion_status(
            str(empty),self.task),(True,'no computer history'))

    def test_exact_prefix_verifies_each_action_and_full_workflow_gate(self):
        session=self.session(); workflow=self.freeze(session)
        first=self.click(session,workflow,'one')
        self.assertEqual(first['status'],'ACTION_DISPATCHED')
        verified=session.verify_invoice_action(first['action_id'],workflow['workflow_id'])
        self.assertEqual(verified['result'],'VERIFIED')
        self.assertFalse(verified['workflow_verified'])
        self.assertFalse(computerverify.completion_status(str(self.root),self.task)[0])
        second=self.click(session,workflow,'two')
        final=session.verify_invoice_action(second['action_id'],workflow['workflow_id'])
        self.assertTrue(final['workflow_verified'])
        self.assertTrue(computerverify.completion_status(str(self.root),self.task)[0])
        self.assertEqual(session.verify_invoice_action(
            second['action_id'],workflow['workflow_id']),final)

    def test_output_is_leased_before_baseline_and_agent_cannot_plant(self):
        session=self.session(); observed=[]
        original=computerverify.capture_baseline
        def capture(root,output_dir,expected_binding=None):
            binding=computerverify.output_binding(root,output_dir)
            lease=fileauth.resolve(root,computerverify.output_lease_rel(binding),
                                   'write','harness')
            with self.assertRaises(TimeoutError):
                with computersession.locks.advisory_holding(lease,timeout=0): pass
            observed.append(True)
            return original(root,output_dir,expected_binding)
        with mock.patch.object(computerverify,'capture_baseline',side_effect=capture):
            self.freeze(session)
        self.assertEqual(observed,[True])
        with self.assertRaises(fileauth.Denied):
            fileauth.write_text(str(self.root),self.output_rel+'/INV-0.json',
                                json.dumps(self._content(0)),actor='agent')
        unprotected=self.root/'out'; unprotected.mkdir()
        with self.assertRaises(C.Refused):
            session.freeze_invoice_workflow('out',self.manifest,self.source,
                'fixture-owner@example.invalid',self.intents,deadline_seconds=20)

    @unittest.skipUnless(os.name=='nt','Windows filesystem alias contract')
    def test_case_alias_cannot_claim_second_lease_for_same_output(self):
        session=self.session(); self.freeze(session)
        alias=self.output_rel.upper()
        self.assertEqual(computerverify.output_binding(str(self.root),alias),
                         computerverify.output_binding(str(self.root),self.output_rel))
        lease=fileauth.resolve(str(self.root),computerverify.output_lease_rel(
            computerverify.output_binding(str(self.root),alias)),'write','harness')
        with self.assertRaises(TimeoutError):
            with computersession.locks.advisory_holding(lease,timeout=0): pass

    def test_one_session_cannot_freeze_two_workflows_on_same_output(self):
        session=self.session(); first=self.freeze(session,[self.intents[0]])
        with self.assertRaises(C.Refused):
            self.freeze(session,[self.intents[1]])
        self.assertEqual(len(session._load()['workflows']),1)
        self.assertEqual(session._load()['workflows'][0]['id'],first['workflow_id'])

    def test_one_session_output_lease_rejects_another_claimant(self):
        session=self.session()
        session._hold_output_path(self.output_rel,'claimant-one')
        with self.assertRaises(C.Refused):
            session._hold_output_path(self.output_rel,'claimant-two')

    def test_durable_output_claim_survives_close_and_reopen(self):
        session=self.session(); first=self.freeze(session,[self.intents[0]])
        session.close('restart before dispatch')
        reopened=self.session()
        with self.assertRaises(C.Refused):
            self.freeze(reopened,[self.intents[1]])
        workflows=reopened._load()['workflows']
        self.assertEqual([item['id'] for item in workflows],[first['workflow_id']])

    def test_durable_output_claim_blocks_different_server_and_lineage(self):
        session=self.session(); self.freeze(session,[self.intents[0]])
        session.close('restart into another ledger')
        config=json.loads((self.root/'mcp.json').read_text())
        second_spec=dict(self.spec)
        second_spec['trust_identity']=mcp.server_identity(second_spec)
        config['servers']['fixture-two']=second_spec
        (self.root/'mcp.json').write_text(json.dumps(config))
        other_task=dict(self.task,id='other-task',lineage='other-lineage')
        other=computersession.ComputerSession(
            str(self.root),other_task,'fixture-two','r1')
        self.addCleanup(other.close,'other cleanup')
        with self.assertRaises(C.Refused):
            self.freeze(other,[self.intents[1]])
        self.assertEqual(other._load()['workflows'],[])

    def test_orphan_prepared_output_claim_aborts_and_allows_retry(self):
        session=self.session(); original=computerverify.write_output_claim
        def crash_after_write(root,claim):
            original(root,claim)
            raise OSError('injected crash after claim write')
        with mock.patch.object(computerverify,'write_output_claim',side_effect=crash_after_write):
            with self.assertRaises(OSError): self.freeze(session,[self.intents[0]])
        session.close('recover orphan claim')
        reopened=self.session()
        workflow=self.freeze(reopened,[self.intents[0]])
        self.assertTrue(workflow['workflow_id'])

    def test_prepared_claim_commits_when_exact_workflow_index_recovers(self):
        session=self.session(); original=session._save_index; calls=[]
        def fail_commit(value):
            calls.append(value.get('state'))
            if len(calls)==2: raise OSError('injected crash before index commit')
            return original(value)
        with mock.patch.object(session,'_save_index',side_effect=fail_commit):
            with self.assertRaises(OSError): self.freeze(session,[self.intents[0]])
        session.close('recover prepared workflow')
        reopened=self.session()
        with self.assertRaises(C.Refused): self.freeze(reopened,[self.intents[1]])
        binding=computerverify.output_binding(str(self.root),self.output_rel)
        self.assertEqual(computerverify.read_output_claim(
            str(self.root),binding)['state'],'COMMITTED')

    def test_prepared_claim_with_tampered_contract_aborts_not_commits(self):
        session=self.session()
        with mock.patch.object(computerverify,'commit_output_claim',
                               side_effect=OSError('injected crash before claim commit')):
            with self.assertRaises(OSError): self.freeze(session,[self.intents[0]])
        data=session._load()
        data['workflows'][0]['contract']['deadline_at']+=1
        session._save(data); session.close('recover tampered claim')
        reopened=self.session()
        workflow=self.freeze(reopened,[self.intents[1]])
        self.assertTrue(workflow['workflow_id'])
        binding=computerverify.output_binding(str(self.root),self.output_rel)
        claim=computerverify.read_output_claim(str(self.root),binding)
        self.assertEqual(claim['state'],'COMMITTED')
        self.assertIsNotNone(claim['prior_claim_sha256'])

    def test_unresolved_navigation_and_dispatched_action_block_completion(self):
        session=self.session()
        session.open('https://example.com/')
        data=session._load(); data['actions'][-1]['state']='UNKNOWN'; session._save(data)
        passed,why=computerverify.completion_status(str(self.root),self.task)
        self.assertFalse(passed); self.assertIn('unresolved',why)
        data=session._load(); data['actions'][-1]['state']='DISPATCHED'; session._save(data)
        passed,why=computerverify.completion_status(str(self.root),self.task)
        self.assertFalse(passed); self.assertIn('unresolved',why)

    def test_noop_and_future_extra_never_receive_verified_receipt(self):
        for mode in ('no_op','create_future'):
            with self.subTest(mode=mode):
                child=self.root/mode; child.mkdir()
                original=self.root; self.root=child
                (child/self.output_rel).mkdir(parents=True); (child/'mcp.json').write_text(json.dumps({'servers':{'fixture':dict(self.spec,args=[self.spec['args'][0],str(child)])}}))
                spec=json.loads((child/'mcp.json').read_text())['servers']['fixture']
                spec['trust_identity']=mcp.server_identity(spec)
                (child/'mcp.json').write_text(json.dumps({'servers':{'fixture':spec}}))
                (child/'settings.toml').write_text('[agent]\n[roles.worker]\ntools=[]\n')
                work={'output_dir':self.output_rel,'targets':{'one':{'file':'INV-0.json','content':self._content(0)},
                                 'two':{'file':'INV-1.json','content':self._content(1)}},mode:{'one':['two']} if mode=='create_future' else ['one']}
                (child/'invoice-work.json').write_text(json.dumps(work))
                try:
                    session=self.session(); workflow=self.freeze(session)
                    action=self.click(session,workflow,'one')
                    with self.assertRaises(C.Refused):
                        session.verify_invoice_action(action['action_id'],workflow['workflow_id'])
                    stored=next(a for a in session.actions() if a['id']==action['action_id'])
                    self.assertEqual(stored['state'],'FAILED_POSTCONDITION')
                    self.assertNotIn('postcondition_receipt',stored)
                    self.assertEqual(stored['verification_attempts'][-1]['result'],'REFUSED')
                finally:
                    self.root=original

    def test_predispatch_refusal_does_not_consume_frozen_intent(self):
        session=self.session(); workflow=self.freeze(session,[self.intents[0]])
        opened=session.open('https://example.com/')
        with mock.patch.object(session.authority,'execute_click',
                               side_effect=C.Refused('stale observation')):
            with self.assertRaises(C.Refused):
                session.click(opened['observation'],'one',
                              workflow_id=workflow['workflow_id'])
        data=session._load(); refused=data['actions'][-1]
        self.assertEqual(refused['state'],'REFUSED')
        self.assertNotIn(refused['id'],data['workflows'][0]['action_ids'])
        retried=self.click(session,workflow,'one')
        self.assertEqual(session.verify_invoice_action(
            retried['action_id'],workflow['workflow_id'])['result'],'VERIFIED')
        self.assertTrue(computerverify.completion_status(str(self.root),self.task)[0])

    def test_unknown_is_never_overwritten_but_independent_resolution_is_usable(self):
        session=self.session(); one=[self.intents[0]]; workflow=self.freeze(session,one)
        action=self.click(session,workflow,'one'); session.close('crash boundary')
        self.assertEqual(next(a for a in session.actions() if a['id']==action['action_id'])['state'],'UNKNOWN')
        recovered=self.session()
        receipt=recovered.verify_invoice_action(action['action_id'],workflow['workflow_id'])
        stored=next(a for a in recovered.actions() if a['id']==action['action_id'])
        self.assertEqual(stored['state'],'UNKNOWN')
        data=recovered._load(); bound_workflow=data['workflows'][0]
        self.assertEqual(computerverify.effective_action_status(
            str(self.root),stored,bound_workflow,bound_workflow['contract']),
            'VERIFIED_BY_POSTCONDITION')
        self.assertEqual(stored['postcondition_resolutions'][-1]['receipt'],receipt)
        self.assertTrue(computerverify.completion_status(str(self.root),self.task)[0])

    def test_simultaneous_finalizers_are_idempotent_and_attempt_history_is_retained(self):
        session=self.session(); workflow=self.freeze(session,[self.intents[0]])
        action=self.click(session,workflow,'one')
        results=[]; errors=[]
        def finish():
            try: results.append(session.verify_invoice_action(action['action_id'],workflow['workflow_id']))
            except BaseException as error: errors.append(error)
        workers=[threading.Thread(target=finish) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        self.assertFalse(errors); self.assertEqual(len(results),2)
        self.assertEqual(results[0],results[1])
        stored=next(a for a in session.actions() if a['id']==action['action_id'])
        self.assertEqual([x['result'] for x in stored['verification_attempts']],['VERIFIED'])

    def test_changed_output_after_receipt_fails_current_completion_readback(self):
        session=self.session(); workflow=self.freeze(session,[self.intents[0]])
        action=self.click(session,workflow,'one')
        session.verify_invoice_action(action['action_id'],workflow['workflow_id'])
        path=self.root/self.output_rel/'INV-0.json'
        path.write_bytes(path.read_bytes().replace(b'1200',b'1209'))
        passed,why=computerverify.completion_status(str(self.root),self.task)
        self.assertFalse(passed); self.assertIn('differ',why)

    def test_manifest_source_account_and_old_output_refuse_before_dispatch(self):
        session=self.session()
        bad_source=dict(self.source,sha256='0'*64)
        with self.assertRaises(C.Refused):
            session.freeze_invoice_workflow(self.output_rel,self.manifest,bad_source,
                self.manifest['account'],self.intents,deadline_seconds=20)
        with self.assertRaises(C.Refused):
            session.freeze_invoice_workflow(self.output_rel,self.manifest,self.source,
                'other@example.invalid',self.intents,deadline_seconds=20)
        (self.root/self.output_rel/'INV-0.json').write_text('old')
        with self.assertRaises(C.Refused): self.freeze(session)
        self.assertFalse(any(action.get('operation')=='click'
                             for action in session.actions()))

    def test_unavailable_verifier_retains_attempt_and_becomes_unknown_on_close(self):
        session=self.session(); workflow=self.freeze(session,[self.intents[0]])
        action=self.click(session,workflow,'one')
        with mock.patch.object(computerverify,'verify_prefix',
                               side_effect=OSError('verifier offline')):
            with self.assertRaises(C.Refused):
                session.verify_invoice_action(action['action_id'],workflow['workflow_id'])
        stored=next(a for a in session.actions() if a['id']==action['action_id'])
        self.assertEqual(stored['state'],'DISPATCHED')
        self.assertEqual(stored['verification_attempts'][-1]['result'],'UNAVAILABLE')
        session.close('unavailable verifier')
        stored=next(a for a in session.actions() if a['id']==action['action_id'])
        self.assertEqual(stored['state'],'UNKNOWN')

    def test_deadline_and_interruption_never_become_failed_postcondition(self):
        session=self.session(); workflow=self.freeze(session,[self.intents[0]])
        action=self.click(session,workflow,'one')
        deadline=session._load()['workflows'][0]['contract']['deadline_at']
        with mock.patch.object(computerverify.time,'time',return_value=deadline+1):
            with self.assertRaises(C.Refused):
                session.verify_invoice_action(action['action_id'],workflow['workflow_id'])
        stored=next(a for a in session.actions() if a['id']==action['action_id'])
        self.assertEqual(stored['state'],'DISPATCHED')
        self.assertEqual(stored['verification_attempts'][-1]['result'],'UNAVAILABLE')

        other=self.root/'interrupt'; other.mkdir(); original=self.root; self.root=other
        try:
            (other/self.output_rel).mkdir(parents=True)
            spec=dict(self.spec,args=[self.spec['args'][0],str(other)])
            spec['trust_identity']=mcp.server_identity(spec)
            (other/'mcp.json').write_text(json.dumps({'servers':{'fixture':spec}}))
            (other/'settings.toml').write_text('[agent]\n[roles.worker]\ntools=[]\n')
            (other/'invoice-work.json').write_text(json.dumps({'output_dir':self.output_rel,
                'targets':{'one':{'file':'INV-0.json','content':self._content(0)}}}))
            second=self.session(); frozen=self.freeze(second,[self.intents[0]])
            clicked=self.click(second,frozen,'one')
            with mock.patch.object(computerverify,'verify_prefix',side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    second.verify_invoice_action(clicked['action_id'],frozen['workflow_id'])
            stored=next(a for a in second.actions() if a['id']==clicked['action_id'])
            self.assertEqual(stored['state'],'DISPATCHED')
            self.assertEqual(stored['verification_attempts'][-1]['result'],'INTERRUPTED')
        finally: self.root=original

    def test_recomputed_forged_receipt_cannot_authorize_next_action(self):
        session=self.session(); workflow=self.freeze(session)
        first=self.click(session,workflow,'one')
        session.verify_invoice_action(first['action_id'],workflow['workflow_id'])
        data=session._load(); action=next(a for a in data['actions'] if a['id']==first['action_id'])
        receipt=action['postcondition_receipt']; receipt['intent_key']='forged'
        body={key:value for key,value in receipt.items()
              if key not in ('receipt_id','receipt_sha256')}
        receipt['receipt_id']=receipt['receipt_sha256']=computerverify.canonical_digest(body)
        attempt=action['verification_attempts'][-1]
        attempt['receipt_id']=receipt['receipt_id']
        attempt['receipt_sha256']=receipt['receipt_sha256']
        session._save(data)
        changed=session._load(); changed_action=next(
            a for a in changed['actions'] if a['id']==first['action_id'])
        self.assertFalse(computerverify._valid_receipt(
            str(self.root),changed_action,changed['workflows'][0],
            changed['workflows'][0]['contract']))
        opened=session.open('https://example.com/')
        with self.assertRaises(C.Refused):
            session.click(opened['observation'],'two',workflow_id=workflow['workflow_id'])

    def test_receipt_requires_durable_cleanup_and_action_contract_history(self):
        session=self.session(); workflow=self.freeze(session)
        first=self.click(session,workflow,'one')
        session.verify_invoice_action(first['action_id'],workflow['workflow_id'])
        data=session._load(); bound=data['workflows'][0]
        action=next(a for a in data['actions'] if a['id']==first['action_id'])
        action['contract_sha256']='0'*64
        self.assertFalse(computerverify._valid_receipt(
            str(self.root),action,bound,bound['contract']))
        action['contract_sha256']=bound['contract_sha256']
        receipt=action['postcondition_receipt']; attempt=action['verification_attempts'][-1]
        def rehash():
            body={key:value for key,value in receipt.items()
                  if key not in ('receipt_id','receipt_sha256')}
            receipt['receipt_id']=receipt['receipt_sha256']=computerverify.canonical_digest(body)
            attempt['receipt_id']=receipt['receipt_id']
            attempt['receipt_sha256']=receipt['receipt_sha256']
        receipt['cleanup_receipt']=dict(action['cleanup_receipt'],
                                        confirmed_at=action['cleanup_receipt']['confirmed_at']+1)
        rehash()
        self.assertFalse(computerverify._valid_receipt(
            str(self.root),action,bound,bound['contract']))
        receipt['cleanup_receipt']=dict(action['cleanup_receipt']); rehash()
        action['cleanup_receipt']['metadata_sha256']='0'*64
        receipt['cleanup_receipt']=dict(action['cleanup_receipt'])
        rehash()
        self.assertFalse(computerverify._valid_receipt(
            str(self.root),action,bound,bound['contract']))

    def test_reordered_intents_verify_against_their_own_manifest_rows(self):
        session=self.session(); reversed_intents=list(reversed(self.intents))
        workflow=self.freeze(session,reversed_intents)
        first=self.click(session,workflow,'two')
        self.assertEqual(session.verify_invoice_action(
            first['action_id'],workflow['workflow_id'])['result'],'VERIFIED')
        second=self.click(session,workflow,'one')
        self.assertTrue(session.verify_invoice_action(
            second['action_id'],workflow['workflow_id'])['workflow_verified'])

    def test_prepared_index_and_cross_task_contract_fail_completion(self):
        session=self.session(); workflow=self.freeze(session,[self.intents[0]])
        action=self.click(session,workflow,'one')
        session.verify_invoice_action(action['action_id'],workflow['workflow_id'])
        other=dict(self.task,id='other-task')
        self.assertFalse(computerverify.completion_status(str(self.root),other)[0])
        index=Path(computerverify.index_path(str(self.root),self.task['lineage']))
        value=json.loads(index.read_text()); value['state']='PREPARED'
        value['pending']={'kind':'workflow','ledger':'missing','workflow_id':'x',
                          'contract_sha256':'0'*64}
        index.write_text(json.dumps(value))
        self.assertFalse(computerverify.completion_status(str(self.root),self.task)[0])

    def test_duplicate_action_identity_blocks_completion(self):
        session=self.session(); workflow=self.freeze(session,[self.intents[0]])
        action=self.click(session,workflow,'one')
        session.verify_invoice_action(action['action_id'],workflow['workflow_id'])
        data=session._load(); duplicate=dict(data['actions'][-1])
        duplicate['state']='REFUSED'; duplicate['required_for_task']=False
        duplicate.pop('postcondition_receipt',None)
        duplicate.pop('verification_attempts',None)
        data['actions'].insert(-1,duplicate); session._save(data)
        passed,why=computerverify.completion_status(str(self.root),self.task)
        self.assertFalse(passed); self.assertIn('identity',why.lower())

    def test_malformed_persisted_baseline_fails_closed_without_exception(self):
        session=self.session(); self.freeze(session,[self.intents[0]])
        data=session._load(); data['workflows'][0]['contract']['baseline']=None
        session._save(data)
        passed,why=computerverify.completion_status(str(self.root),self.task)
        self.assertFalse(passed); self.assertIn('baseline',why.lower())

    def test_each_reconnect_uses_a_fresh_environment_incarnation(self):
        session=self.session(); workflow=self.freeze(session)
        first=self.click(session,workflow,'one')
        session.verify_invoice_action(first['action_id'],workflow['workflow_id'])
        second=self.click(session,workflow,'two')
        session.verify_invoice_action(second['action_id'],workflow['workflow_id'])
        history=session._load()['environment_history']
        self.assertEqual(len(history),2); self.assertEqual(len(set(history)),2)


if __name__=='__main__': unittest.main()
