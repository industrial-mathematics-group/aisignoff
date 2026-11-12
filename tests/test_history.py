"""Line-level declarations from git history ([history] in SIGNOFF.toml)."""
import json
import subprocess

import pytest

from aisignoff import visualize
from aisignoff.cli import main
from aisignoff.config import ConfigError, load
from aisignoff.history import format_runs, parse_trailers
from aisignoff.project import Project

from test_aisignoff import write

BASE_TOML = ('version = 3\n\n[history]\nenabled = true\n\n[[annotations]]\npath = "**"\n'
             'AI-Generation = "G0"\nHuman-Review = "H2"\nAI-Review = "A0"\nReviewed-by = "Jane"\n')
G3 = ("AI-Generation: G3\nHuman-Review: H1\nAI-Review: A1\nAssisted-by: Model A\n"
      "AI-Reviewed-by: Model A, self-check\nReviewed-by: Jane\n")


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(root, message, trailers=""):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message + ("\n\n" + trailers if trailers else ""))
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    git(tmp_path, "config", "commit.gpgsign", "false")
    write(tmp_path, "SIGNOFF.toml", BASE_TOML)
    write(tmp_path, "solver.py", "".join(f"line {i}\n" for i in range(1, 11)))
    commit(tmp_path, "initial, by hand")  # no trailers: the annotation is the fallback
    return tmp_path


def result(root, path="solver.py"):
    project = Project(root)
    return next(r for r in project.results() if r.path == path), project


def shares(r):
    return {p.declaration.short(): p.lines for p in r.parts}


def edit_lines(root, numbers, text="new", path="solver.py"):
    lines = (root / path).read_text().splitlines()
    for n in numbers:
        lines[n - 1] = f"{text} {n}"
    (root / path).write_text("\n".join(lines) + "\n")


def test_without_trailers_the_file_level_declaration_applies(repo):
    r, project = result(repo)
    assert project.history_used
    assert shares(r) == {"G0 H2 A0": 10} and r.errors == []
    assert r.parts[0].kinds == ("file", "file", "file")


def test_lines_take_the_declaration_of_their_commit(repo):
    edit_lines(repo, [3, 4, 5])
    sha = commit(repo, "AI rewrite", G3)
    r, _ = result(repo)
    assert shares(r) == {"G0 H2 A0": 7, "G3 H1 A1": 3}
    ai = next(p for p in r.parts if p.declaration.generation == "G3")
    assert ai.runs == [[3, 5]] and ai.declaration.source.startswith(f"commit {sha[:7]}")
    assert ai.declaration.assisted_by == ("Model A",)


def test_an_attestation_reviews_the_whole_file_but_not_later_changes(repo):
    edit_lines(repo, [3, 4, 5])
    commit(repo, "AI rewrite", G3)
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H2", "--reviewed-by", "Pascal"]) == 0
    commit(repo, "attest solver.py")
    r, _ = result(repo)
    assert shares(r) == {"G0 H2 A0": 7, "G3 H2 A1": 3}  # generation stays, the review is raised
    assert any(p.declaration.reviewed_by == ("Pascal",) for p in r.parts)
    edit_lines(repo, [9])
    commit(repo, "one more AI line", G3)
    r, _ = result(repo)
    assert shares(r) == {"G0 H2 A0": 6, "G3 H2 A1": 3, "G3 H1 A1": 1}


def test_an_attestation_before_its_commit_covers_the_working_tree(repo):
    edit_lines(repo, [1])  # uncommitted: falls back to the annotation, then the attestation covers it
    main(["--root", str(repo), "attest", str(repo / "solver.py"), "-a", "A2", "--ai-reviewed-by", "Model B"])
    r, project = result(repo)
    assert project.history_problems == []
    assert shares(r) == {"G0 H2 A2": 10}


def test_an_attestation_of_content_that_never_landed_is_a_problem(repo, capsys):
    edit_lines(repo, [1])
    main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H3", "--reviewed-by", "P"])
    edit_lines(repo, [2])  # changed again after attesting, before committing
    commit(repo, "changed after review", G3)
    _, project = result(repo)
    assert any("neither in the history" in p for p in project.history_problems)
    assert main(["--root", str(repo), "lint"]) == 1
    assert "run 'aisignoff attest' again" in capsys.readouterr().out


def test_attest_at_an_earlier_commit(repo):
    first = git(repo, "rev-parse", "HEAD")
    edit_lines(repo, [1, 2])
    commit(repo, "AI", G3)
    main(["--root", str(repo), "attest", str(repo / "solver.py"), "--at", first, "-H", "H3", "--reviewed-by", "P"])
    r, _ = result(repo)
    assert shares(r) == {"G0 H3 A0": 8, "G3 H1 A1": 2}


def test_attest_needs_a_level_and_no_todo(repo, capsys):
    assert main(["--root", str(repo), "attest", str(repo / "solver.py")]) == 2
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "TODO"]) == 2
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H2"]) == 2  # no Reviewed-by
    assert "Reviewed-by" in capsys.readouterr().err


def test_commits_entry_corrects_a_commit(repo):
    edit_lines(repo, [2])
    sha = commit(repo, "AI", G3.replace("Human-Review: H1", "Human-Review: TODO"))
    r, _ = result(repo)
    assert any("TODO" in e for e in r.errors) and r.errors[0].startswith("line 2: ")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha[:7]}"\nHuman-Review = "H2"\nReviewed-by = "Jane"\n')
    r, _ = result(repo)
    assert r.errors == [] and shares(r) == {"G0 H2 A0": 9, "G3 H2 A1": 1}


def test_merge_commit_declares_the_branch_and_its_commits_override(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [6])
    commit(repo, "AI on a branch", "AI-Generation: G2\nAssisted-by: Model A\nAI-Review: A1\nAI-Reviewed-by: Model A")
    edit_lines(repo, [8], text="hand")
    commit(repo, "by hand, no declaration")
    git(repo, "checkout", "-q", "main")
    edit_lines(repo, [1], text="main")
    commit(repo, "main moves on", G3)
    git(repo, "merge", "-q", "--no-ff", "feature", "-m",
        "Merge feature\n\n" + G3.replace("Human-Review: H1", "Human-Review: H3").replace("Reviewed-by: Jane", "Reviewed-by: Rita"))
    r, _ = result(repo)
    by_line = {n: p for p in r.parts for a, b in p.runs for n in range(a, b + 1)}
    # the commit that wrote line 6 declares generation; reviews take the highest level (on a tie the
    # later declaration, the merge's)
    assert by_line[6].declaration.short() == "G2 H3 A1" and by_line[6].kinds == ("branch", "commit", "commit")
    # a branch commit without a declaration takes the merge's (the pull request's) levels
    assert by_line[8].declaration.short() == "G3 H3 A1" and by_line[8].kinds == ("commit", "commit", "commit")
    # main's own commit since the branch point, and lines from before it, aren't the merge's
    assert by_line[1].declaration.short() == "G3 H1 A1"
    assert by_line[2].declaration.short() == "G0 H2 A0"


def test_rebased_commits_declare_themselves(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [3])
    commit(repo, "declared", G3)
    edit_lines(repo, [4])
    commit(repo, "not declared")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "feature")  # what a rebase merge leaves on main: the commits, no merge
    r, _ = result(repo)
    by_line = {n: p for p in r.parts for a, b in p.runs for n in range(a, b + 1)}
    assert by_line[3].declaration.short() == "G3 H1 A1"
    assert by_line[4].declaration.short() == "G0 H2 A0"  # the file-level fallback


def test_require_trailers_since(repo):
    first = git(repo, "rev-parse", "HEAD")
    text = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", f'enabled = true\nrequire-trailers-since = "{first}"')
    (repo / "SIGNOFF.toml").write_text(text)
    commit(repo, "config", G3)  # SIGNOFF.toml lines are declared by this commit
    edit_lines(repo, [7])
    sha = commit(repo, "no trailers")
    r, _ = result(repo)
    assert any(f"commit {sha[:7]}" in e and "declares no AI-Generation" in e for e in r.errors)
    assert not any(e.endswith("missing AI-Generation") for e in r.errors)
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [7])
    commit(repo, "no trailers, on a pull request")
    r, _ = result(repo)
    assert r.errors == []  # not on the default branch yet: the pull request will declare it
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "Merge pr")  # landed without a declaration
    r, _ = result(repo)
    assert any("Merge pr" in e and "declares no Human-Review" in e for e in r.errors)


def test_override_annotations_and_binary_files(repo):
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write('\n[[annotations]]\npath = "vendor/**"\nprecedence = "override"\nAI-Generation = "G0"\n'
                'Human-Review = "H0"\nAI-Review = "A0"\nReviewed-by = "V"\n')
    write(repo, "vendor/lib.py", "a\nb\n")
    (repo / "image.png").write_bytes(b"\x89PNG\x00\x01\x02")
    commit(repo, "vendor and image", G3)
    project = Project(repo)
    by_path = {r.path: r for r in project.results()}
    assert by_path["vendor/lib.py"].parts is None and by_path["vendor/lib.py"].declaration.human == "H0"
    assert shares(by_path["image.png"]) == {"G3 H1 A1": 1}


def test_trailers():
    pieces = parse_trailers("AI-Generation: G2\nReviewed-by: Jane\nAssisted-by: M\nai-review: A1\n", "commit x")
    assert set(pieces) == {0, 2}  # Reviewed-by without Human-Review declares nothing
    assert pieces[0].names == ("M",) and pieces[2].names == ()
    conflict = parse_trailers("AI-Generation: G2\nAI-Generation: G3\n", "commit x")
    assert conflict[0].problems
    assert format_runs([[1, 3], [5, 5]]) == "lines 1-3, 5" and format_runs([[4, 4]]) == "line 4"


def test_history_falls_back_outside_git_and_in_shallow_clones(tmp_path_factory, repo, capsys):
    tmp_path = tmp_path_factory.mktemp("elsewhere")
    write(tmp_path / "plain", "SIGNOFF.toml", BASE_TOML)
    write(tmp_path / "plain", "a.py", "x\n")
    project = Project(tmp_path / "plain")
    assert project.results()[0].parts is None and not project.history_used
    assert "not a git work tree" in capsys.readouterr().err
    edit_lines(repo, [1])
    commit(repo, "second")
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)], check=True)
    project = Project(shallow)
    assert project.results()[0].parts is None
    assert "shallow clone" in capsys.readouterr().err


def test_config_validation(tmp_path):
    bad = {
        '[history]\nenabled = "yes"\n': "'enabled' must be true or false",
        '[history]\nfoo = 1\n': "unknown key",
        '[[commits]]\ncommit = "xyz"\nHuman-Review = "H1"\n': "commit hash",
        '[[commits]]\ncommit = "abcd"\nReviewed-by = "J"\n': "declare at least one level",
        '[[attestations]]\npath = "a/*.py"\nblob = "' + "a" * 40 + '"\nHuman-Review = "H1"\n': "no glob",
        '[[attestations]]\npath = "a.py"\nblob = "abc"\nHuman-Review = "H1"\n': "full git blob hash",
        '[[attestations]]\npath = "a.py"\nblob = "' + "a" * 40 + '"\nHuman-Review = "H9"\n': "invalid Human-Review",
    }
    for text, message in bad.items():
        write(tmp_path, "SIGNOFF.toml", "version = 3\n" + text)
        with pytest.raises(ConfigError, match=message):
            load(tmp_path)


def test_report_badge_tree_and_html_count_lines(repo, tmp_path, capsys):
    edit_lines(repo, [3, 4, 5])
    commit(repo, "AI rewrite", G3)
    capsys.readouterr()
    assert main(["--root", str(repo), "report"]) == 0
    out = capsys.readouterr().out
    assert "declared line by line" in out and "G3" in out
    assert main(["--root", str(repo), "report", "--json"]) == 0
    data = {r["path"]: r for r in json.loads(capsys.readouterr().out)["files"]}
    assert sum(p["lines"] for p in data["solver.py"]["parts"]) == 10
    assert main(["--root", str(repo), "badge", "--out", str(tmp_path / "b"), "--weight", "lines"]) == 0
    badge = json.loads((tmp_path / "b" / "aisignoff-generation.json").read_text())
    assert "G3" in badge["message"] and "G0" in badge["message"]
    project = Project(repo)
    tree = visualize.build_tree(project.root, project.results())
    leaf = next(c for c in tree["children"] if c["name"] == "solver.py")
    assert leaf["counts"]["AI-Generation"]["lines"] == {"G0": 7, "G3": 3}
    assert leaf["counts"]["AI-Generation"]["files"] == pytest.approx({"G0": 0.7, "G3": 0.3})
    assert "G0 70% · G3 30%" in visualize.render_text(tree, "lines", files=True)
    assert '"parts"' in visualize.render_html(tree, visualize.report_meta(repo))


def test_diff_shows_added_and_removed_lines(repo, capsys):
    base = git(repo, "rev-parse", "HEAD")
    edit_lines(repo, [3, 4])
    write(repo, "src/new.py", "a\nb\nc\n")
    commit(repo, "AI change", G3)
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", base, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"]["added"] == 5 and data["total"]["removed"] == 2
    assert data["total"]["levels_added"]["AI-Generation"] == {"G3": 5}
    assert data["total"]["levels_removed"]["AI-Generation"] == {"G0": 2}
    assert {r["name"] for r in data["rows"]} == {".", "src/"}
    assert data["after"]["AI-Generation"]["G3"] > data["before"].get("AI-Generation", {}).get("G3", 0)
    assert main(["--root", str(repo), "diff", base, "--markdown"]) == 0
    md = capsys.readouterr().out
    assert "| `src/` | +3 | −0 | G3 +3 |" in md
    assert git(repo, "worktree", "list").count("\n") == 0  # the temporary worktree is gone


def test_diff_declare_fills_uncommitted_lines(repo, capsys):
    base = git(repo, "rev-parse", "HEAD")
    edit_lines(repo, [1])  # not committed: no trailers yet, as in a pull request before the merge
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", base, "--json", "-g", "G2", "--assisted-by", "M",
                 "-a", "A1", "--ai-reviewed-by", "M"]) == 0
    data = json.loads(capsys.readouterr().out)
    # a declaration that leaves out an axis doesn't take it from the file: it is missing
    assert data["total"]["levels_added"]["AI-Generation"] == {"undeclared": 1}
    assert main(["--root", str(repo), "diff", base, "--json", "-g", "G2", "--assisted-by", "M", "-H", "H1",
                 "--reviewed-by", "R", "-a", "A1", "--ai-reviewed-by", "M"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"]["levels_added"]["AI-Generation"] == {"G2": 1}
    assert data["total"]["levels_added"]["Human-Review"] == {"H1": 1}
    assert main(["--root", str(repo), "diff", "nope"]) == 2


def test_diff_lists_new_attestations(repo, capsys):
    base = git(repo, "rev-parse", "HEAD")
    main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H3", "--reviewed-by", "P"])
    commit(repo, "attest")
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", base]) == 0
    out = capsys.readouterr().out
    assert "Attested:" in out and "solver.py  H3" in out
    assert "Human review: H2 " in out and "H3" in out


def test_html_report_with_source_and_since(repo, tmp_path_factory, capsys):
    base = git(repo, "rev-parse", "HEAD")
    edit_lines(repo, [3, 4])
    (repo / "image.png").write_bytes(b"\x89PNG\x00\x01")
    commit(repo, "AI change", G3)
    write(repo, "notes.md", "a\nb\n")  # untracked: added in full
    out = tmp_path_factory.mktemp("out") / "report.html"
    assert main(["--root", str(repo), "report", "--html", str(out), "--with-source", "--since", base]) == 0
    html = out.read_text()
    data = json.loads(html.split('<script type="application/json" id="data">')[1].split("</script>")[0])
    assert data["meta"]["since"] == {"name": base, "commit": base}
    files = {c["name"]: c for c in data["tree"]["children"]}
    solver = files["solver.py"]
    assert solver["source"].startswith("line 1\nline 2\nnew 3\n")
    assert solver["changed"] == [[3, 4]] and solver["added"] == 2 and solver["removed"] == 2
    assert [p["runs"] for p in solver["parts"]] == [[[1, 2], [5, 10]], [[3, 4]]]
    assert files["image.png"]["source_skipped"] == "binary"
    assert files["notes.md"]["changed"] == [[1, 2]]
    assert data["tree"]["added"] == 2 + 1 + 2 and data["tree"]["changed_files"] == 3
    assert "Changed since" in html and "drawLines" in html


def test_html_report_options_need_html(repo, capsys):
    assert main(["--root", str(repo), "report", "--with-source"]) == 2
    assert main(["--root", str(repo), "report", "--html", "x.html", "--since", "nope"]) == 2
    assert "not a commit" in capsys.readouterr().err


def test_json_outputs_carry_the_format_version(repo, capsys):
    from aisignoff import __version__
    from aisignoff.cli import JSON_FORMAT
    base = git(repo, "rev-parse", "HEAD")
    edit_lines(repo, [3])
    commit(repo, "AI change", G3)
    for args in (["report", "--json"], ["report", "--tree", "--json"], ["diff", base, "--json"]):
        capsys.readouterr()
        assert main(["--root", str(repo), *args]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["format"] == JSON_FORMAT == 1 and data["aisignoff"] == __version__, args
