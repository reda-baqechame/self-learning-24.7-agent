"""Frozen CU-1 invoice postconditions; no model or executor entry point."""
import ctypes
import hashlib
import json
import os
import re
import stat
import time
from ctypes import wintypes

import computeruse as C
import fileauth
import locks

SCHEMA='computer.invoice-postcondition.v1'
INDEX_SCHEMA='computer.lineage-index.v1'
RECEIPT_SCHEMA='computer.postcondition-receipt.v1'
CLAIM_SCHEMA='computer.output-claim.v1'
VERIFIER={'identity':'expert-fleet.invoice-postcondition',
          'version':'1'}
MAX_INVOICES=100
MAX_BYTES=10_000_000
MAX_CENSUS=1024


class PredicateMismatch(C.Refused):
    """A stable independent readback conclusively contradicts the contract."""


class VerificationUnavailable(C.Refused):
    """The verifier could not establish a trustworthy predicate result."""


def canonical(value):
    try:
        return json.dumps(value,sort_keys=True,separators=(',',':'),
                          ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (TypeError,ValueError) as error:
        raise C.Refused('postcondition value is not canonical JSON') from error


def canonical_digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def index_rel(lineage):
    if not isinstance(lineage,str) or not lineage:
        raise C.Refused('computer lineage is missing')
    # 192 bits keeps collision risk negligible while leaving room under the
    # legacy Windows 260-character path boundary in deeply nested trial roots.
    return 'effects/computer/task-'+canonical_digest(lineage)[:48]+'.json'


def index_path(root,lineage):
    return fileauth.resolve(root,index_rel(lineage),'read','harness')


def index_lease_path(root,lineage):
    return fileauth.resolve(root,index_rel(lineage)+'.lease','write','harness')


def output_lease_rel(binding):
    if (not isinstance(binding,dict) or set(binding)!={'device','inode'}
            or any(type(binding[key]) is not int for key in ('device','inode'))):
        raise C.Refused('invalid output directory identity')
    return 'effects/computer/output-'+canonical_digest(binding)[:48]+'.lease'


def output_claim_rel(binding):
    return output_lease_rel(binding)[:-6]+'.claim.json'


def _validate_output_claim(claim,binding):
    required={'schema','state','output_identity','workflow_id','contract_sha256',
              'ledger','task','lineage','server','revision','prior_claim_sha256'}
    if (not isinstance(claim,dict) or set(claim)!=required
            or claim.get('schema')!=CLAIM_SCHEMA
            or claim.get('state') not in ('PREPARED','COMMITTED','ABORTED')
            or claim.get('output_identity')!=binding):
        raise C.Refused('invalid durable invoice output claim')
    for key in ('workflow_id','contract_sha256','ledger','task','lineage','server'):
        if not isinstance(claim.get(key),str) or not claim[key]:
            raise C.Refused('invalid durable invoice output claim binding')
    if type(claim.get('revision')) is not int or claim['revision']<1:
        raise C.Refused('invalid durable invoice output claim revision')
    prior=claim.get('prior_claim_sha256')
    if prior is not None and (not isinstance(prior,str) or not re.fullmatch(r'[0-9a-f]{64}',prior)):
        raise C.Refused('invalid durable invoice output claim history')
    return claim


def read_output_claim(root,binding):
    path=fileauth.resolve(root,output_claim_rel(binding),'read','harness')
    if not os.path.exists(path): return None
    return _validate_output_claim(_read_json_secure(path,'invoice output claim'),binding)


def write_output_claim(root,claim):
    binding=claim.get('output_identity') if isinstance(claim,dict) else None
    claim=_validate_output_claim(claim,binding)
    if claim['state']!='PREPARED':
        raise C.Refused('new invoice output claim must be PREPARED')
    current=read_output_claim(root,binding)
    if current is not None and current['state']!='ABORTED':
        raise C.Refused('invoice output authority already has a durable claim')
    prior=canonical_digest(current) if current is not None else None
    expected_revision=(current['revision']+1 if current is not None else 1)
    if claim['prior_claim_sha256']!=prior or claim['revision']!=expected_revision:
        raise C.Refused('invoice output claim history changed')
    fileauth.write_json(root,output_claim_rel(binding),claim,actor='harness',durable=True)


def _replace_output_claim(root,current,state):
    updated=dict(current,state=state)
    observed=read_output_claim(root,current['output_identity'])
    if observed!=current:
        raise C.Refused('invoice output claim changed during recovery')
    fileauth.write_json(root,output_claim_rel(current['output_identity']),updated,
                        actor='harness',durable=True)
    return updated


def _claim_evidence_complete(root,claim):
    try:
        ledger=_read_json_secure(fileauth.resolve(root,claim['ledger'],'read','harness'),
                                 'claimed computer workflow ledger')
        binding={'lineage':claim['lineage'],'server':claim['server']}
        if ledger.get('binding')!=binding:
            return False
        workflows=[item for item in ledger.get('workflows',[])
                   if item.get('id')==claim['workflow_id']]
        if len(workflows)!=1: return False
        workflow=workflows[0]
        contract=validate_contract(workflow.get('contract'))
        if (canonical_digest(contract)!=claim['contract_sha256']
                or workflow.get('contract_sha256')!=claim['contract_sha256']
                or claim['workflow_id']!=claim['contract_sha256'][:32]
                or contract['output_identity']!=claim['output_identity']
                or contract['task']!=claim['task']
                or contract['lineage']!=claim['lineage']
                or contract['server']!=claim['server']):
            return False
        index=_read_json_secure(index_path(root,claim['lineage']),'claimed lineage index')
        reference=(index.get('workflows') or {}).get(claim['workflow_id'])
        return (index.get('schema')==INDEX_SCHEMA and index.get('state')=='COMMITTED'
                and index.get('lineage')==claim['lineage']
                and (index.get('ledgers') or {}).get(claim['ledger'])==binding
                and reference=={'ledger':claim['ledger'],
                                'contract_sha256':claim['contract_sha256']})
    except (C.Refused,OSError,KeyError,TypeError,AttributeError):
        return False


def recover_output_claim(root,binding):
    claim=read_output_claim(root,binding)
    if claim is None or claim['state']!='PREPARED': return claim
    return _replace_output_claim(
        root,claim,'COMMITTED' if _claim_evidence_complete(root,claim) else 'ABORTED')


def commit_output_claim(root,claim):
    current=read_output_claim(root,claim['output_identity'])
    if (current!=claim or current['state']!='PREPARED'
            or not _claim_evidence_complete(root,current)):
        raise C.Refused('prepared invoice output claim changed before commit')
    return _replace_output_claim(root,current,'COMMITTED')


def output_claim_matches(root,binding,workflow_id,contract_sha256,ledger=None):
    try: claim=read_output_claim(root,binding)
    except C.Refused: return False
    return bool(claim and claim['state']=='COMMITTED'
                and claim['workflow_id']==workflow_id
                and claim['contract_sha256']==contract_sha256
                and (ledger is None or claim['ledger']==ledger))


def _simple(value,label,pattern=r'[A-Za-z0-9_.@:-]{1,200}'):
    if not isinstance(value,str) or not re.fullmatch(pattern,value):
        raise C.Refused('invalid '+label)
    return value


def validate_manifest(manifest):
    if not isinstance(manifest,dict) or set(manifest)!={'month','account','invoices'}:
        raise C.Refused('invalid invoice manifest shape')
    if not isinstance(manifest['month'],str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',manifest['month']):
        raise C.Refused('invalid invoice month')
    _simple(manifest['account'],'invoice account')
    rows=manifest['invoices']
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_INVOICES:
        raise C.Refused('invalid expected invoice count')
    ids=set(); names=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'id','file','bytes','sha256','total_cents'}:
            raise C.Refused('invalid expected invoice record')
        _simple(row['id'],'invoice identity',r'[A-Za-z0-9_-]{1,80}')
        _simple(row['file'],'invoice filename',r'[A-Za-z0-9_-]{1,80}\.json')
        if row['id'] in ids or row['file'].casefold() in names:
            raise C.Refused('duplicate invoice identity or filename')
        ids.add(row['id']); names.add(row['file'].casefold())
        if type(row['bytes']) is not int or not 1<=row['bytes']<=MAX_BYTES:
            raise C.Refused('invalid invoice byte bound')
        if not isinstance(row['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',row['sha256']):
            raise C.Refused('invalid invoice digest')
        if type(row['total_cents']) is not int or not 0<=row['total_cents']<=10**12:
            raise C.Refused('invalid invoice amount')
    return rows


def validate_source(source,manifest_digest):
    if not isinstance(source,dict) or set(source)!={'identity','version','sha256'}:
        raise C.Refused('invalid independent expectation source')
    _simple(source['identity'],'expectation source identity')
    _simple(source['version'],'expectation source version')
    if source['sha256']!=manifest_digest:
        raise C.Refused('expectation source does not bind manifest')


def validate_intents(intents,rows):
    if not isinstance(intents,list) or len(intents)!=len(rows):
        raise C.Refused('ordered invoice intents are incomplete')
    expected={row['id'] for row in rows}; seen=set()
    for intent in intents:
        if not isinstance(intent,dict) or set(intent)!={'target_id','invoice_id','destination'}:
            raise C.Refused('invalid invoice intent')
        _simple(intent['target_id'],'target identity',r'[A-Za-z0-9_-]{1,80}')
        _simple(intent['invoice_id'],'intent invoice identity',r'[A-Za-z0-9_-]{1,80}')
        if not isinstance(intent['destination'],str) or len(intent['destination'])>2000:
            raise C.Refused('invalid intent destination')
        if intent['invoice_id'] in seen:
            raise C.Refused('duplicate ordered invoice intent')
        seen.add(intent['invoice_id'])
    if seen!=expected:
        raise C.Refused('ordered intents differ from expected invoices')


def _relative_output(value):
    if not isinstance(value,str) or not value or os.path.isabs(value):
        raise C.Refused('output must be a confined relative directory')
    parts=value.replace('\\','/').split('/')
    if any(part in ('','.','..') or ':' in part for part in parts):
        raise C.Refused('invalid output directory')
    return '/'.join(parts)


def _safe_directory(root,relative):
    relative=_relative_output(relative)
    if fileauth.zone_of(relative) not in (fileauth.ZONE_CONTROL,
                                          fileauth.ZONE_RUNTIME):
        raise C.Refused('invoice output must be protected from agent writes')
    base=os.path.abspath(root)
    C._no_links(base)
    for part in relative.split('/'):
        base=os.path.join(base,part)
        info=C._no_links(base)
        if not stat.S_ISDIR(info.st_mode):
            raise C.Refused('output ancestor is not a directory')
    resolved=fileauth.resolve(root,relative,'read','harness')
    try:
        same_directory=os.path.samefile(resolved,base)
    except OSError as error:
        raise C.Refused('output directory identity could not be established') from error
    if not same_directory:
        raise C.Refused('output directory identity changed')
    return base


def output_binding(root,output_dir):
    info=os.stat(_safe_directory(root,output_dir),follow_symlinks=False)
    return {'device':info.st_dev,'inode':info.st_ino}


def capture_baseline(root,output_dir,expected_binding=None):
    base=_safe_directory(root,output_dir)
    info=os.stat(base,follow_symlinks=False)
    binding={'device':info.st_dev,'inode':info.st_ino}
    if expected_binding is not None and binding!=expected_binding:
        raise C.Refused('output directory identity changed before baseline')
    names=os.listdir(base)
    if names:
        raise C.Refused('invoice output baseline must be empty')
    return {'entries':[],'captured_at':time.time(),
            'directory':binding}


def build_contract(root,task,lineage,epoch,policy_revision,server,origin,
                   output_dir,manifest,source,account,intents,deadline_seconds,
                   expected_output_binding=None):
    rows=validate_manifest(manifest)
    digest=canonical_digest(manifest)
    validate_source(source,digest)
    if account!=manifest['account']:
        raise C.Refused('independent account binding differs')
    validate_intents(intents,rows)
    if type(deadline_seconds) is not int or not 1<=deadline_seconds<=300:
        raise C.Refused('verification deadline bound is invalid')
    output_dir=_relative_output(output_dir)
    binding=output_binding(root,output_dir)
    if expected_output_binding is not None and binding!=expected_output_binding:
        raise C.Refused('leased output directory identity changed')
    contract={'schema':SCHEMA,'predicate':'invoice_exact_prefix',
              'task':str(task),'lineage':str(lineage),'session_epoch':str(epoch),
              'policy_revision':str(policy_revision),'server':str(server),
              'origin':str(origin),'output_dir':output_dir,
              'output_identity':binding,'output_lease':output_lease_rel(binding),
              'manifest':manifest,'manifest_sha256':digest,
              'expectation_source':source,'account':account,'intents':intents,
              'baseline':capture_baseline(root,output_dir,binding),
              'verifier':dict(VERIFIER),'deadline_at':time.time()+deadline_seconds,
              'limits':{'max_invoices':MAX_INVOICES,'max_bytes':MAX_BYTES},
              'required_for_task':True}
    validate_contract(contract)
    return contract


def validate_contract(contract):
    required={'schema','predicate','task','lineage','session_epoch','policy_revision',
              'server','origin','output_dir','output_identity','output_lease','manifest',
              'manifest_sha256','expectation_source','account','intents','baseline',
              'verifier','deadline_at','limits','required_for_task'}
    if not isinstance(contract,dict) or set(contract)!=required:
        raise C.Refused('invalid frozen postcondition contract')
    if contract['schema']!=SCHEMA or contract['predicate']!='invoice_exact_prefix':
        raise C.Refused('unsupported postcondition contract')
    rows=validate_manifest(contract['manifest'])
    digest=canonical_digest(contract['manifest'])
    if contract['manifest_sha256']!=digest:
        raise C.Refused('frozen manifest binding changed')
    validate_source(contract['expectation_source'],digest)
    if contract['account']!=contract['manifest']['account']:
        raise C.Refused('contract account binding changed')
    validate_intents(contract['intents'],rows)
    output=_relative_output(contract['output_dir'])
    baseline=contract['baseline']
    if not isinstance(baseline,dict) \
            or set(baseline)!={'entries','captured_at','directory'} \
            or baseline['entries']!=[] \
            or not isinstance(baseline['directory'],dict) \
            or set(baseline['directory'])!={'device','inode'} \
            or any(type(baseline['directory'][key]) is not int
                   for key in ('device','inode')):
        raise C.Refused('unsupported nonempty or malformed baseline')
    if contract['output_identity']!=baseline['directory'] \
            or contract['output_lease']!=output_lease_rel(contract['output_identity']):
        raise C.Refused('output lease binding changed')
    if contract['verifier']!=VERIFIER or contract['limits']!={'max_invoices':MAX_INVOICES,'max_bytes':MAX_BYTES}:
        raise C.Refused('verifier identity or bounds changed')
    if type(contract['deadline_at']) not in (int,float) or not contract['deadline_at']>0:
        raise C.Refused('invalid frozen verification deadline')
    if contract['required_for_task'] is not True:
        raise C.Refused('required postcondition was weakened')
    for name in ('task','lineage','session_epoch','policy_revision','server','origin'):
        if not isinstance(contract[name],str) or not contract[name]:
            raise C.Refused('invalid contract '+name)
    return contract


def _anchor(path):
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_CLOEXEC',0)
    if os.name!='nt':
        return os.open(path,flags|getattr(os,'O_NOFOLLOW',0))
    kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    create=kernel32.CreateFileW; create.argtypes=(wintypes.LPCWSTR,wintypes.DWORD,
        wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE)
    create.restype=wintypes.HANDLE
    close=kernel32.CloseHandle; close.argtypes=(wintypes.HANDLE,); close.restype=wintypes.BOOL
    full=os.path.abspath(path)
    if not full.startswith('\\\\?\\'):
        full='\\\\?\\UNC\\'+full[2:] if full.startswith('\\\\') else '\\\\?\\'+full
    handle=create(full,0x80000000,0x00000001,None,3,0x00200000,None)
    if handle==wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        import msvcrt
        return msvcrt.open_osfhandle(handle,flags|getattr(os,'O_NOINHERIT',0))
    except BaseException:
        close(handle); raise


def _read_exact(path,expected):
    fd=_anchor(path)
    try:
        before=os.fstat(fd); current=C._no_links(path)
        signature=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_nlink)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1
                or signature(before)!=signature(current)
                or before.st_size!=expected['bytes']):
            raise C.Refused('invoice artifact identity or size differs')
        remaining=expected['bytes']+1; chunks=[]
        while remaining:
            chunk=os.read(fd,remaining)
            if not chunk: break
            chunks.append(chunk); remaining-=len(chunk)
        raw=b''.join(chunks); after=os.fstat(fd); final=C._no_links(path)
        if signature(before)!=signature(after) or signature(before)!=signature(final):
            raise C.Refused('invoice artifact changed during readback')
        if len(raw)!=expected['bytes'] or hashlib.sha256(raw).hexdigest()!=expected['sha256']:
            raise PredicateMismatch('invoice artifact bytes differ')
        return raw,before
    finally:
        os.close(fd)


def verify_prefix(root,contract,prefix_count):
    validate_contract(contract)
    if type(prefix_count) is not int or not 1<=prefix_count<=len(contract['intents']):
        raise C.Refused('invalid invoice verification prefix')
    if time.time()>contract['deadline_at']:
        raise VerificationUnavailable('frozen invoice verification deadline exhausted')
    rows={row['id']:row for row in contract['manifest']['invoices']}
    expected=[rows[item['invoice_id']] for item in contract['intents'][:prefix_count]]
    base=_safe_directory(root,contract['output_dir'])
    directory=os.stat(base,follow_symlinks=False)
    if {'device':directory.st_dev,'inode':directory.st_ino}!=contract['baseline']['directory']:
        raise VerificationUnavailable('invoice output directory identity changed')
    names=set(os.listdir(base)); wanted={row['file'] for row in expected}
    if names!=wanted:
        raise PredicateMismatch('invoice prefix differs: no-op, missing, future, duplicate, partial or extra output')
    readbacks=[]
    for row in expected:
        raw,info=_read_exact(os.path.join(base,row['file']),row)
        try: value=json.loads(raw.decode('utf-8'))
        except (ValueError,UnicodeError) as error:
            raise PredicateMismatch('invoice is not canonical JSON data') from error
        exact={'id','month','account','total_cents'}
        if (not isinstance(value,dict) or set(value)!=exact
                or value['id']!=row['id']
                or value['month']!=contract['manifest']['month']
                or value['account']!=contract['account']
                or value['total_cents']!=row['total_cents']):
            raise PredicateMismatch('invoice identity, month, account or amount differs')
        readbacks.append({'id':row['id'],'file':row['file'],'bytes':len(raw),
                          'sha256':row['sha256'],'device':info.st_dev,'inode':info.st_ino})
    if set(os.listdir(base))!=names:
        raise VerificationUnavailable('invoice output set changed during verification')
    return readbacks


def effective_action_status(root,action,workflow=None,contract=None):
    if workflow is not None and contract is not None and _valid_receipt(root,action,workflow,contract):
        return ('VERIFIED_BY_POSTCONDITION' if action.get('state')=='UNKNOWN'
                else 'VERIFIED')
    if action.get('workflow_id') and action.get('state')=='VERIFIED':
        return 'INVALID_VERIFICATION'
    return action.get('state')


def _read_json_secure(path,label):
    try:
        fd=_anchor(path)
        try:
            before=os.fstat(fd); current=C._no_links(path)
            signature=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_nlink)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1
                    or signature(before)!=signature(current)
                    or before.st_size>25_000_000):
                raise C.Refused(label+' identity is unsafe')
            chunks=[]; remaining=25_000_001
            while remaining:
                chunk=os.read(fd,remaining)
                if not chunk: break
                chunks.append(chunk); remaining-=len(chunk)
            raw=b''.join(chunks); after=os.fstat(fd); final=C._no_links(path)
        finally: os.close(fd)
        if signature(before)!=signature(after) or signature(before)!=signature(final):
            raise C.Refused(label+' changed during read')
        if len(raw)>25_000_000: raise C.Refused(label+' is oversized')
        return json.loads(raw.decode('utf-8'))
    except C.Refused: raise
    except (OSError,ValueError,UnicodeError) as error:
        raise C.Refused(label+' is unreadable') from error


def _census(root,lineage):
    directory=os.path.join(os.path.abspath(root),'effects','computer')
    if not os.path.exists(directory): return []
    C._no_links(directory)
    names=os.listdir(directory)
    if len(names)>MAX_CENSUS: raise C.Refused('computer ledger census bound exceeded')
    found=[]
    for name in names:
        if (not name.endswith('.json')
                or name.startswith(('server-','process-','task-','output-'))):
            continue
        path=os.path.join(directory,name)
        value=_read_json_secure(path,'computer action ledger')
        if not isinstance(value,dict) or not isinstance(value.get('actions'),list):
            raise C.Refused('malformed computer action ledger in census')
        binding=value.get('binding') or {}
        action_lineages={str(a.get('lineage')) for a in value['actions'] if isinstance(a,dict)}
        if binding.get('lineage')==lineage or lineage in action_lineages:
            found.append('effects/computer/'+name)
    return sorted(found)


def _valid_receipt(root,action,workflow,contract):
    receipt=action.get('postcondition_receipt')
    if action.get('state')=='UNKNOWN':
        resolutions=action.get('postcondition_resolutions') or []
        resolution=resolutions[-1] if resolutions and isinstance(resolutions[-1],dict) else None
        if (not resolution or set(resolution)!={'kind','recorded_at','receipt'}
                or resolution['kind']!='independent_postcondition'
                or type(resolution['recorded_at']) not in (int,float)):
            return False
        receipt=resolution.get('receipt')
    elif action.get('state')!='VERIFIED':
        return False
    required={'schema','result','action_id','intent_key','workflow_id','contract_sha256',
              'task','lineage','epoch','policy_revision','verifier','expectation_source',
              'account','sequence','verified_at','prior_verified_ids','readbacks',
              'cleanup_receipt','workflow_verified','receipt_id','receipt_sha256'}
    if not isinstance(receipt,dict) or receipt.get('schema')!=RECEIPT_SCHEMA \
            or set(receipt)!=required or receipt.get('result')!='VERIFIED': return False
    body={key:value for key,value in receipt.items() if key not in ('receipt_id','receipt_sha256')}
    digest=canonical_digest(body)
    if receipt.get('receipt_id')!=digest or receipt.get('receipt_sha256')!=digest:
        return False
    try:
        position=action['intent_index']; expected_intent=contract['intents'][position]
        rows={row['id']:row for row in contract['manifest']['invoices']}
        expected_rows=[rows[item['invoice_id']] for item in contract['intents'][:position+1]]
        expected_prior=[item['invoice_id'] for item in contract['intents'][:position]]
        cleanup=receipt['cleanup_receipt']; attempts=action['verification_attempts']
    except (KeyError,IndexError,TypeError):
        return False
    action_ids=workflow.get('action_ids')
    if (not isinstance(action_ids,list) or position>=len(action_ids)
            or action.get('operation')!='click' or action.get('required_for_task') is not True
            or action_ids[position]!=action.get('id')
            or action.get('intent',{}).get('target_id')!=expected_intent['target_id']
            or action.get('intent',{}).get('href')!=expected_intent['destination']):
        return False
    if (not isinstance(cleanup,dict) or cleanup!=action.get('cleanup_receipt')
            or set(cleanup)!={'environment','state','metadata_sha256','confirmed_at'}
            or cleanup.get('environment')!=action.get('environment')
            or cleanup.get('state')!='closed'
            or not isinstance(cleanup.get('metadata_sha256'),str)
            or not re.fullmatch(r'[0-9a-f]{64}',cleanup['metadata_sha256'])
            or type(cleanup.get('confirmed_at')) not in (int,float)):
        return False
    try:
        environment=_read_json_secure(fileauth.resolve(root,action['environment'],'read','harness'),
                                      'bound computer environment')
    except (C.Refused,KeyError,TypeError):
        return False
    if environment.get('state')!='closed' \
            or canonical_digest(environment)!=cleanup['metadata_sha256']:
        return False
    readbacks=receipt.get('readbacks')
    if not isinstance(readbacks,list) or len(readbacks)!=len(expected_rows): return False
    for readback,row in zip(readbacks,expected_rows):
        if (not isinstance(readback,dict)
                or set(readback)!={'id','file','bytes','sha256','device','inode'}
                or any(readback.get(key)!=row[key] for key in ('id','file','bytes','sha256'))
                or type(readback.get('device')) is not int
                or type(readback.get('inode')) is not int):
            return False
    matching=[attempt for attempt in attempts if isinstance(attempt,dict)
              and attempt.get('sequence')==receipt.get('sequence')]
    if (len(matching)!=1 or matching[0].get('result')!='VERIFIED'
            or matching[0].get('receipt_id')!=digest
            or matching[0].get('receipt_sha256')!=digest
            or matching[0].get('action_id')!=action.get('id')
            or matching[0].get('workflow_id')!=workflow.get('id')
            or matching[0].get('contract_sha256')!=workflow.get('contract_sha256')):
        return False
    return (output_claim_matches(root,contract['output_identity'],workflow.get('id'),
                                 workflow.get('contract_sha256'))
            and receipt.get('action_id')==action.get('id')
            and receipt.get('workflow_id')==workflow.get('id')
            and receipt.get('contract_sha256')==workflow.get('contract_sha256')
            and action.get('contract_sha256')==workflow.get('contract_sha256')
            and receipt.get('task')==contract['task']
            and receipt.get('lineage')==contract['lineage']
            and receipt.get('epoch')==action.get('epoch')
            and receipt.get('policy_revision')==contract['policy_revision']
            and receipt.get('verifier')==VERIFIER
            and receipt.get('expectation_source')==contract['expectation_source']
            and receipt.get('intent_key')==action.get('intent_key')
            and receipt.get('account')==contract['account']
            and receipt.get('prior_verified_ids')==expected_prior
            and receipt.get('workflow_verified') is (position+1==len(contract['intents']))
            and type(receipt.get('sequence')) is int and receipt['sequence']>=1
            and type(receipt.get('verified_at')) in (int,float))


def completion_status(root,task):
    lineage=str(task.get('lineage') or task.get('id') or '')
    try: ledgers=_census(root,lineage)
    except C.Refused as error: return False,str(error)
    path=index_path(root,lineage)
    if not os.path.exists(path):
        return ((True,'no computer history') if not ledgers else
                (False,'computer lineage index is missing for existing history'))
    try:
        index=_read_json_secure(path,'computer lineage index')
        if (not isinstance(index,dict) or index.get('schema')!=INDEX_SCHEMA
                or index.get('state')!='COMMITTED' or index.get('lineage')!=lineage
                or not isinstance(index.get('ledgers'),dict)
                or sorted(index['ledgers'])!=ledgers):
            raise C.Refused('computer lineage index is not a matching committed census')
        workflows=index.get('workflows') or {}
        if not isinstance(workflows,dict): raise C.Refused('computer workflow index is malformed')
        by_ledger={rel:_read_json_secure(fileauth.resolve(root,rel,'read','harness'),
                                         'registered computer ledger') for rel in ledgers}
        for rel,value in by_ledger.items():
            binding=value.get('binding') or {}
            declared=index['ledgers'][rel]
            if binding!=declared or binding.get('lineage')!=lineage:
                raise C.Refused('registered computer ledger binding differs')
        action_identities=[]
        for ledger in by_ledger.values():
            actions=ledger.get('actions')
            if not isinstance(actions,list):
                raise C.Refused('registered computer action history is malformed')
            for action in actions:
                identity=action.get('id') if isinstance(action,dict) else None
                if not isinstance(identity,str) or not identity:
                    raise C.Refused('registered computer action identity is malformed')
                action_identities.append(identity)
        if len(action_identities)!=len(set(action_identities)):
            raise C.Refused('registered computer action identity is not unique')
        referenced=set()
        for workflow_id,reference in workflows.items():
            if not isinstance(reference,dict) or set(reference)!={'ledger','contract_sha256'}:
                raise C.Refused('computer workflow reference is malformed')
            ledger=by_ledger.get(reference['ledger'])
            candidates=[w for w in ledger.get('workflows',[]) if w.get('id')==workflow_id] if ledger else []
            if len(candidates)!=1: raise C.Refused('computer workflow ledger record is missing')
            workflow=candidates[0]; contract=validate_contract(workflow.get('contract'))
            if (canonical_digest(contract)!=reference['contract_sha256']
                    or workflow.get('contract_sha256')!=reference['contract_sha256']
                    or contract['lineage']!=lineage or contract['task']!=str(task.get('id'))):
                raise C.Refused('computer workflow contract binding differs')
            action_ids=workflow.get('action_ids')
            by_id={a.get('id'):a for a in ledger['actions']}
            if (not isinstance(action_ids,list) or len(action_ids)!=len(set(action_ids))
                    or len(action_ids)!=len(contract['intents'])
                    or any(action_id not in by_id for action_id in action_ids)):
                raise C.Refused('required computer workflow is incomplete')
            actions=[by_id[action_id] for action_id in action_ids]
            final_receipt=None
            for position,(action,intent) in enumerate(zip(actions,contract['intents'])):
                referenced.add(action.get('id'))
                if (action.get('intent_index')!=position or action.get('intent') is None
                        or action['intent'].get('target_id')!=intent['target_id']
                        or not _valid_receipt(root,action,workflow,contract)):
                    raise C.Refused('computer action lacks a valid independent postcondition receipt')
                if position==len(actions)-1:
                    final_receipt=(action.get('postcondition_receipt')
                        if action.get('state')=='VERIFIED' else
                        action['postcondition_resolutions'][-1]['receipt'])
            lease=fileauth.resolve(root,contract['output_lease'],'write','harness')
            try:
                with locks.advisory_holding(lease,timeout=0):
                    current=verify_prefix(root,contract,len(contract['intents']))
            except TimeoutError as error:
                raise C.Refused('invoice output authority is unavailable at completion') from error
            if current!=final_receipt.get('readbacks'):
                raise C.Refused('current invoice readback differs from terminal receipt')
        for ledger in by_ledger.values():
            for action in ledger['actions']:
                if action.get('state') in ('PREPARED','DISPATCHED','UNKNOWN') \
                        and not any(_valid_receipt(root,action,w,validate_contract(w['contract']))
                                    for w in ledger.get('workflows',[])
                                    if action.get('workflow_id')==w.get('id')):
                    raise C.Refused('unresolved critical computer action blocks completion')
                if (action.get('operation')=='click' and action.get('id') not in referenced
                        and action.get('state') not in
                            ('REFUSED','FAILED_WITH_KNOWN_NO_EFFECT')):
                    raise C.Refused('legacy or unqualified computer click blocks completion')
        return True,'all required computer postconditions verified'
    except (C.Refused,KeyError,TypeError) as error:
        return False,str(error)
