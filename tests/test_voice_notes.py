from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.voice_notes import get_settings
from app.main import app
from app.voice_notes.transcription import TranscriptionResult


def test_voice_note_status(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = TestClient(app).get("/voice-notes/status")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["max_upload_mb"] == settings.voice_notes.max_upload_mb


def test_voice_note_upload_writes_note(settings, monkeypatch):
    def fake_transcribe(path: Path, settings):
        return TranscriptionResult(
            transcript="Photosynthesis converts light energy into chemical energy.",
            model_path="fake-whisper.gguf",
        )

    def fake_generate(transcript: str, *, settings, title=None, course=None):
        from app.generation.voice_notes import VoiceNoteMarkdown

        return VoiceNoteMarkdown(
            title=title or "Photosynthesis",
            markdown="# Photosynthesis\n\n## Summary\n\n- Plants make chemical energy.",
            model="fake-llm",
        )

    monkeypatch.setattr("app.voice_notes.service.transcribe_audio_file", fake_transcribe)
    monkeypatch.setattr(
        "app.voice_notes.service.generate_voice_note_markdown",
        fake_generate,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = TestClient(app).post(
            "/voice-notes",
            data={"title": "Plant lecture", "folder": "Voice Notes", "write": "true"},
            files={"audio": ("lecture.webm", b"fake-audio", "audio/webm")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["written"] is True
    assert payload["target_path"].startswith("StudyCopilot/Voice Notes/")
    written = settings.vault.root / payload["target_path"]
    assert written.exists()
    assert "## Transcript" in written.read_text(encoding="utf-8")


def test_voice_note_transcribe_endpoint(settings, monkeypatch):
    class FakeTranscription:
        def as_dict(self):
            return {
                "transcript": "The lecture discussed net present value.",
                "whisper_model_path": "fake-whisper.gguf",
                "audio_path": None,
            }

    monkeypatch.setattr(
        "app.api.voice_notes.transcribe_voice_note_audio",
        lambda path, *, settings: FakeTranscription(),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = TestClient(app).post(
            "/voice-notes/transcribe",
            files={"audio": ("lecture.webm", b"fake-audio", "audio/webm")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["transcript"] == "The lecture discussed net present value."


def test_voice_note_generate_from_transcript_endpoint(settings, monkeypatch):
    class FakeNote:
        def as_dict(self):
            return {
                "transcript": "The lecture discussed net present value.",
                "markdown": "# Finance\n\n## Summary\n\n- NPV was discussed.\n\n## Transcript\n\nThe lecture discussed net present value.",
                "title": "Finance",
                "model": "fake-llm",
                "whisper_model_path": "",
                "written": True,
                "target_path": "StudyCopilot/Voice Notes/Finance.md",
                "audio_path": None,
            }

    monkeypatch.setattr(
        "app.api.voice_notes.create_voice_note_from_transcript",
        lambda transcript, **kwargs: FakeNote(),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = TestClient(app).post(
            "/voice-notes/generate",
            json={
                "transcript": "The lecture discussed net present value.",
                "title": "Finance",
                "write": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Finance"
    assert payload["written"] is True
