"""Claude / ChatGPT subscriptions through the Claude Code and Codex CLIs.

The real CLIs are replaced by small fake scripts on PATH that print the same
kind of JSON lines, so these tests run anywhere and need no account.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import textwrap
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.agent.study_agent import stream_answer
from app.config.settings import get_settings
from app.ingestion.service import ingest
from app.main import app
from app.models import cli_models
from app.models.chat import ChatError, ChatMessage, StreamCancel, get_chat_adapter
from app.models.cli_models import ClaudeCodeAdapter, CodexAdapter, cli_status, split_messages
from app.retrieval.indexing import index_embeddings

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="fake CLIs are POSIX scripts")

FAKE_CLAUDE = r'''
import json, os, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
if args[:1] == ["--version"]:
    print("2.1.300 (Claude Code)"); sys.exit(0)
if args[:2] == ["auth", "status"]:
    if os.environ.get("ANTHROPIC_API_KEY"):  # what the real tool says with a key set
        print(json.dumps({"loggedIn": True, "authMethod": "api_key"})); sys.exit(0)
    if mode == "signed_out":
        print(json.dumps({"loggedIn": False})); sys.exit(1)
    if mode == "weird":
        print("boom", file=sys.stderr); sys.exit(1)
    print(json.dumps({"loggedIn": True, "subscriptionType": "max"})); sys.exit(0)
prompt = sys.stdin.read()
system = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read()
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"args": args, "prompt": prompt, "system": system,
                          "api_key": os.environ.get("ANTHROPIC_API_KEY"), "cwd": os.getcwd(),
                          "no_mds": os.environ.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS")}) + "\n")
def out(obj):
    print(json.dumps(obj), flush=True)
out({"type": "system", "subtype": "init", "model": "claude-sonnet"})
if mode == "signed_out":
    out({"type": "result", "subtype": "success", "is_error": True,
         "result": "Invalid API key · Please run /login"})
    sys.exit(1)
if mode == "slow":
    time.sleep(30)
if mode == "stubborn":  # ignores the polite stop
    import signal
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
if mode == "limit":  # the tool's own notice, dressed up as a reply, then a failed result
    out({"type": "assistant", "error": "rate_limit", "is_api_error_message": True,
         "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "You've hit your limit · resets 3pm"}]}})
    out({"type": "result", "subtype": "success", "is_error": True, "result": "You've hit your limit · resets 3pm"})
    sys.exit(1)
if mode == "old":
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Whole answer [S1]."}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "result": "Whole answer [S1]."})
    sys.exit(0)
def delta(kind, key, text):
    out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
         "delta": {"type": kind, key: text}}})
delta("thinking_delta", "thinking", "Looking at the sources.")
for piece in ["Reliability ", "is consistency ", "[S1]."]:
    delta("text_delta", "text", piece)
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Reliability is consistency [S1]."}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": "Reliability is consistency [S1]."})
if mode == "lingers":  # done, but the process takes its time to exit
    time.sleep(30)
'''

FAKE_CODEX = r'''
import json, os, sys
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
if args[:1] == ["--version"]:
    print("codex-cli 0.200.0"); sys.exit(0)
if args[:2] == ["login", "status"]:
    if mode == "signed_out":
        print("Not logged in", file=sys.stderr); sys.exit(1)
    print("Logged in using ChatGPT"); sys.exit(0)
if args[:2] == ["exec", "--help"]:
    if mode == "helpfail":
        sys.exit(2)
    print("Usage: codex exec [OPTIONS] [PROMPT]\n  --json\n  --ephemeral\n  --color <COLOR>"); sys.exit(0)
prompt = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"args": args, "prompt": prompt, "api_key": os.environ.get("OPENAI_API_KEY")}) + "\n")
def out(obj):
    print(json.dumps(obj), flush=True)
out({"type": "thread.started", "thread_id": "t1"})
out({"type": "turn.started"})
if mode == "signed_out":
    out({"type": "error", "message": "401 Unauthorized: please run codex login"})
    sys.exit(1)
out({"type": "item.completed", "item": {"id": "item_0", "type": "reasoning", "text": "Checking the notes."}})
if mode == "two":
    out({"type": "item.completed", "item": {"id": "item_a", "type": "agent_message", "text": "Let me check the sources."}})
out({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": "Validity is accuracy [S1]."}})
out({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
'''


def _script(path, body):
    path.write_text("#!" + sys.executable + "\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def fake_clis(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(bin_dir / "claude", FAKE_CLAUDE)
    _script(bin_dir / "codex", FAKE_CODEX)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_MODE", "ok")
    monkeypatch.setattr(cli_models, "_status_cache", {})
    monkeypatch.setattr(cli_models, "_codex_flags", {})

    def calls():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    return calls


MESSAGES = [
    ChatMessage("system", "Answer only from the sources. Cite [S1]."),
    ChatMessage("user", "What is reliability?"),
    ChatMessage("assistant", "Consistency of a measure [S1]."),
    ChatMessage("user", "[S1] Reliability is consistency.\n\nQuestion: and validity?"),
]


def test_split_messages_puts_earlier_turns_before_the_last():
    system, prompt = split_messages(MESSAGES)
    assert system == "Answer only from the sources. Cite [S1]."
    assert prompt.startswith("Earlier in this conversation:")
    assert "<user>\nWhat is reliability?\n</user>" in prompt
    assert "<assistant>\nConsistency of a measure [S1].\n</assistant>" in prompt
    assert prompt.endswith("Question: and validity?")
    assert split_messages([ChatMessage("user", "hi")]) == ("", "hi")


def test_claude_code_streams_thinking_and_text(fake_clis, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-used")
    chunks = list(ClaudeCodeAdapter(model="opus").stream(MESSAGES))
    assert [(c.kind, c.text) for c in chunks] == [
        ("thinking", "Looking at the sources."),
        ("text", "Reliability "),
        ("text", "is consistency "),
        ("text", "[S1]."),
    ]
    call = fake_clis()[-1]
    args = call["args"]
    assert args[args.index("--model") + 1] == "opus"
    assert args[args.index("--tools") + 1] == ""  # no tools: text only
    assert "--output-format" in args and "stream-json" in args
    assert call["system"] == "Answer only from the sources. Cite [S1]."
    assert call["prompt"].endswith("Question: and validity?")
    # The subscription is used, not an API key from the environment.
    assert call["api_key"] is None
    # It ran in a scratch folder that is gone afterwards.
    assert not os.path.exists(call["cwd"])


def test_claude_code_generate_and_older_versions(fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "old")
    response = ClaudeCodeAdapter().generate(MESSAGES)
    assert response.content == "Whole answer [S1]."
    assert response.model == "claude-code:sonnet"


def test_claude_code_signed_out(fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "signed_out")
    with pytest.raises(ChatError, match="isn't signed in"):
        list(ClaudeCodeAdapter().stream(MESSAGES))


def test_missing_cli_says_how_to_install(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(cli_models.Path, "home", lambda: tmp_path)
    with pytest.raises(ChatError, match="isn't installed"):
        list(ClaudeCodeAdapter().stream(MESSAGES))
    with pytest.raises(ChatError, match="isn't installed"):
        list(CodexAdapter().stream(MESSAGES))


def test_page_images_are_refused_so_the_answer_falls_back_to_text(fake_clis):
    visual = [ChatMessage("user", [{"type": "text", "text": "q"}, {"type": "image_url", "image_url": {"url": "data:"}}])]
    with pytest.raises(ChatError, match="page images"):
        list(ClaudeCodeAdapter().stream(visual))


def test_stop_ends_the_cli_at_once(fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "slow")
    cancel = StreamCancel()
    box: dict = {}

    def run():
        try:
            list(ClaudeCodeAdapter().stream(MESSAGES, cancel=cancel))
        except ChatError as exc:
            box["error"] = str(exc)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(1.0)  # the CLI is up and "thinking"
    began = time.monotonic()
    cancel.cancel()
    thread.join(timeout=10)
    assert not thread.is_alive() and time.monotonic() - began < 5
    assert box["error"] == "Stopped."


def test_codex_streams_reasoning_and_answer(fake_clis, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-used")
    chunks = list(CodexAdapter(model="gpt-test").stream(MESSAGES))
    assert [(c.kind, c.text) for c in chunks] == [
        ("thinking", "Checking the notes."),
        ("text", "Validity is accuracy [S1]."),
    ]
    call = fake_clis()[-1]
    args = call["args"]
    assert args[:2] == ["exec", "--json"]
    assert "--ephemeral" in args and args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("-m") + 1] == "gpt-test" and args[-1] == "-"
    assert "Answer only from the sources" in call["prompt"]
    assert call["prompt"].rstrip().endswith("Question: and validity?")
    assert call["api_key"] is None


def test_codex_signed_out(fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "signed_out")
    with pytest.raises(ChatError, match="codex login"):
        list(CodexAdapter().stream(MESSAGES))


def test_status_reports_install_version_and_sign_in(fake_clis, monkeypatch):
    claude = cli_status("claude_code")
    assert claude["installed"] and claude["signed_in"] is True
    assert claude["version"].startswith("2.1.300") and claude["account"] == "max"
    codex = cli_status("codex")
    assert codex["installed"] and codex["signed_in"] is True
    assert codex["account"] == "Logged in using ChatGPT"
    monkeypatch.setenv("FAKE_MODE", "signed_out")
    assert cli_status("claude_code")["signed_in"] is True  # cached for a minute
    assert cli_status("claude_code", refresh=True)["signed_in"] is False
    assert cli_status("codex", refresh=True)["signed_in"] is False


def test_the_tools_own_error_notice_is_not_saved_as_the_answer(fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "limit")
    got: list[str] = []
    with pytest.raises(ChatError, match="hit your limit"):
        for chunk in ClaudeCodeAdapter().stream(MESSAGES):
            got.append(chunk.text)
    assert got == []  # nothing was passed on as if the model had said it


def test_claude_code_runs_without_the_users_own_claude_setup(fake_clis):
    list(ClaudeCodeAdapter().stream(MESSAGES))
    call = fake_clis()[-1]
    args = call["args"]
    assert args[args.index("--setting-sources") + 1] == "local"  # not ~/.claude or a parent's CLAUDE.md
    assert call["no_mds"] == "1"
    # The system prompt is named relative to the working folder: no path to quote.
    assert args[args.index("--system-prompt-file") + 1] == "system.md"


@pytest.mark.parametrize(
    "name",
    ["haiku&calc.exe", 'x" & calc & "', "%PATH%", "--dangerously-skip-permissions", "a b", "m;rm", "m\nx", "x" * 200],
)
def test_model_names_that_could_be_read_as_a_command_are_refused(name, settings):
    with pytest.raises(ValueError):
        ClaudeCodeAdapter(model=name)
    with pytest.raises(ValueError):
        CodexAdapter(model=name)
    with pytest.raises(ValueError):
        get_chat_adapter(settings, "chat", provider="codex", model=name)


def test_real_model_names_are_accepted():
    for name in ["sonnet", "opus", "claude-opus-4-5[1m]", "gpt-5.5", "gpt-5-codex", "o3", "vendor/model:tag@v1"]:
        assert CodexAdapter(model=name).model == name
    assert CodexAdapter(model="").model == "" and ClaudeCodeAdapter(model="").model == "sonnet"


def test_a_finished_answer_survives_a_scratch_folder_that_will_not_delete(fake_clis, monkeypatch):
    real = cli_models.tempfile.TemporaryDirectory.cleanup
    failures = {"left": 2}

    def locked(self, *a, **kw):  # Windows: still the cwd of a dying process, or being scanned
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError("in use")
        return real(self, *a, **kw)

    monkeypatch.setattr(cli_models.tempfile.TemporaryDirectory, "cleanup", locked)
    chunks = list(ClaudeCodeAdapter().stream(MESSAGES))
    assert "".join(c.text for c in chunks if c.kind == "text") == "Reliability is consistency [S1]."
    assert failures["left"] == 0 and not os.path.exists(fake_clis()[-1]["cwd"])


def test_the_answer_is_done_at_the_result_event_not_when_the_tool_exits(fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "lingers")
    began = time.monotonic()
    text = "".join(c.text for c in ClaudeCodeAdapter().stream(MESSAGES) if c.kind == "text")
    assert text == "Reliability is consistency [S1]." and time.monotonic() - began < 8


def test_stop_still_works_when_the_tool_ignores_the_polite_stop(fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "stubborn")
    cancel = StreamCancel()
    box: dict = {}

    def run():
        try:
            list(ClaudeCodeAdapter().stream(MESSAGES, cancel=cancel))
        except ChatError as exc:
            box["error"] = str(exc)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(1.0)
    began = time.monotonic()
    cancel.cancel()
    thread.join(timeout=15)
    assert not thread.is_alive() and time.monotonic() - began < 10
    assert box["error"] == "Stopped."


def test_codex_messages_in_a_turn_are_separate_paragraphs(fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "two")
    text = "".join(c.text for c in CodexAdapter().stream(MESSAGES) if c.kind == "text")
    assert text == "Let me check the sources.\n\nValidity is accuracy [S1]."


def test_a_failed_flag_check_is_not_remembered_as_no_such_flag(fake_clis, monkeypatch):
    exe = cli_models.find_cli("codex")
    monkeypatch.setenv("FAKE_MODE", "helpfail")
    assert cli_models._codex_supports(exe, "--ephemeral") is False
    assert exe not in cli_models._codex_flags
    monkeypatch.setenv("FAKE_MODE", "ok")
    assert cli_models._codex_supports(exe, "--ephemeral") is True


def test_status_asks_the_way_a_real_run_does(fake_clis, monkeypatch):
    # With an API key in this app's environment the tool says "signed in", but
    # a run drops the key: the menu must not promise what will then fail.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-the-subscription")
    monkeypatch.setenv("FAKE_MODE", "signed_out")
    assert cli_status("claude_code", refresh=True)["signed_in"] is False
    # A tool that fails in some other way can't say either way: not "signed out".
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("FAKE_MODE", "weird")
    assert cli_status("claude_code", refresh=True)["signed_in"] is None


def test_adapter_choice(settings):
    settings.models.default_provider = "lmstudio"
    chosen = get_chat_adapter(settings, "chat", provider="claude_code", model="haiku")
    assert isinstance(chosen, ClaudeCodeAdapter) and chosen.model == "haiku"
    default_codex = get_chat_adapter(settings, "chat", provider="codex")
    assert isinstance(default_codex, CodexAdapter) and default_codex.model == ""
    settings.models.default_provider = "claude_code"
    settings.models.claude_code.model = "opus"
    assert get_chat_adapter(settings, "quiz_marking").model == "opus"
    with pytest.raises(ValueError):
        get_chat_adapter(settings, "chat", provider="nope")


@pytest.fixture
def indexed(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    return settings


def test_streamed_answer_through_the_subscription(indexed, fake_clis):
    events = list(stream_answer("What is reliability?", settings=indexed, adapter=ClaudeCodeAdapter()))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done" and "thinking" in kinds
    done = events[-1]
    assert done["answer"] == "Reliability is consistency [S1]."
    assert done["citations"] and done["model"] == "claude-code:sonnet"


@pytest.fixture
def client(indexed):
    app.dependency_overrides[get_settings] = lambda: indexed
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_http_model_menu_and_a_chat_that_picks_a_model(client, fake_clis, indexed, monkeypatch):
    monkeypatch.setattr("app.api.settings.get_settings", lambda: indexed)
    menu = client.get("/settings/models").json()
    by_provider = {}
    for option in menu["options"]:
        by_provider.setdefault(option["provider"], []).append(option)
    assert [o["model"] for o in by_provider["claude_code"]] == ["sonnet", "opus", "haiku"]
    assert all(o["available"] for o in by_provider["claude_code"] + by_provider["codex"])
    assert menu["status"]["codex"]["signed_in"] is True

    res = client.post(
        "/chat/stream",
        json={"message": "What is validity?", "provider": "codex", "model": ""},
    )
    events = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    assert events[-1]["type"] == "done"
    assert events[-1]["answer"] == "Validity is accuracy [S1]."
    assert events[-1]["model"] == "codex:default"

    bad = client.post("/chat/stream", json={"message": "x", "provider": "nope"})
    assert bad.status_code == 400
    for path, body in (
        ("/chat/stream", {"message": "x", "provider": "codex", "model": "a&calc"}),
        ("/chat", {"message": "x", "provider": "claude_code", "model": "--dangerously-skip-permissions"}),
        ("/settings/test-model", {"provider": "codex", "model": "%PATH%"}),
    ):
        assert client.post(path, json=body).status_code == 400, path

    tried = client.post("/settings/test-model", json={"provider": "claude_code", "model": "haiku"})
    assert tried.status_code == 200, tried.text
    assert tried.json()["reply"] == "Reliability is consistency [S1]."
    assert tried.json()["model"] == "claude-code:haiku"
    monkeypatch.setenv("FAKE_MODE", "signed_out")
    failed = client.post("/settings/test-model", json={"provider": "codex"})
    assert failed.status_code == 400 and "codex login" in failed.json()["detail"]
