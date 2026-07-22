from app.github_poller import is_scan_trigger


def test_dependency_scan_title_and_label_triggers():
    assert is_scan_trigger({"title": "Please run a dependency scan", "labels": []})
    assert is_scan_trigger({"title": "Routine maintenance", "labels": [{"name": "scan"}]})
    assert not is_scan_trigger({"title": "Fix login bug", "labels": []})
