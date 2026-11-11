"""Edge cases of the git-based commands: diff parsing, subfolder roots, symlinks, attestations
that move, blame failures, shallow clones."""
import json
import os
import subprocess

import pytest

from aisignoff import visualize
from aisignoff.cli import main
from aisignoff.diff import _unquote, changed_lines
from aisignoff.project import Project, line_count

from test_aisignoff import write
from test_history import BASE_TOML, G3, commit, edit_lines, git, repo, result, shares  # noqa: F401


def report_data(path):
    html = path.read_text()
    return json.loads(html.split('<script type="application/json" id="data">')[1].split("</script>")[0])


# ------------------------------------------------------------------ diff parsing
def test_diff_content_lines_that_look_like_headers(repo):
    write(repo, "q.sql", "select 1;\n-- old comment\n")
    write(repo, "notes.txt", "a\n")
    base = commit(repo, "sql")
    write(repo, "q.sql", "select 1;\n")
    write(repo, "notes.txt", "a\n++ added\n")
    changes = changed_lines(repo, base)
    assert changes[("q.sql", "q.sql")] == ([2], [])
    assert changes[("notes.txt", "notes.txt")] == ([], [2])


def test_diff_paths_with_spaces_quotes_and_unicode(repo, capsys):
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "my file.py", "a\n")
    write(repo, 'über "x".py', "a\nb\n")
    write(repo, '日本"q".py', "a\n")
    commit(repo, "odd names", G3)
    write(repo, "my file.py", "a\nb\n")  # and a change in the working tree
    changes = changed_lines(repo, base)
    assert changes[(None, "my file.py")] == ([], [1, 2])
    assert changes[(None, 'über "x".py')] == ([], [1, 2])
    assert changes[(None, '日本"q".py')] == ([], [1])
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", base, "--files", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["files"] == 3 and data["total"]["added"] == 5


def test_unquote():
    assert _unquote('"a\\tb"') == "a\tb"
    assert _unquote('"\\303\\274ber \\"x\\".py"') == 'über "x".py'
    assert _unquote('"日本\\"q\\".py"') == '日本"q".py'
    assert _unquote("plain name") == "plain name"


def test_diff_renames_deletions_and_binary_files(repo):
    write(repo, "old.py", "".join(f"{i}\n" for i in range(20)))
    write(repo, "gone.py", "x\ny\n")
    (repo / "pic.png").write_bytes(b"\x89PNG\x00\x01")
    base = commit(repo, "files")
    git(repo, "mv", "old.py", "new.py")
    (repo / "new.py").write_text("".join(f"{i}\n" for i in range(20)) + "extra\n")
    (repo / "gone.py").unlink()
    (repo / "pic.png").write_bytes(b"\x89PNG\x00\x02")
    changes = changed_lines(repo, base)
    assert changes[("old.py", "new.py")] == ([], [21])
    assert changes[("gone.py", None)] == ([1, 2], [])
    assert changes[("pic.png", "pic.png")] == ([1], [1])


# ------------------------------------------------------------------ BASE behind HEAD's branch
def test_diff_and_since_start_from_the_merge_base(repo, capsys, tmp_path_factory):
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [1])
    commit(repo, "feature change")
    git(repo, "checkout", "-q", "main")
    write(repo, "other.py", "o\n")
    commit(repo, "main moves on")
    git(repo, "checkout", "-q", "feature")
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", "main", "--files", "--json", "-g", "G3", "-H", "H1", "-a", "A1",
                 "--assisted-by", "M", "--reviewed-by", "P", "--ai-reviewed-by", "M"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {r["name"] for r in data["rows"]} == {"solver.py"}  # other.py isn't this branch's change
    assert data["total"]["added"] == 1 and data["total"]["removed"] == 1
    assert data["base"] != data["base_tip"]
    assert data["total"]["levels_added"]["AI-Generation"] == {"G3": 1}
    lines = sum(p.lines for r in Project(repo).results() for p in r.parts)
    assert data["after"]["AI-Generation"]["G3"] == pytest.approx(100 / lines)  # only the branch's line is declared
    out = tmp_path_factory.mktemp("out") / "r.html"
    assert main(["--root", str(repo), "report", "--html", str(out), "--since", "main"]) == 0
    tree = report_data(out)["tree"]
    assert tree["changed_files"] == 1


def test_declare_off_the_first_parent_chain_is_not_applied(repo):
    from aisignoff.history import History
    from aisignoff.model import Declaration
    git(repo, "checkout", "-q", "-b", "side")
    edit_lines(repo, [2])
    side = commit(repo, "side")
    git(repo, "checkout", "-q", "main")
    edit_lines(repo, [5])
    commit(repo, "main")
    project = Project(repo)
    h = History(repo, project.config, Declaration.from_mapping({"AI-Generation": "G3"}, "x"), side)
    assert h.declared == {} and any("first-parent" in p for p in h.problems)


# ------------------------------------------------------------------ project root in a subfolder
@pytest.fixture
def nested(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    git(tmp_path, "config", "commit.gpgsign", "false")
    write(tmp_path, "paper/SIGNOFF.toml", BASE_TOML)
    write(tmp_path, "paper/a.py", "1\n2\n")
    write(tmp_path, "elsewhere.py", "e\n")
    commit(tmp_path, "initial")
    return tmp_path


def test_subfolder_root_diff_since_and_attest_at(nested, capsys, tmp_path_factory):
    root = nested / "paper"
    base = git(nested, "rev-parse", "HEAD")
    write(root, "a.py", "1\n2\n3\n")
    write(nested, "elsewhere.py", "e\nf\n")  # outside the project: not part of its change
    capsys.readouterr()
    assert main(["--root", str(root), "diff", base, "--files", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in data["rows"]] == ["a.py"]
    assert data["total"]["added"] == 1 and data["note"] is None
    assert data["before"]["AI-Generation"] == {"G0": 100.0}  # BASE's own SIGNOFF.toml was read
    out = tmp_path_factory.mktemp("out") / "r.html"
    assert main(["--root", str(root), "report", "--html", str(out), "--since", base]) == 0
    files = {c["name"]: c for c in report_data(out)["tree"]["children"]}
    assert files["a.py"]["changed"] == [[3, 3]]
    assert main(["--root", str(root), "attest", str(root / "a.py"), "-H", "H3", "--reviewed-by", "P", "--at", base]) == 0
    assert git(nested, "rev-parse", f"{base}:paper/a.py") in (root / "SIGNOFF.toml").read_text()


def test_subfolder_root_links_include_the_prefix(nested, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_SHA", "abc")
    assert visualize.report_meta(nested / "paper")["link"] == "https://github.com/o/r/blob/abc/paper/"


# ------------------------------------------------------------------ symlinks
def test_with_source_never_embeds_what_a_symlink_points_to(repo, tmp_path_factory, capsys):
    git(repo, "config", "http.extraheader", "AUTHORIZATION: basic SECRET-TOKEN")
    secret = tmp_path_factory.mktemp("outside") / "secret.txt"
    secret.write_text("OUTSIDE-SECRET\n")
    os.symlink(".git/config", repo / "gitcfg")
    os.symlink(str(secret), repo / "outside")
    commit(repo, "links", G3)
    out = tmp_path_factory.mktemp("out") / "r.html"
    assert main(["--root", str(repo), "report", "--html", str(out), "--with-source"]) == 0
    html = out.read_text()
    assert "SECRET-TOKEN" not in html and "OUTSIDE-SECRET" not in html
    files = {c["name"]: c for c in report_data(out)["tree"]["children"]}
    assert files["gitcfg"]["source_skipped"] == "symlink"
    r, _ = result(repo, "gitcfg")
    assert shares(r) == {"G3 H1 A1": 1}  # one unit, declared by its commit
    assert line_count(repo, "outside") == 1


# ------------------------------------------------------------------ attestations
def test_attestation_doesnt_spread_to_a_copy(repo):
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H3", "--reviewed-by", "P"]) == 0
    commit(repo, "attest")
    content = (repo / "solver.py").read_text()
    (repo / "solver.py").write_text(content + "unreviewed\n")
    commit(repo, "one more line")
    write(repo, "template_copy.py", content)
    commit(repo, "copy the old content")
    r, _ = result(repo)
    assert shares(r) == {"G0 H3 A0": 10, "G0 H2 A0": 1}


def test_attestation_follows_a_rename(repo, capsys):
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H3", "--reviewed-by", "P"]) == 0
    commit(repo, "attest")
    git(repo, "mv", "solver.py", "core_solver.py")
    r, project = result(repo, "core_solver.py")  # renamed, not committed yet
    assert project.history_problems == [] and shares(r) == {"G0 H3 A0": 10}
    commit(repo, "rename")
    r, project = result(repo, "core_solver.py")
    assert project.history_problems == [] and shares(r) == {"G0 H3 A0": 10}
    capsys.readouterr()
    assert main(["--root", str(repo), "lint"]) == 0


# ------------------------------------------------------------------ blame failures
def test_unresolvable_ignore_revs_entry_is_a_problem_not_uncommitted(repo, capsys):
    first = git(repo, "rev-parse", "HEAD")
    text = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", f'enabled = true\nrequire-trailers-since = "{first}"')
    (repo / "SIGNOFF.toml").write_text(text)
    commit(repo, "config", G3)
    edit_lines(repo, [7])
    commit(repo, "no trailers")
    write(repo, ".git-blame-ignore-revs", "# reformatting\ndeadbeef\n")
    r, project = result(repo)
    assert any("deadbeef" in p for p in project.history_problems)
    assert any("no AI-Generation trailer" in e for e in r.errors)  # still checked
    capsys.readouterr()
    assert main(["--root", str(repo), "lint"]) == 1


def test_ignore_revs_with_an_abbreviated_hash(repo):
    edit_lines(repo, [2])
    sha = commit(repo, "reformat", G3)
    write(repo, ".git-blame-ignore-revs", sha[:10] + "\n")
    r, project = result(repo)
    assert project.history_problems == []
    assert shares(r) == {"G0 H2 A0": 10}  # the reformatting commit is skipped


def test_missing_ignore_revs_file_is_a_problem(repo):
    text = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", 'enabled = true\nignore-revs-file = "nope"')
    (repo / "SIGNOFF.toml").write_text(text)
    _, project = result(repo)
    assert any("nope does not exist" in p for p in project.history_problems)


def test_corrections_apply_with_an_ignore_revs_file(repo):
    edit_lines(repo, [1])
    sha = commit(repo, "AI change")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha}"\nAI-Generation = "G3"\nAssisted-by = "M"\n')
    write(repo, ".git-blame-ignore-revs", "\n")
    r, _ = result(repo)
    assert shares(r) == {"G0 H2 A0": 9, "G3 H2 A0": 1}


# ------------------------------------------------------------------ shallow clones
def test_shallow_clone_fails_lint_when_trailers_are_required(repo, tmp_path_factory, capsys):
    first = git(repo, "rev-parse", "HEAD")
    text = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", f'enabled = true\nrequire-trailers-since = "{first}"')
    (repo / "SIGNOFF.toml").write_text(text)
    commit(repo, "config", G3)
    shallow = tmp_path_factory.mktemp("clone") / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)], check=True)
    capsys.readouterr()
    assert main(["--root", str(shallow), "lint"]) == 1
    assert "require-trailers-since is set, but this is a shallow clone" in capsys.readouterr().out


# ------------------------------------------------------------------ smaller things
def test_line_count_of_a_last_line_without_newline(tmp_path):
    write(tmp_path, "a.txt", "1\n2\n3")
    write(tmp_path, "b.txt", "")
    assert line_count(tmp_path, "a.txt") == 3 and line_count(tmp_path, "b.txt") == 1


def test_declare_leaves_override_files_alone(repo, capsys):
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write('\n[[annotations]]\npath = "vendor/**"\nprecedence = "override"\nAI-Generation = "G0"\n'
                'Human-Review = "H0"\nAI-Review = "A0"\nReviewed-by = "V"\n')
    commit(repo, "config", G3)
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "vendor/lib.py", "a\n")
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", base, "--json", "--files", "-H", "H3", "--reviewed-by", "P"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"]["levels_added"]["Human-Review"] == {"H0": 1}


def test_file_names_with_control_characters_are_escaped(repo, capsys):
    name = "bad\n::warning title=forged::Injected"
    write(repo, name, "x\n")
    (repo / "SIGNOFF.toml").write_text(BASE_TOML.replace('path = "**"', 'path = "solver.py"'))
    capsys.readouterr()
    assert main(["--root", str(repo), "lint"]) == 1
    out = capsys.readouterr().out
    assert "bad\\n::warning" in out and not any(line.startswith("::") for line in out.splitlines())


def test_title_with_the_data_placeholder(repo):
    tree = visualize.build_tree(repo, Project(repo).results())
    html = visualize.render_html(tree, visualize.report_meta(repo, title="x __AISIGNOFF_DATA__ y"))
    assert "<title>AI signoff · x __AISIGNOFF_DATA__ y</title>" in html


def test_pr_diff_example_reads_the_trailers_of_the_description(tmp_path):
    """The PR-body parser of examples/workflows/signoff-pr-diff.yml, run as the workflow runs it."""
    from pathlib import Path
    workflow = (Path(__file__).parent.parent / "examples/workflows/signoff-pr-diff.yml").read_text()
    block = workflow.split("<<'PY'\n")[1].split("          PY\n")[0]
    script = tmp_path / "parse.py"
    script.write_text("\n".join(line[10:] for line in block.splitlines()))

    def options(body):
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"body": body}}))
        r = subprocess.run(["python3", str(script), str(event)], capture_output=True, text=True, check=True)
        return r.stdout.splitlines(), r.stderr

    out, _ = options("Intro\n\nHuman-Review: H3 in prose\n\n```\nAI-Review: A3\n```\n\n"
                     "AI-Generation: G3\nHuman-Review: H1\nAssisted-by: -odd name\n")
    assert sorted(out) == ["--assisted-by=-odd name", "--generation=G3", "--human=H1"]
    out, err = options("x\n\nAI-Generation: G2 (mostly)\nHuman-Review: H1\nAI-Review: TODO\n")
    assert out == ["--human=H1"] and "::warning::" in err
    out, err = options("x\n\nAI-Generation: G2\nAI-Generation: G3\n")
    assert out == [] and "conflicting" in err
    out, _ = options(TEMPLATE.format(a2=" ", model=""))
    assert sorted(out) == ["--ai-reviewed-by=Claude Opus (Anthropic), self-check by the generating session",
                           "--ai-reviewed-by=Some Model 2, self-check by the generating session", "--ai=A1",
                           "--assisted-by=Claude Opus (Anthropic)", "--assisted-by=Some Model 2", "--generation=G3",
                           "--human=H1"]  # no author in this event, so no --reviewed-by
    out, err = options(TEMPLATE.format(a2=" ", model="") + "\nHuman-Review: H2\nReviewed-by: Max\n")
    assert out == [] and "both" in err


def test_examples_pin_the_current_version():
    import re
    from pathlib import Path
    from aisignoff import __version__
    top = Path(__file__).parent.parent
    for f in sorted((top / "examples/workflows").glob("*.yml")):
        assert f'AISIGNOFF_VERSION: "{__version__}"' in f.read_text(), f.name
    hook = (top / "examples/pre-commit-config.yaml").read_text()
    assert f"rev: v{__version__}" in hook and f"aisignoff=={__version__}" in hook
    assert f"rev: v{__version__}" in (top / "docs/integration.md").read_text()
    assert re.search(r'^version = "' + re.escape(__version__) + '"', (top / "pyproject.toml").read_text(), re.M)


# ------------------------------------------------------------------ pull request checkboxes
TEMPLATE = """Add a thing (#7)

Some description.

## Checklist

- [x] Tests pass locally (`pytest`), and new behaviour is covered by
tests
- [x] I take responsibility for this change, however it was created

## AI declaration

Generation (tick exactly one: the highest level of any substantial part):
- [ ] **G0** Written by a human, without AI
- [ ] **G2** AI-generated: AI wrote substantial parts, a human directed
the work and edited the result
- [x] **G3** AI-autonomous: an agent produced it largely end to end

AI models that wrote parts of it (G1-G3, tick all that apply):
- [x] **Claude Opus** (Anthropic)
- [ ] **GPT Sol** (OpenAI)
- [x] **Other:** Some Model 2

Human review (at least H0 is required; the levels build on each other):
- [x] **H0** I checked the result as a whole
- [x] **H1** I ran the tests or reproduced the key results myself, and
read the important parts
- [ ] **H2** I read every changed line

AI review (leave all unticked for A0):
- [x] **A1** The AI that wrote the change checked its own work
- [{a2}] **A2** A new AI session, without the generating conversation,
reviewed the final change and ran the tests. Model, if not one of the
above: {model}
- [ ] **A3** A different model reviewed it. Model:
"""


def test_parse_checkboxes():
    from aisignoff.history import parse_checkboxes
    pieces = parse_checkboxes(TEMPLATE.format(a2=" ", model=""), "Jane <j@x>", "commit abc")
    assert {i: p.level for i, p in pieces.items()} == {0: "G3", 1: "H1", 2: "A1"}
    assert pieces[0].names == ("Claude Opus (Anthropic)", "Some Model 2")
    assert pieces[1].names == ("Jane <j@x>",)
    assert pieces[2].names[0] == "Claude Opus (Anthropic), self-check by the generating session"
    pieces = parse_checkboxes(TEMPLATE.format(a2="x", model="GPT Sol (OpenAI), fresh session"), "J", "c")
    assert pieces[2].level == "A2" and pieces[2].names == ("GPT Sol (OpenAI), fresh session",)
    assert parse_checkboxes("Fix\n\n- [x] done\n- [ ] **G3** not ticked\n", "J", "c") == {}
    two = parse_checkboxes("- [x] **G2** a\n- [x] **G3** b\n- [x] **Claude Opus** (Anthropic)\n", "J", "c")
    assert two[0].level == "G3" and two[0].problems


def test_squash_commit_with_checkboxes_declares_its_lines(repo):
    edit_lines(repo, [2, 3])
    commit(repo, TEMPLATE.format(a2=" ", model=""))
    r, project = result(repo)
    assert shares(r) == {"G0 H2 A0": 8, "G3 H1 A1": 2} and r.errors == []
    part = next(p for p in r.parts if p.declaration.short() == "G3 H1 A1")
    assert part.declaration.reviewed_by == ("T <t@example.com>",)
    assert "pull request checkboxes" in part.declaration.source
    edit_lines(repo, [5], text="again")
    commit(repo, TEMPLATE.format(a2=" ", model=""), "Human-Review: H2\nReviewed-by: Max")  # both: one or the other
    r, project = result(repo)
    assert any(e.startswith("line 5:") and "both as trailers and as ticked checkboxes" in e for e in r.errors)


def test_small_branch_commits_inherit_the_rest_from_the_merge(repo):
    """A hand-written commit declares only what it knows (G0, H2); the merge of the pull request,
    reviewed as a whole by a fresh AI session, adds the AI review."""
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [4])
    commit(repo, "by hand", "AI-Generation: G0\nHuman-Review: H2\nReviewed-by: Pascal")
    edit_lines(repo, [9], text="ai")
    commit(repo, "AI part")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "feature", "-m",
        "Merge feature\n\n" + TEMPLATE.format(a2="x", model="GPT Sol (OpenAI), fresh session"))
    r, _ = result(repo)
    by_line = {n: p for p in r.parts for a, b in p.runs for n in range(a, b + 1)}
    assert by_line[4].declaration.short() == "G0 H2 A2" and by_line[4].errors == []
    assert by_line[4].kinds == ("branch", "branch", "commit")
    assert by_line[9].declaration.short() == "G3 H1 A2"
