"""Run Study Copilot for the browser tests (``frontend/e2e``).

Starts one server on ``--port`` with:

* a fresh copy of ``frontend/e2e/fixtures/vault`` and an empty database in a
  temp folder (ingested and embedded with the offline hash embedder),
* a scripted chat model at ``/mock-llm/v1`` (OpenAI-compatible; it streams and
  sends a little reasoning first) so answers are deterministic,
* the built web UI (``frontend/dist-web``, from ``npm run build:web``).

Playwright starts this through ``webServer`` in ``frontend/playwright.config.ts``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_VAULT = ROOT / "frontend" / "e2e" / "fixtures" / "vault"


def _write_config(tmp: Path, port: int) -> Path:
    vault = tmp / "vault"
    shutil.copytree(FIXTURE_VAULT, vault)
    config = tmp / "config.yaml"
    config.write_text(
        "\n".join(
            [
                "vault:",
                f"  root: {json.dumps(vault.as_posix())}",
                "  read_paths: ['**']",
                "  write_paths: ['StudyCopilot/**']",
                "  denied_paths: ['**/.obsidian/**', '**/.git/**', '**/.env', '**/.trash/**']",
                "external_sources: []",
                "models:",
                "  default_provider: lmstudio",
                "  lmstudio:",
                f"    base_url: http://127.0.0.1:{port}/mock-llm/v1",
                "    model: e2e-model",
                "embeddings:",
                "  provider: hash",
                "  model: hash",
                "generation:",
                "  temperature: 0.1",
                "  require_citations: true",
                "sync:",
                "  enabled: false",
                "voice_notes:",
                "  enabled: false",
                f"database_url: sqlite:///{(tmp / 'e2e.db').as_posix()}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config


def _first_source(prompt: str) -> tuple[str, str]:
    """``(marker, first sentence)`` of the first source block in a prompt."""
    match = re.search(r"\[(S\d+)\][^\n]*\n(.+?)(?:\n\n\[S\d+\]|\Z)", prompt, re.S)
    if not match:
        return "S1", "Your notes cover this"
    # The first line that reads like prose (skips headings and front matter).
    for line in match.group(2).splitlines():
        line = line.strip().lstrip("-*> ").strip()
        if len(line.split()) >= 6 and not line.startswith(("#", "---")):
            return match.group(1), re.split(r"(?<=[.!?])\s", line)[0].rstrip(".")
    return match.group(1), "Your notes cover this"


def _answer_for(prompt: str) -> str:
    marker, sentence = _first_source(prompt)
    return (
        f"According to your notes: {sentence} [{marker}].\n\n"
        f"**Key point:** check this against the cited note before the exam [{marker}]."
    )


def _mock_llm():
    """A tiny OpenAI-compatible chat model with predictable answers."""
    # Imported here (not at the top) so ``--help`` works without the backend
    # installed; module-level names so FastAPI can resolve the annotations.
    global FastAPI, Request, StreamingResponse
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse

    mock = FastAPI()

    def completion(content: str) -> dict:
        return {
            "id": "e2e",
            "object": "chat.completion",
            "model": "e2e-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }

    @mock.get("/v1/models")
    def models() -> dict:
        return {"data": [{"id": "e2e-model"}]}

    @mock.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        messages = body.get("messages", [])
        first = messages[0].get("content") if messages else ""
        system = first if isinstance(first, str) else ""
        last = messages[-1].get("content") if messages else ""
        if isinstance(last, list):
            last = " ".join(part.get("text", "") for part in last if isinstance(part, dict))
        if "quiz questions" in system or "exam-style" in system:
            quiz = {
                "questions": [
                    {
                        "type": "mcq",
                        "question": "What does calibrated trust mean?",
                        "options": [
                            "Reliance matches what the system can do",
                            "Always trusting the AI",
                            "Never trusting the AI",
                            "Trusting explanations only",
                        ],
                        "answer": "Reliance matches what the system can do",
                        "concept": "Trust calibration",
                        "difficulty": "easy",
                        "explanation": "Reliance should match capability.",
                        "sources": ["S1"],
                    },
                    {
                        "type": "short",
                        "question": "Name one way an interface can support calibrated trust.",
                        "answer": "Communicate confidence and limitations.",
                        "concept": "Trust calibration",
                        "difficulty": "medium",
                        "explanation": "Showing limits helps people calibrate.",
                        "sources": ["S1"],
                    },
                ]
            }
            return completion(json.dumps(quiz))
        if "grade a student" in system:
            return completion(json.dumps({"verdict": "partial", "feedback": "Good start."}))
        text = _answer_for(last)
        if not body.get("stream"):
            return completion(text)

        # A model whose chat template opens <think> in the prompt: its
        # reasoning arrives as plain text ending in </think>.
        think_in_prompt = "(think in the prompt)" in last

        async def events():
            if think_in_prompt:
                for piece in ["Working it ", "out.</th", "ink>\n\n"]:
                    await asyncio.sleep(0.15)
                    yield "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}) + "\n\n"
            else:
                for piece in ["Checking ", "the sources."]:
                    await asyncio.sleep(0.15)
                    delta = {"choices": [{"delta": {"reasoning_content": piece}}]}
                    yield "data: " + json.dumps(delta) + "\n\n"
            for token in re.findall(r"\S+\s*", text):
                await asyncio.sleep(0.12)
                yield "data: " + json.dumps({"choices": [{"delta": {"content": token}}]}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return mock


# Stand-ins for the Claude Code and Codex CLIs (a Claude / ChatGPT
# subscription), signed in, answering like the scripted model does.
_FAKE_CLI = r"""
import json, os, re, sys
TOOL = %(tool)r
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("9.9.9 (e2e " + TOOL + ")"); sys.exit(0)
if args[:2] in (["auth", "status"], ["login", "status"]):
    print(json.dumps({"loggedIn": True, "subscriptionType": "max"}) if TOOL == "claude" else "Logged in using ChatGPT")
    sys.exit(0)
if args[:2] == ["exec", "--help"]:
    print("--json --ephemeral --color"); sys.exit(0)
prompt = sys.stdin.read()
match = re.search(r"\[(S\d+)\][^\n]*\n(.+?)(?:\n\n\[S\d+\]|\Z)", prompt, re.S)
marker, sentence = "S1", "Your notes cover this"
if match:
    for line in match.group(2).splitlines():
        line = line.strip().lstrip("-*> ").strip()
        if len(line.split()) >= 6 and not line.startswith(("#", "---")):
            marker, sentence = match.group(1), re.split(r"(?<=[.!?])\s", line)[0].rstrip(".")
            break
if TOOL == "claude":
    model = args[args.index("--model") + 1]
    answer = f"Claude {model} says: {sentence} [{marker}]."
    def out(obj): print(json.dumps(obj), flush=True)
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "Reading the sources."}}})
    for word in re.findall(r"\S+\s*", answer):
        out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": word}}})
    out({"type": "result", "subtype": "success", "is_error": False, "result": answer})
else:
    answer = f"ChatGPT says: {sentence} [{marker}]."
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}), flush=True)
    print(json.dumps({"type": "turn.completed", "usage": {}}), flush=True)
"""


def _install_fake_clis(tmp: Path) -> None:
    """Put fake ``claude`` / ``codex`` first on PATH for this server."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    for tool in ("claude", "codex"):
        script = bin_dir / f"{tool}.py"
        script.write_text(_FAKE_CLI % {"tool": tool}, encoding="utf-8")
        if sys.platform == "win32":
            (bin_dir / f"{tool}.cmd").write_text(
                f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
            )
        else:
            launcher = bin_dir / tool
            launcher.write_text(f"#!{sys.executable}\n" + script.read_text(encoding="utf-8"), encoding="utf-8")
            launcher.chmod(0o755)
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Study Copilot for the browser tests.")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--web-dir", default=str(ROOT / "frontend" / "dist-web"))
    parser.add_argument(
        "--no-fake-clis", action="store_true", help="don't add the stand-in claude / codex CLIs"
    )
    args = parser.parse_args()

    if not (Path(args.web_dir) / "index.html").is_file():
        sys.exit(f"No built UI in {args.web_dir}. Run `npm run build:web` in frontend/ first.")

    tmp = Path(tempfile.mkdtemp(prefix="study-copilot-e2e-"))
    os.environ["STUDY_COPILOT_CONFIG"] = str(_write_config(tmp, args.port))
    os.environ["STUDY_COPILOT_WEB_DIR"] = args.web_dir
    sys.path.insert(0, str(ROOT))
    if not args.no_fake_clis:
        _install_fake_clis(tmp)

    import uvicorn
    from starlette.routing import Mount

    from app.config.settings import get_settings
    from app.database.db import init_db
    from app.ingestion.service import ingest
    from app.retrieval.indexing import index_embeddings
    from app.vault import service as vault_service

    # Keep the note-link cache in the temp folder, not the repo's data/.
    vault_service._link_cache_path = lambda root: tmp / "note_links.json"

    # "(slow search)" in a question makes retrieval take a moment, so a test
    # can press Stop before the answer starts.
    from app.agent import study_agent

    real_search = study_agent.search

    def search(question, *args, **kwargs):
        if "(slow search)" in question:
            time.sleep(1.5)
        return real_search(question, *args, **kwargs)

    study_agent.search = search
    settings = get_settings()
    init_db(settings)
    ingest(settings)
    index_embeddings(settings)

    from app.main import app

    # Ahead of the web UI's catch-all mount, so the scripted model is reachable.
    app.router.routes.insert(0, Mount("/mock-llm", app=_mock_llm()))
    print(f"Study Copilot e2e server on http://127.0.0.1:{args.port} (data in {tmp})", flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
