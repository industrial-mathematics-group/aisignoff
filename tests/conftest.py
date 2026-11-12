import pytest


@pytest.fixture(autouse=True)
def no_merge_queue(monkeypatch):
    """The tests' repositories aren't the run they are in: in a merge queue's run of this
    repository, GITHUB_REF would make every HEAD count as landed."""
    monkeypatch.delenv("GITHUB_REF", raising=False)
