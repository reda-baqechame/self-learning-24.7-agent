"""Opt-in real Chromium synthetic actionability; no provider or external network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import computeruse as C
import mcp
import org

DOCKER = 'C:/Program Files/Docker/Docker/resources/bin/docker.exe' if os.name == 'nt' else 'docker'
IMAGE = 'mcr.microsoft.com/playwright/mcp@sha256:add8756264bc95962597d2e5095b66317acb1d89a7c8b64f264e7d2dee140bc9'
ORIGIN = 'http://127.0.0.1:8765'
CHANGES = {
    'hidden': "a.style.visibility='hidden'",
    'covered': "const cover=document.createElement('div');cover.style='position:absolute;left:0;top:0;width:400px;height:200px;z-index:9';document.body.append(cover)",
    'disabled': "a.setAttribute('disabled','')",
    'aria-disabled': "a.setAttribute('aria-disabled','true')",
    'detached': "a.remove()",
    'duplicate': "document.body.append(a.cloneNode(true))",
    'moved': "a.style.left='80px'",
    'replaced': "a.replaceWith(a.cloneNode(true))",
    'frame-replaced': "const f=document.createElement('iframe');document.body.append(f);f.contentDocument.body.append(a);f.contentDocument.addEventListener('click',e=>{if(e.target.closest('a')){e.preventDefault();window.activations++;if(e.isTrusted)window.trustedActivations++;}})",
}

def run():
    if os.environ.get('AGENT_COMPUTER_LIVE') != '1':
        print('SKIP test_computeruse_live: set AGENT_COMPUTER_LIVE=1 for pinned network-none Chromium fixture')
        return
    name = 'agent-click-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='click-') as tmp:
        root = Path(tmp)
        output = root/'output'; output.mkdir()
        org.create(str(root),'Synthetic click fixture','fixture-owner@example.invalid')
        org.set_policy(str(root),'fixture-owner@example.invalid','agents_may_reach_internal_network',True)
        tools = ['browser_navigate','browser_evaluate','browser_run_code_unsafe','browser_tabs']
        spec = {'cmd':DOCKER,'args':['run','-i','--rm','--init','--pull=never','--name='+name,
            '--network=none','--read-only','--tmpfs=/tmp:rw,nosuid,nodev,size=256m',
            '--tmpfs=/home/node:rw,nosuid,nodev,size=64m,uid=1000,gid=1000',
            '--memory=1g','--pids-limit=256','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--mount',f'type=bind,source={Path(__file__).parent/"computer-click-fixture"},target=/fixture,readonly',
            '--mount',f'type=bind,source={output},target=/artifacts',
            '--entrypoint=sh',IMAGE,'-c','node /fixture/server.cjs & exec node /app/cli.js --headless --browser chromium --no-sandbox --isolated --snapshot-mode=none --output-dir=/artifacts --timeout-action=1000 --timeout-navigation=3000'],
            'env_allow':[],'allow_roles':['default'],'allow_tools':tools,'approval':'all','no_approval':tools,
            'version':'0.0.79','integrity':IMAGE.split('@')[1],'atomic_browser_adapter':True,
            'computer_locator_tool':'browser_run_code_unsafe'}
        spec['trust_identity']=mcp.server_identity(spec)
        (root/'mcp.json').write_text(json.dumps({'servers':{'click-fixture':spec}}),encoding='utf-8')
        server = None
        def code(js):
            result, how = mcp.computer_guarded_call(server,'browser_run_code_unsafe',{'code':js},root=str(root),fresh=True)
            assert how == 'live' and not result.get('isError'), result
            return C._playwright_json(result)
        def navigate():
            result, how = mcp.guarded_call(server,'browser_navigate',{'url':ORIGIN},root=str(root),fresh=True)
            assert how == 'live' and not result.get('isError'), result
        try:
            server=mcp.connect(str(root),'click-fixture',timeout=15)
            inspected=subprocess.run([DOCKER,'inspect',name],capture_output=True,text=True,check=True,timeout=15,env=mcp.server_environment({}))
            actual=json.loads(inspected.stdout)[0]
            assert actual['HostConfig']['NetworkMode']=='none' and actual['HostConfig']['ReadonlyRootfs']
            assert actual['Config']['User']=='node' and len(actual['Mounts'])==2
            navigate()
            print('[chromium] '+json.dumps(code('async page => ({version:page.context().browser().version()})')),flush=True)
            for case in [*CHANGES,'valid','document-replaced','tab-replaced',
                         'wrong-tab-binding','wrong-frame-binding','unknown-after-dispatch']:
                navigate()
                auth=C.BrowserAuthority(ORIGIN,max_age=20)
                observed=C.playwright_observe(server,str(root))
                if case in ('wrong-tab-binding','wrong-frame-binding'):
                    observed['binding']['tab' if case=='wrong-tab-binding' else 'frame']='wrong'
                receipt=auth.observe(observed)
                if case in CHANGES:
                    code('async page => {await page.evaluate(()=>{const a=document.querySelector("a");'+CHANGES[case]+'});return {ok:true}}')
                elif case == 'document-replaced':
                    code('async page => {await page.reload();return {ok:true}}')
                elif case == 'tab-replaced':
                    result,how=mcp.guarded_call(server,'browser_tabs',{'action':'new'},root=str(root),fresh=True)
                    assert how=='live' and not result.get('isError')
                    navigate()
                def click(p):
                    if case == 'unknown-after-dispatch':
                        with patch.object(C,'playwright_observe',side_effect=C.Unresolved('lost post readback')):
                            return C.playwright_atomic_click(server,str(root),p)
                    return C.playwright_atomic_click(server,str(root),p)
                try:
                    result=auth.execute_click(receipt,'INV-0',time.monotonic()+5,click)
                    outcome='ACTION_DISPATCHED'
                    if case == 'valid':
                        assert result['status']=='ACTION_DISPATCHED' and not result['workflow_verified']
                        assert result['post_observation']['url']==ORIGIN+'/'
                except C.Refused:
                    outcome='REFUSED'
                except C.Unresolved:
                    outcome='UNKNOWN'
                counters=code('''async page => {let count=0,trusted=0;
                    for(const tab of page.context().pages()){
                        const c=await tab.evaluate(()=>({count:window.activations||0,trusted:window.trustedActivations||0}));
                        count+=c.count;trusted+=c.trusted;
                    }return {count,trusted};}''')
                count=counters['count']
                expected='ACTION_DISPATCHED' if case=='valid' else 'UNKNOWN' if case=='unknown-after-dispatch' else 'REFUSED'
                expected_count=1 if case in ('valid','unknown-after-dispatch') else 0
                print(f'[real-click:{case}] {outcome}, activations={count}, expected={expected}/{expected_count}',flush=True)
                assert (outcome,count)==(expected,expected_count), case
                assert counters['trusted']==expected_count, 'click must deliver trusted user input'
                try:
                    auth.execute_click(receipt,'INV-0',time.monotonic()+5,click)
                    raise AssertionError('consumed receipt reused')
                except C.Refused:
                    pass
        finally:
            if server:
                server.close()
            subprocess.run([DOCKER,'stop','--time=2',name],capture_output=True,timeout=15,env=mcp.server_environment({}))
            stopped=subprocess.run([DOCKER,'ps','-a','--filter','name=^/'+name+'$','--format','{{.ID}}'],capture_output=True,text=True,check=True,timeout=15,env=mcp.server_environment({}))
            assert not stopped.stdout.strip(), 'fixture container remains'
    print('PASS test_computeruse_live')

if __name__=='__main__':
    run()
