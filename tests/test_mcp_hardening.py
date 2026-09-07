"""Local regression fixtures; no packages are installed or provider keys used."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcp


class MCPHardening(unittest.TestCase):
    def test_child_does_not_inherit_ungranted_environment(self):
        # A real child reports only the names of planted values, never secrets.
        code = "import os,json,sys; q=json.loads(sys.stdin.readline()); print(json.dumps({'id':q['id'],'result':{k:os.getenv(k) for k in ['OPENAI_API_KEY','AWS_SECRET_ACCESS_KEY','GITHUB_TOKEN','INNOCENT_CONFIG','PATH']}}),flush=True); sys.stdin.read()"
        with patch.dict(os.environ, {'OPENAI_API_KEY':'planted-model',
                'AWS_SECRET_ACCESS_KEY':'planted-cloud', 'GITHUB_TOKEN':'planted-github',
                'INNOCENT_CONFIG':'ungranted'}):
            s = mcp.Server('fixture', {'cmd':sys.executable, 'args':['-c',code],
                                     'env_allow':['GITHUB_TOKEN']})
            try:
                env = s._rpc('environment')
                self.assertIsNone(env['OPENAI_API_KEY'])
                self.assertIsNone(env['AWS_SECRET_ACCESS_KEY'])
                self.assertIsNone(env['INNOCENT_CONFIG'])
                self.assertEqual(env['GITHUB_TOKEN'], 'planted-github')
                self.assertTrue(env['PATH'])
            finally:
                s.close()

    def test_invalid_environment_grants_fail_before_spawn(self):
        for allow in ('*', ['*'], ['A=B'], [3]):
            with self.subTest(allow=allow), self.assertRaises(ValueError):
                mcp.Server('bad', {'cmd':sys.executable, 'args':['-c','pass'],
                                   'env_allow':allow})

    def protocol_server(self, result=None, error=None):
        reply = {'jsonrpc':'2.0','id':1}
        reply.update({'error':error} if error else {'result':result})
        code = 'import sys; sys.stdin.readline(); print('+repr(json.dumps(reply))+',flush=True); sys.stdin.read()'
        return mcp.Server('protocol-fixture', {'cmd':sys.executable,'args':['-c',code]}, timeout=2)

    def test_modern_rejection_is_not_fake_negotiation(self):
        s = self.protocol_server(error={'code':-32022,'message':'Unsupported protocol'})
        try:
            with self.assertRaises(RuntimeError):
                s.handshake()
            self.assertIsNone(s._era)
        finally:
            s.close()

    def test_unimplemented_version_is_rejected(self):
        s = self.protocol_server(result={'protocolVersion':'2026-07-28'})
        try:
            with self.assertRaises(RuntimeError):
                s.handshake()
        finally:
            s.close()

    def test_enable_pins_executable_and_detects_configuration_drift(self):
        with tempfile.TemporaryDirectory() as root, patch('shutil.which', return_value=sys.executable):
            path, entry = mcp.enable(root, 'playwright')
            self.assertRegex(entry['args'][1], r'^@playwright/mcp@\d+\.\d+\.\d+$')
            self.assertTrue(entry.get('integrity'))
            self.assertTrue(entry.get('trust_identity'))
            # Changing code while retaining old trust evidence must not launch.
            entry['args'][-1] = '@playwright/mcp@0.0.1'
            Path(path).write_text(json.dumps({'servers':{'playwright':entry}}))
            with patch('subprocess.Popen') as spawn, self.assertRaises(ValueError):
                mcp.connect(root, 'playwright')
            spawn.assert_not_called()

    def test_catalog_has_no_floating_executable(self):
        with tempfile.TemporaryDirectory() as root, patch('shutil.which', return_value=sys.executable):
            for name in mcp.CATALOG:
                _, entry = mcp.enable(root, name)
                args = entry['args']
                package = args[1] if entry['cmd'] == 'npx' else args[0]
                self.assertRegex(package, r'(?:@|==)\d+\.\d+\.\d+$')
                self.assertTrue(entry.get('version'))
                self.assertTrue(entry.get('source'))

    def test_code_update_invalidates_grant_but_not_completed_effect(self):
        import approvals
        import effects
        fixture = str(Path(__file__).with_name('mock_mcp_server.py'))
        with tempfile.TemporaryDirectory() as root:
            spec = {'cmd':sys.executable, 'args':[fixture], 'version':'1.0.0'}
            spec['trust_identity'] = mcp.server_identity(spec)
            config = Path(root, 'mcp.json')
            config.write_text(json.dumps({'servers':{'fixture':spec}}))
            server = mcp.connect(root, 'fixture')
            args = {'id':'disposable-record'}
            try:
                _, status = mcp.guarded_call(server, 'delete_record', args, root=root)
                self.assertEqual(status, 'approval_required')
                old = approvals.pending(root)[0]
                approvals.decide(root, old['id'], True)
            finally:
                server.close()
            spec['version'] = '1.0.1'
            spec['trust_identity'] = mcp.server_identity(spec)
            config.write_text(json.dumps({'servers':{'fixture':spec}}))
            server = mcp.connect(root, 'fixture')
            try:
                _, status = mcp.guarded_call(server, 'delete_record', args, root=root)
                self.assertEqual(status, 'approval_required')
                self.assertNotEqual(approvals.pending(root)[0]['id'], old['id'])
                self.assertFalse(Path(root, 'deleted.log').exists())
                # Code updates never make a previously completed effect repeat.
                key = effects.key_of(os.getenv('AGENT_TASK_LINEAGE') or 'manual',
                                     'fixture', 'delete_record', args)
                effects.record(root,key,'t','fixture','delete_record',args,{'content':[]})
                _, status = mcp.guarded_call(server, 'delete_record', args, root=root)
                self.assertEqual(status, 'replayed')
                self.assertFalse(Path(root, 'deleted.log').exists())
            finally:
                server.close()


class MCPTransport(unittest.TestCase):
    def server(self, body, timeout=2):
        code = ('import sys,json,time\n'
                'def read(): return json.loads(sys.stdin.readline())\n'
                'def reply(q): print(json.dumps({"id":q["id"],"result":q["method"]}),flush=True)\n'
                + body)
        server = mcp.Server('transport-fixture',
                            {'cmd':sys.executable, 'args':['-u', '-c', code]},
                            timeout=timeout)
        self.addCleanup(server.close)
        return server

    def start_call(self, server, method):
        box = {}
        def call():
            try:
                box['result'] = server._rpc(method)
            except Exception as exc:
                box['error'] = exc
        thread = threading.Thread(target=call, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        return thread, box

    def wait_pending(self, server, count):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with server._pending_lock:
                if len(server._pending) == count:
                    return
            time.sleep(.005)
        self.fail(f'{count} pending requests never registered')

    def test_timeout_late_reply_and_notifications_do_not_steal_next_response(self):
        # A surviving per-request reader or wrong-ID routing breaks B.
        s = self.server('a=read()\nb=read()\n'
                        'print(json.dumps({"method":"progress"}),flush=True)\n'
                        'print(json.dumps({"id":999,"result":"foreign"}),flush=True)\n'
                        'reply(a)\nreply(b)\nsys.stdin.read()\n', timeout=.1)
        with self.assertRaises(TimeoutError):
            s._rpc('A')
        s.timeout = 2
        self.assertEqual(s._rpc('B'), 'B')
        with s._pending_lock:
            self.assertEqual(len(s._pending), 0)

    def test_one_reader_owns_stdout_across_calls_and_timeout(self):
        # Observe actual pipe reads, without replacing the child or transport.
        owners, sizes = set(), []
        real_popen = mcp.subprocess.Popen
        class ObservedPipe:
            def __init__(self, pipe): self.pipe = pipe
            def readline(self, *args):
                owners.add(threading.current_thread())
                sizes.append(args)
                return self.pipe.readline(*args)
            def __getattr__(self, name): return getattr(self.pipe, name)
        def spawn(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            proc.stdout = ObservedPipe(proc.stdout)
            return proc
        with patch.object(mcp.subprocess, 'Popen', side_effect=spawn):
            s = self.server('a=read()\nb=read()\nreply(a)\nreply(b)\n'
                            'c=read()\nreply(c)\nsys.stdin.read()\n', timeout=.1)
        with self.assertRaises(TimeoutError):
            s._rpc('A')
        s.timeout = 2
        self.assertEqual(s._rpc('B'), 'B')
        self.assertEqual(s._rpc('C'), 'C')
        self.assertEqual(len(owners), 1, 'more than one thread consumed stdout')
        self.assertTrue(all(args == (4_194_305,) for args in sizes))

    def test_concurrent_calls_route_reversed_responses_by_id(self):
        s = self.server('a=read()\nb=read()\nreply(b)\nreply(a)\nsys.stdin.read()\n')
        a, first = self.start_call(s, 'A')
        b, second = self.start_call(s, 'B')
        a.join(3); b.join(3)
        self.assertEqual(first, {'result':'A'})
        self.assertEqual(second, {'result':'B'})

    def test_eof_wakes_all_waiters_and_refuses_future_dispatch(self):
        s = self.server('read()\nread()\nsys.stdout.close()\n', timeout=5)
        started = time.monotonic()
        a, first = self.start_call(s, 'A')
        b, second = self.start_call(s, 'B')
        a.join(1.5); b.join(1.5)
        self.assertFalse(a.is_alive() or b.is_alive(), 'EOF left waiters asleep')
        self.assertLess(time.monotonic() - started, 3)
        for box in (first, second):
            self.assertIsInstance(box.get('error'), RuntimeError)
            self.assertIn('closed', str(box['error']))
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            s._rpc('C')

    def test_oversized_unterminated_and_malformed_frames_taint_connection(self):
        for expression in ('"x" * 4_194_305', '"{bad}\\n"', '"{}"'):
            with self.subTest(frame=expression):
                tail = ('sys.stdout.close()\n' if expression == '"{}"'
                        else 'sys.stdin.read()\n')
                s = self.server('read()\nsys.stdout.write('+expression+')\n'
                                'sys.stdout.flush()\n' + tail)
                with self.assertRaisesRegex(RuntimeError, 'frame'):
                    s._rpc('A')
                with self.assertRaisesRegex(RuntimeError, 'frame'):
                    s._rpc('B')
                s.close()

    def test_pending_capacity_refuses_before_dispatch_and_timeout_releases_slot(self):
        s = self.server('for line in sys.stdin:\n'
                        ' q=json.loads(line)\n'
                        ' if q["method"] == "forbidden": sys.exit(7)\n'
                        ' if q["method"] == "B": reply(q)\n', timeout=.4)
        with patch.object(mcp, 'MAX_PENDING_REQUESTS', 1, create=True):
            a, first = self.start_call(s, 'A')
            self.wait_pending(s, 1)
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                s._rpc('forbidden')
            a.join(2)
            self.assertIsInstance(first.get('error'), TimeoutError)
            with s._pending_lock:
                self.assertEqual(len(s._pending), 0)
            self.assertEqual(s._rpc('B'), 'B')

    def test_close_wakes_waiters_and_reaps_process_and_reader(self):
        s = self.server('read()\ntime.sleep(30)\n', timeout=10)
        thread, box = self.start_call(s, 'A')
        self.wait_pending(s, 1)
        started = time.monotonic()
        s.close()
        thread.join(.5)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(box.get('error'), RuntimeError)
        self.assertIn('closed', str(box['error']))
        self.assertIsNotNone(s.proc.poll())
        self.assertFalse(s._reader.is_alive())
        s.close()
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            s._rpc('B')

    def test_default_capacity_allows_64_calls_and_refuses_65th(self):
        s = self.server('sys.stdin.read()\n', timeout=10)
        calls = [self.start_call(s, str(i)) for i in range(64)]
        self.wait_pending(s, 64)
        with self.assertRaisesRegex(RuntimeError, 'pending'):
            s._rpc('65th')
        s.close()
        for thread, box in calls:
            thread.join(.5)
            self.assertIsInstance(box.get('error'), RuntimeError)


if __name__ == '__main__':
    unittest.main()
