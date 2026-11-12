import pytest


@pytest.fixture(autouse=True)
def _not_a_github_push(monkeypatch):
    """CI runs the tests on push events too; on a push, aisignoff takes no commit for a pull
    request's merge preview (GITHUB_EVENT_NAME=push), which the preview tests must not inherit."""
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
