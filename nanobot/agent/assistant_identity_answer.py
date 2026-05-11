from __future__ import annotations

import re
from pathlib import Path

_EXACT_SELF_IDENTITY_QUESTIONS = {
    "what is your name",
    "what is your name?",
    "who are you",
    "who are you?",
    "are you chatgpt",
    "are you chatgpt?",
    "are you nanobot",
    "are you nanobot?",
    "what should i call you",
    "what should i call you?",
}

_CANONICAL_ASSISTANT_NAME = "Nanobot"
_DISPLAY_ASSISTANT_NAME = "nanobot 🐈"


def normalize_assistant_identity_question(text: str) -> str:
    normalized = (text or "").strip().lower()
    normalized = normalized.replace("’", "'")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def is_assistant_identity_question(text: str) -> bool:
    return normalize_assistant_identity_question(text) in _EXACT_SELF_IDENTITY_QUESTIONS


def _canonical_assistant_name(workspace: Path) -> str:
    soul_path = workspace / "SOUL.md"
    if soul_path.is_file():
        soul_text = soul_path.read_text(encoding="utf-8")
        if "nanobot" in soul_text.lower():
            return _CANONICAL_ASSISTANT_NAME
    return _CANONICAL_ASSISTANT_NAME


def answer_assistant_identity_question(workspace: Path, text: str) -> str | None:
    normalized = normalize_assistant_identity_question(text)
    if normalized not in _EXACT_SELF_IDENTITY_QUESTIONS:
        return None

    assistant_name = _canonical_assistant_name(workspace)

    if normalized in {"what is your name", "what is your name?", "who are you", "who are you?", "what should i call you", "what should i call you?"}:
        return f"I’m {assistant_name} / {_DISPLAY_ASSISTANT_NAME}."
    if normalized in {"are you nanobot", "are you nanobot?"}:
        return f"Yes — I’m {assistant_name} / {_DISPLAY_ASSISTANT_NAME}."
    if normalized in {"are you chatgpt", "are you chatgpt?"}:
        return (
            f"I’m {assistant_name} / {_DISPLAY_ASSISTANT_NAME}. "
            "The underlying model may be ChatGPT/OpenAI-powered, but this assistant/runtime identity is Nanobot."
        )
    return None
