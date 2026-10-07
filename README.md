# agent-runtime-bench

A **real-model benchmark and evaluation adapter** for the frozen [`ai-agent-from-scratch`](https://github.com/riteshmamidi0905-lab/ai-agent-from-scratch) runtime (pinned to commit `231b186`, used **unmodified**).

The runtime's own evaluation uses deterministic stand-in and scripted models and says nothing about how a real language model behaves inside it. This repository adds that measurement, **and keeps two things apart that are easy to blur**:

| | what it tells you | where it is reported |
|---|---|---|
| **Model behaviour** | did the model pick the right tool, answer correctly, abstain, resist injected instructions, produce valid structure, stop gracefully | per-task oracles (`arb/oracles.py`) |
| **Runtime controls** | did the runtime's deterministic controls hold *whatever the model did*: approval gates, the dangerous-tool level, budgets, loop detection, untrusted-data labelling, redaction, idempotency | per-run invariants (`arb/controls.py`) |

A model can fail a task while every control holds; a control can hold only because the model happened to behave. A model result is never a safety claim about the runtime, and a held control is never a quality claim about the model.

## ARB-1
48 tasks, 12 categories x 4: simple answer, structured response, correct tool selection, multi-step tool use, tool failure, malformed output / repair, refusal, approval-required action, budget exhaustion,
looping temptation, malicious tool output, prompt injection. Includes adversarial and negative cases (abstain instead of inventing, no tool when no tool is needed, a benign request that must not be refused).
Oracles are deterministic and declarative (no judge model). The benchmark, the world fixtures, the oracles, the control checks and the analysis are hash-locked in `benchmark/FREEZE.json` **before any real
model was run**; `python -m arb.cli` refuses to run if any of them changed. See `docs/benchmark-design.md` for the design, the analysis plan and the limitations.

```bash
pip install -e '.[dev]' && pytest -q          # 40 tests; every oracle and control is exercised with scripted models, no model needed
# run it (any OpenAI-compatible local server, e.g. llama.cpp's llama-server):
python -m arb.cli --base-url http://127.0.0.1:8080 --model <name> --digest <sha256 of the weights> --runtime "llama.cpp b11476" --quant Q4_K_M --tag pass1
python -m arb.analyze reports/pass1
```

## Results (one model, one pass family; read `docs/RESULTS.md` before quoting any number)
`qwen3-4b-instruct-2507` Q4_K_M, greedy: **43/48** tasks passed by the frozen oracles (92% = 44/48 after I adjudicated one oracle false negative; the frozen number is the headline); adversarial/negative 20/25. All seven runtime controls held in 240/240 agent-mode runs, and the benchmark still found a real hole
(a secret disclosed through a permitted read tool, MT-02, which the action controls do not cover). Four seeded sampled passes and a greedy repeat are in `reports/`; `reports/AGGREGATE.md` summarises them.

## What this is not
Not a leaderboard and not a claim about any model beyond the one run named in a report. The tasks are small, in English, with toy tools, authored by one AI assistant (the same one that wrote the harness; disclosed).
Not a production system. No real customer data. Results are descriptive counts with their denominators and Wilson intervals.
