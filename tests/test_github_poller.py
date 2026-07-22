from app.github_poller import is_scan_trigger, triage_decision


def test_dependency_scan_title_and_label_triggers():
    assert is_scan_trigger({"title": "Please run a dependency scan", "labels": []})
    assert is_scan_trigger({"title": "Routine maintenance", "labels": [{"name": "scan"}]})
    assert not is_scan_trigger({"title": "Fix login bug", "labels": []})


def test_triage_auto_path_uses_confidence_signal():
    decision, reason = triage_decision(
        {"title": "Fix login bug", "labels": [{"name": "security"}]}, "maintainer"
    )
    assert decision == "auto"
    assert "security" in reason


def test_triage_waits_without_confidence_or_assignment():
    decision, _ = triage_decision(
        {"title": "Refactor dashboard", "labels": []}, "maintainer"
    )
    assert decision == "await"


def test_triage_explicit_assignment_overrides_confidence():
    decision, reason = triage_decision(
        {
            "title": "Refactor dashboard",
            "labels": [],
            "assignees": [{"login": "maintainer"}],
        },
        "maintainer",
    )
    assert decision == "explicit"
    assert "assigned" in reason


def test_triage_remediate_label_overrides_confidence():
    decision, _ = triage_decision(
        {"title": "Refactor dashboard", "labels": [{"name": "remediate"}]},
        "maintainer",
    )
    assert decision == "explicit"
