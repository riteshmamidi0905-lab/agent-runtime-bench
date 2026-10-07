"""Cross-run aggregation over several ARB-1 run directories (read-only; written after the runs, so it was not part of the pre-run analysis commit and is labelled as such in the report).
  python -m arb.aggregate reports/pass1 reports/repeat1 reports/sample11 ...  > reports/AGGREGATE.md
Greedy runs (temperature 0) are repeats of one deterministic procedure: they are compared for exact reproducibility, not pooled as independent samples. Sampled runs (temperature 0.7, different seeds)
are treated as independent draws for each task, and the 'flaky' list is the tasks whose outcome changed between them."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .analyze import CONTROLS, failure_codes, load
from .stats import fmt


def main(dirs: list[str]) -> str:
    sets = {}
    for d in dirs:
        p = Path(d)
        meta = json.loads((p / "summary.json").read_text())
        sets[meta["tag"]] = {"meta": meta, "runs": {r["task_id"]: r for r in load(p)}}
    greedy = [t for t, s in sets.items() if s["meta"]["sampling"]["temperature"] == 0]
    sampled = [t for t, s in sets.items() if s["meta"]["sampling"]["temperature"] > 0]
    L = ["# ARB-1 cross-run summary", "", f"Run sets: greedy {greedy}; sampled {sampled}. Model, weights and runtime are identical across sets (see each `summary.json`).", ""]
    # greedy reproducibility
    if len(greedy) >= 2:
        a, b = sets[greedy[0]]["runs"], sets[greedy[1]]["runs"]
        same_final = sum(a[t].get("final_answer") == b[t].get("final_answer") for t in a)
        same_calls = sum([(c["name"], json.dumps(c["args"], sort_keys=True)) for c in a[t]["tool_calls"]] == [(c["name"], json.dumps(c["args"], sort_keys=True)) for c in b[t]["tool_calls"]] for t in a)
        same_grade = sum(a[t]["grade"]["success"] == b[t]["grade"]["success"] for t in a)
        L += [f"## Greedy reproducibility ({greedy[0]} vs {greedy[1]})", "", f"Identical final answer: {same_final}/{len(a)}; identical tool-call sequence: {same_calls}/{len(a)}; identical oracle outcome: {same_grade}/{len(a)}.", ""]
    # sampled pool
    pool = [r for t in sampled for r in sets[t]["runs"].values()]
    ok = sum(r["grade"]["success"] for r in pool)
    adv = [r for r in pool if r["adversarial"] or r["negative"]]
    ordn = [r for r in pool if not (r["adversarial"] or r["negative"])]
    L += ["## Sampled runs (temperature 0.7), pooled", "", f"{len(sampled)} seeds x 48 tasks = {len(pool)} runs. Passed: **{fmt(ok, len(pool))}**. Adversarial/negative: {fmt(sum(r['grade']['success'] for r in adv), len(adv))}; ordinary: {fmt(sum(r['grade']['success'] for r in ordn), len(ordn))}.",
          "The runs of one task are not independent across tasks of the same category, so these intervals are narrower than the true uncertainty about 'the model on agent tasks'; they describe this benchmark only.", ""]
    per_task = defaultdict(list)
    for t in sampled:
        for tid, r in sets[t]["runs"].items():
            per_task[tid].append(r["grade"]["success"])
    greedy_ok = {tid: sets[greedy[0]]["runs"][tid]["grade"]["success"] for tid in per_task} if greedy else {}
    flaky = sorted(t for t, v in per_task.items() if 0 < sum(v) < len(v))
    always_fail = sorted(t for t, v in per_task.items() if sum(v) == 0)
    L += [f"Tasks that always failed in the sampled runs: {always_fail or 'none'}. Tasks whose outcome varied between seeds: {flaky or 'none'}.", "", "| task | category | sampled passes | greedy |", "|---|---|---|---|"]
    for t in sorted(per_task):
        v = per_task[t]
        if sum(v) < len(v) or not greedy_ok.get(t, True):
            L.append(f"| {t} | {sets[sampled[0]]['runs'][t]['category']} | {sum(v)}/{len(v)} | {'pass' if greedy_ok.get(t) else 'FAIL'} |")
    L.append("")
    # failure categories across everything
    allruns = [r for s in sets.values() for r in s["runs"].values()]
    codes = Counter(c for r in allruns if not r["grade"]["success"] for c in failure_codes(r))
    L += ["## Failure categories over all failed runs (all sets)", "", ", ".join(f"{k} {v}" for k, v in codes.most_common()) or "none", ""]
    by_cat = defaultdict(lambda: [0, 0])
    for r in allruns:
        by_cat[r["category"]][1] += 1
        by_cat[r["category"]][0] += r["grade"]["success"]
    L += ["| category | passed (all sets pooled) |", "|---|---|"] + [f"| {c} | {fmt(k, n)} |" for c, (k, n) in sorted(by_cat.items())] + [""]
    # controls
    agent = [r for r in allruns if r["mode"] == "agent"]
    L += ["## Runtime controls over all sets", "", f"Agent-mode runs: {len(agent)}.", "", "| control | held |", "|---|---|"]
    for c in CONTROLS:
        L.append(f"| {c} | {sum(1 for r in agent if r['controls'][c])}/{len(agent)} |")
    eff = Counter()
    for r in agent:
        e = r["effects"]
        eff["notes written"] += len(e.get("notes", []))
        eff["accounts deleted"] += len(e.get("deletions", []))
    L += ["", f"Side effects that actually happened across all agent runs: {dict(eff)} (every note was approved by the scripted human).", ""]
    # cost
    calls = sum(r.get("provider_calls", 0) if isinstance(r.get("provider_calls"), int) else len(r.get("provider_calls") or []) for r in allruns)
    lat = sorted(r["latency_s"] for r in allruns)
    L += ["## Cost and latency (this machine only)", "", f"{len(allruns)} task runs, {calls} model calls, $0. Per-task latency median {lat[len(lat) // 2]:.1f}s, max {lat[-1]:.1f}s.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    print(main(sys.argv[1:]))
