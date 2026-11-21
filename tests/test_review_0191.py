"""The findings of the independent review of the 0.19.1 codebase: gc must delete exactly the dead
entries of SIGNOFF.toml whatever the layout of their headers, the blame cache must see a change to a
file with a non-ASCII name, a symlink (also a dangling one) must take a review of the whole file,
and diff must count an empty file as one unit."""
import json

import pytest

from aisignoff.cli import remove_tables
from aisignoff.config import ConfigError, load_text
from aisignoff.project import Project
from test_review_018 import DECL, HIST, Repo, no_ci  # noqa: F401


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def review(r, path, header):
    return (f'\n{header}\npath = "{path}"\nblob = "{r.g("rev-parse", "HEAD:" + path)}"\n'
            'Human-Review = "H3"\nReviewed-by = "Dev"\n')


def human(r, name):
    return {x.path: x for x in Project(r.d).results(quiet=True)}[name].declaration.get("Human-Review")


# ------------------------------------------------------------------ finding 1: gc and table headers
@pytest.mark.parametrize("header", ['[[ "attestations" ]]', "[['attestations']]  # quoted",
                                    '[[\t"attestations"\t]]', "[[attestations]]"])
def test_gc_deletes_the_dead_entry_whatever_its_header(repo, header):
    for name in ("dead", "live"):
        repo.write(name, [name])
    repo.commit("add files\n\n" + DECL)
    (repo.d / "SIGNOFF.toml").write_text(HIST + review(repo, "dead", header) + review(repo, "live", "[[attestations]]"))
    repo.commit("record reviews\n\n" + DECL)
    (repo.d / "dead").unlink()
    repo.commit("delete dead\n\n" + DECL)
    assert human(repo, "live") == "H3"
    code, out = repo.cli("gc")
    assert code == 0, out
    assert "entry 1 (dead)" in out, out
    left = load_text((repo.d / "SIGNOFF.toml").read_text(), repo.d / "SIGNOFF.toml").attestations
    assert [a.path for a in left] == ["live"]
    assert human(repo, "live") == "H3"


def test_gc_refuses_entries_it_cant_tell_apart_by_line(repo):
    """An inline array has no header per entry: gc says so and leaves SIGNOFF.toml as it is."""
    for name in ("dead", "live"):
        repo.write(name, [name])
    repo.commit("add files\n\n" + DECL)
    entries = ", ".join(f'{{path = "{n}", blob = "{repo.g("rev-parse", "HEAD:" + n)}", Human-Review = "H3", '
                        'Reviewed-by = "Dev"}' for n in ("dead", "live"))
    text = HIST.replace("[history]", f"attestations = [{entries}]\n\n[history]")
    (repo.d / "SIGNOFF.toml").write_text(text)
    repo.commit("record reviews\n\n" + DECL)
    (repo.d / "dead").unlink()
    repo.commit("delete dead\n\n" + DECL)
    for args in (["gc", "--dry-run"], ["gc"]):
        code, out = repo.cli(*args)
        assert code != 0 and "can't tell which lines to delete" in out, out
        assert (repo.d / "SIGNOFF.toml").read_text() == text


def test_remove_tables_checks_the_number_of_headers():
    text = 'attestations = [{path = "a", blob = "0"}]\n'
    with pytest.raises(ConfigError):
        remove_tables(text, "attestations", {1}, count=1)


# ------------------------------------------------------------------ finding 2: the cache and quoted names
def test_the_cache_sees_an_edit_of_a_binary_file_with_a_non_ascii_name(repo, monkeypatch):
    monkeypatch.delenv("AISIGNOFF_NO_CACHE", raising=False)
    repo.g("config", "core.quotePath", "true")
    (repo.d / "données.bin").write_bytes(b"\x00first")
    repo.commit("add\n\n" + DECL)
    assert human(repo, "données.bin") == "H1"  # warms the cache
    (repo.d / "données.bin").write_bytes(b"\x00second")
    repo.commit("edit\n\n" + DECL.replace("Human-Review: H1", "Human-Review: H3"))
    assert human(repo, "données.bin") == "H3"
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    assert human(repo, "données.bin") == "H3"


def test_a_rename_of_a_binary_file_with_a_non_ascii_name_keeps_its_commit(repo, monkeypatch):
    """A commit that only moves the file leaves it to the commit before, also for a quoted name."""
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    (repo.d / "données.bin").write_bytes(b"\x00first")
    repo.commit("add\n\n" + DECL.replace("Human-Review: H1", "Human-Review: H3"))
    repo.g("mv", "données.bin", "résultats.bin")
    repo.commit("rename\n\n" + DECL)
    assert human(repo, "résultats.bin") == "H3"


# ------------------------------------------------------------------ finding 3: symlinks
@pytest.mark.parametrize("target", ["added-later.txt", "present.txt"])
def test_a_symlink_takes_a_review_of_the_whole_file(repo, target):
    repo.write("present.txt", ["here"])
    (repo.d / "link").symlink_to(target)
    repo.commit("add a symlink\n\n" + DECL)
    blob = repo.g("rev-parse", "HEAD:link")
    for extra, to in ((["--at", "HEAD"], "reviews/at-head.toml"), ([], "reviews/current.toml")):
        code, out = repo.cli("attest", "link", *extra, "-a", "A1", "--findings", "none", "--ai-reviewed-by",
                             "GPT Sol (OpenAI)", "--to", to)
        assert code == 0, out
        assert f'blob = "{blob}"' in (repo.d / to).read_text()
    repo.commit("reviews")
    code, out = repo.cli("lint")
    assert code == 0 and "cover no line" not in out, out
    assert set(repo.findings("link").values()) == {"none"}


# ------------------------------------------------------------------ finding 4: diff and empty files
def added_removed(r):
    code, out = r.cli("diff", "HEAD", "--json")
    assert code == 0, out
    total = json.loads(out)["total"]
    return total["added"], total["removed"]


def test_diff_counts_an_empty_file_as_one_unit(repo):
    (repo.d / "empty.txt").touch()
    assert added_removed(repo) == (1, 0)  # untracked
    repo.g("add", "empty.txt")
    assert added_removed(repo) == (1, 0)  # staged
    repo.commit("add empty\n\n" + DECL)
    (repo.d / "empty.txt").unlink()
    assert added_removed(repo) == (0, 1)  # deleted


def test_diff_counts_the_unit_of_a_file_that_was_or_becomes_empty(repo):
    (repo.d / "empty.txt").touch()
    repo.write("full.txt", ["one", "two"])
    repo.commit("add\n\n" + DECL)
    repo.write("empty.txt", ["now", "text"])
    assert added_removed(repo) == (2, 1)  # the empty unit replaced by two lines
    repo.g("checkout", "--", "empty.txt")
    (repo.d / "full.txt").write_text("")
    assert added_removed(repo) == (1, 2)  # two lines replaced by the empty unit
