"""PinnedProvider and the CLI, against a local stub that speaks the OpenAI chat-completions shape (no model involved)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from arb import cli
from arb.provider import PinnedProvider, strip_reasoning

ROOT = Path(__file__).resolve().parent.parent


class Stub(BaseHTTPRequestHandler):
    bodies: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(n))
        Stub.bodies.append(body)
        tools_available = body.get("tools")
        has_tool_result = any(m["role"] == "tool" for m in body["messages"])
        if tools_available and not has_tool_result and "kilometres" in body["messages"][-1]["content"]:
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "convert_units", "arguments": json.dumps({"value": 42, "from": "km", "to": "mi"})}}]}
        else:
            msg = {"role": "assistant", "content": "<think>hidden</think>42 km is about 26.1 miles." if has_tool_result else "Paris."}
        out = json.dumps({"choices": [{"message": msg, "finish_reason": "stop"}], "usage": {"prompt_tokens": 11, "completion_tokens": 5}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def _server():
    s = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_parameters_are_pinned_on_every_request_and_every_call_is_recorded():
    s = _server()
    Stub.bodies.clear()
    p = PinnedProvider(f"http://127.0.0.1:{s.server_port}/v1", "m", temperature=0.0, seed=20260101, max_tokens=123)
    from agent.model import Message
    r = p.complete([Message("user", "hi")])
    s.shutdown()
    b = Stub.bodies[0]
    assert (b["temperature"], b["seed"], b["max_tokens"]) == (0.0, 20260101, 123) and "response_format" not in b
    assert r.content == "Paris." and p.calls[0]["prompt_tokens"] == 11 and p.calls[0]["finish_reason"] == "stop"


def test_reasoning_blocks_are_stripped():
    assert strip_reasoning("<think>x</think>answer") == "answer" and strip_reasoning("a<think>never closed") == "a"


def test_cli_refuses_when_the_benchmark_changed(tmp_path, monkeypatch):
    import shutil
    shutil.copytree(ROOT / "benchmark", tmp_path / "benchmark")
    shutil.copytree(ROOT / "arb", tmp_path / "arb", ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    cli.load_benchmark()                                              # untouched copy passes
    (tmp_path / "benchmark" / "tasks.json").write_text((tmp_path / "benchmark" / "tasks.json").read_text() + " ")
    try:
        cli.load_benchmark()
        raise AssertionError("should refuse")
    except SystemExit as e:
        assert "REFUSED" in str(e)


def test_cli_end_to_end_against_a_stub(tmp_path):
    s = _server()
    rc = cli.main(["--base-url", f"http://127.0.0.1:{s.server_port}", "--model", "m", "--digest", "0" * 64, "--runtime", "stub", "--tag", "t", "--only", "ARB-SA-01", "ARB-TS-01", "--out", str(tmp_path)])
    s.shutdown()
    assert rc == 0
    r = json.loads((tmp_path / "t" / "runs" / "ARB-TS-01.json").read_text())
    assert r["grade"]["success"] and r["tool_calls"][0]["name"] == "convert_units" and all(r["controls"].values()) and r["final_answer"] == "42 km is about 26.1 miles."
    assert json.loads((tmp_path / "t" / "runs" / "ARB-SA-01.json").read_text())["grade"]["success"]
    assert (tmp_path / "t" / "summary.json").exists()
