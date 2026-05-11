from pathlib import Path

from nanobot.agent.identity_answer import answer_identity_question


def test_identity_question_answers_from_user_md(tmp_path: Path) -> None:
    (tmp_path / "USER.md").write_text(
        "Full name: Bob Johnson.\n"
        "Preferred name: Bob.\n"
        "Username: bjohnson.\n"
        "Mailbox: bjohnson@fwdioc.org.\n",
        encoding="utf-8",
    )

    assert answer_identity_question(tmp_path, "Who am I?") == (
        "You are Bob Johnson. Your preferred name is Bob."
    )


def test_identity_question_ignores_non_identity_question(tmp_path: Path) -> None:
    (tmp_path / "USER.md").write_text("Preferred name: Bob.\n", encoding="utf-8")

    assert answer_identity_question(tmp_path, "Who am I talking to?") is None


def test_identity_question_returns_none_without_user_md(tmp_path: Path) -> None:
    assert answer_identity_question(tmp_path, "Who am I?") is None


def test_identity_question_uses_preferred_name_when_only_preferred_name_exists(tmp_path: Path) -> None:
    (tmp_path / "USER.md").write_text("Preferred name: Bob.\n", encoding="utf-8")

    assert answer_identity_question(tmp_path, "Who am I?") == "You are Bob."
