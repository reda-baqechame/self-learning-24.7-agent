# File Authority path identity and zone contract

Status: CU-0R corrective sub-design, 2026-09-08. This defines offline path
handling; it is not computer-use or release qualification.

## Two independent decisions

`resolve(root, rel, ...)` treats `root` as trusted configuration and `rel` as
untrusted. It makes both of these decisions before returning a path:

1. The requested spelling has one unambiguous logical zone. Absolute paths,
   dot components, drive-relative names, UNC/device names supplied as `rel`,
   and Windows alternate-stream/trailing-dot/trailing-space/reserved-device
   spellings are refused.
2. The resolved target is physically inside the same root object and its
   physical zone is independently permitted. Existing ancestors are compared
   by filesystem identity, so a supported Windows long/8.3 root alias is not
   rejected merely because its strings differ. POSIX case is not folded.

Both logical and physical zones are enforced. A CONTROL-looking symlink or
junction into WORKSPACE therefore cannot authorize a WORKSPACE object, and a
WORKSPACE-looking alias cannot make CONTROL writable. Links that leave the
root are refused. Same-zone links inside the root remain subject to each
consumer's link/inode rules; File Authority does not claim that resolving a
pathname is a race-free open.

## Caller census

| Call family | Actor/mode | Allowed zones | Existing/new | Reason |
|---|---|---|---|---|
| `loop`, `context`, `operators`, `procedure`, `verification`, `verifier`, `candidates`, `computeruse` | agent/read or agent/write | normal zone policy | both | model-influenced work paths; CONTROL/RUNTIME writes and all secrets remain denied |
| `computersession` ledgers, leases, state and configured source | harness/read or harness/write | normal zone policy | both | runtime-owned durable session state; callers still validate schemas and ownership |
| `computerprocess` state, stop requests and Docker ownership files | harness/read or harness/write | normal zone policy | both | host supervisor bookkeeping; the CID reader adds its separate exact-name/content contract |
| MCP immutable artifact publication | harness/write | ROOT only | new/existing | content-addressed publication uses its own no-link, identity and atomic-publication checks |
| Owner reconciliation evidence | harness/read | CONTROL or RUNTIME only | existing | owner-only entry plus exact path/digest/byte schema; the artifact is reopened and inode/zone/digest checked before state changes |
| Direct `zone_of` consumers in `controlplane` and `loop` | classification only | n/a | n/a | classify platform-generated root-relative names; untrusted filesystem access still goes through `resolve` |

No call receives arbitrary CONTROL-file-reading authority from a permitted
zone alone. The consumer must still name the exact expected record and validate
its schema/binding. `allow_zones` narrows access; it never bypasses containment,
credential exclusion, agent write policy, or consumer validation.

## Open and replacement races

Generic `resolve` is a pathname authority, not a descriptor-returning secure
open. Callers facing an adversarial writer must either use a dedicated
descriptor/open-relative implementation or perform independent before/open/
after identity checks and have no side effect before those checks finish.

Owner reconciliation uses the latter bounded contract: the zone is checked on
every resolution; `lstat` identity must equal the opened descriptor; the file
must be one regular single-link object of the declared size; bytes must match
the declared SHA-256; and a post-read resolution and `lstat` must still name the
opened inode. A failure records no reconciliation. This protects the supported
local evidence read. It does not turn an unsafe shared developer-host account
into an isolated verifier identity, and it does not authorize production use.

The external ComputerBench verifier instead uses POSIX descriptor/no-follow
opens. Windows production external verification remains explicitly
unsupported and fails closed because Python does not expose the required
open-relative/no-reparse primitive in this implementation.

## Qualification matrix

Focused tests cover actual Windows long/8.3 root identity when available,
CONTROL/RUNTIME positive access, ROOT/WORKSPACE denial, dot and mixed-separator
traversal, absolute/drive/UNC/device and Windows ambiguous names, physical
escape and cross-zone links where the host can construct them, non-existing
leaves under an aliased parent, credential and hardlink refusal, inode
replacement checks, and ordinary file operations. Platform-specific cases are
reported as such; a POSIX symlink is never evidence of a Windows junction.
