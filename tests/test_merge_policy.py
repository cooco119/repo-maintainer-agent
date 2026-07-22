from app.evaluator import merge_policy


def test_small_passing_pr_is_eligible_for_auto_merge():
    task = {"pr_url": "https://github.com/acme/repo/pull/1", "labels": []}
    decision, rationale = merge_policy(
        task, True, {"changed_files": 2, "additions": 20, "deletions": 10}, auto_merge=True
    )
    assert decision == "AUTO_MERGE"
    assert "small PR" in rationale


def test_unknown_checks_require_human_review():
    task = {"pr_url": "https://github.com/acme/repo/pull/1", "labels":["security"]}
    decision, _ = merge_policy(task, None, {"changed_files": 1}, auto_merge=True)
    assert decision == "AWAITING_HUMAN_REVIEW"
