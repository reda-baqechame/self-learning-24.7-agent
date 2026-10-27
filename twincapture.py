#!/usr/bin/env python3
"""THE WORK STREAM — Layer 1 of the twin, as far as consent and a stdlib
process can honestly reach (docs/DESIGN-P10.1-twin-depth.md).

The brief asked for total experience capture: what the owner does, in
what order, how long between acts. Without a screen recorder there are
three streams a consented process can read, and each is named by the
owner before a byte of it is stored:

  panel     org/audit.jsonl — the platform's own attributable log of every
            mutating panel route (who, action, object). Covered by the
            `predict` consent: it is the record of the owner using the
            fleet.
  command   a shell history file the owner NAMES in [agent.twin]
            capture_history. Stored after redaction: a token that is
            key-shaped (credentials.key_shaped) is replaced, and a line
            with one is kept only as "[redacted command]".
  edit      directories the owner NAMES in [agent.twin] capture_dirs. A
            manifest of (size, hash, line count) per file is kept; on
            change an event records the path, lines added/removed, byte
            delta and seconds since that path last changed — never the
            content.

From the stream:

  routines(events)     the owner's WORKFLOW PROGRAMS: a bigram next-act
                       table and frequent trigrams ("after git commit,
                       git push — 12/14")
  workflow_fidelity()  next-act accuracy on the held-out tail (last 20 %)
                       against the majority baseline, with lift

Everything lands in twin/events.jsonl (CONTROL) and twin/capture-state.json.
A source that is not named captures nothing; the benchmark proves it.
"""

import hashlib
import json
import os
import re
import time

HOME = os.path.dirname(os.path.abspath(__file__))

EVENTS = os.path.join("twin", "events.jsonl")
STATE = os.path.join("twin", "capture-state.json")
MAX_FILES_DEFAULT = 5000
MAX_TEXT_BYTES = 1_000_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             ".mypy_cache", ".pytest_cache", "dist", "build"}
MAX_HISTORY_LINES = 2000
MIN_ROUTINE_SUPPORT = 3
HOLDOUT_SHARE = 0.2


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def _read_jsonl(path):
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return out


def _append(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def twin_cfg(cfg):
    return ((cfg or {}).get("agent") or {}).get("twin") or {}


def _home_of(root):
    parent = os.path.dirname(root)
    if os.path.basename(parent) == "experts":
        return os.path.dirname(parent)
    return root


# ================================================================= events

def events(root):
    return _read_jsonl(os.path.join(root, EVENTS))


def _record(root, have, kind, text, origin, at=None, meta=None, source=""):
    h = _sha([kind, origin])
    if h in have:
        return False
    have.add(h)
    _append(os.path.join(root, EVENTS), {
        "id": "ev-" + h[:12], "at": at or _now(), "kind": kind,
        "text": str(text)[:500], "meta": meta or {}, "source": source,
        "origin": origin, "hash": h})
    return True


def redact_command(line):
    """A command line safe to keep: key-shaped tokens replaced; a line that
    carried one is reduced to a marker, because the shape of a secret's
    context ("curl -H Authorization: ...") is itself a leak."""
    try:
        import credentials
        shaped = credentials.key_shaped
    except Exception:            # pragma: no cover
        def shaped(_t):
            return False
    toks = line.split()
    if any(shaped(t.strip("\"'")) or shaped(t.split("=", 1)[-1].strip("\"'"))
           for t in toks):
        return "[redacted command]"
    return line


def _capture_panel(root, have, owner, recorded):
    """The platform's own audit of the owner at the panel."""
    try:
        import org
        rows = org.trail(_home_of(root), limit=500)
    except Exception:
        rows = []
    n = 0
    legacy_seen = {(e.get("origin"), (e.get("meta") or {}).get("actor"))
                   for e in recorded if e.get("kind") == "panel"}
    for r in rows:
        actor = str(r.get("actor") or "")
        if not owner or actor != owner or actor.startswith("agent:"):
            continue
        legacy = f"panel:{r.get('at')}:{r.get('action')}:{r.get('object')}"
        if (legacy, actor) in legacy_seen:
            continue
        origin = "panel:v2:" + _sha([actor, r.get("at"), r.get("action"),
                                      r.get("object_kind"), r.get("object")])
        n += int(_record(root, have, "panel",
                         f"{r.get('action')} {r.get('object_kind')} {r.get('object')}",
                         origin, at=r.get("at"),
                         meta={"actor": actor, "action": r.get("action"),
                               "object": r.get("object")},
                         source="harvest:panel"))
    return n


def _capture_history(root, have, state, path):
    """New lines of a named shell history file, redacted, from the offset
    the last tick stopped at (a truncated file restarts at zero)."""
    if not path:
        return 0
    path = os.path.expandvars(os.path.expanduser(str(path)))
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0
    hist = state.setdefault("history", {"path": path, "offset": 0, "lines": 0})
    if hist.get("path") != path or hist.get("offset", 0) > size:
        hist.update({"path": path, "offset": 0, "lines": 0})
    n = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(hist["offset"])
            chunk = f.read()
            hist["offset"] = f.tell()
    except OSError:
        return 0
    lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
    for ln in lines[-MAX_HISTORY_LINES:]:
        hist["lines"] = hist.get("lines", 0) + 1
        text = redact_command(ln)
        n += int(_record(root, have, "command", text,
                         f"command:{path}:{hist['lines']}",
                         meta={"at_estimated": True,
                               "redacted": text == "[redacted command]"},
                         source="capture:history"))
    return n


def _manifest(dirpath, max_files):
    out = {}
    count = 0
    for dp, dns, fns in os.walk(dirpath):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in sorted(fns):
            if fn.startswith("."):
                continue
            p = os.path.join(dp, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size > MAX_TEXT_BYTES:
                continue
            count += 1
            if count > max_files:
                return out, True
            rel = os.path.relpath(p, dirpath).replace("\\", "/")
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            lines = data.count(b"\n")
            out[rel] = [st.st_size, hashlib.sha256(data).hexdigest()[:16], lines,
                        hashlib.sha256(b"\n".join(sorted(set(data.split(b"\n")))))
                        .hexdigest()[:16]]
    return out, False


def _capture_dirs(root, have, state, dirs, max_files):
    n = 0
    dstate = state.setdefault("dirs", {})
    for d in dirs or []:
        d = os.path.expandvars(os.path.expanduser(str(d)))
        if not os.path.isabs(d):
            d = os.path.join(root, d)
        if not os.path.isdir(d):
            continue
        cur, truncated = _manifest(d, max_files)
        prev = dstate.get(d, {}).get("manifest")
        last_at = dstate.get(d, {}).get("last_at", {})
        now = time.time()
        if prev is not None:
            for rel, (size, digest, lines, _bag) in cur.items():
                before = prev.get(rel)
                if before is None:
                    added, removed, delta = lines, 0, size
                elif before[1] == digest:
                    continue
                else:
                    added = max(lines - before[2], 0)
                    removed = max(before[2] - lines, 0)
                    if added == 0 and removed == 0:
                        added = removed = 1      # same length, different bytes
                    delta = size - before[0]
                since = (round(now - last_at[rel], 1) if rel in last_at else None)
                last_at[rel] = now
                n += int(_record(root, have, "edit", f"edit {rel}",
                                 f"edit:{d}:{rel}:{digest}",
                                 meta={"path": rel, "added": added,
                                       "removed": removed, "bytes": delta,
                                       "since_last_s": since,
                                       "ext": os.path.splitext(rel)[1]},
                                 source="capture:dirs"))
            for rel in prev:
                if rel not in cur:
                    last_at.pop(rel, None)
                    n += int(_record(root, have, "edit", f"delete {rel}",
                                     f"delete:{d}:{rel}:{prev[rel][1]}",
                                     meta={"path": rel, "added": 0,
                                           "removed": prev[rel][2],
                                           "bytes": -prev[rel][0],
                                           "ext": os.path.splitext(rel)[1]},
                                     source="capture:dirs"))
        dstate[d] = {"manifest": cur, "last_at": last_at, "at": _now(),
                     "truncated": truncated, "files": len(cur)}
    return n


def tick(root, cfg=None):
    """Read every named source once. Returns {panel, command, edit}."""
    import twin
    consented = twin.need_scope(root, "predict")
    tc = twin_cfg(cfg)
    recorded = events(root)
    have = {e["hash"] for e in recorded if "hash" in e}
    state = _read_json(os.path.join(root, STATE), {})
    out = {"panel": _capture_panel(root, have, str(consented.get("by") or ""), recorded),
           "command": _capture_history(root, have, state, tc.get("capture_history")),
           "edit": _capture_dirs(root, have, state, tc.get("capture_dirs"),
                                 int(tc.get("capture_max_files", MAX_FILES_DEFAULT)))}
    _write_json(os.path.join(root, STATE), state)
    return out


# =============================================================== routines

def act_token(ev):
    """The act an event IS, coarse enough to recur: a command's first two
    words, an edit's extension, a panel action."""
    k = ev.get("kind")
    if k == "command":
        words = re.findall(r"[A-Za-z0-9_.\-/\\]+", ev.get("text") or "")
        words = [w for w in words if not w.startswith("-")][:2]
        return "cmd:" + " ".join(words).lower() if words else "cmd:?"
    if k == "edit":
        m = ev.get("meta") or {}
        return "edit:" + ((m.get("ext") or "").lower() or "file")
    if k == "panel":
        return "panel:" + str((ev.get("meta") or {}).get("action") or "?")
    return f"{k}:?"


def sequence(evs):
    return [act_token(e) for e in evs]


def routines(evs, min_support=MIN_ROUTINE_SUPPORT, top=12):
    """Bigram next-act table + frequent trigrams."""
    seq = sequence(evs)
    big, tri, uni = {}, {}, {}
    for i, a in enumerate(seq):
        uni[a] = uni.get(a, 0) + 1
        if i + 1 < len(seq):
            big.setdefault(a, {})
            big[a][seq[i + 1]] = big[a].get(seq[i + 1], 0) + 1
        if i + 2 < len(seq):
            t = (a, seq[i + 1], seq[i + 2])
            tri[t] = tri.get(t, 0) + 1
    habits = []
    for a, nxt in big.items():
        total = sum(nxt.values())
        b, k = max(nxt.items(), key=lambda kv: (kv[1], kv[0]))
        if k >= min_support and k / total >= 0.5:
            habits.append({"after": a, "then": b, "support": k,
                           "of": total, "confidence": round(k / total, 3)})
    habits.sort(key=lambda h: (-h["support"], h["after"]))
    chains = [{"steps": list(t), "support": n} for t, n in tri.items()
              if n >= min_support]
    chains.sort(key=lambda c: (-c["support"], c["steps"]))
    return {"acts": len(seq), "distinct": len(uni), "habits": habits[:top],
            "chains": chains[:top], "table": {a: n for a, n in big.items()}}


def workflow_fidelity(evs, holdout_share=HOLDOUT_SHARE):
    """Next-act accuracy on the tail the table never saw, vs. always
    guessing the most common act."""
    seq = sequence(evs)
    if len(seq) < 10:
        return {"n": len(seq), "accuracy": None, "baseline": None, "lift": None,
                "why": "fewer than ten acts"}
    cut = int(len(seq) * (1 - holdout_share))
    head, tail = seq[:cut], seq[cut:]
    table, uni = {}, {}
    for i, a in enumerate(head):
        uni[a] = uni.get(a, 0) + 1
        if i + 1 < len(head):
            table.setdefault(a, {})
            table[a][head[i + 1]] = table[a].get(head[i + 1], 0) + 1
    majority = max(uni.items(), key=lambda kv: (kv[1], kv[0]))[0]
    hits = base = 0
    prev = head[-1]
    for a in tail:
        guess = (max(table[prev].items(), key=lambda kv: (kv[1], kv[0]))[0]
                 if prev in table else majority)
        hits += int(guess == a)
        base += int(majority == a)
        prev = a
    n = len(tail)
    acc, bl = round(hits / n, 4), round(base / n, 4)
    return {"n": n, "accuracy": acc, "baseline": bl,
            "lift": round(acc - bl, 4)}


def render_lines(evs, cap=3):
    r = routines(evs)
    if not r["acts"]:
        return []
    out = []
    counts = {}
    for e in evs:
        counts[e.get("kind")] = counts.get(e.get("kind"), 0) + 1
    out.append("- how they work (observed): "
               + ", ".join(f"{n} {k} acts" for k, n in sorted(counts.items())))
    for h in r["habits"][:cap - 1]:
        out.append(f"- after `{h['after']}` they usually `{h['then']}` "
                   f"({h['support']}/{h['of']})")
    return out[:cap]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="the owner's work stream")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick")
    sub.add_parser("routines")
    sub.add_parser("fidelity")
    p = sub.add_parser("events"); p.add_argument("--limit", type=int, default=30)
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    cfg = {}
    try:
        import tomllib
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            cfg = tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError):
        pass
    if a.cmd == "tick":
        print(json.dumps(tick(root, cfg), indent=1))
    elif a.cmd == "routines":
        print(json.dumps(routines(events(root)), indent=1))
    elif a.cmd == "fidelity":
        print(json.dumps(workflow_fidelity(events(root)), indent=1))
    else:
        for e in events(root)[-a.limit:]:
            print(f"{e['at']}  {e['kind']:8} {e['text'][:100]}")


if __name__ == "__main__":
    main()
