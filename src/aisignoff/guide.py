"""Role guides for AI agents: what a developing agent declares, and how a reviewing agent reviews.

The text lives once, in guides/<role>.md. `aisignoff guide --role ROLE` prints it, followed by what
this repository's SIGNOFF.toml sets. `--skills` writes the same text as Claude skills, and
`--agents-md` (and `init`) point AGENTS.md at the command.
"""
from __future__ import annotations

import json

from importlib.resources import files
from pathlib import Path

from . import __version__
from .config import ConfigError, load

ROLES = ("dev", "review")
SKILL_DESCRIPTIONS = {
    "dev": "How to declare AI use with aisignoff when you write or change code or text in this repository: "
           "generation level, Assisted-by, and what to leave to the reviewers. Use before committing or "
           "opening a pull request.",
    "review": "How to review a change as an independent AI reviewer under aisignoff: read-only, the A1-A3 "
              "levels, the severity scale and the AI-Review-Findings line. Use when asked to review a change.",
}
MARK_BEGIN = "<!-- aisignoff:begin -->"
MARK_END = "<!-- aisignoff:end -->"
AGENTS_SNIPPET = f"""{MARK_BEGIN}
## AI signoff

This repository declares AI use with [aisignoff](https://industrial-mathematics-group.github.io/aisignoff/).
Before you commit or open a pull request, run `aisignoff guide --role dev` and follow it.
If you are reviewing a change instead, run `aisignoff guide --role review`: a reviewer only reviews and changes nothing.
{MARK_END}
"""


def text(role: str) -> str:
    """The guide for ROLE, for the installed version of aisignoff."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r} (use {' or '.join(ROLES)})")
    raw = files("aisignoff").joinpath("guides", f"{role}.md").read_text(encoding="utf-8")
    return raw.replace("{{version}}", __version__)


def repository_notes(root: Path) -> list[str]:
    """What this repository's SIGNOFF.toml sets that the guide's reader needs, as Markdown lines."""
    try:
        config = load(root)
    except ConfigError as e:
        return ["## This repository", "", f"`SIGNOFF.toml` doesn't load: {e}"]
    if config.path is None:
        return ["## This repository", "", "No `SIGNOFF.toml` here: run this command in the repository's root, "
                "or pass `--root`."]
    h = config.history
    out = ["## This repository", ""]
    if h.enabled and h.merge_method == "rebase":
        out.append("- `[history]` is on and pull requests are rebased: **every commit message declares its own "
                   "lines**; the pull request description lands nowhere.")
    elif h.enabled:
        out.append(f"- `[history]` is on and pull requests land as a {h.merge_method}: **the pull request "
                   "description declares the change**. A commit pushed to the default branch directly declares "
                   "itself.")
        if h.undeclared == "error" or h.require_trailers_since:
            out.append("- Every commit that lands lines on the default branch must declare them "
                       "(`undeclared = \"error\"` or `require-trailers-since`).")
    else:
        out.append("- No `[history]`: declarations are per file, in the `[[annotations]]` of `SIGNOFF.toml`.")
    if config.policy.rules:
        rules = []
        for gen in ("*", "G0", "G1", "G2", "G3"):
            req = config.policy.rules.get(gen)
            if req:
                parts = ", ".join(req[k] for k in ("human", "ai") if k in req)
                rules.append(f"{'every level' if gen == '*' else gen}: at least {parts}")
        out.append(f"- Minimum review levels (`[policy]`): {'; '.join(rules)}. `lint` fails below them.")
    else:
        out.append("- No minimum review levels (`[policy]`).")
    if config.exclude:
        out.append(f"- Need no declaration (`exclude`): {', '.join(f'`{p}`' for p in config.exclude)}.")
    return out


def full(role: str, root: Path) -> str:
    return text(role).rstrip("\n") + "\n\n" + "\n".join(repository_notes(root)) + "\n"


def skill(role: str) -> str:
    """A Claude skill (SKILL.md) that hands over to the command and carries the guide as a fallback."""
    return (f"---\nname: aisignoff-{role}\ndescription: {json.dumps(SKILL_DESCRIPTIONS[role])}\n---\n\n"
            f"Run `aisignoff guide --role {role}` in the repository's root and follow what it prints: it matches "
            "the aisignoff version this repository uses and adds what its `SIGNOFF.toml` sets.\n\n"
            f"If aisignoff isn't installed, follow the guide below, written by aisignoff {__version__} "
            f"(`aisignoff guide --skills` rewrites it).\n\n" + text(role))


def write_skills(directory: Path) -> list[Path]:
    written = []
    for role in ROLES:
        path = directory / f"aisignoff-{role}" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(skill(role), encoding="utf-8")
        written.append(path)
    return written


def add_pointer(path: Path, create: bool) -> str | None:
    """Add the aisignoff section to an agent instructions file such as AGENTS.md, or bring it up to date.

    Returns what happened ("created", "added", "updated"), or None when nothing changed."""
    if not path.exists():
        if not create:
            return None
        path.write_text("# Instructions for AI agents\n\n" + AGENTS_SNIPPET, encoding="utf-8")
        return "created"
    old = path.read_text(encoding="utf-8")
    begin, end = old.find(MARK_BEGIN), old.find(MARK_END)
    if begin != -1 and end > begin:
        new = old[:begin] + AGENTS_SNIPPET.rstrip("\n") + old[end + len(MARK_END):]
        if new == old:
            return None
        path.write_text(new, encoding="utf-8")
        return "updated"
    sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
    path.write_text(old + sep + AGENTS_SNIPPET, encoding="utf-8")
    return "added"


def point_agents(root: Path) -> list[str]:
    """Point AGENTS.md (created if missing) and an existing CLAUDE.md at the guides; one message per change."""
    messages = []
    for name, create in (("AGENTS.md", True), ("CLAUDE.md", False)):
        done = add_pointer(root / name, create)
        if done:
            messages.append({"created": f"Created {root / name} with the aisignoff section",
                             "added": f"Added the aisignoff section to {root / name}",
                             "updated": f"Updated the aisignoff section in {root / name}"}[done])
    return messages
