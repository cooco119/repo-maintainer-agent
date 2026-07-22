from app.slack_bot import route_message


def test_slack_command_router():
    assert route_message("status") == {"action": "status"}
    assert route_message("<@U123> report") == {"action": "report"}
    assert route_message("issue #42") == {"action": "issue", "issue_number": 42}
    assert route_message("#7") == {"action": "issue", "issue_number": 7}
    assert route_message("remediate #8") == {
        "action": "remediate",
        "repo": "cooco119/superset",
        "issue_number": 8,
    }
    assert route_message("remediate owner/project#9") == {
        "action": "remediate",
        "repo": "owner/project",
        "issue_number": 9,
    }
    assert route_message("hello bot") == {"action": "help"}
