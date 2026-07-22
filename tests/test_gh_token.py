import app.gh_token as gh_token


def test_command_token_is_cached_until_ttl_then_refreshed(monkeypatch):
    clock = [100.0]
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])

        class Result:
            stdout = "tok\n"

        return Result()

    monkeypatch.setattr(gh_token.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(gh_token.subprocess, "run", fake_run)
    monkeypatch.setenv("GITHUB_TOKEN_CMD", "echo tok")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    gh_token.invalidate()

    assert gh_token.get_github_token() == "tok"
    clock[0] += gh_token.TOKEN_TTL_SEC - 1
    assert gh_token.get_github_token() == "tok"
    assert len(calls) == 1
    clock[0] += 2
    assert gh_token.get_github_token() == "tok"
    assert len(calls) == 2


def test_invalidate_forces_command_refresh(monkeypatch):
    outputs = iter(["first\n", "second\n"])

    def fake_run(*args, **kwargs):
        class Result:
            stdout = next(outputs)

        return Result()

    monkeypatch.setattr(gh_token.subprocess, "run", fake_run)
    monkeypatch.setenv("GITHUB_TOKEN_CMD", "echo tok")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    gh_token.invalidate()
    assert gh_token.get_github_token() == "first"
    gh_token.invalidate()
    assert gh_token.get_github_token() == "second"
