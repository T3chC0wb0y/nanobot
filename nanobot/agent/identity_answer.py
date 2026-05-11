from __future__ import annotations

import re
from pathlib import Path

_IDENTITY_QUESTIONS = {
    "who am i",
    "who am i?",
    "what is my name",
    "what is my name?",
    "what's my name",
    "what's my name?",
    "do you know who i am",
    "do you know who i am?",
}


def is_identity_question(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return normalized in _IDENTITY_QUESTIONS


def _clean_value(value: str) -> str:
    return value.strip().strip("-").strip().rstrip(".")


def parse_user_identity(user_md: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    patterns = {
        "full_name": r"(?im)^\s*(?:[-*]\s*)?Full name:\s*(.+?)\s*$",
        "preferred_name": r"(?im)^\s*(?:[-*]\s*)?Preferred name:\s*(.+?)\s*$",
        "username": r"(?im)^\s*(?:[-*]\s*)?Username:\s*(.+?)\s*$",
        "mailbox": r"(?im)^\s*(?:[-*]\s*)?Mailbox:\s*(.+?)\s*$",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, user_md)
        if match:
            fields[key] = _clean_value(match.group(1))
    return fields


def answer_identity_question(workspace: Path, text: str) -> str | None:
    if not is_identity_question(text):
        return None

    user_path = workspace / "USER.md"
    if not user_path.is_file():
        return None

    identity = parse_user_identity(user_path.read_text(encoding="utf-8"))
    full_name = identity.get("full_name")
    preferred_name = identity.get("preferred_name")
    username = identity.get("username")
    mailbox = identity.get("mailbox")

    if not (full_name or preferred_name or username or mailbox):
        return None

    if full_name and preferred_name and preferred_name != full_name:
        return f"You are {full_name}. Your preferred name is {preferred_name}."
    if preferred_name:
        return f"You are {preferred_name}."
    if full_name:
        return f"You are {full_name}."
    if username:
        return f"You are {username}."
    return f"You are {mailbox}."
