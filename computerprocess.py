"""Owned stdio process tree. No model entry point and no daemon attachment.

Windows: a non-inherited kill-on-close Job contains the supervisor before any
child is started. POSIX: a private process group is terminated on owner EOF.
See https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects.
Only reviewed children that do not detach on POSIX are supported.
"""
import ctypes
import json
import os
import queue
import signal
import stat
import subprocess
import sys
import threading
import time

import fileauth


def _windows():
    from ctypes import wintypes as W
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    class Basic(ctypes.Structure):
        _fields_=[('user',ctypes.c_longlong),('jobuser',ctypes.c_longlong),('flags',W.DWORD),
                  ('min',ctypes.c_size_t),('max',ctypes.c_size_t),('active',W.DWORD),
                  ('affinity',ctypes.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[(n,ctypes.c_ulonglong) for n in ('ro','wo','oo','rt','wt','ot')]
    class Limits(ctypes.Structure):
        _fields_=[('basic',Basic),('io',IO),('processmem',ctypes.c_size_t),
                  ('jobmem',ctypes.c_size_t),('peakprocess',ctypes.c_size_t),('peakjob',ctypes.c_size_t)]
    class Accounting(ctypes.Structure):
        _fields_=[(n,ctypes.c_longlong) for n in ('ut','kt','pu','pk')]+[
            (n,W.DWORD) for n in ('faults','total','active','terminated')]
    for name,args,result in (
        ('CreateJobObjectW',[ctypes.c_void_p,W.LPCWSTR],W.HANDLE),
        ('OpenJobObjectW',[W.DWORD,W.BOOL,W.LPCWSTR],W.HANDLE),
        ('SetInformationJobObject',[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD],W.BOOL),
        ('AssignProcessToJobObject',[W.HANDLE,W.HANDLE],W.BOOL),
        ('GetCurrentProcess',[],W.HANDLE),
        ('TerminateJobObject',[W.HANDLE,W.UINT],W.BOOL),
        ('QueryInformationJobObject',[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.c_void_p],W.BOOL),
        ('CloseHandle',[W.HANDLE],W.BOOL)):
        f=getattr(k,name); f.argtypes=args; f.restype=result
    return k,Limits,Accounting


def _job_create(name):
    k,Limits,_=_windows()
    handle=k.CreateJobObjectW(None,name)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    limits=Limits(); limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not k.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits))
            or not k.AssignProcessToJobObject(handle,k.GetCurrentProcess())):
        error=ctypes.get_last_error(); k.CloseHandle(handle)
        raise ctypes.WinError(error)
    return handle


def _job_stop(name):
    k,_,Accounting=_windows()
    handle=k.OpenJobObjectW(0x0008|0x0004,False,name)  # TERMINATE | QUERY
    if not handle:
        if ctypes.get_last_error()==2: return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not k.TerminateJobObject(handle,1): raise ctypes.WinError(ctypes.get_last_error())
        deadline=time.monotonic()+3
        while True:
            info=Accounting()
            if not k.QueryInformationJobObject(handle,1,ctypes.byref(info),ctypes.sizeof(info),None):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.active==0: return
            if time.monotonic()>=deadline: raise RuntimeError('owned job cleanup not confirmed')
            time.sleep(.02)
    finally: k.CloseHandle(handle)


def read(root,rel):
    path=fileauth.resolve(root,rel,'read','harness')
    with open(path,encoding='utf-8') as f: return json.load(f)


def _cid(root,rel):
    """Docker's runtime-created 64-hex ID is not a credential.

    Resolve its CONTROL parent with File Authority, then accept only the
    exact generated filename, no links and a single bounded identifier. The
    generic secret-content heuristic classifies bare 64-hex files as keys.
    This narrow reader never returns arbitrary contents to a model.
    """
    import computeruse
    parent,name=os.path.split(rel)
    if parent!='effects/computer' or not name.startswith('process-') or not name.endswith('.json.cid'):
        raise ValueError('invalid owned cidfile path')
    directory=fileauth.resolve(root,parent,'read','harness')
    path=os.path.join(directory,name); computeruse._no_links(path)
    with open(path,'rb') as f:
        info=os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>65:
            raise ValueError('invalid owned cidfile identity')
        value=f.read(66).decode('ascii').strip()
    computeruse._no_links(path)
    if len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('invalid owned container identifier')
    return value


def cleanup(root,rel):
    """Only the unique job/group persisted by this supervisor is a target."""
    data=read(root,rel)
    if data['state']=='closed': return
    if data['state'] not in ('ready','process_closed'):
        raise RuntimeError('owned process startup identity unavailable; owner reconciliation required')
    if data['state']=='process_closed':
        pass
    elif os.name=='nt':
        _job_stop(data['job'])
    else:
        # Never signal a stale persisted PID/group: it may have been reused.
        # The live supervisor owns the child handle and performs the cleanup.
        fileauth.write_json(root,rel+'.stop',{'stop':True},actor='harness')
        deadline=time.monotonic()+5
        while read(root,rel)['state'] not in ('closed','process_closed'):
            if time.monotonic()>=deadline:
                raise RuntimeError('owned supervisor cleanup unconfirmed; retain taint')
            time.sleep(.03)
    # Container cleanup is explicit: terminating docker CLI is insufficient.
    if data.get('docker'):
        import mcp
        docker=data['docker']
        try:
            cid=_cid(root,docker['cidfile'])
        except FileNotFoundError:
            raise RuntimeError('container startup ambiguous: no owned cidfile')
        if len(cid)!=64 or any(c not in '0123456789abcdef' for c in cid):
            raise RuntimeError('invalid owned container identity')
        command=[docker['executable']]
        subprocess.run(command+['rm','-f',cid],capture_output=True,text=True,timeout=15,env=mcp.server_environment({}))
        # A missing container is fine only when daemon readback is available.
        check=subprocess.run(command+['container','ls','-a','--no-trunc','--filter','id='+cid,'--format','{{.ID}}'],capture_output=True,text=True,timeout=15,env=mcp.server_environment({}))
        if check.returncode or check.stdout.strip():
            raise RuntimeError('owned container closure could not be confirmed')
    data['state']='closed'
    fileauth.write_json(root,rel,data,actor='harness')


def command(spec,root,rel):
    """Wrap owner-reviewed argv; reject remote/attached Docker invocations."""
    argv=[spec['cmd']]+list(spec.get('args') or [])
    if spec.get('shell'): raise ValueError('owned computer process requires argv without shell')
    data=read(root,rel)
    if os.path.basename(str(argv[0])).lower() in ('docker','docker.exe'):
        if (len(argv)<2 or argv[1]!='run' or '--rm' not in argv or '--network=none' not in argv
                or any(a in ('--cidfile','--name') or a.startswith(('--cidfile=','--name=')) for a in argv)):
            raise ValueError('owned Docker requires run --rm --network=none and runtime-owned name/cidfile')
        cidrel=rel+'.cid'
        cidpath=fileauth.resolve(root,cidrel,'write','harness')
        data['docker']={'executable':argv[0],'cidfile':cidrel}
        argv[2:2]=['--cidfile='+cidpath,'--name=agent-computer-'+data['token']]
        fileauth.write_json(root,rel,data,actor='harness')
    return [sys.executable,os.path.abspath(__file__),root,rel,'--']+argv


def supervise(root,rel,argv):
    data=read(root,rel)
    job=None
    if os.name=='nt':
        job=_job_create(data['job'])
    data.update(state='ready',group=os.getpid())
    fileauth.write_json(root,rel,data,actor='harness')
    child=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=sys.stdout.buffer,
                           stderr=subprocess.DEVNULL,bufsize=0,start_new_session=os.name!='nt')
    ended=threading.Event()
    pending=queue.Queue(maxsize=64)
    def receive():
        try:
            for line in sys.stdin.buffer:
                pending.put_nowait(line)
        except (OSError,ValueError,queue.Full): pass
        finally: ended.set()
    def forward():
        try:
            while not ended.is_set():
                try: line=pending.get(timeout=.1)
                except queue.Empty: continue
                child.stdin.write(line); child.stdin.flush()
        except (OSError,ValueError): ended.set()
    threading.Thread(target=receive,daemon=True).start()
    threading.Thread(target=forward,daemon=True).start()
    while not ended.wait(.05):
        if child.poll() is not None or os.path.exists(fileauth.resolve(root,rel+'.stop','read','harness')): break
    # Docker daemon resources are outside the process job/group.
    if data.get('docker'):
        # Cleanup performs readback before terminating this supervisor's job.
        # Host finalization/recovery will repeat exact-ID cleanup if interrupted.
        try:
            cid=_cid(root,data['docker']['cidfile'])
            if len(cid)==64 and all(c in '0123456789abcdef' for c in cid):
                subprocess.run([data['docker']['executable'],'rm','-f',cid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
        except (OSError,subprocess.TimeoutExpired): pass
    if os.name=='nt':
        k,_,_=_windows(); k.CloseHandle(job)  # last handle kills self and descendants
    else:
        try: os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        child.wait(timeout=3)
        data['state']='process_closed' if data.get('docker') else 'closed'
        fileauth.write_json(root,rel,data,actor='harness')


if __name__=='__main__':
    supervise(sys.argv[1],sys.argv[2],sys.argv[4:])
