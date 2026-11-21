"""The findings of the independent review of 0.18.0 (reviews/2026-11-21-v0.18.md): the order of
reviews (an attestation of a commit, SIGNOFF.toml and the review folder), the protected
[review] dir, the report and placement of record files, AI reviews added to SIGNOFF.toml,
evidence in subfolders of the review folder, and gc with excluded files."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aisignoff.project import Project

HIST = '''version = 4

[history]
enabled = true
default-branch = "main"

[[annotations]]
path = "**"
AI-Generation = "G3"
Human-Review = "H1"
AI-Review = "A0"
Assisted-by = ["Claude Opus 5.5 (Anthropic)"]
Reviewed-by = ["Dev"]
'''
DECL = ("AI-Generation: G3\nHuman-Review: H1\nAI-Review: A0\nAssisted-by: Claude Opus 5.5 (Anthropic)\n"
        "Reviewed-by: Dev\n")


@pytest.fixture(autouse=True)
def no_ci(monkeypatch):
    for k in ("GITHUB_EVENT_NAME", "GITHUB_ACTIONS", "GITHUB_REF", "GITHUB_EVENT_PATH"):
        monkeypatch.delenv(k, raising=False)


class Repo:
    def __init__(self, d: Path, toml: str = HIST):
        self.d = d
        self.g("init", "-q", "-b", "main")
        self.g("config", "user.name", "Dev")
        self.g("config", "user.email", "d@x")
        self.g("config", "commit.gpgsign", "false")
        (d / "SIGNOFF.toml").write_text(toml)
        self.commit("init\n\n" + DECL)

    def g(self, *a):
        return subprocess.run(["git", "-C", str(self.d), *a], check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name, lines):
        p = self.d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(f"{line}\n" for line in lines))

    def commit(self, msg):
        self.g("add", "-A")
        self.g("commit", "-q", "--allow-empty", "-m", msg)
        return self.g("rev-parse", "HEAD")

    def cli(self, *args):
        r = subprocess.run([sys.executable, "-m", "aisignoff", *args], cwd=self.d, capture_output=True, text=True,
                           env=dict(os.environ))
        return r.returncode, r.stdout + r.stderr

    def findings(self, name):
        """{line: findings} of a file."""
        res = {r.path: r for r in Project(self.d).results(quiet=True)}[name]
        return {n: p.declaration.findings for p in res.parts for a, b in p.runs for n in range(a, b + 1)}

    def problems(self):
        p = Project(self.d)
        p.results(quiet=True)
        return p.history_problems

    def pr_check(self, branch, description, tmp):
        """lint as the check before the merge runs it, on the merge preview."""
        self.g("checkout", "-q", "--detach", "main")
        self.g("merge", "-q", "--no-ff", "-m", "Merge preview", branch)
        desc = tmp / "description.md"
        desc.write_text(description)
        try:
            return self.cli("lint", "--declare-from", str(desc), "--author", "dev", "--base", "HEAD^1")
        finally:
            self.g("checkout", "-q", "main")


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def attest_commit(r, sha, findings, report, to=None, signoff=False):
    args = ["attest", "--commit", sha, "-a", "A2", "--findings", findings, "--ai-reviewed-by",
            f"GPT Sol (OpenAI), {report}"]
    code, out = r.cli(*args, *(["--to", to] if to else []), *(["--signoff"] if signoff else []))
    assert code == 0, out


# ------------------------------------------------------------------ the order of reviews
def test_a_commit_review_doesnt_outrank_a_later_whole_file_review(repo):
    """Finding 1: a --commit review counted as the newest content, so an earlier review of a commit
    replaced the findings of a later review of the whole file once any other line changed."""
    repo.write("a.py", [f"x{i}" for i in range(5)])
    x = repo.commit("add a.py\n\n" + DECL)
    repo.write("reviews/one.md", ["report 1"])
    attest_commit(repo, x, "none", "reviews/one.md", to="reviews/1-commit.toml")
    repo.commit("review 1")
    repo.write("reviews/two.md", ["report 2"])
    code, out = repo.cli("attest", "a.py", "-a", "A2", "--findings", "critical", "--ai-reviewed-by",
                         "GPT Sol (OpenAI), reviews/two.md", "--to", "reviews/2-file.toml")
    assert code == 0, out
    repo.commit("review 2")
    assert set(repo.findings("a.py").values()) == {"critical"}
    repo.write("a.py", [f"x{i}" for i in range(5)] + ["new"])
    repo.commit("append a line\n\n" + DECL)
    got = repo.findings("a.py")
    assert [got[n] for n in range(1, 6)] == ["critical"] * 5
    assert got[6] is None


def test_a_commit_review_recorded_later_replaces_a_whole_file_review(repo):
    """The other way round: a re-review of the commit, recorded after the whole-file review of the
    same content, gives the findings, also after the file changed elsewhere."""
    repo.write("a.py", ["a", "b", "c"])
    x = repo.commit("add a.py\n\n" + DECL)
    repo.write("reviews/one.md", ["report 1"])
    code, out = repo.cli("attest", "a.py", "-a", "A2", "--findings", "major", "--ai-reviewed-by",
                         "GPT Sol (OpenAI), reviews/one.md", "--to", "reviews/1-file.toml")
    assert code == 0, out
    repo.commit("review 1")
    repo.write("reviews/two.md", ["report 2"])
    attest_commit(repo, x, "none", "reviews/two.md", to="reviews/2-commit.toml")
    repo.commit("review 2")
    repo.write("a.py", ["a", "b", "c", "d"])
    repo.commit("append\n\n" + DECL)
    got = repo.findings("a.py")
    assert [got[n] for n in (1, 2, 3)] == ["none"] * 3


def test_a_signoff_re_review_clears_a_finding_of_the_review_folder(repo):
    """Finding 2: SIGNOFF.toml counted before every record file, so a re-review recorded with
    --signoff (the signoff request and @signoff workflows) couldn't clear a finding of reviews/."""
    repo.write("a.py", ["a", "b", "c"])
    x = repo.commit("add a.py\n\n" + DECL)
    repo.write("reviews/one.md", ["critical: b is wrong"])
    attest_commit(repo, x, "critical", "reviews/one.md", to="reviews/one.toml")
    repo.commit("review 1")
    repo.write("a.py", ["a", "B", "c"])
    y = repo.commit("fix b\n\n" + DECL)
    repo.write("reviews/two.md", ["fixed"])
    repo.commit("report 2")
    for c in (x, y):
        attest_commit(repo, c, "none", "reviews/two.md", signoff=True)
    assert repo.findings("a.py") == {1: "none", 2: "none", 3: "none"}  # not landed yet: the newest
    repo.commit("signoff request: re-review")
    assert repo.findings("a.py") == {1: "none", 2: "none", 3: "none"}
    # and a review in the review folder recorded after it counts after it
    repo.write("reviews/three.md", ["b is wrong again"])
    attest_commit(repo, y, "major", "reviews/three.md", to="reviews/three.toml")
    repo.commit("review 3")
    assert repo.findings("a.py") == {1: "none", 2: "major", 3: "none"}
    assert repo.problems() == []


# ------------------------------------------------------------------ [review] dir is protected
def test_a_pull_request_cant_move_the_review_folder(repo, tmp_path):
    """Finding 3: [review] dir decides which files need no declaration and which are add-only."""
    repo.write("src/solver.py", ["def f():", "    return 1"])
    repo.write("reviews/old-review.md", ["critical: f() is wrong"])
    repo.commit("add\n\n" + DECL)
    repo.g("checkout", "-q", "-b", "dir-src", "main")
    (repo.d / "SIGNOFF.toml").write_text(HIST + '\n[review]\ndir = "src"\n')
    repo.commit("move the review folder")
    repo.g("checkout", "-q", "main")
    code, out = repo.pr_check("dir-src", DECL, tmp_path)
    assert code == 1 and "alters [review] dir in SIGNOFF.toml" in out, out

    repo.g("checkout", "-q", "-b", "rewrite", "main")
    (repo.d / "SIGNOFF.toml").write_text(HIST + '\n[review]\ndir = "reviews2"\n')
    repo.write("reviews/old-review.md", ["none"])
    repo.commit("tidy up")
    repo.g("checkout", "-q", "main")
    code, out = repo.pr_check("rewrite", DECL, tmp_path)
    assert code == 1 and "the change modifies reviews/old-review.md" in out, out
    # even when a maintainer lets the setting change, the base branch's folder stays add-only
    desc = tmp_path / "d.md"
    desc.write_text(DECL)
    repo.g("checkout", "-q", "--detach", "main")
    repo.g("merge", "-q", "--no-ff", "-m", "Merge preview", "rewrite")
    code, out = repo.cli("lint", "--declare-from", str(desc), "--author", "dev", "--base", "HEAD^1",
                         "--allow-policy-change")
    repo.g("checkout", "-q", "main")
    assert code == 1 and "the change modifies reviews/old-review.md" in out, out


# ------------------------------------------------------------------ record files
def test_a_record_file_names_a_report_of_its_own_change(repo, tmp_path):
    """Finding 4: a record file of a change names a report the change adds, or a link, as a
    description does; an earlier review's report isn't this one's."""
    repo.write("solver.py", ["def f():", "    return 1"])
    repo.write("reviews/2026-01-old.md", ["an earlier review"])
    x = repo.commit("add solver\n\n" + DECL)
    record = (f'[[attestations]]\ncommit = "{x}"\nAI-Review = "A3"\n'
              'AI-Reviewed-by = ["GPT Sol (OpenAI), {report}"]\nAI-Review-Findings = "none"\n')
    for n, report in enumerate(("reviews/2026-01-old.md", "README.md")):
        if report == "README.md":
            repo.write("README.md", ["readme"])
            repo.commit("readme\n\n" + DECL)
        repo.g("checkout", "-q", "-b", f"old{n}", "main")
        (repo.d / f"reviews/r{n}.toml").write_text(record.format(report=report))
        repo.commit("review")
        repo.g("checkout", "-q", "main")
        code, out = repo.pr_check(f"old{n}", "a review", tmp_path)
        assert code == 1 and f"the review report {report} isn't part of this change" in out, out
    repo.g("checkout", "-q", "-b", "new", "main")
    repo.write("reviews/new.md", ["a new review"])
    (repo.d / "reviews/new.toml").write_text(record.format(report="reviews/new.md"))
    repo.commit("review")
    repo.g("checkout", "-q", "main")
    code, out = repo.pr_check("new", "a review", tmp_path)
    assert code == 0, out
    # once landed, the report has to exist only; its wording no longer speaks of a pull request
    repo.g("merge", "-q", "--no-ff", "-m", "Merge pull request #3", "new")
    assert repo.problems() == []
    (repo.d / "reviews/gone.toml").write_text(record.format(report="reviews/gone.md"))
    repo.commit("a record whose report is missing")
    assert any("the review report reviews/gone.md doesn't exist: commit it, or link it" in p
               for p in repo.problems())


def test_a_code_change_cant_add_a_review_record(repo, tmp_path):
    """Finding 5: a record file next to the content would raise the change's own lines."""
    repo.write("solver.py", ["def f():", "    return 1"])
    repo.commit("add solver\n\n" + DECL)
    repo.g("checkout", "-q", "-b", "self", "main")
    repo.write("solver.py", ["def f():", "    return 2"])
    repo.write("reviews/self.md", ["looks fine"])
    (repo.d / "reviews/self.toml").write_text(
        f'[[attestations]]\npath = "solver.py"\nblob = "{repo.g("hash-object", "solver.py")}"\nAI-Review = "A3"\n'
        'AI-Reviewed-by = ["GPT Sol (OpenAI), reviews/self.md"]\nAI-Review-Findings = "none"\n')
    repo.commit("change and self-attest")
    repo.g("checkout", "-q", "main")
    code, out = repo.pr_check("self", DECL, tmp_path)
    assert code == 1 and "the change adds the review record reviews/self.toml and also changes solver.py" in out, out


def test_toml_evidence_in_a_subfolder_isnt_a_record_file(repo):
    """Finding 7: an A3 review's evidence may hold a pyproject.toml."""
    repo.write("solver.py", ["def f():", "    return 1"])
    x = repo.commit("add solver\n\n" + DECL)
    repo.write("reviews/pr7.md", ["report"])
    repo.write("reviews/pr7-evidence/pyproject.toml", ["[project]", 'name = "evidence"'])
    repo.write("reviews/pr7-evidence/broken.toml", ["not = = toml"])
    repo.write("reviews/pr7-evidence/fixture.toml", ["[[attestations]]", f'commit = "{x}"', 'AI-Review = "A1"'])
    attest_commit(repo, x, "none", "reviews/pr7.md", to="reviews/pr7.toml")
    repo.commit("review")
    code, out = repo.cli("lint")
    assert code == 0, out
    assert "reviews/pr7-evidence/fixture.toml is in a subfolder of the review folder" in out
    assert set(repo.findings("solver.py").values()) == {"none"}
    code, out = repo.cli("attest", "solver.py", "-a", "A1", "--findings", "none", "--ai-reviewed-by", "M",
                         "--to", "reviews/sub/x.toml")
    assert code == 2 and "directly in the review folder" in out


# ------------------------------------------------------------------ AI reviews in SIGNOFF.toml
def test_an_ai_review_a_change_adds_to_signoff_toml_gives_findings_and_report(repo, tmp_path):
    """Finding 6: checked like a record file. Entries that have landed are read as they are (a
    review recorded before findings existed has none)."""
    repo.write("solver.py", ["def f():", "    return 1"])
    sha = repo.commit("add solver\n\n" + DECL)
    blob = repo.g("hash-object", "solver.py")
    entry = (f'\n[[attestations]]\npath = "solver.py"\nblob = "{blob}"\nAI-Review = "A3"\n'
             'AI-Reviewed-by = ["GPT Sol (OpenAI), reviews/does-not-exist.md"]\n')
    repo.g("checkout", "-q", "-b", "signoff", "main")
    (repo.d / "SIGNOFF.toml").write_text(HIST + entry)
    repo.commit("signoff\n\n" + DECL)
    repo.g("checkout", "-q", "main")
    code, out = repo.pr_check("signoff", DECL, tmp_path)
    assert code == 1, out
    assert "SIGNOFF.toml [[attestations]] entry 1: A3 needs a line 'AI-Review-Findings:'" in out
    assert "the review report reviews/does-not-exist.md doesn't exist" in out
    # a [[commits]] entry that gives an AI review too
    repo.g("checkout", "-q", "-b", "correct", "main")
    (repo.d / "SIGNOFF.toml").write_text(HIST + f'\n[[commits]]\ncommit = "{sha}"\nAI-Review = "A2"\n'
                                         'AI-Reviewed-by = ["GPT Sol (OpenAI)"]\n')
    repo.commit("correct\n\n" + DECL)
    repo.g("checkout", "-q", "main")
    code, out = repo.pr_check("correct", DECL, tmp_path)
    assert code == 1 and "SIGNOFF.toml [[commits]] entry 1: A2 needs a line 'AI-Review-Findings:'" in out, out
    # landed as it is (committed to the default branch directly): read as it is
    (repo.d / "SIGNOFF.toml").write_text(HIST + entry)
    repo.commit("an old review\n\n" + DECL)
    assert repo.problems() == []


# ------------------------------------------------------------------ gc and excluded files
def test_gc_keeps_the_records_of_excluded_files(repo):
    """Finding 8: an excluded file is never resolved, so its records can't be told dead."""
    repo.write("gen/table.py", ["t = 1"])
    repo.write("README.md", ["readme"])
    repo.commit("add\n\n" + DECL)
    code, out = repo.cli("attest", "gen/table.py", "-H", "H3", "--reviewed-by", "Pascal")
    assert code == 0, out
    repo.commit("signoff")
    text = (repo.d / "SIGNOFF.toml").read_text()
    (repo.d / "SIGNOFF.toml").write_text(text.replace("[history]", 'exclude = ["gen/**"]\n\n[history]'))
    repo.commit("exclude gen for now")
    code, out = repo.cli("gc")
    assert code == 0 and "Nothing to delete" in out, out
