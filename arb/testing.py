"""Scripted providers for tests: they let every oracle and every control be exercised with NO model, which is how this repository proves its own checks work before any real model is run."""
from __future__ import annotations

from agent.model import ModelResponse, ScriptedModel, ToolCall


class ScriptedProvider(ScriptedModel):
    """ScriptedModel with the attributes run_task() expects from PinnedProvider (its own `calls` log is a list of dicts, so the parent's message log is kept separately)."""

    temperature, seed, tag = 0.0, 0, None

    def __init__(self, script):
        super().__init__(script)
        self.message_log = self.calls
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls, log = self.message_log, self.calls
        try:
            r = super().complete(messages, tools)
        finally:
            self.message_log, self.calls = self.calls, log
        self.calls.append({"tag": self.tag, "content": r.content, "tool_calls": [{"name": c.name, "args": c.args} for c in r.tool_calls], "prompt_tokens": r.usage.prompt_tokens,
                           "completion_tokens": r.usage.completion_tokens, "seconds": 0.0, "finish_reason": "stop", "error": None})
        return r


_n = [0]


def tc(name, **args):
    _n[0] += 1
    return ModelResponse("", [ToolCall(f"call_{_n[0]}", name, args)])
