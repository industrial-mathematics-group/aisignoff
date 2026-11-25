"""Helpers for the probes: throwaway git repositories and the aisignoff executable under test.

Nothing here imports aisignoff: every probe drives the command line, as a workflow does."""
import json
import os
import shutil
import subprocess
from pathlib import Path

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
H3 = DECL.replace("Human-Review: H1", "Human-Review: H3")

ENV = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "d@x", "GIT_COMMITTER_NAME": "Dev",
       "GIT_COMMITTER_EMAIL": "d@x", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
       "AISIGNOFF_NO_CACHE": "1"}
for _k in ("GITHUB_REF", "GITHUB_EVENT_PATH", "GITHUB_EVENT_NAME", "GITHUB_ACTIONS"):
    ENV.pop(_k, None)


class Repo:
    def __init__(self, d: Path, exe: str, toml: str | None = HIST, env: dict | None = None):
        self.d, self.exe, self.env = Path(d), exe, dict(env or ENV)
        if self.d.exists():
            shutil.rmtree(self.d)
        self.d.mkdir(parents=True)
        self.g("init", "-q", "-b", "main")
        if toml is not None:
            (self.d / "SIGNOFF.toml").write_text(toml)
        self.commit("init\n\n" + DECL)

    def g(self, *a, check=True):
        r = subprocess.run(["git", "-C", str(self.d), *a], check=check, capture_output=True, text=True, env=self.env)
        return r.stdout.strip()

    def write(self, name, data):
        p = self.d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            p.write_text(data)

    def commit(self, msg):
        self.g("add", "-A")
        self.g("commit", "-q", "--allow-empty", "-m", msg)
        return self.g("rev-parse", "HEAD")

    def cli(self, *args, env=None, stdin=None):
        r = subprocess.run([self.exe, *args], cwd=self.d, capture_output=True, text=True, env=env or self.env,
                           input=stdin)
        return r.returncode, r.stdout, r.stderr

    def lines(self, path, *args, key="Human-Review"):
        """[level of each line or unit] of a file, from report --json."""
        code, out, err = self.cli("report", "--json", *args)
        if code != 0:
            return f"exit {code}: {err.strip()[-300:]}"
        f = next(f for f in json.loads(out)["files"] if f["path"] == path)
        got = {}
        for p in f["parts"]:
            for a, b in p["runs"]:
                for n in range(a, b + 1):
                    got[n] = p[key]
        return [got[n] for n in sorted(got)]


def show(title, code, out, err="", limit=1200):
    print(f"--- {title}")
    print(f"exit code: {code}")
    text = (out + (("\n[stderr]\n" + err) if err.strip() else "")).strip()
    print(text[:limit] + (" ..." if len(text) > limit else ""))
    print()
