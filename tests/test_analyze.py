import json
from pathlib import Path

from arb import analyze
from arb.runner import run_task
from arb.stats import bootstrap_diff, fmt, quantile, wilson
from arb.testing import ScriptedProvider
from tests.gold import BAD, GOLD

ROOT = Path(__file__).resolve().parent.parent
BENCH = json.loads((ROOT / "benchmark" / "tasks.json").read_text())
TASKS = {t["id"]: t for t in BENCH["tasks"]}
LEX = {"decline": BENCH["decline_lexicon"], "refusal": BENCH["refusal_lexicon"]}


def _runs(scripts):
    return [run_task(TASKS[tid], ScriptedProvider(s), LEX) for tid, s in scripts.items()]


def test_summary_of_gold_runs_is_all_success_and_all_controls_held():
    runs = _runs(GOLD)
    s = analyze.summarize(runs)
    assert s["n"] == 48 and s["success"] == 48 and s["failure_codes"] == {}
    assert all(v == 0 for v in s["controls"]["violations"].values()) and s["controls"]["runs"] == 40
    assert s["effects"]["accounts_deleted"] == 0 and s["model_obedience"]["requested_forbidden_tool"] == 0


def test_bad_runs_are_attributed_to_failure_categories_and_obedience_is_counted_but_controls_hold():
    runs = _runs(BAD)
    s = analyze.summarize(runs)
    assert s["success"] == 0
    assert s["model_obedience"]["requested_forbidden_tool"] >= 4
    assert set(s["failure_codes"]) >= {"OBEYED_INJECTION", "FABRICATION_OR_LEAK", "FALSE_SUCCESS_CLAIM"}
    assert all(v == 0 for v in s["controls"]["violations"].values()), "model misbehaviour must not break a control"
    assert s["effects"]["accounts_deleted"] == 0 and s["effects"]["notes_written"] == 0


def test_render_names_both_sections_and_keeps_them_apart():
    runs = _runs(GOLD)
    meta = {"model": {"name": "scripted", "weights_sha256": "0" * 64, "runtime": "none", "quantisation": ""}, "tag": "t", "sampling": {}, "runtime_commit": "x" * 40, "n_tasks": 48, "wall_seconds": 1}
    md = analyze.render(analyze.summarize(runs), runs, meta)
    assert "## Model behaviour" in md and "## Runtime controls" in md and "reported separately" in md


def test_stats():
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0.25 < hi < 0.35
    assert fmt(5, 10).startswith("5/10 (50%")
    d, lo, hi = bootstrap_diff([1] * 10, [0] * 10)
    assert d == 1.0 and lo == 1.0 and hi == 1.0
    assert quantile([1, 2, 3, 4], 0.5) == 2
