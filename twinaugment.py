#!/usr/bin/env python3
"""COLD START AND THE AUGMENTATION ENGINE (docs/DESIGN-P10.1-twin-depth.md).

Two findings from the research behind Phase 10 shaped this module:

  * Park et al. (arXiv 2411.10109): a person's own first-person account —
    a structured interview — grounds a simulation better than any tag, and
    the person's own retest agreement is the ceiling to score against.
    Hence INTERVIEW (fourteen questions in the owner's words) and VIGNETTES
    (decision situations generated from a feature schema, answered by the
    owner; a re-answer is a retest).
  * The brief's Super-Self is an augmentation ENGINE, not one prompt. Hence
    LENSES (K analyst calls, one per lens, aggregated by vote with evidence
    and disputed assumptions) and SIMULATION (the Clone re-run over
    perturbed situations: decision stability and flip points — mechanical,
    honest about being a sensitivity analysis, never a claim about the
    world).

Also here: consider() — the alternatives the owner weighed in the nearest
past situations, for when only a situation is known.
"""

import hashlib
import json
import math
import random
import re
import time

INTERVIEW = [
    ("values", "What do you refuse to compromise on, in your own words?"),
    ("optimize", "When you decide, what are you actually optimizing for most "
                 "of the time?"),
    ("risk", "Describe a risk you took that others would not, and one you "
             "refused that others took. Why?"),
    ("speed", "When do you decide fast, and when do you slow down and dig?"),
    ("money_time", "How do you trade money against time? Give a real example."),
    ("persuasion", "What kind of evidence changes your mind? What never does?"),
    ("investigate", "How do you know you have investigated enough?"),
    ("delegate", "What do you delegate without a second look, and what do "
                 "you never delegate?"),
    ("refuse", "What do you say no to on sight?"),
    ("people", "Name two people you deal with very differently and say how."),
    ("attention", "When something lands on your desk, what do you check "
                  "first, second, third?"),
    ("writing", "Write three sentences the way you would actually write them "
                "to a supplier who missed a deadline."),
    ("change", "How have your decisions changed in the last two years, and "
               "why?"),
    ("aspiration", "What are you building toward over the next five years?"),
]

DEFAULT_FEATURES = [
    {"name": "risk", "low": 0.0, "high": 1.0,
     "text": "probability the downside materializes"},
    {"name": "margin", "low": 0.0, "high": 0.6, "text": "expected margin"},
    {"name": "cost_usd", "low": 1000, "high": 1000000, "log": True,
     "text": "capital at stake"},
    {"name": "reversibility", "low": 0.0, "high": 1.0,
     "text": "how easily the decision can be undone"},
    {"name": "trust", "low": 0.0, "high": 1.0,
     "text": "how much you trust the counterpart"},
    {"name": "time_pressure", "low": 0.0, "high": 1.0,
     "text": "how soon it must be decided"},
]
DEFAULT_OPTIONS = ["grant", "deny"]
COUNTERPARTS = ["a long-time partner", "a new supplier", "an investor",
                "an employee", "a stranger"]
DEFAULT_LENSES = ["finance", "risk", "relationships"]
SIM_SAMPLES = 400
SIM_NOISE = 0.5              # in standard deviations
SWEEP_STEPS = 8
SWEEP_SIGMA = 2.0            # how far each feature is swept, each way


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


# ============================================================== interview

def interview_bank(kernel):
    done = (kernel.get("identity") or {}).get("interview") or {}
    return [{"id": qid, "question": q, "answer": (done.get(qid) or {}).get("text"),
             "at": (done.get(qid) or {}).get("at")} for qid, q in INTERVIEW]


def interview_answer(kernel, qid, text, by="owner"):
    if qid not in dict(INTERVIEW):
        raise ValueError(f"no interview question {qid!r}")
    text = " ".join(str(text).split())[:3000]
    if not text:
        raise ValueError("an empty answer is not an answer")
    ident = kernel.setdefault("identity", {})
    ident.setdefault("interview", {})[qid] = {
        "text": text, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by}
    return ident["interview"][qid]


def interview_texts(kernel):
    return [v["text"] for v in ((kernel.get("identity") or {}).get("interview")
                                or {}).values() if v.get("text")]


# ============================================================== vignettes

def schema(cfg):
    tc = ((cfg or {}).get("agent") or {}).get("twin") or {}
    feats = tc.get("features") or DEFAULT_FEATURES
    out = []
    for f in feats:
        if isinstance(f, str):
            out.append({"name": f, "low": 0.0, "high": 1.0, "text": f})
        elif isinstance(f, dict) and f.get("name"):
            out.append({"name": str(f["name"]), "low": float(f.get("low", 0.0)),
                        "high": float(f.get("high", 1.0)),
                        "log": bool(f.get("log")), "text": str(f.get("text") or f["name"])})
    options = tc.get("vignette_options") or DEFAULT_OPTIONS
    return out[:8], [str(o) for o in options][:6]


def generate(cfg, n=24, seed=7):
    """Deterministic stratified sampling over the schema: every feature is
    spread across its range within every block of vignettes, so a first
    fit sees the corners, not a cluster."""
    feats, options = schema(cfg)
    rng = random.Random(seed)
    out = []
    strata = max(n, 1)
    perms = {f["name"]: rng.sample(range(strata), strata) for f in feats}
    for i in range(n):
        features = {}
        parts = []
        for f in feats:
            u = (perms[f["name"]][i] + rng.random()) / strata
            if f.get("log") and f["low"] > 0:
                v = math.exp(math.log(f["low"]) + u * (math.log(f["high"]) - math.log(f["low"])))
                v = round(v, -2) if v >= 1000 else round(v, 1)
            else:
                v = round(f["low"] + u * (f["high"] - f["low"]), 2)
            features[f["name"]] = v
            parts.append(f"{f['text']} {v:g}")
        cp = COUNTERPARTS[i % len(COUNTERPARTS)]
        text = f"Vignette: {cp} brings a proposal — " + "; ".join(parts) + "."
        vid = "vg-" + _sha([text, features, options])[:10]
        out.append({"id": vid, "text": text, "features": features,
                    "options": options, "counterpart": cp})
    return out


def vignette_status(vignettes, episodes):
    """Which vignettes are answered, and how many times (a second answer
    is a retest)."""
    rounds = {}
    for e in episodes:
        o = str(e.get("origin") or "")
        if o.startswith("vignette:"):
            vid = o.split(":")[1]
            rounds[vid] = rounds.get(vid, 0) + 1
    return [dict(v, answered=rounds.get(v["id"], 0)) for v in vignettes]


# ================================================================ consider

def consider(similar_episodes, limit=6):
    """The options the owner weighed in the nearest past situations, most
    frequent first, with how often each was chosen."""
    seen, chosen = {}, {}
    for e in similar_episodes:
        for o in e.get("options") or []:
            seen[o["id"]] = seen.get(o["id"], 0) + 1
        c = e.get("choice")
        if c is not None:
            chosen[str(c)] = chosen.get(str(c), 0) + 1
    ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"id": oid, "seen": n, "chosen": chosen.get(oid, 0)} for oid, n in ranked]


# ================================================================== lenses

LENS_SYSTEM = (
    "You are the SUPER-SELF of the owner described below, working as their "
    "{lens} analyst: the same person, objectives, standards and relationships, "
    "with more time and research than they biologically have. Decide as they "
    "would if they knew everything you can find out about {lens}. Preserve "
    "their objectives; do not import your own. Return JSON only: "
    "{{\"choice\": <option id>, \"reason\": <one paragraph>, "
    "\"disputed_assumption\": <the owner's likely assumption you think is "
    "false, or null>, \"evidence\": [<short strings>]}}.")


def _json_in(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def run_lenses(agent, role, owner_block, payload, option_ids, lenses):
    """One metered call per lens; the vote is the recommendation. Ties go
    to the first option in vote order, and the caller breaks a tie with the
    Clone's argmax."""
    results = []
    for lens in lenses:
        msg, _u, _p = agent.call_model(
            role, [{"role": "system", "content": LENS_SYSTEM.format(lens=lens)
                    + "\n\n" + owner_block},
                   {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            use_tools=False, purpose="twin")
        parsed = _json_in(msg.get("content") or "") or {}
        choice = str(parsed.get("choice")) if parsed.get("choice") is not None else None
        results.append({"lens": lens, "choice": choice if choice in option_ids else None,
                        "reason": parsed.get("reason"),
                        "disputed_assumption": parsed.get("disputed_assumption"),
                        "evidence": [str(x) for x in (parsed.get("evidence") or [])][:8]})
    votes = {}
    for r in results:
        if r["choice"]:
            votes[r["choice"]] = votes.get(r["choice"], 0) + 1
    return {"lenses": results, "votes": votes,
            "disputed": [r["disputed_assumption"] for r in results
                         if r.get("disputed_assumption")],
            "evidence": sorted({e for r in results for e in r["evidence"]})}


# ============================================================== simulation

def simulate(predict_fn, situation, counterpart, stats, samples=SIM_SAMPLES,
             noise=SIM_NOISE, steps=SWEEP_STEPS, seed=11):
    """The Clone over perturbed situations. predict_fn(situation) ->
    prediction dict with argmax/probs. stats: {"sit:<f>": (mean, std)}."""
    feats = {k: float(v) for k, v in (situation.get("features") or {}).items()}
    base = predict_fn(situation)
    argmax = base["argmax"]
    if not feats:
        return {"stability": None, "flips": [], "samples": 0,
                "why": "no numeric features to perturb"}
    rng = random.Random(seed)
    agree = 0
    for _ in range(samples):
        pert = dict(feats)
        for k in pert:
            _m, s = stats.get(f"sit:{k}", (0.0, 0.0))
            s = s if s and s > 1e-9 else abs(pert[k]) * 0.1 or 0.1
            pert[k] = pert[k] + rng.gauss(0.0, noise * s)
        p = predict_fn(dict(situation, features=pert))
        agree += int(p["argmax"] == argmax)
    flips = []
    for k in sorted(feats):
        _m, s = stats.get(f"sit:{k}", (0.0, 0.0))
        s = s if s and s > 1e-9 else abs(feats[k]) * 0.1 or 0.1
        flip = None
        for direction in (1, -1):
            for i in range(1, steps + 1):
                v = feats[k] + direction * SWEEP_SIGMA * s * i / steps
                p = predict_fn(dict(situation, features=dict(feats, **{k: v})))
                if p["argmax"] != argmax:
                    cand = {"feature": k, "at": round(v, 4), "becomes": p["argmax"],
                            "from": round(feats[k], 4)}
                    if flip is None or abs(v - feats[k]) < abs(flip["at"] - feats[k]):
                        flip = cand
                    break
        if flip:
            flips.append(flip)
    return {"stability": round(agree / samples, 4), "samples": samples,
            "noise_sd": noise, "flips": flips,
            "why": "the Clone's own policy over perturbed situations — a "
                   "sensitivity analysis, not a forecast of the world"}
