"""Chat through a Claude or ChatGPT subscription, via the vendors' own CLIs.

Anthropic and OpenAI don't let other apps sign in with a Claude Pro/Max or a
ChatGPT account. What they do support is their own command-line tools, which
the user signs in to once: Claude Code (``claude``) and Codex (``codex``).
These adapters run that tool for each reply, as the user would from a
terminal. The app never sees the account or its tokens; usage counts toward
the user's plan. (For API-key access, see the OpenAI / Anthropic adapters.)

Both tools are agents that can run commands and edit files. Here they are
used only to write text: Claude Code runs with every tool turned off; Codex
runs read-only in an empty scratch folder.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Iterator

from app.models.chat import ChatError, ChatMessage, ChatResponse, StreamCancel, StreamChunk

_WINDOWS = sys.platform == "win32"
# No console window flashing up when the app runs without one (pythonw).
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200

CLAUDE_MODELS = (("sonnet", "Claude Sonnet"), ("opus", "Claude Opus"), ("haiku", "Claude Haiku"))
_DEFAULT_SYSTEM = "You are a helpful study assistant."

# Model names become command-line arguments, and on Windows an npm-installed
# tool starts through cmd.exe, where `&`, `|`, `%` and quotes mean something.
# Real names are like ``sonnet``, ``gpt-5.5``, ``claude-opus-4-5[1m]``.
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,80}$")
_EFFORT_NAME = re.compile(r"^[a-z]{3,10}$")


def check_model_name(model: str | None) -> str:
    """``model`` if it is safe to pass to a CLI (empty is fine), else ValueError."""
    model = (model or "").strip()
    if model and not _MODEL_NAME.match(model):
        raise ValueError(f"Not a valid model name: {model[:40]!r}")
    return model


def _check_effort(effort: str | None) -> str | None:
    effort = (effort or "").strip().lower()
    if effort and not _EFFORT_NAME.match(effort):
        raise ValueError(f"Not a valid effort level: {effort[:20]!r}")
    return effort or None


# ---- finding and running the tools ---------------------------------------


def find_cli(name: str, command: str | None = None) -> str | None:
    """Full path of a CLI: the configured command (a name or a path), else
    ``name`` on PATH, else where its installers usually put it."""
    wanted = (command or "").strip() or name
    if os.sep in wanted or "/" in wanted:
        path = Path(os.path.expandvars(os.path.expanduser(wanted)))
        return str(path) if path.is_file() else None
    found = shutil.which(wanted)
    if found:
        return found
    if _WINDOWS:
        # Installed after this app started: the saved PATH already has it.
        found = shutil.which(wanted, path=_registry_path())
        if found:
            return found
    home = Path.home()
    if _WINDOWS:
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        candidates = [
            home / ".local" / "bin" / f"{wanted}.exe",  # native installers
            appdata / "npm" / f"{wanted}.cmd",  # npm install -g
        ]
    else:
        candidates = [
            home / ".local" / "bin" / wanted,
            home / ".claude" / "local" / wanted,
            home / ".npm-global" / "bin" / wanted,
            Path("/opt/homebrew/bin") / wanted,
            Path("/usr/local/bin") / wanted,
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _registry_path() -> str | None:
    """The user's + machine's PATH as saved in the registry (Windows)."""
    try:
        import winreg
    except ImportError:
        return None
    parts: list[str] = []
    for root, key in (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ):
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "Path")
                parts.append(os.path.expandvars(str(value)))
        except OSError:
            continue
    return os.pathsep.join(parts) or None


def _child_env(drop: tuple[str, ...]) -> dict[str, str]:
    """This process's environment without ``drop`` (API keys that would make
    the tool bill an API account instead of the subscription)."""
    return {k: v for k, v in os.environ.items() if k not in drop}


def _popen(argv: list[str], *, cwd: str, env: dict[str, str]) -> subprocess.Popen:
    kwargs: dict = {}
    if _WINDOWS:
        kwargs["creationflags"] = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **kwargs,
    )


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop the tool and anything it started (npm installs run it via node).

    A no-op once the tool has been reaped, so a late Stop can never hit a
    process that has since reused its id.
    """
    if proc.poll() is not None:
        return
    try:
        if _WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                creationflags=_CREATE_NO_WINDOW,
                timeout=10,
            )
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=2 if not _WINDOWS else 5)
        return
    except subprocess.TimeoutExpired:
        pass
    # Ignored the polite stop: the whole group, not just the leader.
    try:
        if _WINDOWS:
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _quick(
    argv: list[str], timeout: float = 20.0, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess | None:
    """Run a short command (version, sign-in status); None if it can't run."""
    kwargs: dict = {"creationflags": _CREATE_NO_WINDOW} if _WINDOWS else {}
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=env,
            **kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        return None


class _Run:
    """One run of a CLI: prompt on stdin, JSON lines on stdout.

    Stops on ``cancel`` (the reader pressed Stop), on ``timeout``, or when the
    caller closes the line iterator early.
    """

    def __init__(
        self,
        argv: list[str],
        stdin_text: str,
        *,
        env: dict[str, str],
        timeout: float,
        cancel: StreamCancel | None,
        label: str,
        scratch: tempfile.TemporaryDirectory,
    ) -> None:
        self._label = label
        self._scratch = scratch  # the tool's working folder; removed afterwards
        self.scratch = Path(scratch.name)
        self._argv = argv
        self._stdin_text = stdin_text
        self._env = env
        self._timeout = timeout
        self._cancel = cancel
        self._stderr: list[str] = []
        self.timed_out = False
        self.proc: subprocess.Popen | None = None

    def lines(self) -> Iterator[str]:
        try:
            self.proc = proc = _popen(self._argv, cwd=str(self.scratch), env=self._env)
        except OSError as exc:
            self._cleanup_scratch()
            raise ChatError(f"Could not start {self._label}: {exc}") from exc
        if self._cancel is not None:
            self._cancel.add(lambda: _kill_tree(proc))
        timer = threading.Timer(self._timeout, self._on_timeout)
        timer.daemon = True
        timer.start()
        reader = threading.Thread(target=self._drain_stderr, daemon=True)
        reader.start()
        # Fed from a thread, so a long prompt can't deadlock against output.
        writer = threading.Thread(target=self._feed_stdin, daemon=True)
        writer.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if line:
                    yield line
            proc.wait()
        finally:
            timer.cancel()
            _kill_tree(proc)
            reader.join(timeout=2)
            # Closing a pipe another thread is still blocked reading can hang,
            # so only close stderr once its reader is done.
            streams = [proc.stdout] + ([] if reader.is_alive() else [proc.stderr])
            for stream in streams:
                try:
                    if stream is not None:
                        stream.close()
                except (OSError, ValueError):
                    pass
            self._cleanup_scratch()

    def _cleanup_scratch(self) -> None:
        """Remove the tool's working folder. On Windows it can stay locked for a
        moment after the tool is killed (or while a virus scanner looks at it);
        that must never lose an answer that has already been written."""
        for _ in range(5):
            try:
                self._scratch.cleanup()
                return
            except OSError:
                time.sleep(0.2)
        shutil.rmtree(self._scratch.name, ignore_errors=True)

    def _feed_stdin(self) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None:
            return
        try:
            # UTF-8 bytes as they are: text mode would turn "\n" into "\r\n" on Windows.
            proc.stdin.buffer.write(self._stdin_text.encode("utf-8"))
            proc.stdin.buffer.flush()
            proc.stdin.close()
        except (OSError, ValueError):
            pass  # it exited early; stdout/stderr say why

    def _on_timeout(self) -> None:
        self.timed_out = True
        if self.proc is not None:
            _kill_tree(self.proc)

    def _drain_stderr(self) -> None:
        proc = self.proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                self._stderr.append(line)
                del self._stderr[:-40]
        except (OSError, ValueError):
            pass

    @property
    def returncode(self) -> int | None:
        return self.proc.returncode if self.proc is not None else None

    @property
    def stderr(self) -> str:
        return "".join(self._stderr).strip()


def _text_of(content: str | list[dict]) -> tuple[str, bool]:
    """Text of a message and whether it also had images (which are dropped)."""
    if isinstance(content, str):
        return content, False
    texts = [part.get("text", "") for part in content if part.get("type") == "text"]
    return "\n\n".join(t for t in texts if t), any(p.get("type") != "text" for p in content)


def split_messages(messages: list[ChatMessage]) -> tuple[str, str]:
    """``(system prompt, prompt)``: earlier turns become a transcript ahead of
    the last message, since the CLIs take a single prompt."""
    system_parts: list[str] = []
    turns: list[tuple[str, str]] = []
    for message in messages:
        text, has_images = _text_of(message.content)
        if message.role == "system":
            system_parts.append(text)
            continue
        if has_images:
            raise ChatError("This model can't read page images here; answering from text.")
        turns.append((message.role, text))
    system = "\n\n".join(p for p in system_parts if p.strip())
    if not turns:
        return system, ""
    *earlier, (_, last) = turns
    if not earlier:
        return system, last
    transcript = "\n\n".join(
        f"<{'user' if role == 'user' else 'assistant'}>\n{text}\n</{'user' if role == 'user' else 'assistant'}>"
        for role, text in earlier
    )
    return system, (
        "Earlier in this conversation:\n\n"
        f"{transcript}\n\n"
        "Now reply to this:\n\n"
        f"{last}"
    )


_SIGNED_OUT = re.compile(
    r"not logged in|please run /login|\blog ?in\b|sign in|unauthori[sz]ed|\b401\b|invalid api key|authentication",
    re.IGNORECASE,
)


def _looks_signed_out(text: str) -> bool:
    return bool(_SIGNED_OUT.search(text))


# ---- Claude Code -----------------------------------------------------------


_CLAUDE_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
_CODEX_KEYS = ("OPENAI_API_KEY", "CODEX_API_KEY")


class ClaudeCodeAdapter:
    """Claude through the user's Claude subscription (the Claude Code CLI)."""

    provider = "claude_code"

    def __init__(
        self,
        model: str = "sonnet",
        command: str | None = None,
        timeout: float = 300.0,
        effort: str | None = None,
    ) -> None:
        self.model = check_model_name(model) or "sonnet"
        self.command = command
        self.model_name = f"claude-code:{self.model}"
        self._timeout = timeout
        self._effort = _check_effort(effort)

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        cancel: StreamCancel | None = None,
    ) -> Iterator[StreamChunk]:
        exe = find_cli("claude", self.command)
        if exe is None:
            raise ChatError(
                "Claude Code isn't installed. Install it (see Settings → Language model), "
                "run `claude` once and sign in with your Claude account."
            )
        system, prompt = split_messages(messages)
        scratch = tempfile.TemporaryDirectory(prefix="study-copilot-")
        (Path(scratch.name) / "system.md").write_text(system or _DEFAULT_SYSTEM, encoding="utf-8")
        argv = [
            exe, "-p",
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--model", self.model,
            # Our prompt replaces Claude Code's own (a coding assistant's). A
            # path relative to the working folder, so nothing in it (spaces, `&`
            # in a user name) can trip up a Windows .cmd launcher.
            "--system-prompt-file", "system.md",
            "--tools", "",  # write text only: no commands, no file edits
            "--strict-mcp-config",  # and none of the user's MCP servers
            "--disable-slash-commands",
            "--no-session-persistence",
            # Not the user's own Claude Code setup: their CLAUDE.md, hooks and
            # plugins, or a CLAUDE.md in a folder above the temp folder.
            "--setting-sources", "local",
        ]
        if self._effort:
            argv += ["--effort", self._effort]
        run = _Run(
            argv,
            prompt,
            # A Console API key in the environment would take precedence over
            # the subscription sign-in.
            env={**_child_env(_CLAUDE_KEYS), "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
            timeout=self._timeout,
            cancel=cancel,
            label="Claude Code",
            scratch=scratch,
        )

        saw_delta = False
        wrote = False
        finished = False
        error: str | None = None
        with closing(run.lines()) as lines:
            for line in lines:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "stream_event":
                    inner = event.get("event") or {}
                    if inner.get("type") != "content_block_delta":
                        continue
                    delta = inner.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        saw_delta = wrote = True
                        yield StreamChunk("text", delta["text"])
                    elif delta.get("type") == "thinking_delta" and delta.get("thinking"):
                        saw_delta = True
                        yield StreamChunk("thinking", delta["thinking"])
                elif kind == "assistant":
                    message = event.get("message") or {}
                    if event.get("error") or event.get("is_api_error_message") or message.get("model") == "<synthetic>":
                        # The tool's own error notice ("You've hit your limit",
                        # "model not found"), dressed up as a reply: not an answer.
                        error = error or _synthetic_text(message)
                    elif not saw_delta:
                        # Versions without partial messages send whole blocks.
                        for block in message.get("content") or []:
                            if block.get("type") == "text" and block.get("text"):
                                wrote = True
                                yield StreamChunk("text", block["text"])
                elif kind == "result":
                    finished = True
                    if event.get("is_error") or event.get("subtype") not in (None, "success"):
                        error = str(event.get("result") or error or event.get("subtype") or "failed")
                    else:
                        error = None  # it worked after all
                        if not wrote and event.get("result"):
                            wrote = True
                            yield StreamChunk("text", str(event["result"]))
                    break  # the last event: don't wait for the tool to wind down
        if cancel is not None and cancel.cancelled:
            raise ChatError("Stopped.")
        if run.timed_out and not finished:
            raise ChatError(f"Claude Code took longer than {int(self._timeout)} s.")
        if error is None and not finished:
            error = run.stderr or f"Claude Code exited with code {run.returncode}"
        if error is not None:
            raise ChatError(_claude_message(error))

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        text = "".join(c.text for c in self.stream(messages) if c.kind == "text")
        return ChatResponse(content=text, model=self.model_name)


def _synthetic_text(message: dict) -> str:
    return " ".join(
        block.get("text", "")
        for block in message.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def _claude_message(error: str) -> str:
    error = error.strip()[-600:]
    if _looks_signed_out(error):
        return (
            "Claude Code isn't signed in to your Claude account. Open a terminal, "
            f"run `claude`, and sign in. ({error})"
        )
    if "unknown option" in error.lower():
        return f"Claude Code is too old for this; run `claude update`. ({error})"
    return f"Claude Code: {error}"


# ---- Codex (ChatGPT) --------------------------------------------------------


_codex_flags: dict[str, str] = {}


def _codex_supports(exe: str, flag: str) -> bool:
    """Whether this Codex version knows ``flag`` (checked once per install)."""
    if exe not in _codex_flags:
        result = _quick([exe, "exec", "--help"])
        if result is None or result.returncode != 0:
            return False  # couldn't ask: don't remember that as "no such flag"
        _codex_flags[exe] = result.stdout + result.stderr
    return flag in _codex_flags[exe]


class CodexAdapter:
    """ChatGPT through the user's ChatGPT plan (the Codex CLI)."""

    provider = "codex"

    def __init__(
        self,
        model: str = "",
        command: str | None = None,
        timeout: float = 300.0,
        effort: str | None = None,
    ) -> None:
        self.model = check_model_name(model)
        self.command = command
        self.model_name = f"codex:{self.model or 'default'}"
        self._timeout = timeout
        self._effort = _check_effort(effort)

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        cancel: StreamCancel | None = None,
    ) -> Iterator[StreamChunk]:
        exe = find_cli("codex", self.command)
        if exe is None:
            raise ChatError(
                "Codex isn't installed. Install it (see Settings → Language model), "
                "then run `codex login` and sign in with ChatGPT."
            )
        system, prompt = split_messages(messages)
        full_prompt = (
            "Reply with text only: don't run commands, read files or change anything.\n\n"
            + (f"{system}\n\n---\n\n" if system else "")
            + prompt
        )
        argv = [exe, "exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only"]
        if _codex_supports(exe, "--ephemeral"):
            argv.append("--ephemeral")
        if _codex_supports(exe, "--color"):
            argv += ["--color", "never"]
        if self.model:
            argv += ["-m", self.model]
        if self._effort:
            argv += ["-c", f'model_reasoning_effort="{self._effort}"']
        argv.append("-")  # the prompt comes on stdin
        run = _Run(
            argv,
            full_prompt,
            # An API key in the environment would bill the API, not the plan.
            env=_child_env(_CODEX_KEYS),
            timeout=self._timeout,
            cancel=cancel,
            label="Codex",
            scratch=tempfile.TemporaryDirectory(prefix="study-copilot-"),
        )
        finished = False
        failure: str | None = None
        last_error: str | None = None
        spoke = False
        with closing(run.lines()) as lines:
            for line in lines:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "item.completed":
                    item = event.get("item") or {}
                    if item.get("type") == "agent_message" and item.get("text"):
                        # Several messages (Codex narrates between steps) are paragraphs.
                        yield StreamChunk("text", ("\n\n" if spoke else "") + item["text"])
                        spoke = True
                    elif item.get("type") == "reasoning" and item.get("text"):
                        yield StreamChunk("thinking", item["text"])
                elif kind == "turn.completed":
                    finished = True
                    break  # nothing follows: don't wait for the tool to wind down
                elif kind == "turn.failed":
                    failure = str((event.get("error") or {}).get("message") or "failed")
                elif kind == "error":
                    last_error = str(event.get("message") or "")
        if cancel is not None and cancel.cancelled:
            raise ChatError("Stopped.")
        if run.timed_out and not finished:
            raise ChatError(f"Codex took longer than {int(self._timeout)} s.")
        if failure is None and not finished:
            failure = last_error or run.stderr or f"Codex exited with code {run.returncode}"
        if failure is not None:
            raise ChatError(_codex_message(failure))

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        text = "".join(c.text for c in self.stream(messages) if c.kind == "text")
        return ChatResponse(content=text, model=self.model_name)


def _codex_message(error: str) -> str:
    error = error.strip()[-600:]
    if _looks_signed_out(error):
        return (
            "Codex isn't signed in to your ChatGPT account. Open a terminal, run "
            f"`codex login`, and sign in with ChatGPT. ({error})"
        )
    return f"Codex: {error}"


# ---- status for Settings and the model menu ------------------------------------


_status_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_STATUS_TTL = 60.0


def cli_status(kind: str, command: str | None = None, *, refresh: bool = False) -> dict:
    """Is the Claude Code / Codex CLI installed, which version, signed in?

    ``signed_in`` is None when the tool can't say (older versions).
    """
    key = (kind, command or "")
    now = time.monotonic()
    cached = _status_cache.get(key)
    if cached and not refresh and now - cached[0] < _STATUS_TTL:
        return cached[1]
    name = "claude" if kind == "claude_code" else "codex"
    exe = find_cli(name, command)
    status: dict = {"installed": exe is not None, "path": exe, "version": None, "signed_in": None, "account": None}
    if exe is not None:
        version = _quick([exe, "--version"])
        if version is not None and version.returncode == 0:
            lines = (version.stdout or version.stderr).strip().splitlines()
            status["version"] = lines[0][:80] if lines else None
        # Asked the way a real run would be: without the API keys a run drops,
        # or "signed in" could just mean a key that no run will ever use.
        if kind == "claude_code":
            env = _child_env(_CLAUDE_KEYS)
            result = _quick([exe, "auth", "status"], env=env)
            if result is not None:
                text = (result.stdout or "").strip()
                try:
                    info = json.loads(text)
                except ValueError:
                    info = None
                if isinstance(info, dict) and isinstance(info.get("loggedIn"), bool):
                    status["signed_in"] = info["loggedIn"]
                    if info["loggedIn"]:
                        status["account"] = (
                            info.get("subscriptionType")
                            or info.get("subscription_type")
                            or info.get("email")
                            or info.get("authMethod")
                        )
                elif result.returncode == 0:
                    status["signed_in"] = True
                elif result.returncode == 1 and "not logged in" in (text + result.stderr).lower():
                    status["signed_in"] = False
                # Anything else: the tool can't say, and that must not lock the model out.
        else:
            env = _child_env(_CODEX_KEYS)
            result = _quick([exe, "login", "status"], env=env)
            if result is not None:
                text = (result.stdout + "\n" + result.stderr).strip()
                if result.returncode == 0:
                    status["signed_in"] = True
                    first = text.splitlines()[0] if text else ""
                    status["account"] = first[:80] or None
                elif "not logged in" in text.lower():
                    status["signed_in"] = False
    _status_cache[key] = (now, status)
    return status
