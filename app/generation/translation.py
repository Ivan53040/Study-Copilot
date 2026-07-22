"""Local-LLM translation helpers for note reading."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.config.settings import Settings
from app.models.chat import (
    ChatAdapter,
    ChatError,
    ChatMessage,
    LMStudioChatAdapter,
    get_chat_adapter,
)

SOURCE_LANGUAGE = "English"
TARGET_LANGUAGE = "Traditional Chinese"
MAX_TRANSLATION_CHARS = 4000
MAX_BATCH_ITEMS = 4
MAX_BATCH_CHARS = 5000

_SYSTEM = """/no_think
You translate study notes from English to Traditional Chinese.
Return only the translation. Do not add explanations, labels, romanization, or commentary.
Preserve Markdown syntax, headings, bullet lists, numbered lists, and simple line breaks where possible."""


@dataclass
class TranslationResult:
    text: str
    translation: str
    source_language: str
    target_language: str
    model: str

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "translation": self.translation,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "model": self.model,
        }


@dataclass
class TranslationBatchResult:
    texts: list[str]
    translations: list[str]
    source_language: str
    target_language: str
    model: str

    def as_dict(self) -> dict:
        return {
            "texts": self.texts,
            "translations": self.translations,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "model": self.model,
        }


def _clean_text(text: str) -> str:
    return text.strip()


def _local_model(settings: Settings, adapter: ChatAdapter | None) -> ChatAdapter:
    if adapter is not None:
        return adapter
    override = settings.task_models.translation
    if override.provider:
        return get_chat_adapter(settings, task="translation")
    local = settings.models.lmstudio
    return LMStudioChatAdapter(
        base_url=local.base_url,
        model=local.model,
        extra_payload={
            "chat_template_kwargs": {"enable_thinking": False},
            "enable_thinking": False,
            "top_p": 0.8,
        },
    )


def _translation_or_error(response_content: str) -> str:
    translation = response_content.strip()
    if not translation:
        raise ChatError(
            "Local LLM returned an empty translation. If you are using a Qwen reasoning "
            "model, enable no-thinking/non-reasoning mode in LM Studio or use an instruct "
            "model that writes the answer to message.content."
        )
    return translation


def _parse_translation_array(content: str, expected: int) -> list[str]:
    raw = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChatError(f"Local LLM returned invalid batch translation JSON: {exc}") from exc
    if not isinstance(parsed, list) or len(parsed) != expected:
        raise ChatError(
            f"Local LLM returned {len(parsed) if isinstance(parsed, list) else 'non-list'} "
            f"translations; expected {expected}."
        )
    translations = [str(item).strip() for item in parsed]
    if any(not item for item in translations):
        raise ChatError("Local LLM returned an empty item in the batch translation.")
    return translations


def translate_english_to_traditional_chinese(
    text: str,
    *,
    settings: Settings,
    context: str | None = None,
    adapter: ChatAdapter | None = None,
) -> TranslationResult:
    cleaned = _clean_text(text)
    if not cleaned:
        raise ValueError("Text to translate cannot be empty.")
    if len(cleaned) > MAX_TRANSLATION_CHARS:
        raise ValueError(
            f"Text to translate is too long; maximum is {MAX_TRANSLATION_CHARS} characters."
        )

    model = _local_model(settings, adapter)
    prompt = f"/no_think\nTranslate this English text into Traditional Chinese:\n\n{cleaned}"
    if context and context.strip():
        prompt = (
            "Use this surrounding note context only to resolve ambiguous terms. "
            "Do not translate the context unless it appears in the text.\n\n"
            f"Context:\n{context.strip()[:1000]}\n\n{prompt}"
        )

    response = model.generate(
        [
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(role="user", content=prompt),
        ],
        temperature=0.1,
        max_tokens=2048,
    )
    translation = _translation_or_error(response.content)
    return TranslationResult(
        text=cleaned,
        translation=translation,
        source_language=SOURCE_LANGUAGE,
        target_language=TARGET_LANGUAGE,
        model=response.model,
    )


def translate_batch_english_to_traditional_chinese(
    texts: list[str],
    *,
    settings: Settings,
    adapter: ChatAdapter | None = None,
) -> TranslationBatchResult:
    cleaned = [_clean_text(text) for text in texts]
    if not cleaned or any(not text for text in cleaned):
        raise ValueError("Batch translation texts cannot be empty.")
    if len(cleaned) > MAX_BATCH_ITEMS:
        raise ValueError(f"Batch translation supports at most {MAX_BATCH_ITEMS} items.")
    if any(len(text) > MAX_TRANSLATION_CHARS for text in cleaned):
        raise ValueError(
            f"Each text to translate must be at most {MAX_TRANSLATION_CHARS} characters."
        )
    if sum(len(text) for text in cleaned) > MAX_BATCH_CHARS:
        raise ValueError(
            f"Batch translation is too long; maximum is {MAX_BATCH_CHARS} characters."
        )

    model = _local_model(settings, adapter)
    payload = json.dumps(cleaned, ensure_ascii=False)
    response = model.generate(
        [
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(
                role="user",
                content=(
                    "/no_think\nTranslate each English string in this JSON array into "
                    "Traditional Chinese. Return only a JSON array of translated strings "
                    f"in the same order, with no markdown and no commentary:\n\n{payload}"
                ),
            ),
        ],
        temperature=0.0,
        max_tokens=8192,
    )
    content = _translation_or_error(response.content)
    translations = _parse_translation_array(content, len(cleaned))
    return TranslationBatchResult(
        texts=cleaned,
        translations=translations,
        source_language=SOURCE_LANGUAGE,
        target_language=TARGET_LANGUAGE,
        model=response.model,
    )
