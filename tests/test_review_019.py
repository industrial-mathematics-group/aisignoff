"""The findings of the independent review of 0.19.0: an unrelated edit and its revert must not
make an earlier review of the same lines the later one, a quoted TOML table header must not
change the order of SIGNOFF.toml entries, and gc must keep a commit's record while a file it
covers is excluded, also after a rename and for the root commit."""
import pytest

from test_review_018 import DECL, HIST, Repo, attest_commit, no_ci  # noqa: F401


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def a1(r, args, findings, to=None, signoff=False):
    code, out = r.cli("attest", *args, "-a", "A1", "--findings", findings, "--ai-reviewed-by", "GPT Sol (OpenAI)",
                      *(["--to", to] if to else []), *(["--signoff"] if signoff else []))
    assert code == 0, out


# ------------------------------------------------------------------ finding 1: edit and revert
def test_reverting_an_unrelated_line_keeps_the_later_commit_review(repo):
    repo.write("a.py", ["one", "two", "three"])
    x = repo.commit("add a.py\n\n" + DECL)
    a1(repo, ["--commit", x], "none", to="reviews/1.toml")
    repo.commit("review 1")
    repo.write("a.py", ["one", "two", "THREE"])
    repo.commit("edit line 3\n\n" + DECL)
    a1(repo, ["--commit", x], "critical", to="reviews/2.toml")
    repo.commit("review 2")
    assert repo.findings("a.py")[1] == "critical"
    repo.write("a.py", ["one", "two", "three"])
    repo.commit("revert line 3\n\n" + DECL)
    got = repo.findings("a.py")
    assert got[1] == got[2] == "critical"


def test_reverting_an_unrelated_line_keeps_a_later_whole_file_review(repo):
    repo.write("a.py", ["one", "two", "three"])
    x = repo.commit("add a.py\n\n" + DECL)
    a1(repo, ["--commit", x], "none", to="reviews/1.toml")
    repo.commit("review 1")
    repo.write("a.py", ["one", "two", "THREE"])
    repo.commit("edit line 3\n\n" + DECL)
    a1(repo, ["a.py"], "critical", to="reviews/2.toml")
    repo.commit("review 2")
    repo.write("a.py", ["one", "two", "three"])
    repo.commit("revert line 3\n\n" + DECL)
    got = repo.findings("a.py")
    assert got[1] == got[2] == "critical"


def test_reverting_an_unrelated_line_keeps_the_later_of_two_whole_file_reviews(repo):
    repo.write("a.py", ["one", "two", "three"])
    repo.commit("add a.py\n\n" + DECL)
    a1(repo, ["a.py"], "none", to="reviews/1.toml")
    repo.commit("review 1")
    repo.write("a.py", ["one", "two", "THREE"])
    repo.commit("edit line 3\n\n" + DECL)
    a1(repo, ["a.py"], "critical", to="reviews/2.toml")
    repo.commit("review 2")
    repo.write("a.py", ["one", "two", "three"])
    repo.commit("revert line 3\n\n" + DECL)
    got = repo.findings("a.py")
    assert got[1] == got[2] == "critical"


def test_a_review_recorded_after_the_revert_is_the_later_one(repo):
    """The control: a re-review of the reverted content counts after the review of the edit."""
    repo.write("a.py", ["one", "two", "three"])
    x = repo.commit("add a.py\n\n" + DECL)
    repo.write("a.py", ["one", "two", "THREE"])
    repo.commit("edit line 3\n\n" + DECL)
    a1(repo, ["--commit", x], "critical", to="reviews/1.toml")
    repo.commit("review 1")
    repo.write("a.py", ["one", "two", "three"])
    repo.commit("revert line 3\n\n" + DECL)
    a1(repo, ["--commit", x], "none", to="reviews/2.toml")
    repo.commit("review 2")
    got = repo.findings("a.py")
    assert got[1] == got[2] == "none"


# ------------------------------------------------------------------ finding 2: quoted table headers
LEGACY = '''
{header}
path = "a.py"
blob = "{blob}"
AI-Review = "A2"
AI-Reviewed-by = ["GPT Sol (OpenAI), reviews/old.md"]
'''


@pytest.fixture(params=['[[ "attestations" ]]', "[['attestations']]  # quoted", "[[attestations]]"])
def header(request):
    return request.param


def test_a_quoted_attestations_header_is_an_entry_that_has_landed(repo, header):
    repo.write("a.py", ["one", "two"])
    repo.write("reviews/old.md", ["an old report"])
    repo.commit("add a.py\n\n" + DECL)
    (repo.d / "SIGNOFF.toml").write_text(HIST + LEGACY.format(header=header, blob=repo.g("hash-object", "a.py")))
    repo.commit("an old review, from before findings\n\n" + DECL)
    assert repo.problems() == []
    code, out = repo.cli("lint")
    assert code == 0, out


def test_a_quoted_header_keeps_the_order_of_reviews(repo, header):
    repo.write("a.py", ["one", "two"])
    repo.write("reviews/old.md", ["an old report"])
    x = repo.commit("add a.py\n\n" + DECL)
    (repo.d / "SIGNOFF.toml").write_text(HIST + LEGACY.format(header=header, blob=repo.g("hash-object", "a.py")))
    repo.commit("an old review\n\n" + DECL)
    a1(repo, ["--commit", x], "major", to="reviews/1.toml")
    repo.commit("review 1")
    assert set(repo.findings("a.py").values()) == {"major"}
    a1(repo, ["--commit", x], "none", signoff=True)
    repo.commit("re-review, recorded by a person")
    assert set(repo.findings("a.py").values()) == {"none"}


def test_entries_that_arent_tables_are_landed_if_the_default_branch_has_them(repo, tmp_path):
    """An inline array can't be split into entries by line: an entry the default branch's
    SIGNOFF.toml has too has landed and is read as it is; one the change adds is checked."""
    repo.write("a.py", ["one", "two"])
    repo.write("reviews/old.md", ["an old report"])
    repo.commit("add a.py\n\n" + DECL)
    blob = repo.g("hash-object", "a.py")
    old = (f'{{path = "a.py", blob = "{blob}", AI-Review = "A2", '
           'AI-Reviewed-by = ["GPT Sol (OpenAI), reviews/old.md"]}')
    (repo.d / "SIGNOFF.toml").write_text(HIST.replace("[history]", f"attestations = [{old}]\n\n[history]"))
    repo.commit("an old review\n\n" + DECL)
    assert repo.problems() == []
    repo.g("checkout", "-q", "-b", "inline", "main")
    new = (f'{{path = "a.py", blob = "{blob}", AI-Review = "A2", '
           'AI-Reviewed-by = ["GPT Sol (OpenAI), reviews/new.md"]}')
    (repo.d / "SIGNOFF.toml").write_text(HIST.replace("[history]", f"attestations = [{old}, {new}]\n\n[history]"))
    repo.commit("a new review\n\n" + DECL)
    repo.g("checkout", "-q", "main")
    code, out = repo.pr_check("inline", DECL, tmp_path)
    assert code == 1, out
    assert "entry 2: A2 needs a line 'AI-Review-Findings:'" in out and "entry 1:" not in out, out


# ------------------------------------------------------------------ finding 3: gc and exclusions
def exclude(r, pattern):
    text = (r.d / "SIGNOFF.toml").read_text()
    (r.d / "SIGNOFF.toml").write_text(text.replace("[history]", f'exclude = ["{pattern}"]\n\n[history]', 1))
    r.commit("exclude for now")


def lift(r, pattern):
    text = (r.d / "SIGNOFF.toml").read_text()
    (r.d / "SIGNOFF.toml").write_text(text.replace(f'exclude = ["{pattern}"]\n\n', ""))
    r.commit("lift the exclusion")


def test_gc_keeps_a_commit_review_of_a_renamed_excluded_file(repo):
    repo.write("solver.py", [f"x{i}" for i in range(5)])
    x = repo.commit("add solver\n\n" + DECL)
    a1(repo, ["--commit", x], "major", to="reviews/solver.toml")
    repo.commit("review")
    repo.g("mv", "solver.py", "gen.py")
    repo.commit("rename\n\n" + DECL)
    assert set(repo.findings("gen.py").values()) == {"major"}
    exclude(repo, "gen.py")
    code, out = repo.cli("gc")
    assert code == 0 and "Nothing to delete" in out, out
    lift(repo, "gen.py")
    assert set(repo.findings("gen.py").values()) == {"major"}


def test_gc_keeps_a_commit_review_of_the_root_commit_while_excluded(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    r = Repo.__new__(Repo)
    r.d = d
    r.g("init", "-q", "-b", "main")
    r.g("config", "user.name", "Dev")
    r.g("config", "user.email", "d@x")
    r.g("config", "commit.gpgsign", "false")
    (d / "SIGNOFF.toml").write_text(HIST)
    r.write("solver.py", [f"x{i}" for i in range(5)])
    x = r.commit("init\n\n" + DECL)
    a1(r, ["--commit", x], "major", to="reviews/solver.toml")
    r.commit("review")
    exclude(r, "solver.py")
    code, out = r.cli("gc")
    assert code == 0 and "Nothing to delete" in out, out
    lift(r, "solver.py")
    assert set(r.findings("solver.py").values()) == {"major"}
