from pathlib import Path

from nanobot.agent.assistant_identity_answer import answer_assistant_identity_question


def test_assistant_identity_answers_what_is_your_name(tmp_path: Path) -> None:
    assert answer_assistant_identity_question(tmp_path, "What is your name?") == "I’m Nanobot / nanobot 🐈."


def test_assistant_identity_answers_who_are_you(tmp_path: Path) -> None:
    assert answer_assistant_identity_question(tmp_path, "Who are you?") == "I’m Nanobot / nanobot 🐈."


def test_assistant_identity_answers_are_you_chatgpt(tmp_path: Path) -> None:
    assert answer_assistant_identity_question(tmp_path, "Are you ChatGPT?") == (
        "I’m Nanobot / nanobot 🐈. "
        "The underlying model may be ChatGPT/OpenAI-powered, but this assistant/runtime identity is Nanobot."
    )


def test_assistant_identity_answers_are_you_nanobot(tmp_path: Path) -> None:
    assert answer_assistant_identity_question(tmp_path, "Are you Nanobot?") == "Yes — I’m Nanobot / nanobot 🐈."


def test_assistant_identity_answers_what_should_i_call_you(tmp_path: Path) -> None:
    assert answer_assistant_identity_question(tmp_path, "What should I call you?") == "I’m Nanobot / nanobot 🐈."


def test_assistant_identity_does_not_trigger_on_model_question(tmp_path: Path) -> None:
    assert answer_assistant_identity_question(tmp_path, "What model are you?") is None


def test_assistant_identity_uses_canonical_nanobot_identity_from_soul(tmp_path: Path) -> None:
    (tmp_path / "SOUL.md").write_text("# SOUL\nRuntime identity: Nanobot\n", encoding="utf-8")

    assert answer_assistant_identity_question(tmp_path, "Who are you?") == "I’m Nanobot / nanobot 🐈."
