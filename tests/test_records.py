"""Who writes what: SIGNOFF.toml is the file a person signs off, the review folder the AI side, whose
record files can only make a declaration stricter. Records that cover no line any more are no error,
and 'aisignoff gc' deletes them."""
import pytest

from aisignoff.cli import main, remove_tables
from aisignoff.config import ConfigError, load

from test_aisignoff import write
from test_history import commit, edit_lines, git, repo, result  # noqa: F401

G1 = ("AI-Generation: G1\nAssisted-by: Model A\nHuman-Review: H2\nReviewed-by: Jane\nAI-Review: A0\n")


def generations(root, path="solver.py"):
    r, project = result(root, path)
    out = {}
    for p in r.parts:
        for a, b in p.runs:
            for n in range(a, b + 1):
                out[n] = p.declaration.generation
    return [out[n] for n in sorted(out)], project


def lint(root, capsys, *args):
    capsys.readouterr()
    code = main(["--root", str(root), "lint", *args])
    return code, capsys.readouterr().out


def raise_to_g3(sha, model="Claude Opus 5.5 (Anthropic)"):
    return f'[[commits]]\ncommit = "{sha}"\nAI-Generation = "G3"\nAssisted-by = "{model}"\n'


def test_a_record_file_raises_the_generation_of_a_commit(repo):
    edit_lines(repo, [2, 3])
    sha = commit(repo, "said G1", G1)
    write(repo, "reviews/g3.toml", raise_to_g3(sha))
    commit(repo, "it was G3")
    got, project = generations(repo)
    assert got[1:3] == ["G3", "G3"] and got[0] == "G0"
    assert project.history_problems == []


def test_a_generation_a_person_gives_wins(repo):
    edit_lines(repo, [2, 3])
    sha = commit(repo, "said G1", G1)
    write(repo, "SIGNOFF.toml", (repo / "SIGNOFF.toml").read_text()
          + f'\n[[commits]]\ncommit = "{sha}"\nAI-Generation = "G1"\nAssisted-by = "Model A"\n')
    write(repo, "reviews/g3.toml", raise_to_g3(sha))
    commit(repo, "a person says G1, an agent G3")
    got, project = generations(repo)
    assert got[1:3] == ["G1", "G1"]
    assert any("SIGNOFF.toml gives the generation" in n for n in project.history_notes)


@pytest.mark.parametrize("entry, message", [
    ('AI-Generation = "G1"\nAssisted-by = "M"\n', "can only raise a commit's generation"),
    ('AI-Generation = "G0"\n', "can only raise a commit's generation"),
    ('AI-Generation = "G3"\nAssisted-by = "M"\nHuman-Review = "H3"\nReviewed-by = "Jane"\n', "a person's word"),
    ('AI-Generation = "G3"\n', "needs Assisted-by"),
])
def test_record_files_never_speak_for_a_person(repo, entry, message):
    sha = git(repo, "rev-parse", "HEAD")
    write(repo, "reviews/x.toml", f'[[commits]]\ncommit = "{sha}"\n' + entry)
    with pytest.raises(ConfigError, match=message):
        load(repo)


def test_an_attestation_of_a_deleted_file_is_no_error(repo, capsys):
    write(repo, "other.py", "a\nb\n")
    commit(repo, "other")
    write(repo, "reviews/r.md", "# review\n")
    assert main(["--root", str(repo), "attest", str(repo / "other.py"), "-a", "A2", "--findings", "none",
                 "--ai-reviewed-by", "GPT Sol (OpenAI), reviews/r.md", "--to", str(repo / "reviews/r.toml")]) == 0
    commit(repo, "review")
    code, out = lint(repo, capsys)
    assert code == 0 and "cover no line" not in out
    git(repo, "rm", "-q", "other.py")
    commit(repo, "delete other.py")
    code, out = lint(repo, capsys)
    assert code == 0, out  # the review folder is add-only: an error here could never be fixed
    assert "1 record(s) cover no line any more: reviews/r.toml" in out
    # a path that never existed is still a mistake
    write(repo, "reviews/s.toml", f'[[attestations]]\npath = "nothere.py"\nblob = "{"a" * 40}"\nAI-Review = "A2"\n'
          'AI-Reviewed-by = "GPT Sol (OpenAI), reviews/r.md"\nAI-Review-Findings = "none"\n')
    code, out = lint(repo, capsys)
    assert code == 1 and "nothere.py does not exist" in out


def test_gc_deletes_what_covers_no_line(repo, capsys):
    edit_lines(repo, [2])
    gone = commit(repo, "line 2", G1)
    edit_lines(repo, [5])
    kept = commit(repo, "line 5", G1)
    write(repo, "SIGNOFF.toml", (repo / "SIGNOFF.toml").read_text()
          + f'\n[[commits]]   # line 2\ncommit = "{gone}"\nHuman-Review = "H3"\nReviewed-by = "Jane"\n'
          + f'\n# line 5, still there\n[[commits]]\ncommit = "{kept}"\nHuman-Review = "H3"\nReviewed-by = "Jane"\n')
    write(repo, "reviews/gone.toml", raise_to_g3(gone))
    write(repo, "reviews/both.toml", raise_to_g3(gone) + "\n" + raise_to_g3(kept))
    commit(repo, "records")
    edit_lines(repo, [2], "rewritten")
    commit(repo, "line 2 again", G1)
    before, _ = generations(repo)
    capsys.readouterr()
    assert main(["--root", str(repo), "gc", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"would delete SIGNOFF.toml [[commits]] entry 1 ({gone[:7]})" in out and "would delete reviews/gone.toml" in out
    assert "both.toml" not in out  # one of its entries still covers a line: the file stays as it was
    assert (repo / "reviews/gone.toml").exists()
    assert main(["--root", str(repo), "gc"]) == 0
    text = (repo / "SIGNOFF.toml").read_text()
    assert gone not in text and kept in text and "# line 5, still there" in text
    assert not (repo / "reviews/gone.toml").exists() and (repo / "reviews/both.toml").exists()
    assert generations(repo)[0] == before
    capsys.readouterr()
    assert main(["--root", str(repo), "gc"]) == 0
    assert "Nothing to delete" in capsys.readouterr().out


def _pull_request(repo, capsys, body_text):
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "preview")
    body = write(repo.parent, "body.md", body_text)
    return lint(repo, capsys, "--declare-from", str(body), "--base", "HEAD^1")


@pytest.mark.parametrize("dead", [True, False])
def test_a_change_may_delete_a_record_file_that_covers_no_line(repo, capsys, dead):
    edit_lines(repo, [2])
    sha = commit(repo, "line 2", G1)
    write(repo, "reviews/g3.toml", raise_to_g3(sha))
    commit(repo, "record")
    if dead:
        edit_lines(repo, [2], "rewritten")
        commit(repo, "line 2 again", G1)
    git(repo, "checkout", "-q", "-b", "pr")
    git(repo, "rm", "-q", "reviews/g3.toml")
    commit(repo, "gc")
    code, out = _pull_request(repo, capsys, "Delete records that cover no line.\n")
    if dead:
        assert code == 0, out
        assert "it is a review" in out
    else:
        assert code == 1 and "the change deletes reviews/g3.toml" in out


def test_attest_writes_an_ai_review_into_the_review_folder(repo, capsys):
    write(repo, "reviews/r.md", "# review\n")
    commit(repo, "report")
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-a", "A2", "--findings", "none",
                 "--ai-reviewed-by", "GPT Sol (OpenAI), reviews/r.md"]) == 0
    files = sorted(p.name for p in (repo / "reviews").glob("*.toml"))
    assert len(files) == 1 and files[0].endswith("-solver.toml")
    assert "AI-Reviewed-by" not in (repo / "SIGNOFF.toml").read_text()
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-a", "A2", "--findings", "none",
                 "--ai-reviewed-by", "GPT Sol (OpenAI), reviews/r.md"]) == 0
    assert len(list((repo / "reviews").glob("*-solver-2.toml"))) == 1  # a new file, never an existing one
    # a person's review, and an AI review a person records with --signoff, go into SIGNOFF.toml
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H3", "--reviewed-by", "Jane"]) == 0
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-a", "A1", "--findings", "none",
                 "--ai-reviewed-by", "Model B", "--signoff"]) == 0
    text = (repo / "SIGNOFF.toml").read_text()
    assert 'Human-Review = "H3"' in text and 'AI-Review = "A1"' in text


def test_correct_writes_each_side_where_it_belongs(repo, capsys):
    edit_lines(repo, [2])
    sha = commit(repo, "line 2", G1)
    assert main(["--root", str(repo), "correct", sha[:7], "-g", "G3", "--assisted-by", "Model A"]) == 0
    [record] = list((repo / "reviews").glob("*.toml"))
    assert f'commit = "{sha}"' in record.read_text() and sha not in (repo / "SIGNOFF.toml").read_text()
    assert main(["--root", str(repo), "correct", sha[:7], "-H", "H3", "--reviewed-by", "Jane"]) == 0
    assert 'Human-Review = "H3"' in (repo / "SIGNOFF.toml").read_text()
    assert main(["--root", str(repo), "correct", sha[:7], "-g", "G1", "--assisted-by", "M",
                 "--to", str(repo / "reviews/x.toml")]) == 2
    assert "a person's correction goes into SIGNOFF.toml" in capsys.readouterr().err
    commit(repo, "corrections")
    assert generations(repo)[0][1] == "G3"


def test_remove_tables_keeps_the_comments_of_the_next_table():
    text = ('version = 4\n\n[[commits]]   # one\ncommit = "aaaa"\nHuman-Review = "H1"\n\n# about two\n'
            '[[commits]]\ncommit = "bbbb"\nHuman-Review = "H1"\n\n[[attestations]]\npath = "x"\n')
    out = remove_tables(text, "commits", {1})
    assert out == ('version = 4\n\n# about two\n[[commits]]\ncommit = "bbbb"\nHuman-Review = "H1"\n\n'
                   '[[attestations]]\npath = "x"\n')
    assert remove_tables(text, "attestations", {1}).endswith('Human-Review = "H1"\n')
