from __future__ import annotations

import re

_RESTART_EXACT_QUESTIONS = {
    "how do i restart nanobot on this box?",
    "how do i restart the gateway here?",
    "what should i run to restart the teams listener on this box?",
}

_FALLBACK_EXACT_QUESTIONS = {
    "if the wrapper doesn't fix it, what next?",
    "if the wrapper doesnt fix it, what next?",
    "if the wrapper does not fix it, what next?",
}

_RESTART_WRAPPER = "/home/bjohnson/.nanobot/bin/restart-by-agent.sh"
_FALLBACK_STATUS = "systemctl --user status nanobot-gateway.service"
_FALLBACK_JOURNAL = "journalctl --user -u nanobot-gateway.service -n 160 --no-pager"
_FALLBACK_SOCKET = "ss -ltnp | grep ':18790'"
_FALLBACK_RESTART_LOG = "/home/bjohnson/.nanobot/logs/restart-by-agent.log"
_FALLBACK_GATEWAY_LOG = "/home/bjohnson/.nanobot/logs/gateway.log"


def normalize_host_ops_question(text: str) -> str:
    normalized = (text or "").strip().lower()
    normalized = normalized.replace("’", "'")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def is_host_ops_restart_question(text: str) -> bool:
    normalized = normalize_host_ops_question(text)
    if ".service" in normalized:
        return False
    return normalized in _RESTART_EXACT_QUESTIONS


def is_host_ops_fallback_question(text: str) -> bool:
    normalized = normalize_host_ops_question(text)
    return normalized in _FALLBACK_EXACT_QUESTIONS


def host_ops_restart_answer() -> str:
    return (
        "Run:\n\n"
        f"{_RESTART_WRAPPER}\n\n"
        "That is the approved primary restart method on this host for the local Nanobot gateway/listener.\n\n"
        "If the wrapper does not fix it, next run:\n"
        f"1. {_FALLBACK_STATUS}\n"
        f"2. {_FALLBACK_JOURNAL}\n"
        f"3. {_FALLBACK_SOCKET}\n\n"
        "Then inspect:\n"
        f"4. {_FALLBACK_RESTART_LOG}\n"
        f"5. {_FALLBACK_GATEWAY_LOG}"
    )


def host_ops_fallback_answer() -> str:
    return (
        "If the wrapper does not fix it, use this local diagnostic sequence:\n"
        f"1. {_FALLBACK_STATUS}\n"
        f"2. {_FALLBACK_JOURNAL}\n"
        f"3. {_FALLBACK_SOCKET}\n"
        f"4. inspect {_FALLBACK_RESTART_LOG}\n"
        f"5. inspect {_FALLBACK_GATEWAY_LOG}"
    )


def answer_host_ops_question(text: str) -> str | None:
    if is_host_ops_fallback_question(text):
        return host_ops_fallback_answer()
    if is_host_ops_restart_question(text):
        return host_ops_restart_answer()
    return None
