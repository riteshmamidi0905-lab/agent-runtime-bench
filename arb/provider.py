"""PinnedProvider: the frozen runtime's OpenAI-compatible provider sends NO inference parameters, so this adapter (a subclass, in THIS repository; the runtime is unmodified) sends the pinned ones
(temperature, seed, max_tokens) and records every call: raw reply, finish reason, server-reported usage, wall-clock seconds, errors."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from agent.model import Message, ModelResponse, OpenAICompatProvider, ProviderError, ToolCall, Usage, estimate_tokens, messages_tokens

_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.S)


def strip_reasoning(text: str) -> str:
    """Remove <think> blocks (an unterminated one swallows the rest). The model used here does not emit them; defensive for other models."""
    return _THINK.sub("", text).strip()


def _loads(s):
    if isinstance(s, dict):
        return s
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {"_raw": s}
    except (json.JSONDecodeError, TypeError):
        return {"_raw": s}


class PinnedProvider(OpenAICompatProvider):
    def __init__(self, base_url: str, model: str, *, temperature: float = 0.0, seed: int = 20260101, max_tokens: int = 700, timeout: float = 600.0, json_mode: bool = False):
        super().__init__(base_url, model, "", timeout)
        self.temperature, self.seed, self.max_tokens, self.json_mode = temperature, seed, max_tokens, json_mode
        self.calls: list[dict] = []
        self.tag: str | None = None

    def complete(self, messages: list[Message], tools=None) -> ModelResponse:
        body = {"model": self.model, "messages": [self._wire(m) for m in messages], "temperature": self.temperature, "seed": self.seed, "max_tokens": self.max_tokens}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        rec = {"tag": self.tag, "n_messages": len(messages), "n_tools": len(tools or [])}
        t0 = time.time()
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - local URL chosen by the operator
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            e.close()
            rec.update(seconds=round(time.time() - t0, 2), error=f"HTTP {e.code}")
            self.calls.append(rec)
            raise ProviderError(f"HTTP {e.code}", retryable=e.code in (408, 429, 500, 502, 503, 504), kind="http") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            rec.update(seconds=round(time.time() - t0, 2), error=f"network: {e}")
            self.calls.append(rec)
            raise ProviderError(f"network: {e}", retryable=True, kind="network") from None
        try:
            choice = data["choices"][0]
            msg = choice["message"]
            content = strip_reasoning(msg.get("content") or "")
            calls = [ToolCall(c["id"], c["function"]["name"], _loads(c["function"]["arguments"])) for c in (msg.get("tool_calls") or [])]
            u = data.get("usage") or {}
        except (KeyError, IndexError, TypeError):
            rec.update(seconds=round(time.time() - t0, 2), error="unexpected response shape")
            self.calls.append(rec)
            raise ProviderError("unexpected response shape", retryable=False, kind="malformed") from None
        usage = Usage(u.get("prompt_tokens", messages_tokens(messages)), u.get("completion_tokens", estimate_tokens(content)))
        rec.update(seconds=round(time.time() - t0, 2), finish_reason=choice.get("finish_reason"), prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens, content=content,
                   tool_calls=[{"name": c.name, "args": c.args} for c in calls], error=None)
        self.calls.append(rec)
        return ModelResponse(content, calls, usage)
