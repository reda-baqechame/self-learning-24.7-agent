#!/usr/bin/env python3
"""WHAT BREAKS AFTER THE FIRST HOUR — the failures a test run is too short
to have.

Every other test finishes in seconds. This platform is meant to run for
weeks, and the failures of a long run are a different family: ledgers that
grow without bound, logs that never rotate, locks that accumulate, memory
that creeps, an archive that is re-read in full on every task. None of them
is visible in a run that ends before the file gets big.

This does not simulate weeks — nothing can. It does the honest version:
drive a REAL loop through hundreds of tasks and measure whether the things
that would grow, grow. A quantity that is O(n) in total work is a quantity
that ends a 24/7 run; a quantity that is bounded is one that does not.

  1. the hot task queue stays bounded while total work grows — finished
     work is archived, not accumulated
  2. per-task latency does not degrade as the ledgers fill
  3. logs rotate rather than growing forever
  4. no lock file survives its holder
  5. the model-gateway ledger and the failure ledger stay proportionate
  6. the context window a task is given does not grow with fleet history

Scaled by AGENT_SOAK_TASKS (default 120, enough to see a trend without
making the suite unusable). Set it to 2000 for a real soak.

Run from the agent/ directory:  python tests/test_endurance.py
"""

import glob
import io
import json
import os
import statistics
import sys
import time

from common import (AGENT_DIR, agent_setting, make_sandbox, read_state,
                    run_drain)

sys.path.insert(0, AGENT_DIR)
import loop                    # noqa: E402

N = int(os.environ.get("AGENT_SOAK_TASKS", "120"))
SCRIPT = [{"tool": "write_file",
           "args": {"path": "out/soak.md", "content": "x"}},
          {"tool": "finish_task", "args": {"summary": "done"}}]


def _dir_bytes(path):
    total = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return total


def check_the_hot_queue_stays_bounded(root):
    """`state.json` is read and rewritten on every step. If it grows with
    total work, every task gets slower than the last one forever."""
    sizes, queue_lengths, per_batch = [], [], []
    a = loop.Agent(root)
    batch = max(10, N // 6)
    for cycle in range(6):
        for i in range(batch):
            a.add_task("practitioner", f"soak task {cycle}-{i}")
        t0 = time.time()
        run_drain(root, timeout=900)
        per_batch.append((time.time() - t0) / batch)
        st = read_state(root)
        queue_lengths.append(len(st["tasks"]))
        sizes.append(os.path.getsize(os.path.join(root, "state.json")))
    done_total = batch * 6
    a = loop.Agent(root)
    assert queue_lengths[-1] <= a.retain_finished + 30, (
        f"after {done_total} finished tasks the hot queue holds "
        f"{queue_lengths[-1]} of them against a retention setting of "
        f"{a.retain_finished} — nothing is being archived, so every future "
        f"task re-reads the entire history")
    # and NOTHING was lost: every task that left the queue is in the archive
    arch = a.archive_path()
    archived = 0
    if os.path.isfile(arch):
        with io.open(arch, encoding="utf-8", errors="replace") as f:
            archived = sum(1 for line in f if line.strip())
    assert archived + queue_lengths[-1] >= done_total, (
        f"{done_total} tasks ran, {queue_lengths[-1]} are in the queue and "
        f"{archived} are in the archive — {done_total - archived - queue_lengths[-1]} "
        f"vanished. Archiving must move work, never drop it")
    growth = sizes[-1] / max(sizes[0], 1)
    assert growth < 6, (
        f"state.json grew {growth:.1f}x over {done_total} tasks "
        f"({sizes[0]} -> {sizes[-1]} bytes). At this rate a month of work "
        f"makes every step read a file nobody can hold in memory")
    print(f"[queue] {done_total} tasks completed; the hot queue held "
          f"{queue_lengths[0]} then {queue_lengths[-1]} against a retention "
          f"of {a.retain_finished}, {archived} moved to the append-only "
          f"archive with none lost, and state.json went {sizes[0]} -> "
          f"{sizes[-1]} bytes ({growth:.1f}x)")
    return per_batch


def check_latency_does_not_degrade(per_batch, remeasure=None, retries=2):
    """The number that decides whether this is a 24/7 platform.

    A DEGRADING loop and a STALLED runner both make one batch slow, and only
    one of them is a defect. Hosted Windows runners stall for a batch at a
    time — on PR #28 the same code ran 0.12-0.18s flat on 3.11, spiked to
    0.86s in batch 2 on 3.12, and failed 3.13 only because its spike landed
    on the last batch, the single sample this check reads. Pristine main
    had a 0.61s spike in batch 5 on the same job. So an outlier last batch
    is re-measured with fresh work: a loop that slows as its history grows
    is slower STILL on the next batch (history only grew), while a stall
    clears. Only a slowdown that persists through every re-measure fails.
    """
    first, last = per_batch[0], per_batch[-1]
    median = statistics.median(per_batch)
    # a slow first batch (cold caches, first compile) is normal; the trend
    # that matters is late-vs-median
    bound = median * 3 + 0.5
    remeasured = []
    while last >= bound and remeasure is not None and len(remeasured) < retries:
        last = remeasure()
        remeasured.append(last)
    assert last < bound, (
        f"per-task time went {first:.3f}s -> {per_batch[-1]:.3f}s against a "
        f"median of {median:.3f}s"
        + (f", and stayed above {bound:.3f}s on {len(remeasured)} fresh "
           f"re-measure(s): {', '.join(f'{t:.3f}s' for t in remeasured)}"
           if remeasured else "")
        + ". Work that gets steadily slower as the ledgers fill is work that "
        "stops entirely at some point nobody planned for")
    note = (f"; the last batch read {per_batch[-1]:.2f}s, so it was "
            f"re-measured on fresh work at "
            f"{', '.join(f'{t:.2f}s' for t in remeasured)} — a stall, "
            f"not a trend" if remeasured else "")
    print(f"[latency] per-task wall time across 6 batches: "
          f"{', '.join(f'{t:.2f}s' for t in per_batch)} — median "
          f"{median:.2f}s, and the last batch is not an outlier{note}: the "
          f"loop does not get slower as its own history grows")


def check_latency_judge_tells_stall_from_trend():
    """The re-measure must not become a way to pass a real slowdown. Fed
    synthetic batches, the judge passes a stall that clears, and fails a
    loop that is slower again on fresh work and an outlier it cannot
    re-measure."""
    import contextlib
    flat = [0.12, 0.17, 0.17, 0.17, 0.17]
    # synthetic numbers must not print as a [latency] measurement, because
    # evidence.py quotes every tagged line as something the suite observed
    with contextlib.redirect_stdout(io.StringIO()):
        check_latency_does_not_degrade(flat + [1.17], lambda: 0.18)  # stall
    for name, per_batch, again in (
            ("trend", flat + [1.17], iter([1.30, 1.55]).__next__),
            ("no re-measure", flat + [1.17], None)):
        try:
            check_latency_does_not_degrade(per_batch, again)
        except AssertionError:
            continue
        raise AssertionError(f"the latency judge passed a {name} it must fail")
    print("[latency-judge] a one-batch stall that clears on fresh work "
          "passes; a slowdown that persists on fresh work fails, and so does "
          "an outlier that cannot be re-measured")


def check_logs_rotate(root):
    """A log that never rotates fills the disk, and it is always the disk of
    the machine somebody left running."""
    logs = os.path.join(root, "logs")
    agent_log = os.path.join(logs, "agent.log")
    assert os.path.isfile(agent_log)
    size = os.path.getsize(agent_log)
    cap = 5 * 1024 * 1024
    assert size < cap * 1.5, (
        f"agent.log is {size} bytes with no rotation in sight")
    # the rotation is configured, not hoped for
    import logging.handlers
    handlers = [h for h in loop.Agent(root).log.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert handlers, (
        "the agent log has no rotating handler — it will grow until the disk "
        "does not")
    h = handlers[0]
    assert h.maxBytes > 0 and h.backupCount > 0, (h.maxBytes, h.backupCount)
    total_cap = h.maxBytes * (h.backupCount + 1)
    print(f"[logs] agent.log is {size / 1024:.0f} KB and rotates at "
          f"{h.maxBytes / 1024 / 1024:.0f} MB x {h.backupCount} backups — a "
          f"hard ceiling of {total_cap / 1024 / 1024:.0f} MB per expert, "
          f"whatever happens")


def check_no_lock_outlives_its_holder(root):
    """A stale lock is how a 24/7 loop stops without anybody noticing."""
    stale = []
    for p in glob.glob(os.path.join(root, "**", "*.lock"), recursive=True):
        stale.append(p)
    for p in glob.glob(os.path.join(root, "**", ".lock*"), recursive=True):
        stale.append(p)
    assert not stale, (
        f"{len(stale)} lock file(s) survived the drain: {stale[:4]}. The next "
        f"loop to start will wait for a process that no longer exists")
    print(f"[locks] no lock file survived {N}+ tasks and 6 loop restarts — "
          f"every one was released by its holder or reclaimed as stale")


def check_ledgers_stay_proportionate(root):
    """Growth is fine. Growth per task that is worse than linear is not."""
    facts = {}
    for rel, what in (("logs/model-calls.jsonl", "the model gateway"),
                      ("logs/model-outcomes.jsonl", "routing outcomes"),
                      ("memory/failures.jsonl", "the failure ledger"),
                      ("contexts", "compiled context windows")):
        p = os.path.join(root, rel.replace("/", os.sep))
        if os.path.isdir(p):
            facts[what] = _dir_bytes(p)
        elif os.path.isfile(p):
            facts[what] = os.path.getsize(p)
    total = _dir_bytes(root)
    assert total < 400 * 1024 * 1024, (
        f"one expert consumed {total / 1024 / 1024:.0f} MB for {N} trivial "
        f"tasks")
    per_task = total / max(N, 1)
    assert per_task < 400_000, (
        f"{per_task:.0f} bytes per trivial task — a year of real work would "
        f"be measured in hundreds of gigabytes")
    print(f"[ledgers] the whole expert directory is "
          f"{total / 1024 / 1024:.1f} MB after {N}+ tasks "
          f"({per_task / 1024:.1f} KB per task): "
          + ", ".join(f"{w} {b / 1024:.0f} KB" for w, b in facts.items()))


def check_context_does_not_grow_with_history(root):
    """The window a task is given must be bounded by its BUDGET, not by how
    much the fleet happens to remember."""
    manifests = sorted(glob.glob(os.path.join(root, "contexts",
                                              "*.compile.json")),
                       key=os.path.getmtime)
    if len(manifests) < 4:
        print(f"[context] only {len(manifests)} compile manifest(s) written — "
              f"not enough to establish a trend, and saying so beats "
              f"inventing one")
        return
    def total_tokens(p):
        """The manifest's own accounting: the system block plus every
        source's used_tokens. Reading a key the manifest does not have
        returns 0 for every window, and a check whose numbers are all zero
        passes without measuring anything — which is how the first version
        of this function reported '0 -> 0 characters' and called it bounded.
        """
        with io.open(p, encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m.get("total_tokens"), (int, float)) and m["total_tokens"]:
            return float(m["total_tokens"])
        n = float((m.get("system") or {}).get("tokens", 0))
        n += float(m.get("user_tokens", 0))
        n += sum(float(s.get("used_tokens", 0))
                 for s in (m.get("sources") or []))
        return n
    early = statistics.median([total_tokens(p) for p in manifests[:3]])
    late = statistics.median([total_tokens(p) for p in manifests[-3:]])
    assert early > 0, (
        "every compiled window measured zero tokens — the manifest key this "
        "reads does not exist, so the check would pass whatever happened")
    assert late <= max(early * 2.5, early + 4_000), (
        f"the compiled context grew from {early:.0f} to {late:.0f} tokens "
        f"as history accumulated. A window that grows with memory is a bill "
        f"that grows with memory, and eventually a window that does not fit")
    print(f"[context] across {len(manifests)} compiled windows the median "
          f"size went {early:.0f} -> {late:.0f} tokens: the window is bounded "
          f"by its budget, not by how much the fleet remembers")


def main():
    root = make_sandbox("endurance", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": SCRIPT})
    # The default retention is 150 finished tasks and archiving fires at
    # 175 — more than a suite-friendly soak reaches, so the mechanism would
    # never run and the test would prove nothing while passing. Lowering it
    # exercises the MECHANISM several times over; the default itself is a
    # policy choice, not the thing under test.
    agent_setting(root, "retain_finished_tasks = 20")
    print(f"[soak] driving {N} real tasks through a real loop "
          f"(AGENT_SOAK_TASKS to change)")
    t0 = time.time()
    per_batch = check_the_hot_queue_stays_bounded(root)
    extra = []

    def remeasure():
        """One more batch on the SAME, now larger, history."""
        a = loop.Agent(root)
        batch = max(10, N // 6)
        for i in range(batch):
            a.add_task("practitioner", f"soak re-measure {len(extra)}-{i}")
        t0 = time.time()
        run_drain(root, timeout=900)
        extra.append((time.time() - t0) / batch)
        return extra[-1]

    check_latency_does_not_degrade(per_batch, remeasure)
    check_latency_judge_tells_stall_from_trend()
    check_logs_rotate(root)
    check_no_lock_outlives_its_holder(root)
    check_ledgers_stay_proportionate(root)
    check_context_does_not_grow_with_history(root)
    print(f"[soak] {time.time() - t0:.0f}s of continuous operation. This is "
          f"minutes, not weeks: it rules out the growth that is O(total "
          f"work), and it cannot rule out a leak that needs days to show.")
    print("PASS test_endurance")


if __name__ == "__main__":
    main()
