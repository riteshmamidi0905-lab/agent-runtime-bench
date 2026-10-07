"""python -m arb.cli --base-url http://127.0.0.1:8080 --model <name> --digest <sha256> --runtime "llama.cpp b11476" --quant Q4_K_M --tag pass1 [--temperature 0 --seed 20260101] [--only ARB-SA-01 ...]

Verifies the benchmark freeze, runs every task once, writes one JSON per run plus a summary under reports/<tag>/, and a raw call log. It refuses to run if benchmark/tasks.json differs from benchmark/FREEZE.json."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

from .provider import PinnedProvider
from .runner import run_task

ROOT = Path(__file__).resolve().parent.parent


def load_benchmark():
    freeze = json.loads((ROOT / "benchmark" / "FREEZE.json").read_text())
    for rel, digest in freeze["files"].items():
        if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"REFUSED: {rel} changed after the freeze; a benchmark change needs ARB-2 and a new freeze")
    return json.loads((ROOT / "benchmark" / "tasks.json").read_text()), freeze


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--model", required=True)
    ap.add_argument("--digest", required=True, help="sha256 of the weights file")
    ap.add_argument("--runtime", required=True)
    ap.add_argument("--quant", default="")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--out", default=str(ROOT / "reports"))
    a = ap.parse_args(argv)
    bench, freeze = load_benchmark()
    provider = PinnedProvider(a.base_url.rstrip("/") + "/v1", a.model, temperature=a.temperature, seed=a.seed, max_tokens=bench["inference"]["max_tokens_per_call"])
    tasks = [t for t in bench["tasks"] if not a.only or t["id"] in a.only]
    dest = Path(a.out) / a.tag
    (dest / "runs").mkdir(parents=True, exist_ok=True)
    runs, t_start = [], time.time()
    for t in tasks:
        r = run_task(t, provider, {"decline": bench["decline_lexicon"], "refusal": bench["refusal_lexicon"]}, run_tag=a.tag, sample={"temperature": a.temperature, "seed": a.seed})
        (dest / "runs" / f"{t['id']}.json").write_text(json.dumps(r, indent=1, default=str) + "\n")
        runs.append(r)
        bad = [k for k, v in r["controls"].items() if not v]
        print(f"{t['id']:<11} {t['category']:<24} status={r['status']}/{r.get('stop_reason')} success={r['grade']['success']} controls={'ok' if not bad else 'VIOLATED ' + ','.join(bad)} {r['latency_s']}s", flush=True)
    summary = {"benchmark": bench["benchmark"], "tag": a.tag, "model": {"name": a.model, "weights_sha256": a.digest, "quantisation": a.quant, "runtime": a.runtime},
               "freeze": freeze["files"], "machine": {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version()}, "sampling": {"temperature": a.temperature, "seed": a.seed},
               "runtime_commit": "231b1866f88ac31339fbb2b87ffee88d75d5a573", "wall_seconds": round(time.time() - t_start), "n_tasks": len(runs)}
    (dest / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({"tasks": len(runs), "success": sum(r["grade"]["success"] for r in runs), "control_violations": sum(1 for r in runs for v in r["controls"].values() if not v)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
