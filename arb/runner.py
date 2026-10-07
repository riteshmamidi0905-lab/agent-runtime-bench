"""Run one ARB-1 task against the frozen runtime with a given provider and return a self-contained run artifact (everything MAREF or any other evaluator needs: the objective, the trajectory,
every tool call with arguments and results, the runtime's trace events, recorded side effects, usage, latency, and the runtime-control checks)."""
from __future__ import annotations

import json
import time

from agent.loop import SYSTEM_PROMPT, Agent
from agent.memory import ConversationMemory
from agent.model import Message
from agent.reliability import Budget
from agent.security import Policy
from agent.structured import extract_json, generate_structured, validate
from agent.trace import Tracer

from . import controls, oracles
from .world import World, approver

SCHEMA_VERSION = "arb-run/1"


def run_task(task: dict, provider, lexicon, *, run_tag: str = "", sample: dict | None = None) -> dict:
    """`lexicon` is a dict {"decline": regex, "refusal": regex} (or just the decline regex)."""
    lex = lexicon if isinstance(lexicon, dict) else {"decline": lexicon, "refusal": r"(?i)\bi (?:can(?:no|')t|won't)\b"}
    n0 = len(provider.calls)
    provider.tag = task["id"]
    t0 = time.time()
    world = World(task.get("world"))
    run: dict = {"schema": SCHEMA_VERSION, "task_id": task["id"], "category": task["category"], "mode": task["mode"], "tag": run_tag, "sampling": sample or {"temperature": provider.temperature, "seed": provider.seed},
                 "adversarial": task["adversarial"], "negative": task["negative"]}
    if task["mode"] == "structured":
        schema = task["schema"]
        messages = [Message("user", task["user"])]
        err = None
        data, repairs, usage = None, 0, None
        try:
            data, usage, repairs = generate_structured(provider, messages, schema, max_repairs=2)
        except Exception as e:  # noqa: BLE001 - the runtime raises ProviderError(kind='structured') when it never validates
            err = f"{type(e).__name__}: {e}"[:300]
        calls = provider.calls[n0:]
        first_valid = False
        if calls:
            try:
                first_valid = not validate(extract_json(calls[0].get("content") or ""), schema)
            except (ValueError, json.JSONDecodeError):
                first_valid = False
        run.update(structured={"data": data, "valid": err is None and data is not None, "repairs": repairs, "first_try_valid": first_valid, "error": err}, final_answer=json.dumps(data) if data is not None else None,
                   status="completed" if err is None else "failed", stop_reason="structured_ok" if err is None else "structured_invalid", tool_calls=[], effects=world.effects, model_calls=len(calls), trace=[],
                   tool_messages=[], policy={"max_level": "write"}, budget={"max_steps": 3, "max_tokens": 20000}, steps=[], usage={"prompt": sum(c.get("prompt_tokens", 0) for c in calls), "completion": sum(c.get("completion_tokens", 0) for c in calls)})
    else:
        pol = task["policy"]
        tracer = Tracer(run_id=task["id"])
        memory = ConversationMemory()
        agent = Agent(provider, world.registry(task["tools"]), Policy(max_level=pol["max_level"], approver=approver(pol["approver"]), block_injection=pol["block_injection"]),
                      Budget(**task["budget"]), tracer, memory, system_prompt=SYSTEM_PROMPT + task.get("system_extra", ""), sleep=lambda s: None)
        state = agent.run(task["objective"])
        calls = provider.calls[n0:]
        tool_steps = [s for s in state.steps if s.kind == "tool"]
        run.update(final_answer=state.final_answer, status=state.status, stop_reason=state.stop_reason,
                   tool_calls=[{"name": s.detail["tool"], "args": s.detail.get("args", {}), "ok": s.detail.get("ok"), "output": s.detail.get("output", ""), "error": s.detail.get("error", ""), "failure": s.detail.get("failure")} for s in tool_steps],
                   effects=world.effects, model_calls=sum(1 for s in state.steps if s.kind == "model"), trace=tracer.events, tool_messages=[{"name": m.name, "content": m.content} for m in memory.messages if m.role == "tool"],
                   policy=pol, budget=task["budget"], steps=[{"kind": s.kind, **{k: v for k, v in s.detail.items() if k in ("content", "tool_calls", "tool", "args", "ok", "output", "error")}} for s in state.steps],
                   usage={"prompt": state.usage.prompt_tokens, "completion": state.usage.completion_tokens}, errors=[e["kind"] for e in state.errors])
    run["latency_s"] = round(time.time() - t0, 2)
    run["provider_calls"] = [{k: c.get(k) for k in ("seconds", "prompt_tokens", "completion_tokens", "finish_reason", "error")} for c in provider.calls[n0:]]
    run["raw_replies"] = [{"content": c.get("content"), "tool_calls": c.get("tool_calls")} for c in provider.calls[n0:]]
    run["grade"] = oracles.grade(task, run, lex["decline"], lex["refusal"])
    run["controls"] = controls.evaluate(run) if task["mode"] == "agent" else {}
    return run
