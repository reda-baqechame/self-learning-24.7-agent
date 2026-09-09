"""Local protocol fixture, not a browser or acceptance benchmark."""
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import base64

root = Path(sys.argv[1])
url = 'https://example.com/'
document = 1
if (root/'spawn-grandchild').exists():
    # Bounded lifetime limits damage under the deliberately broken cleanup mutant.
    subprocess.Popen([sys.executable,'-c',
        'import pathlib,time,sys; p=pathlib.Path(sys.argv[1]); '
        '[(p.open("ab").write(b"x"),time.sleep(.05)) for _ in range(100)]',
        str(root/'grandchild-ticks')],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def reply(mid, result):
    print(json.dumps({'jsonrpc':'2.0', 'id':mid, 'result':result}), flush=True)
def state():
    return {'url':url, 'title':'Local fixture', 'dialog':False, 'expired':False,
            'view_context':None if (root/'omit-view-context').exists() else {
                'viewport':{'width':int((root/'viewport-width').read_text()) if (root/'viewport-width').exists() else 800,'height':600},
                'viewport_source':'playwright_host','device_scale':1,'device_scale_source':'page_untrusted'},
            'binding':{'tab':'tab-one', 'frame':'main', 'document':document},
            'links':[{'id':name, 'href':'https://example.com/'+name,
                      'text':name, 'box':{'x':1,'y':1,'width':20,'height':10}}
                     for name in ('one','two')]}
def invoice_effect(target):
    """Controlled executor output for CU-1 tests; never verifier evidence."""
    config = root/'invoice-work.json'
    if not config.exists():
        return
    work = json.loads(config.read_text(encoding='utf-8'))
    if target in work.get('no_op',[]):
        return
    output = root/work.get('output_dir','output'); output.mkdir(parents=True,exist_ok=True)
    rows = work['targets']
    selected = [target]
    if target in work.get('create_future',{}):
        selected += list(work['create_future'][target])
    for name in selected:
        row = rows[name]
        (output/row['file']).write_text(json.dumps(row['content'],separators=(',',':')),encoding='utf-8')
try:
    for line in sys.stdin:
        msg = json.loads(line)
        mid, method = msg.get('id'), msg.get('method')
        if method == 'initialize':
            reply(mid, {'protocolVersion':'2025-06-18'})
        elif method == 'tools/list':
            reply(mid, {'tools':[{'name':name,'annotations':{'readOnlyHint':True}}
                                for name in ('browser_navigate','browser_run_code_unsafe')]})
        elif method == 'tools/call':
            params = msg['params']; args = params['arguments']
            if params['name']=='stop_reading':
                (root/'ready').touch(); time.sleep(10); continue
            with (root/'calls.jsonl').open('a') as f:
                f.write(json.dumps({'pid':os.getpid(),'tool':params['name']})+'\n')
            if params['name'] == 'browser_navigate':
                url = args['url']; document += 1
                if (root/'redirect-outside').exists(): url='https://outside.example/'
                result = {'content':[]}
            else:
                code = args['code']
                if 'const p=' in code:
                    p = json.JSONDecoder().raw_decode(code.split('const p=',1)[1])[0]
                    if p.get('view_context',{}).get('viewport')!=(state()['view_context'] or {}).get('viewport'):
                        reply(mid,{'content':[{'type':'text','text':'### Result\n'+json.dumps({'refused':'viewport changed'})}]})
                        continue
                    (root/'effect-seen').write_text(p['target']['id'])
                    invoice_effect(p['target']['id'])
                    if (root/'hold-response').exists():
                        continue
                    data = {'status':'ACTION_DISPATCHED','clicked':True,
                            'precondition_sha256':p['state_sha256'],
                            'destination':p['target']['href']}
                else:
                    data = state()
                result = {'content':[{'type':'text','text':'### Result\n'+json.dumps(data)}]}
                if (root/'emit-image').exists():
                    raw=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44ae426082')
                    result['content'].append({'type':'image','data':base64.b64encode(raw).decode(),'mimeType':'image/png'})
            reply(mid,result)
finally:
    (root/'fixture-exited').write_text(str(os.getpid()))
