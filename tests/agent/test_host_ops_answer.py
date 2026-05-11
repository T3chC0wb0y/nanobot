from nanobot.agent.host_ops_answer import answer_host_ops_question


RESTART_WRAPPER = "/home/bjohnson/.nanobot/bin/restart-by-agent.sh"
STATUS_CMD = "systemctl --user status nanobot-gateway.service"
JOURNAL_CMD = "journalctl --user -u nanobot-gateway.service -n 160 --no-pager"
SOCKET_CMD = "ss -ltnp | grep ':18790'"
RESTART_LOG = "/home/bjohnson/.nanobot/logs/restart-by-agent.log"
GATEWAY_LOG = "/home/bjohnson/.nanobot/logs/gateway.log"


def test_host_ops_answers_restart_nanobot_on_this_box() -> None:
    answer = answer_host_ops_question("How do I restart nanobot on this box?")

    assert answer is not None
    assert answer.startswith("Run:\n\n" + RESTART_WRAPPER)



def test_host_ops_answers_restart_gateway_here() -> None:
    answer = answer_host_ops_question("How do I restart the gateway here?")

    assert answer is not None
    assert answer.startswith("Run:\n\n" + RESTART_WRAPPER)



def test_host_ops_answers_restart_teams_listener() -> None:
    answer = answer_host_ops_question("What should I run to restart the Teams listener on this box?")

    assert answer is not None
    assert answer.startswith("Run:\n\n" + RESTART_WRAPPER)



def test_host_ops_answers_wrapper_fallback_with_local_diagnostics() -> None:
    answer = answer_host_ops_question("If the wrapper doesn’t fix it, what next?")

    assert answer is not None
    assert STATUS_CMD in answer
    assert JOURNAL_CMD in answer
    assert SOCKET_CMD in answer
    assert RESTART_LOG in answer
    assert GATEWAY_LOG in answer



def test_host_ops_ignores_unrelated_gateway_service() -> None:
    assert answer_host_ops_question("How do I restart msadmin-gateway.service?") is None



def test_host_ops_ignores_generic_gateway_question() -> None:
    assert answer_host_ops_question("How do I restart the API gateway?") is None



def test_host_ops_ignores_router_gateway_question() -> None:
    assert answer_host_ops_question("How do I restart my home gateway?") is None



def test_host_ops_ignores_generic_wrapper_question() -> None:
    assert answer_host_ops_question("If a wrapper fails, what next?") is None
