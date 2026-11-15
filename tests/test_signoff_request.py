"""examples/workflows/signoff-request.yml: the script that turns the issue form into a SIGNOFF.toml change,
run as the workflow runs it (in its dry-run mode, which prints the GitHub API calls instead of making them)."""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

TOP = Path(__file__).parent.parent
pytestmark = pytest.mark.skipif(shutil.which("aisignoff") is None, reason="needs the aisignoff command")

TEMPLATE = """## What does this PR change?

<!-- Short description. -->

Closes #

## AI declaration

<!-- Tick what applies.
     Opened by a bot? Add a line "Responsible person: @login" below this comment. -->

- [ ] **G0** Written by a human, without AI
- [ ] **G1** AI-assisted
- [ ] **H0** I checked the result as a whole
- [ ] **A0** No independent AI review
- [ ] **A1** A new AI session, without the generating conversation, checked the change
"""


def script() -> str:
    workflow = (TOP / "examples/workflows/signoff-request.yml").read_text(encoding="utf-8")
    code = workflow.split("python3 - <<'PY'\n", 1)[1].rsplit("\n          PY\n", 1)[0]
    return textwrap.dedent(code)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def checkout(tmp_path):
    """A repository with SIGNOFF.toml and a PR template, cloned from a bare 'origin' as actions/checkout would."""
    src = tmp_path / "src"
    (src / "results").mkdir(parents=True)
    (src / "results/fit.csv").write_text("a,b\n1,2\n")
    (src / "README.md").write_text("# x\n")
    (src / ".github").mkdir()
    (src / ".github/pull_request_template.md").write_text(TEMPLATE)
    (src / "SIGNOFF.toml").write_text('version = 4\n\n[[annotations]]\npath = "**"\nAI-Generation = "G0"\n'
                                      'Human-Review = "H1"\nAI-Review = "A0"\nReviewed-by = "Jane Doe"\n')
    git(tmp_path, "init", "-q", "-b", "main", str(src))
    git(src, "add", "-A")
    git(src, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "-m", "start")
    git(tmp_path, "clone", "-q", "--bare", str(src), str(tmp_path / "origin.git"))
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(tmp_path / "work"))
    return tmp_path


def form(**answers):
    labels = {"kind": "What should be recorded?", "paths": "Files, folders or globs", "commit": "Commit",
              "gen": "How much of it did AI write?", "models": "Which AI tools and models wrote parts of it?",
              "human": "How did a human check it?", "responsible": "Responsible person",
              "ai": "Did an AI review it?", "ai_by": "Which model reviewed it, and how?",
              "notes": "Notes for the reviewer"}
    parts = [f"### {label}\n\n{answers.get(key) or '_No response_'}\n" for key, label in labels.items()]
    parts.append("### Confirmation\n\n- [X] The answers are true\n" if answers.get("confirm", True)
                 else "### Confirmation\n\n- [ ] The answers are true\n")
    return "\n".join(parts)


def request(base, body, **env_more):
    event = base / "event.json"
    event.write_text(json.dumps({"issue": {"number": 7, "title": "Signoff: ", "body": body,
                                           "user": {"login": "jane", "id": 1}},
                                 "repository": {"default_branch": "main"}}))
    out = base / "api.md"
    out.unlink(missing_ok=True)
    env = {**os.environ, "GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "org/repo",
           "SIGNOFF_DRY_RUN": "1", "SIGNOFF_DRY_RUN_OUT": str(out), "DISPATCH_WORKFLOWS": "signoff-lint.yml",
           **env_more}
    r = subprocess.run([sys.executable, "-I", "-"], input=script(), cwd=base / "work", env=env,
                       capture_output=True, text=True)
    return r, (out.read_text() if out.exists() else "")


def test_declare_files_opens_a_pull_request_from_the_template(checkout):
    r, api = request(checkout, form(kind="Declare files: how they were made", paths="results/",
                                    gen="G2: AI wrote substantial parts", models="Claude Opus 5.5 (Anthropic)",
                                    human="H1: ran it", responsible="Jane Doe", ai="A1: the AI that wrote it",
                                    ai_by="Claude Sonnet 5.5 (Anthropic), new session", notes="Checked."))
    assert r.returncode == 0, r.stdout + r.stderr
    work = checkout / "work"
    assert git(work, "branch", "--show-current").strip() == "signoff-request/issue-7"
    toml = (work / "SIGNOFF.toml").read_text()
    assert 'path = "results/**"' in toml and 'AI-Generation = "G2"' in toml and "new session" in toml
    assert "Co-authored-by: jane <1+jane@users.noreply.github.com>" in git(work, "log", "-1", "--format=%B")
    pr = api.split("----- POST /repos/org/repo/pulls\n", 1)[1].split("\n----- ", 1)[0]
    assert pr.startswith("Declare results/ (signoff request #7)")
    assert "```diff" in pr and "Closes #7\n" in pr and "> Checked." in pr
    assert "- [x] **G0**" in pr and "- [ ] **G1**" in pr and "- [ ] **H0**" in pr
    # after the comment of the AI declaration section, where the PR-signoff check reads it
    assert pr.index("Responsible person: @jane") > pr.index("below this comment. -->")
    assert "/actions/workflows/signoff-lint.yml/dispatches" in r.stdout
    # the description as it will land: G0 ticked, the review left to the requester, whom the check names
    assert subprocess.run(["aisignoff", "lint"], cwd=work, capture_output=True).returncode == 0
    body = pr.split("\n", 2)[2]
    desc = checkout / "description.md"
    check = ["aisignoff", "lint", "--declare-from", str(desc), "--author", "github-actions[bot]",
             "--base", "origin/main"]
    desc.write_text(body)
    r = subprocess.run(check, cwd=work, capture_output=True, text=True)
    assert r.returncode == 1 and "Human-Review is still TODO" in r.stdout
    desc.write_text(body.replace("- [ ] **H0**", "- [x] **H0**"))
    r = subprocess.run(check, cwd=work, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_attest_and_correct_a_commit(checkout):
    r, _ = request(checkout, form(kind="Raise the review of files I checked", paths="results/fit.csv",
                                  human="H2: read every line", responsible="Jane Doe"))
    assert r.returncode == 0, r.stdout + r.stderr
    toml = (checkout / "work/SIGNOFF.toml").read_text()
    assert '[[attestations]]\npath = "results/fit.csv"\nblob = "' in toml and 'Human-Review = "H2"' in toml

    commit = git(checkout / "work", "rev-parse", "--short", "origin/main").strip()
    r, _ = request(checkout, form(kind="Correct the declaration of a commit", commit=commit, gen="G1: x",
                                  models="M (V)", human="H2: read", responsible='Jane "JD" Doe', ai="A1: y",
                                  ai_by="M (V), new session"))
    assert r.returncode == 0, r.stdout + r.stderr
    toml = (checkout / "work/SIGNOFF.toml").read_text()
    assert "[[attestations]]" not in toml   # each run starts from the default branch
    assert f'[[commits]]\ncommit = "{commit}"\nAI-Generation = "G1"' in toml
    assert 'Reviewed-by = ["Jane \\"JD\\" Doe"]' in toml


@pytest.mark.parametrize("answers, message", [
    (dict(kind="Declare files", paths="results/", gen="G0: x", human="H1: x", ai="A0: x", responsible="J",
          confirm=False), 'Tick the box under "Confirmation"'),
    (dict(kind="Declare files", paths="--root=/", gen="G0: x", human="H1: x", ai="A0: x", responsible="J"),
     "`--root=/` isn't a path"),
    (dict(kind="Declare files", paths="results/", gen="G0: x", human="H0: x", ai="A0: x", responsible="J"),
     "`aisignoff annotate` refused the request"),   # below the policy the test adds
    (dict(kind="Raise the review", paths="results/", gen="G1: x"), "An attestation records a review only"),
    (dict(kind="Correct the declaration of a commit", commit="deadbeef", gen="G0: x"),
     "There is no commit `deadbeef`"),
])
def test_refused_requests_say_why(checkout, answers, message):
    if "H0" in answers.get("human", ""):   # a policy on the default branch that the request falls below
        git(checkout / "work", "config", "user.name", "t")
        git(checkout / "work", "config", "user.email", "t@x")
        path = checkout / "work/SIGNOFF.toml"
        path.write_text(path.read_text() + '\n[policy]\n"*" = { human = "H1" }\n')
        git(checkout / "work", "commit", "-qam", "policy")
        git(checkout / "work", "push", "-q", "origin", "HEAD:main")
        git(checkout / "work", "fetch", "-q")
    r, api = request(checkout, form(**answers))
    assert r.returncode == 1
    assert "/issues/7/comments" in api and message in api, api
    assert "POST /repos/org/repo/pulls" not in r.stdout


def test_as_a_github_app(checkout):
    """With an app's token, the commit is the app's and no workflow is started by hand: the app's pull
    request starts them itself."""
    r, _ = request(checkout, form(kind="Declare files", paths="results/", gen="G0: x", human="H1: x",
                                  ai="A0: x", responsible="Jane Doe"), APP_SLUG="signoff-bot")
    assert r.returncode == 0, r.stdout + r.stderr
    assert git(checkout / "work", "log", "-1", "--format=%an").strip() == "signoff-bot[bot]"
    assert "/dispatches" not in r.stdout
