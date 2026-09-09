#!/usr/bin/env python3
"""MUTATION TESTING — break the feature, confirm the test notices.

A passing test proves nothing on its own: a test that would pass with the
feature removed is a test that measures nothing. This deliberately breaks
each load-bearing behaviour and requires the test that claims to cover it to
FAIL. Every mutation is reverted afterwards.

Run from the agent/ directory.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

AGENT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# (label, file, find, replace, test, what the test must notice)
MUTATIONS = [
    ("computerbench: candidate CLI reports acceptance success", "computerbench.py",
     '''        return 2
    report = run_development''',
     '''        return 0
    report = run_development''', "test_computerbench.py",
     "the candidate CLI can never establish independent acceptance"),
    ("computerbench: RSA public authentication bypassed", "computerbench_verifier.py",
     '''    if not _rsa_verify(_canonical(body), seal["signature_hex"], modulus,
                       exponent):''',
     '''    if False:''', "test_computerbench.py",
     "artifact bytes require a strict external private-key signature"),
    ("computerbench: weak RSA modulus accepted", "computerbench_verifier.py",
     '''    if (not 2048 <= modulus.bit_length() <= 8192 or modulus % 2 == 0''',
     '''    if (not 512 <= modulus.bit_length() <= 8192 or modulus % 2 == 0''',
     "test_computerbench.py", "public verification keys must be 2048 through 8192 bits"),
    ("computerbench: verifier may share worker identity", "computerbench_verifier.py",
     '''                or value["verifier_uid"] == value["worker_uid"]):''',
     '''                or False):''', "test_computerbench.py",
     "the dedicated verifier identity must never equal the worker identity"),
    ("computerbench: public trust store may be worker-owned", "computerbench_verifier.py",
     '''        if (trust.st_uid != 0 or not stat.S_ISDIR(trust.st_mode)''',
     '''        if (False or not stat.S_ISDIR(trust.st_mode)''',
     "test_computerbench.py", "the fixed public trust store must be root-owned"),
    ("computerbench: acceptance may run as a different UID", "computerbench_verifier.py",
     '''                    or os.geteuid() != verifier_uid):''',
     '''                    or False):''', "test_computerbench.py",
     "acceptance and challenge operations must run as the configured verifier UID"),
    ("computerbench: frozen step budget ignored", "computerbench_verifier.py",
     '        total_steps += row["steps"]',
     '        total_steps += 0', "test_computerbench.py",
     "sealed results must remain inside the independently frozen step budget"),
    ("computerbench: scenario name overrides controller evidence", "computerbench.py",
     '''    if outcome == "completed":
        return "rejected_artifacts"''',
     '''    if outcome == "completed" and record.get("case") == "corrupt":
        return "rejected_artifacts"''',
     "test_computerbench.py",
     "scenario labels must not influence terminal status"),
    ("computerbench: portal fixture file mounted as a directory", "computerbench.py",
     '                      "type=bind,source=" + os.fspath(fixture.parent)',
     '                      "type=bind,source=" + os.fspath(fixture)',
     "test_computerbench.py", "the exact fixture parent must be the read-only /fixture mount"),
    ("computerbench: portal readiness probe removed", "computerbench.py",
     '               "for attempt in $(seq 1 100); do "',
     '               "for attempt in $(seq 1 0); do "',
     "test_computerbench.py", "fixture readiness must be bounded and precede MCP startup"),
    ("computerbench: portal bypasses task-owned runtime", "computerbench.py",
     '''        current = computersession.ComputerSession(
            os.fspath(root), task, "portal", "computerbench-dev-v1")
        sessions.append(current)''',
     '''        current = mcp.connect(os.fspath(root), "portal")
        sessions.append(current)''',
     "test_computerbench.py", "development trials must traverse ComputerSession, never direct MCP"),
    ("computerbench: moved observation identity ignored", "computerbench.py",
     '''    return (before["observation"]["state_sha256"]
            != after["observation"]["state_sha256"])''',
     '''    return False''', "test_computerbench.py",
     "a stale click may be attempted only after two sealed observation identities differ"),
    ("computerbench: internal fixture simulates independent acceptance", "computerbench_verifier.py",
     '''    report["acceptance_complete"] = (not backend.internal and all(''',
     '''    report["acceptance_complete"] = (all(''', "test_computerbench.py",
     "an internal temp authority can validate mechanics but cannot certify independence"),
    ("computerbench: challenge candidate substitution accepted", "computerbench_verifier.py",
     '''    if pack["challenge"]["candidate"] != pack["candidate"]:''',
     '''    if False:''', "test_computerbench.py",
     "pack and challenge must bind the exact verifier-derived candidate"),
    ("computerbench: results use pack issuer authority", "computerbench_verifier.py",
     '''    role = "pack_issuer" if kind == "acceptance_pack" else "results_evaluator"''',
     '''    role = "pack_issuer"''', "test_computerbench.py",
     "pack issuer and result evaluator authorities must remain distinct"),
    ("computerbench: consumed challenge remains replayable", "computerbench_verifier.py",
     '''        backend.consume(pack["challenge"])''',
     '''        backend.challenge(pack["challenge"])''', "test_computerbench.py",
     "a successful evaluation must durably consume its one-run challenge"),
    ("computerbench: consumed tombstone no longer dominates restore", "computerbench_verifier.py",
     '''        if self._has_tombstone(value["nonce"]):''',
     '''        if False:''', "test_computerbench.py",
     "a durable tombstone must permanently dominate a restored issued file"),
    ("computerbench: full archive manifest narrowed to candidate CLI", "computerbench_verifier.py",
     '''            rows.append(row)
            if path.endswith(".py"):''',
     '''            if path == "computerbench.py":
                rows.append(row)
            if path.endswith(".py"):''', "test_computerbench.py",
     "candidate identity must change with every shipped authority and policy/config file"),
    ("computerbench: trust binding canonicalizes away metadata bytes", "computerbench_verifier.py",
     '''        self._profile_digests[trust_id] = hashlib.sha256(raw).hexdigest()''',
     '''        self._profile_digests[trust_id] = hashlib.sha256(_canonical(value)).hexdigest()''',
     "test_computerbench.py", "candidate identity must bind the exact public trust metadata bytes"),
    ("computerbench: issued challenge removed before durable tombstone", "computerbench_verifier.py",
     '''                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT |
                                     os.O_EXCL, 0o600)''',
     '''                os.unlink(source)
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT |
                                     os.O_EXCL, 0o600)''',
     "test_computerbench.py", "durable consumed state must be created before issued state is removed"),
    ("computerbench: required human help ignored", "computerbench_verifier.py",
     '''                and not row["human_help_used"]:''',
     '''                and False:''', "test_computerbench.py",
     "a pack requiring human help must reject rows that did not use it"),
    ("computerbench: durable UNKNOWN action treated as terminal", "computerbench.py",
     '''action.get("state") not in ("VERIFIED", "REFUSED")''',
     '''action.get("state") not in ("VERIFIED", "REFUSED", "UNKNOWN")''',
     "test_computerbench.py",
     "any unreconciled durable UNKNOWN action must keep the trial unresolved"),
    ("computerbench: readiness attempt has no abort timeout", "computerbench.py",
     '''AbortSignal.timeout(250)''', '''AbortSignal.abort()''', "test_computerbench.py",
     "every readiness fetch attempt needs its own bounded abort signal"),
    ("computerbench: Windows reparse artifact followed", "computerbench_verifier.py",
     '''            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 0x400):
                raise ContractError(label + " reparse or alias path refused")''',
     '''            if False:
                raise ContractError(label + " reparse or alias path refused")''', "test_computerbench.py",
     "Windows internal fixtures must refuse reparse aliases and production fails closed",
     False, None, ("nt", "Windows reparse behavior")),
    ("computerbench: POSIX final artifact follows symlink", "computerbench_verifier.py",
     '''        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)''',
     '''        fd = os.open(parts[-1], os.O_RDONLY, dir_fd=directory)''',
     "test_computerbench.py", "POSIX external artifacts require descriptor no-follow",
     "Windows lacks POSIX openat/O_NOFOLLOW; production refuses instead"),
    ("computerbench: external install path ignored", "computerbench_verifier.py",
     '''    if (Path(absolute_file) != _FIXED_VERIFIER_FILE
            or Path(resolved_file) != _FIXED_VERIFIER_FILE):''',
     '''    if False:''', "test_computerbench.py",
     "only the fixed root-managed installed verifier may exercise authority"),
    ("computerbench: external install directory may be worker-owned", "computerbench_verifier.py",
     '''        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise ContractError("verifier installation directory is unsafe")''',
     '''        if False:
            raise ContractError("verifier installation directory is unsafe")''', "test_computerbench.py",
     "every verifier installation directory must be root-owned and non-writable"),
    ("computerbench: external verifier file may be worker-owned", "computerbench_verifier.py",
     '''    if (not stat.S_ISREG(file_info.st_mode) or file_info.st_uid != 0
            or file_info.st_nlink != 1
            or stat.S_IMODE(file_info.st_mode) & 0o133):''',
     '''    if False:''', "test_computerbench.py",
     "the installed verifier source must be root-owned, single-linked and non-writable"),
    ("computerbench: external launcher inherits caller environment",
     "computerbench-verifier",
     "/usr/bin/env -i PATH=/usr/bin:/bin",
     "/usr/bin/env PATH=/usr/bin:/bin",
     "test_computerbench.py",
     "hostile PATH, PYTHONPATH and sitecustomize must be removed before Python starts"),
    ("computerbench: external launcher searches PATH for Python",
     "computerbench-verifier",
     "/usr/bin/python3 -I -S",
     "python3 -I -S",
     "test_computerbench.py",
     "the root-managed launcher must use the fixed absolute interpreter"),
    ("computerbench: external launcher drops isolated mode",
     "computerbench-verifier",
     "/usr/bin/python3 -I -S",
     "/usr/bin/python3 -S",
     "test_computerbench.py",
     "the verifier must start in isolated mode before candidate-controlled imports are possible"),
    ("computerbench: external launcher enables site initialization",
     "computerbench-verifier",
     "/usr/bin/python3 -I -S",
     "/usr/bin/python3 -I",
     "test_computerbench.py",
     "site initialization must be disabled before verifier validation runs"),
    ("computerbench: external verifier bypasses launch validation",
     "computerbench_verifier.py",
     '''    _validate_launch_facts(_bootstrap_sys.executable,
                           list(_bootstrap_sys.orig_argv),
                           _bootstrap_sys.flags, dict(os.environ))
    _validate_interpreter_root()''',
     '''    return None''',
     "test_computerbench.py",
     "production entry must validate exact launch facts and the root-owned interpreter"),
    ("computerbench: archive path traversal accepted", "computerbench_verifier.py",
     '''            or "\\\\x00" in name or "\\\\" in name or name.startswith("/")''',
     '''            or "\\\\x00" in name or False or name.startswith("/")''',
     "test_computerbench.py",
     "candidate archives are inert data and may not contain platform path aliases"),
    ("computerbench: archive symlink accepted", "computerbench_verifier.py",
     '''            if kind not in (0, stat.S_IFREG):''',
     '''            if False:''', "test_computerbench.py",
     "candidate archives must not contain symlinks or special files"),
    ("computerbench: duplicate archive identity accepted", "computerbench_verifier.py",
     '''            if path in seen or folded_path in folded:''',
     '''            if False:''', "test_computerbench.py",
     "candidate archives must not contain exact or case-alias duplicate names"),
    ("computerbench: exact archive bytes not bound", "computerbench_verifier.py",
     '''        "archive_sha256": hashlib.sha256(raw).hexdigest(),''',
     '''        "archive_sha256": "0" * 64,''', "test_computerbench.py",
     "candidate identity binds exact archive bytes as well as parsed members"),
    ("computerbench: candidate archive change after challenge ignored", "computerbench_verifier.py",
     '''                or value["candidate"] != self.candidate(trust_digest)):''',
     '''                or False):''', "test_computerbench.py",
     "the candidate archive must be remeasured when a challenge is validated"),
    ("computerbench: configuration digest ignores configuration", "computerbench_verifier.py",
     '''            _canonical(configuration_rows)).hexdigest(),''',
     '''            _canonical([])).hexdigest(),''', "test_computerbench.py",
     "effective configuration bytes inside the archive remain explicitly bound"),
    ("computerbench: oversized RSA exponent accepted", "computerbench_verifier.py",
     '''or type(exponent) is not int or not 3 <= exponent <= 0xffffffff''',
     '''or type(exponent) is not int or exponent < 3''', "test_computerbench.py",
     "RSA exponent bounds must be checked before modular exponentiation"),
    ("computerbench: action read failure ignored", "computerbench.py",
     '''    if "action_read_error" in record:''',
     '''    if False:''', "test_computerbench.py",
     "a failed durable-action read can never be replaced by success-capable evidence"),
    ("computerbench: missing actions treated as empty", "computerbench.py",
     '''    actions = record.get("actions")''',
     '''    actions = record.get("actions", [])''', "test_computerbench.py",
     "the development evidence schema must explicitly record its action list"),
    ("computerbench: verifier exits on contract instead of acceptance", "computerbench_verifier.py",
     '''    return 0 if report["acceptance_complete"] else 2''',
     '''    return 0 if report["contract_valid"] else 2''', "test_computerbench.py",
     "pack-only validity is not an accepted independent result"),
    ("computerbench: invalid RSA reaches modular exponentiation", "computerbench_verifier.py",
     '''    if (type(modulus) is not int
            or not 2048 <= modulus.bit_length() <= 8192
            or modulus % 2 == 0 or type(exponent) is not int
            or not 3 <= exponent <= 0xffffffff or exponent % 2 == 0
            or exponent >= modulus):''',
     '''    if False:''', "test_computerbench.py",
     "oversized modulus or exponent must refuse before pow"),
    ("computerbench: nonboolean cleanup accepted", "computerbench.py",
     '''            or cleanup.get("confirmed") is not True''',
     '''            or not cleanup.get("confirmed")''', "test_computerbench.py",
     "cleanup confirmation must be the explicit boolean schema value"),
    ("computerbench: partial batch exits success", "computerbench.py",
     '''    complete = (report.get("selection_complete") if args.case
                else report.get("development_complete"))''',
     '''    complete = report.get("selection_complete")''', "test_computerbench.py",
     "an all-case batch exits success only when the full development gate completes"),
    ("computerbench: verifier build change after challenge ignored", "computerbench_verifier.py",
     '''        "verifier_build_sha256": verifier_build_sha256,''',
     '''        "verifier_build_sha256": "0" * 64,''', "test_computerbench.py",
     "challenge identity must change when the external verifier build changes"),
    ("computerbench: missing external artifact escapes contract refusal", "computerbench_verifier.py",
     '''    except OSError as error:
        raise ContractError(label + " secure open refused") from error
    finally:
        os.close(directory)''',
     '''    except FileExistsError as error:
        raise ContractError(label + " secure open refused") from error
    finally:
        os.close(directory)''', "test_computerbench.py",
     "missing or unreadable external evidence must remain a non-success contract result",
     "Windows production refuses before the POSIX descriptor-open branch"),
    ("evidence: output after machine terminal accepted", "evidence.py",
     '''    if index != last:''', '''    if False:''', "test_package.py",
     "the sole runner record must be the last nonempty output"),
    ("evidence: runner registry order not pinned", "evidence.py",
     '''    if record["tests"] != expected_tests:''', '''    if False:''',
     "test_package.py", "the terminal record must name the registered tests in exact order"),
    ("evidence: child may forge reserved parent framing", "tests/run_all.py",
     '''        if (normalized.startswith(TERMINAL_PREFIX)
                or HEADER_RE.fullmatch(normalized)):''',
     '''        if False:''', "test_package.py",
     "child headers and terminal records must be escaped before captured relay"),
    ("evidence: Unicode parent framing reduced to ASCII whitespace",
     "tests/run_all.py",
     '''        character = line[start]
        if not (character.isspace() or ord(character) < 32''',
     '''        character = line[start]
        if not (character in " \\t\\r\\n\\v\\f" or ord(character) < 32''',
     "test_package.py",
     "NBSP and other Unicode whitespace cannot expose child-controlled parent framing"),
    ("evidence: undecodable bytes become replacement characters", "evidence.py",
     '''    return raw.decode("utf-8", errors="backslashreplace")''',
     '''    return raw.decode("utf-8", errors="replace")''', "test_package.py",
     "evidence generation must preserve invalid bytes as escapes, never U+FFFD"),
    ("computer run boundary: cleanup replaces main exception", "loop.py",
     "                primary.add_note('Computer cleanup also failed: '+repr(cleanup))",
     '                raise', "test_computer_session.py", "main cancellation/exit must survive cleanup failure after all sessions are attempted"),
    ("computer review interaction: quarantine masks interruption", "computersession.py",
     "            original.add_note('Quarantine refresh failed: '+type(persistence_error).__name__)",
     '            raise', "test_computer_session.py", "storage failure must not replace the original system interruption"),
    ("computer review: lineage-keyed ownership", "computersession.py",
     "self._owner_rel='effects/computer/server-'+_digest(server_name)+'.json'",
     "self._owner_rel='effects/computer/server-'+_digest([server_name,self.lineage])+'.json'",
     "test_computer_session.py", "failed construction must quarantine the server across unrelated lineages"),
    ("computer review: cleanup default daemon", "computerprocess.py",
     '        command=_docker_verified(root,docker)', "        command=[docker['executable']]",
     "test_computer_session.py", "absence on another daemon cannot certify owned container closure"),
    ("computer review: daemon identity precheck removed", "computerprocess.py",
     "    if _docker_identity(command)!=docker['daemon_id']:", '    if False:',
     "test_computer_session.py", "replacement daemon refuses before any destructive cleanup"),
    ("computer review: cached public role policy", "loop.py",
     "                with open(path,'rb') as f: roles=tomllib.load(f).get('roles',{})",
     "                roles=self.cfg.get('roles',{})",
     "test_computer_session.py", "owner settings-file revocation must deny the next direct public call"),
    ("computer review: MCP source pin removed", "computersession.py",
     "        if hasattr(self,'_source') and source!=self._source:", '        if False:',
     "test_computer_session.py", "identical fallback content cannot inherit trust from a deleted config source"),
    ("computer review: system exception aborts cleanup", "loop.py",
     '                except BaseException as error:\n                    errors.append(error)',
     '                except Exception as error:\n                    errors.append(error)',
     "test_computer_session.py", "KeyboardInterrupt must not abandon later owned sessions"),
    ("computer review: POSIX leader reaped early", "computerprocess.py",
     '    return os.waitid(os.P_PID,child.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is not None',
     '    return child.poll() is not None',
     "test_computer_session.py", "non-reaping observation must retain identity until group termination"),
    ("computer review: POSIX group readback removed", "computerprocess.py",
     '    child.wait(timeout=3)\n    deadline=time.monotonic()+3',
     '    child.wait(timeout=3)\n    return\n    deadline=time.monotonic()+3',
     "test_computer_session.py", "lingering group cannot be certified closed from leader wait alone"),
    ("computer session correction: viewport recheck removed", "computeruse.py",
     '    if(p.view_context){', '    if(false){',
     "test_computer_session.py", "real host viewport change must refuse before input", False, ('AGENT_COMPUTER_LIVE','1')),
    ("computer session correction: cleanup stops at first failure", "loop.py",
     '                    errors.append(error)', '                    raise',
     "test_computer_session.py", "later owned sessions must close even when an earlier environment cleanup fails"),
    ("computer session: process reuse removed", "computersession.py",
     '        if self.server is None:\n            environment=',
     '        if True:\n            environment=',
     "test_computer_session.py", "turns and failover must retain the same owned process"),
    ("computer session: exclusive lease bypassed", "computersession.py",
     '            self._lease.__enter__()', '            self._lease = None',
     "test_computer_session.py", "a second task cannot take an existing task browser"),
    ("computer session: epoch receipt verification removed", "computersession.py",
     '            observation=self._unseal(receipt)', '            observation=receipt[\'observation\']',
     "test_computer_session.py", "task envelope and physical artifact integrity must be verified"),
    ("computer session: PREPARED persistence removed", "computersession.py",
     "        data['actions'].append(action); self._save(data)", "        data['actions'].append(action)",
     "test_computer_session.py", "intent must exist durably before dispatch"),
    ("computer session: DISPATCHED transport hook removed", "mcp.py",
     '                if before_send is not None:\n                    before_send()',
     '                if False:\n                    before_send()',
     "test_computer_session.py", "killed dispatch owner must recover UNKNOWN, never known-no-effect"),
    ("computer session: fsync removed", "computersession.py",
     "fileauth.write_json(self.root,self._rel,data,actor='harness',durable=True)",
     "fileauth.write_json(self.root,self._rel,data,actor='harness')",
     "test_computer_session.py", "PREPARED and DISPATCHED require completed file fsync"),
    ("computer session: UNKNOWN lineage retry allowed", "computersession.py",
     "        if mutation and any(a['state']=='UNKNOWN' and not self._resolved(a) for a in self.actions()):",
     "        if False:", "test_computer_session.py", "a fresh retry task cannot escape unknown lineage history"),
    ("computer session: pending click certified", "computersession.py",
     '                self._update(identity,dispatch_acknowledged=True)',
     "                self._update(identity,state='VERIFIED',dispatch_acknowledged=True)",
     "test_computer_session.py", "dispatch acknowledgment never proves workflow completion"),
    ("computer session: terminal cleanup removed", "loop.py",
     "            self.close_computers('task '+task['status'], task['id'])",
     '            pass', "test_computer_session.py", "done and failed tasks release no live process"),
    ("computer session: direct role allowlist removed", "loop.py",
     "            if role_tools is not None and name not in role_tools:",
     '            if False:', "test_computer_session.py", "direct tool callers cannot bypass a denied role"),
    ("computer session: owner-only reconciliation removed", "computersession.py",
      "        controlplane.owner_only('reconcile computer action')", '        pass',
      "test_computer_session.py", "worker environment cannot attest its own effect"),
    ("computer session: reconciliation evidence zone authority bypassed",
     "computersession.py",
     '''                    allow_zones={fileauth.ZONE_CONTROL,fileauth.ZONE_RUNTIME})''',
     '''                    allow_zones=None)''',
     "test_computer_session.py",
     "the original root-relative evidence path must be typed by File Authority"),
    ("fileauth: dot path borrows trusted prefix zone", "fileauth.py",
     '''    if any(part in (".", "..") for part in parts):''',
     '''    if False:''', "test_computer_session.py",
     "logical zone authority must refuse ambiguous dot components",
     "Windows separately rejects dot components as ambiguous trailing-dot names"),
    ("fileauth: filesystem control characters reach path APIs", "fileauth.py",
     '''    if any(ord(character) < 32 or ord(character) == 127
           for character in raw):''',
     '''    if False:''', "test_computer_session.py",
     "malformed filesystem strings must produce a typed denial"),
    ("fileauth: physical identity and zone containment bypassed", "fileauth.py",
     '''        physical_logical, physical_root = _physical_relative(root_real, full)''',
     '''        physical_logical, physical_root = logical, root_real''',
     "test_computer_session.py",
     "outside and cross-zone links must not inherit their lexical zone"),
    ("fileauth: credential exclusion bypassed after alias resolution", "fileauth.py",
     '''    if credentials.is_secret(full, physical_root):''',
     '''    if False:''', "test_computer_session.py",
     "resolved credential objects must remain unreadable through every zone"),
    ("computer session: caller reclassifies physical alias spelling",
     "computersession.py",
     '''                self._artifact(evidence,allow_zones={
                    fileauth.ZONE_CONTROL,fileauth.ZONE_RUNTIME})''',
     '''                physical=fileauth.resolve(
                    self.root,evidence['path'],'read','harness')
                rel=os.path.relpath(physical,self.root).replace(os.sep,'/')
                if fileauth.zone_of(rel) not in (
                        fileauth.ZONE_CONTROL,fileauth.ZONE_RUNTIME):
                    raise C.Refused('owner evidence must be CONTROL or RUNTIME, not worker output alone')
                self._artifact(evidence)''',
     "test_computer_session.py",
     "filesystem aliases must not be reclassified from a derived spelling",
     "the deterministic alias witness uses a POSIX symlink; Windows 8.3 is tested separately when available"),
    ("computer session: artifact filesystem errors escape public refusal",
     "computersession.py",
     '''        except (fileauth.Denied,OSError,ValueError) as error:''',
     '''        except fileauth.Denied as error:''',
     "test_computer_session.py",
     "missing or concurrently removed evidence must be a recoverable refusal"),
    ("computer session: POSIX artifact anchor follows raced leaf",
     "computersession.py",
     '''        return os.open(path,flags|getattr(os,'O_NOFOLLOW',0))''',
     '''        return os.open(path,flags)''',
     "test_computer_session.py",
     "a leaf replaced after resolution must never redirect the evidence anchor",
     "Windows uses CreateFileW with FILE_FLAG_OPEN_REPARSE_POINT instead"),
    ("computer session: Windows artifact anchor allows delete sharing",
     "computersession.py",
     '''    handle=create(full,0x80000000,0x00000001,None,3,0x00200000,None)''',
     '''    handle=create(full,0x80000000,0x00000005,None,3,0x00200000,None)''',
     "test_computer_session.py",
     "the artifact anchor must deny rename and unlink until validation finishes",
     False,None,('nt','Windows CreateFile sharing behavior')),
    ("computer session: artifact post-read inode binding removed",
     "computersession.py",
     '''            if (after.st_dev,after.st_ino)!=(anchor.st_dev,anchor.st_ino):''',
     '''            if False:''',
     "test_computer_session.py",
     "a pathname replacement after descriptor read must refuse",
     "Windows can deny replacement while the anchor is open; POSIX permits the rename and exercises this comparison"),
    ("computer session: raw evaluator exposed", "mcp.py",
     '            and _authority is not _COMPUTER_AUTHORITY):', '            and False):',
     "test_computeruse.py", "generic raw code remains denied on the bounded adapter"),
    ("computer session: process-tree supervisor bypassed", "mcp.py",
     '            cmd=computerprocess.command(spec,*owned_process)', '            pass',
     "test_computer_session.py", "owned grandchild must lose execution at session finalization"),
    ("mcp transport: second stdout reader", "mcp.py",
     '        self._reader.start()',
     '        self._reader.start()\n        threading.Thread(target=self._read_frames, daemon=True).start()',
     "test_mcp_hardening.py", "one thread must own every stdout read across timeouts"),
    ("mcp transport: wrong-ID response delivery", "mcp.py",
     '                    slot = self._pending.pop(msg["id"], None)',
     '                    slot = self._pending.pop(next(iter(self._pending), None), None)',
     "test_mcp_hardening.py", "reversed and late responses must reach only their request ID"),
    ("mcp transport: timeout slot retained", "mcp.py",
     '                self._pending.pop(request_id, None)',
     '                pass',
     "test_mcp_hardening.py", "timeout must free its slot so the next call can dispatch"),
    ("mcp transport: EOF leaves waiters asleep", "mcp.py",
     '                    self._terminate("MCP server closed the pipe")',
     '                    pass',
     "test_mcp_hardening.py", "EOF must wake all waiters before their request timeouts"),
    ("mcp image: digest dropped from artifact name", "mcp.py",
     '    name = digest + ext',
     '    name = "artifact" + ext',
     "test_mcp.py", "different literal image bytes must retain distinct SHA-256 paths"),
    ("mcp image: target byte and identity gate bypassed", "mcp.py",
     '    if not _read_immutable_target(path, raw):',
     '    if False:',
     "test_mcp.py", "linked or swapped existing digest targets must refuse"),
    ("mcp image: post-verification directory gate bypassed", "mcp.py",
     '    if not _stable_artifact_directory(root, directory, identity):',
     '    if False:',
     "test_mcp.py", "a parent moved during target verification must refuse"),
    ("mcp image: directory race recheck removed", "mcp.py",
     '        current, current_identity = _artifact_directory(root)',
     '        return True',
     "test_mcp.py", "a redirected artifact directory must fail closed after creation"),
    ("mcp image: raced publication cleanup removed", "mcp.py",
     '                        _remove_published_alias(path, temporary)',
     '                        pass',
     "test_mcp.py", "a last-moment directory swap must leave no outside digest",
     False, None, ("nt", "POSIX publication is directory-fd anchored and never "
                        "uses the Windows alias-cleanup fallback")),
    ("mcp image: POSIX directory-fd publication anchor removed", "mcp.py",
     '''                            os.link(os.path.basename(temporary), name,
                                    src_dir_fd=dir_fd, dst_dir_fd=dir_fd,
                                    follow_symlinks=False)''',
     '''                            os.link(os.path.basename(temporary), name)''',
     "test_mcp.py", "POSIX source and destination names must use the validated directory descriptor",
     "Windows has no dir_fd link API; it uses identity revalidation and alias cleanup"),
    ("mcp image: physical root alias canonicalization removed", "mcp.py",
     '    root_real = os.path.realpath(root or ".")',
     '    root_real = os.path.abspath(root or ".")',
     "test_mcp.py", "normal and actual 8.3 spellings must reach the same physical read-boundary test",
     False, None, ("nt", "8.3 short-name aliases are a Windows path-spelling contract")),
    ("mcp image: structured artifact sink dropped", "mcp.py",
     '                    artifacts.append(dict(saved))',
     '                    pass',
     "test_mcp.py", "artifact metadata must survive flattened display truncation"),
    ("mcp image: declaration conflict accepted", "mcp.py",
     '        return image if not normalized or normalized == mime else None',
     '        return image',
     "test_mcp.py", "mislabeled image bytes must not claim the declared MIME"),
    ("mcp image: WAV canonicalization removed", "mcp.py",
     '        return "audio/wav", ".wav", None, None',
     '        return "application/octet-stream", ".bin", None, None',
     "test_mcp.py", "WAV bytes must retain safe canonical audio metadata"),
    ("mcp image: generic declaration controls suffix", "mcp.py",
     '    return "application/octet-stream", ".bin", None, None',
     '    return declared or "application/octet-stream", ".exe", None, None',
     "test_mcp.py", "generic bytes must use .bin and application/octet-stream"),
    ("mcp image: encoded allocation bound removed", "mcp.py",
     '    if encoded_size // 4 * 3 - padding > _MAX_BLOB_BYTES:',
     '    if False:',
     "test_mcp.py", "oversized encoded input must refuse before base64 decoding"),
    ("computer: browser selector misclassified as URL", "mcp.py",
     '        looks_urlish = ((str(k).lower() in _URL_KEYS and not selector_target)',
     '        looks_urlish = ((str(k).lower() in _URL_KEYS)',
     "test_computeruse.py", "browser click selectors must reach the guarded server"),
    ("computer: extra artifacts ignored", "computeruse.py",
     '    if names != {r["file"] for r in rows}:',
     '    if False:',
     "test_computeruse.py", "extra and duplicate output must refuse"),
    ("computer: corrupt bytes accepted", "computeruse.py",
     '        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:',
     '        if len(data) != row["bytes"]:',
     "test_computeruse.py", "same-length content corruption must refuse"),
    ("computer: expected manifest can change", "computeruse.py",
     '    if digest_manifest(manifest) != expected_digest:',
     '    if False:',
     "test_computeruse.py", "an altered expected manifest must refuse"),
    ("computer: forged browser receipt accepted", "computeruse.py",
     '        if not isinstance(receipt["mac"], str) or not hmac.compare_digest(self._mac(body), receipt["mac"]):',
     '        if False:',
     "test_computeruse.py", "a changed observation receipt must refuse"),
    ("computer: stale browser observation accepted", "computeruse.py",
     '        if receipt["session"] != self.session_id or receipt["revision"] != self._revision:',
     '        if False:',
     "test_computeruse.py", "a superseded browser observation must refuse"),
    ("computer: browser authorization reusable", "computeruse.py",
     '            self._consumed.add(receipt["mac"])',
     '            pass',
     "test_computeruse.py", "one browser action receipt cannot authorize a retry"),
    ("computer: off-origin browser target accepted", "computeruse.py",
     '            if _origin(link["href"]) != self.allowed_origin:',
     '            if False:',
     "test_computeruse.py", "off-origin browser targets must refuse"),
    ("computer: untrusted atomic observation enabled", "computeruse.py",
     'def playwright_observe(server, root, trace=None):\n'
     '    """Fixed read-only observation for the bounded invoice adapter."""\n'
     '    import mcp\n'
     '    spec = getattr(server, "spec", {}) or {}\n'
     '    if spec.get("atomic_browser_adapter") is not True:',
     'def playwright_observe(server, root, trace=None):\n'
     '    """Fixed read-only observation for the bounded invoice adapter."""\n'
     '    import mcp\n'
     '    spec = getattr(server, "spec", {}) or {}\n'
     '    if False:',
     "test_computeruse.py", "the shipped observation requires owner-bound enablement"),
    ("computer: untrusted atomic action enabled", "computeruse.py",
     'def playwright_atomic_click(server, root, preconditions, trace=None):\n'
     '    """Bounded locator click; legacy name does not imply atomic check-and-act.\n\n'
     '    The owner must opt this adapter into the MCP server\'s trusted identity.\n'
     '    Network containment remains the server configuration\'s responsibility.\n'
     '    """\n'
     '    import mcp\n'
     '    spec = getattr(server, "spec", {}) or {}\n'
     '    if spec.get("atomic_browser_adapter") is not True:',
     'def playwright_atomic_click(server, root, preconditions, trace=None):\n'
     '    """Bounded locator click; legacy name does not imply atomic check-and-act.\n\n'
     '    The owner must opt this adapter into the MCP server\'s trusted identity.\n'
     '    Network containment remains the server configuration\'s responsibility.\n'
     '    """\n'
     '    import mcp\n'
     '    spec = getattr(server, "spec", {}) or {}\n'
     '    if False:',
     "test_computeruse.py", "the shipped action requires owner-bound enablement"),
    ("computer: adapter precondition refusal ignored", "computeruse.py",
     '    if parsed.get("refused"):',
     '    if False:',
     "test_computeruse.py", "an adapter precondition refusal cannot become an action receipt"),
    ("computer: raw browser evaluator bypass", "mcp.py",
     '            and _authority is not _COMPUTER_AUTHORITY):',
     '            and False):',
     "test_computeruse.py", "an atomic-adapter server must deny direct evaluator calls"),
    ("computer: visibility actionability removed", "computeruse.py",
     "    code = _HOST_CLICK % (json.dumps(p, separators=(\",\", \":\"), allow_nan=False), deadline_epoch)",
     "    code = _HOST_CLICK.replace(\"if(s.visibility!=='visible'||s.display==='none'||r.width<=0||r.height<=0)\", \"if(false)\").replace(\"await locator.click({trial:true,force:false,timeout:remaining()});\", \"/* mutation removes actionability trial */\").replace(\"await locator.click({force:false,timeout:remaining()});\", \"await locator.click({force:true,timeout:remaining()});\").replace(\"if(!hit || !(a===hit || a.contains(hit)))\", \"if(false)\") % (json.dumps(p, separators=(\",\", \":\"), allow_nan=False), deadline_epoch)",
     "test_computeruse_live.py", "real activation counters must reject missing visibility protection"),
    ("computer: enabled actionability removed", "computeruse.py",
     "    code = _HOST_CLICK % (json.dumps(p, separators=(\",\", \":\"), allow_nan=False), deadline_epoch)",
     "    code = _HOST_CLICK.replace(\"if(a.closest('[disabled],[aria-disabled=\\\"true\\\"],[inert]'))\", \"if(false)\") % (json.dumps(p, separators=(\",\", \":\"), allow_nan=False), deadline_epoch)",
     "test_computeruse_live.py", "real activation counters must reject missing enabled protection"),
    ("computer: hit-test actionability removed", "computeruse.py",
     "    code = _HOST_CLICK % (json.dumps(p, separators=(\",\", \":\"), allow_nan=False), deadline_epoch)",
     "    code = _HOST_CLICK.replace(\"if(!hit || !(a===hit || a.contains(hit)))\", \"if(false)\").replace(\"await locator.click({trial:true,force:false,timeout:remaining()});\", \"/* mutation removes actionability trial */\").replace(\"await locator.click({force:false,timeout:remaining()});\", \"await locator.click({force:true,timeout:remaining()});\") % (json.dumps(p, separators=(\",\", \":\"), allow_nan=False), deadline_epoch)",
     "test_computeruse_live.py", "real activation counters must reject missing hit-test protection"),
    ("computer: tab-frame actionability removed", "computeruse.py",
     "    code = _HOST_CLICK % (json.dumps(p, separators=(\",\", \":\"), allow_nan=False), deadline_epoch)",
     "    code = _HOST_CLICK.replace(\"host.tab===p.binding.tab && host.frame===p.binding.frame && host.document===p.binding.document\", \"true\") % (json.dumps(p, separators=(\",\", \":\"), allow_nan=False), deadline_epoch)",
     "test_computeruse_live.py", "real activation counters must reject missing tab-frame protection"),
    ("computer: post observation omitted", "computeruse.py",
     '        parsed["post_observation"] = playwright_observe(server, root, trace)',
     '        pass',
     "test_computeruse.py", "dispatch without post-observation must not report success"),
    ("computer: blocked observation dispatch permitted", "computeruse.py",
     '            if state["dialog"] or state["expired"]:',
     '            if False:',
     "test_computeruse.py", "a blocked observation must refuse before consumption and adapter entry"),
    ("computer: malformed post observation accepted", "computeruse.py",
     '                post = self._state(result["post_observation"])',
     '                post = result["post_observation"]',
     "test_computeruse.py", "structurally malformed post-state must remain unresolved"),
    ("providers: unrelated root settings dropped", "providers.py",
     '    _emit_table(lines, (), cfg)',
     '    _emit_table(lines, (), {k: v for k, v in cfg.items() if k in ("agent", "providers", "roles")})',
     "test_providers.py", "provider edits must preserve unrelated root tables"),
    ("providers: nested tables stringified", "providers.py",
     '            _emit_table(lines, path + (key,), value)',
     '            lines.append(f"{_key(key)} = {_fmt(str(value))}")',
     "test_providers.py", "provider edits must preserve nested tables as tables"),
    ("providers: transaction lock removed", "providers.py",
     '    with locks.advisory_holding(p + ".update", timeout=20):',
     '    if True:',
     "test_providers.py", "concurrent public add and set_role must both survive"),
    ("providers: shared temporary file", "providers.py",
     '    fd, tmp = tempfile.mkstemp(prefix="settings.toml.", suffix=".tmp", dir=root)',
     '    tmp = p + ".tmp"\n    fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)',
     "test_providers.py", "concurrent failed saves must isolate and clean only their own temps"),
    ("providers: stale load before transaction lock", "providers.py",
     '    with locks.advisory_holding(p + ".update", timeout=20):\n        cfg = load(root)',
     '    cfg = load(root)\n    with locks.advisory_holding(p + ".update", timeout=20):',
     "test_providers.py", "the waiting public update must read the preceding commit"),
    ("providers: stealable age-based lock restored", "providers.py",
     '    with locks.advisory_holding(p + ".update", timeout=20):',
     '    with locks.holding(p + ".update", timeout=20, stale=60):',
     "test_providers.py", "an aged live provider owner must retain exclusion"),
    ("panel goal: raw grader field restored", "ui.html",
     'class="field gGate" aria-label="acceptance gate"',
     'class="field" id="gAccept" aria-label="acceptance gate"',
     "test_ledger_defects.py", "goal form must expose named gates only"),

    ("mission work: acceptance gate made optional", "ui.py",
     '''    if not d.get("done_check"):
        raise ValueError("mission work needs a named acceptance gate")
    done_check = _net_gate(d["done_check"])''',
     '''    done_check = _net_gate(d.get("done_check"))''',
     "test_ledger_defects.py", "ungated mission work was queued"),

    ("panel routes: browser history overwritten", "ui.html",
     'if(S.routeReady) history.pushState(null, "", h);',
     'if(S.routeReady) history.replaceState(null, "", h);',
     "test_ledger_defects.py", "Back/Forward route history must be retained"),

    ("panel goal: raw network grader accepted", "ui.py",
     '''        if not isinstance(spec, dict):
            raise ValueError("goal acceptance over the network must name a gate")''',
     '''        if not isinstance(spec, dict):
            spec = {"gate": "exists", "path": "out/x"}''',
     "test_ledger_defects.py", "network acceptance accepted"),

    ("goal budget: nonfinite limit accepted", "contract.py",
     '    if not math.isfinite(number):',
     '    if False:',
     "test_ledger_defects.py", "invalid goal limit was accepted"),

    ("goal contract: non-string grader accepted", "contract.py",
     '        if not isinstance(check, str) or not check.strip():',
     '        if False:',
     "test_ledger_defects.py", "malformed contract acceptance was accepted"),

    ("goal contract: traversal id accepted", "contract.py",
     '''    if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):''',
     '''    if False:''',
     "test_ledger_defects.py", "malformed goal identity was accepted"),

    ("goal contract: unsafe swarm group accepted", "contract.py",
     '''            if not isinstance(group, str) or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", group):''',
     '''            if False:''',
     "test_ledger_defects.py", "malformed contract acceptance was accepted"),

    ("goal contract: empty objective accepted", "contract.py",
     '    goal = validate_goal_text(goal)',
     '    goal = str(goal)',
     "test_ledger_defects.py", "malformed goal identity was accepted"),

    ("goal pursuit: artifacts precede validation", "goal.py",
     '    goal = contractmod.validate_goal_text(goal)',
     '    goal = str(goal)',
     "test_ledger_defects.py", "invalid pursuit reached artifact creation"),

    ("goal pursuit: empty explicit id becomes default", "goal.py",
     '''        time.strftime("g-%Y%m%d-%H%M%S") if gid is None else gid)''',
     '''        gid or time.strftime("g-%Y%m%d-%H%M%S"))''',
     "test_ledger_defects.py", "invalid pursuit reached artifact creation"),

    ("goal pursuit: expert path escapes the fleet", "goal.py",
     '''    if not isinstance(expert, str) or not re.fullmatch(
            r"[a-z0-9-]{1,64}", expert):''',
     '''    if False:''',
     "test_ledger_defects.py", "invalid pursuit reached artifact creation"),

    ("learner: invalid cycles silently default", "ui.py",
     '''                learner_cycles = _goal_request({
                    "cycles": d["cycles"] if "cycles" in d else 6
                })["cycles"]''',
     '''                learner_cycles = d.get("cycles") or 6''',
     "test_ui.py", "invalid learner launch created an expert before refusing"),

    ("review: ambiguous option IDs accepted", "twinmeasurement.py",
     '            raise ValueError("duplicate option ID after normalization")',
     '            pass',
     "test_twin_measurement.py", "normalized duplicate IDs must refuse in either order"),

    ("review: skipped observations inflate headline", "evidence.py",
     '"observations": sum(s["observations"] for s in systems)',
     '"observations": sum(len(v["sections"]) for v in per.values())',
     "test_package.py", "headline must equal the passing classified ledger"),

    ("review: suite registry silently omits a file", "tests/run_all.py",
     'TESTS = ["test_resume.py", "test_lock.py",',
     'TESTS = ["test_lock.py",',
     "test_ledger_defects.py", "badge check must reject missing registered tests"),

    ("measurement: evaluation skips record validation", "twin.py",
     '        held = TM.split(rows)["test"]',
     '        held = [e for e in rows if TM.partition(e) == "test"]',
     "test_twin_measurement.py", "post-fit malformed records are accepted"),

    ("measurement: intervening input changes ignored", "twinmeasurement.py",
     '        raise twin.Refused("inputs changed during evaluation; rerun fidelity")',
     '        pass',
     "test_twin_measurement.py", "concurrent updates do not refuse archival"),

    ("measurement: final labels select rules", "twin.py",
     '    rules = M.validate_rules(M.mine_rules(fitset), validation)',
     '    rules = M.validate_rules(M.mine_rules(fitset), holdout)',
     "test_twin_measurement.py", "final rows enter actual rule validation"),

    ("measurement: split depends on the answer", "twinmeasurement.py",
     '    bucket = int(group(row), 16) % 5',
     '    bucket = int(digest([group(row), row.get("choice")]), 16) % 5',
     "test_twin_measurement.py", "choice changes partition membership"),

    ("measurement: live neighbors leak into the frozen predictor", "twin.py",
     '            v["neighbors"] if "neighbors" in v else decisions(episodes(root)))',
     '            decisions(episodes(root)))',
     "test_twin_measurement.py", "poisoned live rows change predictions"),

    ("measurement: stale report treated as current", "twinmeasurement.py",
     '        if report != authoritative or report["binding"] != expected:',
     '        if False:',
     "test_twin_measurement.py", "old evidence survives policy changes"),

    ("measurement: cold-start novelty is treated as policy drift", "twin.py",
     '    if row.get("novelty", 1.0) >= NOVEL:',
     '    if False:',
     "test_twin_measurement.py", "cold errors freeze the owner model"),

    # ---- the clean window (docs/DESIGN-P11): marked data, grounded compaction
    ("window: read_file returns its bytes unmarked", "loop.py",
     '''                    result = context.fence_tool("read_file", rel, truncate(f.read()))''',
     '''                    result = truncate(f.read())''',
     "test_guardrails.py",
     "a directive inside a file indistinguishable from harness text"),

    ("window: a marker inside data closes the fence", "context.py",
     '''    return _FENCE_RE.sub(FENCE_ESCAPE, str(text))''',
     '''    return str(text)''',
     "test_guardrails.py",
     "a poisoned file closing its own fence early"),

    ("compaction: the summarizer reads the transcript as instructions", "loop.py",
     '''                    {"role": "system", "content": COMPACTION_SYSTEM},''',
     '''                    {"role": "system", "content": "You compress agent transcripts."},''',
     "test_compaction.py",
     "a summarizer with no grounding contract"),

    ("compaction: the byte bound ignored until the gate refuses", "loop.py",
     '''        return used > COMPACT_AT_FRACTION * maximum''',
     '''        return False''',
     "test_compaction.py",
     "a transcript refused by the provider before the compactor ran"),

    ("fileauth: conflict rulings back in the worker's workspace", "fileauth.py",
     '''    "courses": {"source-overrides.json", "conflicts.json",''',
     '''    "courses": {"source-overrides.json",''',
     "test_promotion_leakage.py",
     "a worker forging BINDING rulings"),

    ("memory: the fleet ledger appended without its lock", "memory.py",
     '''    with locks.holding(path):
        existing = _read_jsonl(path)''',
     '''    if True:
        existing = _read_jsonl(path)''',
     "test_memory.py",
     "two writers filing the same recurrence count"),

    # ---- the owner's twin (docs/DESIGN-P10): four laws, each broken once
    ("twin: sealed prediction revealed before the decision", "twin.py",
     '''    if p.get("status") == "sealed":
        return {"id": pid, "status": "sealed", "sealed": p["sealed"],''',
     '''    if False:
        return {"id": pid, "status": "sealed", "sealed": p["sealed"],''',
     "test_twin.py",
     "a shadow prediction shown to the owner before they decided"),

    ("twin: the clone predicts without consent", "twin.py",
     '''    need_scope(root, "predict")
    k = kernel or load_kernel(root)''',
     '''    k = kernel or load_kernel(root)''',
     "test_twin.py",
     "a prediction about the owner with no consent on record"),

    ("twin: the label dropped from the clone's output", "twin.py",
     '''    return {"label": LABEL, "kernel_version": v["v"], "kernel_hash": v["hash"],''',
     '''    return {"label": "", "kernel_version": v["v"], "kernel_hash": v["hash"],''',
     "test_twin.py",
     "a clone output that does not say it is a model of the owner"),

    ("twin: act runs without a definition of done", "twin.py",
     '''    if not done_check:
        raise Refused("a twin acting for the owner must be gated: pass "''',
     '''    if False:
        raise Refused("a twin acting for the owner must be gated: pass "''',
     "test_twin.py",
     "the twin queuing ungated work on the owner's behalf"),

    ("docker: egress allowed by default", "sandbox.py",
     '''    if not _cfg(cfg).get("sandbox_network"):
        argv += ["--network", "none"]           # default-deny egress''',
     '''    if False:
        argv += ["--network", "none"]''',
     "test_docker_live.py",
     "a container that can reach the internet by default"),

    ("docker: timeout leaves the container", "sandbox.py",
     '''    except subprocess.TimeoutExpired:
        _kill_container(name)
        raise''',
     '''    except subprocess.TimeoutExpired:
        raise''',
     "test_docker_live.py",
     "an orphaned container after a timeout"),

    # Was labelled "docker: credentials passed through" and paired with the
    # credential assertions, which scrub_env has already satisfied before
    # _docker runs at all -- so this breaks the SECOND filter, not the one
    # that stops credentials. It reported CAUGHT on Windows for a reason that
    # had nothing to do with the test noticing: forwarding a Windows PATH
    # into a Linux container means `sh` is not found and the container never
    # boots, so the credential check never executed. Linux, where the host
    # PATH is valid, told the truth and reported MISSED. Now it says what it
    # breaks, is POSIX-only for the same boot reason, and the docker test
    # asserts the property it actually removes.
    ("docker: every host variable forwarded into the container", "sandbox.py",
     '''    for k, v in sorted(_agent_env(env).items()):''',
     '''    for k, v in sorted(env.items()):''',
     "test_docker_live.py",
     "the host's entire environment inside the container",
     "forwarding a Windows PATH into a Linux container stops `sh` from being "
     "found, so the container never boots and no assertion is ever reached — "
     "a CAUGHT here would be the crash being counted, not the test noticing"),

    ("backup: the S3 query string signed uncanonicalised", "backup.py",
     '''    query = "&".join(f"{k}={v}" for k, v in sorted(parts))''',
     '''    query = u.query or ""''',
     "test_backup.py",
     "every signed request with a query string rejected by the store"),

    ("backup: a push proceeds without credentials", "backup.py",
     '''    if not kid or not secret:
        raise SystemExit(
            f"ERROR: no S3 credentials. Put {S3_KEY_ID} and {S3_KEY_SECRET} "''',
     '''    if False:
        raise SystemExit(
            f"ERROR: no S3 credentials. Put {S3_KEY_ID} and {S3_KEY_SECRET} "''',
     "test_backup.py",
     "an unauthenticated upload attempt instead of a refusal"),

    ("acquire: install becomes bookkeeping again", "acquire.py",
     '''        rc, out, err = sandbox.run(shlex.join(argv), arena, {}, 900, install_cfg)''',
     '''        rc, out, err = 0, "(install recorded without execution)", ""''',
     "test_acquire.py",
     "an acquisition reaching 'trusted' with nothing installed"),

    ("acquire: the capability test accepts a supplied verdict", "acquire.py",
     '''    if passed is None:''',
     '''    if False:''',
     "test_acquire.py",
     "the MANDATORY step recording a claim instead of an observation"),

    ("acquire: a need matches a capability by substring", "acquire.py",
     '''    hay = set(re.findall(r"[a-z0-9_]+", str(haystack or "").lower()))
    return bool(need_words & hay)''',
     '''    return any(w in str(haystack or "").lower() for w in need_words)''',
     "test_acquire.py",
     "unrelated requests refused because 'thing' is inside 'everything'"),

    ("backup: a snapshot archives its own backups", "backup.py",
     '''    for full, rel in _walk(home, with_logs, exclude_dir=out_dir):''',
     '''    for full, rel in _walk(home, with_logs):''',
     "test_backup.py",
     "archives compounding until the disk the fleet saves itself onto is full"),

    ("execution: the declared approval control is skipped", "execution.py",
     '''    if spec.get("approval"):''',
     '''    if False:''',
     "test_invariants.py",
     "an agent publishing or deleting without the owner ever being asked"),

    ("policy: a consequential command is treated as ordinary", "policy.py",
     '''    for pattern, why in REVIEW + extra:''',
     '''    for pattern, why in extra:''',
     "test_invariants.py",
     "git push, npm publish and rm -r all running unreviewed"),

    ("activate: a provider is chosen whose key is absent", "bootstrap.py",
     '''        probe = {"api_key_env": key_env}
        if not credentials.resolve(probe, root=home):
            continue''',
     '''        probe = {"api_key_env": key_env}
        if False:
            continue''',
     "test_first_day.py",
     "every role pointed at a provider that cannot authenticate"),

    ("activate: incomplete credentials are used anyway", "bootstrap.py",
     '''        if any(not v for v in extra.values()):
            continue                      # a key without its account id is not usable''',
     '''        if False:
            continue''',
     "test_first_day.py",
     "a base_url still containing {CLOUDFLARE_ACCOUNT_ID}"),

    ("toolbox: a capability is judged by PATH alone", "toolbox.py",
     '''        import ingest
        return ingest.tool_argv(binary, module)''',
     '''        return [shutil.which(binary)] if shutil.which(binary) else None''',
     "test_invariants.py",
     "a capability reported MISSING that the machine actually has"),

    ("inbox: a zero settle window can still hold a file back", "ingest.py",
     '''        if settle > 0 and age < settle:''',
     '''        if age < settle:''',
     "test_url.py",
     "a dropped file never ingested because a clock ran a few ms ahead"),

    ("credentials: the environment scrub removed from every backend",
     "sandbox.py",
     '''    env, dropped = scrub_env({**os.environ, **(env or {})}, cfg, cmd)''',
     '''    env, dropped = {**os.environ, **(env or {})}, []''',
     "test_secrets.py",
     "API keys handed to a command the harness did not write"),

    ("provider: no Authorization header", "loop.py",
     '''                        "Authorization": f"Bearer {self._api_key(prov)}",''',
     '''                        "X-Not-Auth": "removed",''',
     "test_live_provider.py",
     "requests sent with no credential"),

    ("provider: malformed body kills the task", "loop.py",
     '''                    except (ValueError, KeyError, IndexError, TypeError) as e:''',
     '''                    except (KeyError, IndexError) as e:''',
     "test_live_provider.py",
     "a garbled body escaping the retry ladder"),

    ("provider: 4xx retried like weather", "loop.py",
     '''                    if e.code in (429, 500, 502, 503, 504):''',
     '''                    if e.code in (400, 401, 429, 500, 502, 503, 504):''',
     "test_live_provider.py",
     "five paid retries of a request that cannot succeed"),

    ("package: ship the credential file", "package.py",
     None,   # handled specially: plant agent.env and neuter the skip rule
     None,
     "test_package.py",
     "a shipped API key"),

    ("endurance: never archive finished work", "loop.py",
     '''        if len(finished) <= self.retain_finished + 25:''',
     '''        if True:''',
     "test_endurance.py",
     "a hot queue that grows without bound"),

    # The anchor below is the AUTHORIZATION CALL ITSELF, not the shape of the
    # code around it. The previous anchor quoted three lines including a
    # `return True` that moved when _may_write/_may were split apart, so the
    # mutation silently stopped applying ("anchor appears 0x") and the RBAC
    # control lost its mutation coverage without anything going red. A
    # mutation that cannot be applied proves exactly as much as a test that
    # cannot fail.
    ("rbac: every write allowed", "ui.py",
     '''            org.check(self.home, actor, permission, obj)''',
     '''            pass''',
     "test_rbac.py",
     "a viewer able to delete an agent"),

    ("fleet: creation stops seeding the home", "fleet.py",
     '''    seed_home(home)
    os.makedirs(os.path.join(home, "experts"), exist_ok=True)''',
     '''    os.makedirs(os.path.join(home, "experts"), exist_ok=True)''',
     "test_invariants.py",
     "a crash on a never-bootstrapped home"),

    # --- found by CI, the first time this suite ran on Linux ---

    ("loop: a running task is stolen from a live sibling", "loop.py",
     '''    def _may_resume(self, task):
        """May THIS loop pick up a task already marked running?"""
        r = task.get("runner")''',
     '''    def _may_resume(self, task):
        """May THIS loop pick up a task already marked running?"""
        return True
        r = task.get("runner")''',
     "test_audit.py",
     "two loops executing one task at the same time"),

    ("credentials: a secret written under the umask", "credentials.py",
     '''    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)''',
     '''    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path''',
     "test_preflight.py",
     "a fleet token every account on the machine can read", True),

    ("docker: the container runs as root in the mount", "sandbox.py",
     '''    if os.name != "nt":
        # Files created in a bind mount belong to the user INSIDE the''',
     '''    if False:
        # Files created in a bind mount belong to the user INSIDE the''',
     "test_docker_live.py",
     "a workspace the agent can no longer write to", True),

    # All three are paired with test_frontier.py, which needs no Docker and
    # never prints the token these results are scored on — so they are CAUGHT
    # or MISSED on every machine, never silently skipped.
    ("frontier: a probe need not fail before acquiring", "frontier.py",
     '''    if row["stage"] != "red":''',
     '''    if False:''',
     "test_frontier.py",
     "installing on the strength of a probe that never distinguished having "
     "the capability from not having it"),

    ("frontier: the last seal wins", "frontier.py",
     '''        if first is None:
            first = h
        elif h != first:
            conflict = True''',
     '''        first = h''',
     "test_frontier.py",
     "an attacker who never needs to edit a seal, because appending one wins"),

    ("universal: physical actuation is not an authority gap", "universal.py",
     '''     "acting on physical equipment, which cannot be undone by a retry"),''',
     '''     "acting on physical equipment (unreachable)") if False else
     (r"(?!x)x", "unreachable"),''',
     "test_universal.py",
     "a fleet that cuts power to a heater or changes a CNC feed rate without "
     "ever stopping to ask — the one failure here that burns something"),

    ("universal: a media noun has no direction", "universal.py",
     '''        makes = producing or verb''',
     '''        makes = False''',
     "test_universal.py",
     "synthesis answered with recognition — a run sent at the tool that does "
     "the reverse of the task"),

    ("universal: the losing side of a direction is not suppressed",
     "universal.py",
     '''        seen.add(make_cap)
        seen.add(read_cap)''',
     '''        seen.add(cap)''',
     "test_universal.py",
     "a goal asking for BOTH synthesis and recognition of the same noun, so "
     "the run picks whichever it likes"),

    ("frontier: readiness is decided inside the expert root", "frontier.py",
     '''            if (ad and ad.get("probe_hash") == row.get("probe_hash")
                    and ad.get("how_hash") == _how_hash(row.get("how_argv") or [])):''',
     '''            if True:''',
     "test_frontier.py",
     "a capability made READY by writing one word into a file the worker can "
     "reach"),
]


def run_test(name, timeout=900):
    """-> "CAUGHT" | "MISSED" | "SKIP".

    A test that SKIPS itself (docker unavailable, for instance) exits 0
    without having run anything, and calling that MISSED would report a
    false alarm on every machine without a daemon. Read the marker the test
    prints rather than the exit code alone.
    """
    r = subprocess.run([PY, os.path.join(AGENT, "tests", name)],
                       cwd=os.path.join(AGENT, "tests"),
                       capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "PYTHONUTF8": "1"})
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 and "SKIP " in out:
        return "SKIP"
    return "CAUGHT" if r.returncode != 0 else "MISSED"


def _plant_decoy(path, text):
    """Create a decoy file, or return None if a REAL one is already there.

    THE RETURN VALUE IS THE WHOLE POINT: `planted` must mean "a file WE
    created and may therefore delete". It used to be assigned BEFORE the
    existence check —

        planted = os.path.join(AGENT, "agent.env")
        if os.path.exists(planted):
            results.append((label, "SKIP", "agent.env already exists"))
            continue                 # a `continue` inside try RUNS finally
        ...
        finally:
            if planted and os.path.exists(planted):
                os.remove(planted)   # ...and deleted the owner's real keys

    — so the guard correctly detected a real agent.env, announced that it was
    SKIPPING to avoid touching it, and then deleted it on the way out.
    Running `python mutate_check.py` destroyed the operator's API keys
    silently, while reporting a skip. Found when a real agent.env vanished
    from this working tree mid-session and the deletion was traced here.

    A name that means "ours" cannot be assigned before we know it is ours.
    """
    if os.path.exists(path):
        return None
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = []
    for entry in MUTATIONS:
        label, fname, find, repl, test, expect = entry[:6]
        # Some properties exist only on POSIX — file modes are one, because
        # Windows uses ACLs and the platform says so at every chmod. Calling
        # such a mutation MISSED on Windows would be a false alarm; calling
        # it CAUGHT would be a lie. It is declared, and skipped out loud.
        # True, or a string saying WHY this one is POSIX-only. A single
        # blanket reason was wrong the moment a second kind of mutation
        # became POSIX-only for a different cause, and a skip line nobody
        # can trust is worse than no skip line.
        posix_only = entry[6] if len(entry) > 6 else False
        if only and only not in label:
            continue
        required_env = entry[7] if len(entry) > 7 else None
        if required_env and os.environ.get(required_env[0]) != required_env[1]:
            results.append((label, "SKIP", "requires " + "=".join(required_env)))
            continue
        platform_only = entry[8] if len(entry) > 8 else None
        if platform_only and os.name != platform_only[0]:
            platform = "Windows" if platform_only[0] == "nt" else platform_only[0]
            results.append((label, "SKIP", platform + "-only: "
                            + platform_only[1]))
            continue
        if posix_only and os.name == "nt":
            why = posix_only if isinstance(posix_only, str) else \
                "Windows uses ACLs, not modes, so nothing here can catch it"
            results.append((label, "SKIP", f"POSIX-only: {why} — run on Linux"))
            continue
        path = os.path.join(AGENT, fname)
        backup = path + ".mutbak"
        planted = None
        shutil.copy(path, backup)
        try:
            if find is None:                    # the packaging mutation
                planted = _plant_decoy(
                    os.path.join(AGENT, "agent.env"),
                    "OPENAI_API_KEY=sk-mutation-should-be-caught\n")
                if planted is None:
                    results.append((label, "SKIP", "agent.env already exists"))
                    continue
                src = io.open(path, encoding="utf-8").read()
                mutated = src.replace("def should_skip(", "def _orig_skip(")
                mutated += ("\n\ndef should_skip(*a, **k):\n"
                            "    return False\n")
                io.open(path, "w", encoding="utf-8", newline="\n").write(mutated)
            else:
                src = io.open(path, encoding="utf-8").read()
                if src.count(find) != 1:
                    results.append((label, "SKIP",
                                    f"anchor appears {src.count(find)}x"))
                    continue
                io.open(path, "w", encoding="utf-8", newline="\n").write(
                    src.replace(find, repl, 1))
            t0 = time.time()
            verdict = run_test(test)
            took = time.time() - t0
            said = {"CAUGHT": "failed", "MISSED": "PASSED ANYWAY",
                    "SKIP": "skipped itself (a prerequisite is missing)"}
            results.append((label, verdict,
                            f"{test} {said[verdict]} in {took:.0f}s — {expect}"))
        finally:
            shutil.copy(backup, path)
            os.remove(backup)
            if planted and os.path.exists(planted):
                os.remove(planted)
    print()
    print("=" * 78)
    print("MUTATION RESULTS — a MISSED row is a test that measures nothing")
    print("=" * 78)
    for label, verdict, detail in results:
        print(f"  {verdict:<7} {label}")
        print(f"          {detail}")
    missed = [r for r in results if r[1] == "MISSED"]
    print()
    print(f"{len(results)} mutations: "
          f"{sum(1 for r in results if r[1] == 'CAUGHT')} caught, "
          f"{len(missed)} missed, "
          f"{sum(1 for r in results if r[1] == 'SKIP')} skipped")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
