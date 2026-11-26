"""The declarations of the changes that landed: one per commit of the default branch's first-parent history
(a merged pull request's merge or squash commit), read from its message as the check before the merge reads
a pull request description. `aisignoff badge --commits` counts them, for repositories that declare changes
but not files (no SIGNOFF.toml needed)."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .history import _git, _prose_lines, _records, check_git, parse_message, short
from .model import AI, GENERATION, HUMAN, TODO

FORMAT = "%H%x00%P%x00%s%x00%an <%ae>%x00%B%x00"
UNKNOWN = "unknown"

# The first version of the policy declared "AI-Verification: V0-V3" instead of human and AI review. Commit
# messages can't be rewritten, so those commits keep counting, mapped conservatively: what V0-V3 can't tell
# is unknown.
_VERIFICATION = re.compile(r"^AI-Verification:[ \t]*(V[0-3])[ \t]*$", re.I)
_V_HUMAN = {"V0": "H2", "V3": "H2"}
_V_AI = {"V1": "A2", "V2": "A2", "V3": "A2"}


@dataclass
class Changes:
    """How many of the commits declare which level, per axis."""

    commits: int = 0
    generation: Counter = field(default_factory=Counter)
    human: Counter = field(default_factory=Counter)
    ai: Counter = field(default_factory=Counter)
    boxes: int = 0  # declared with the ticked boxes of the pull request template
    legacy: int = 0  # declared with the V0-V3 trailers of the first policy
    problems: list[str] = field(default_factory=list)

    @property
    def declared(self) -> int:
        return sum(self.generation.values())

    @property
    def trailers(self) -> int:
        return self.declared - self.boxes - self.legacy


def _verification(body: str) -> str | None:
    for line in _prose_lines(body):
        m = _VERIFICATION.match(line)
        if m:
            return m.group(1).upper()
    return None


def _level(piece, levels: dict) -> str:
    """A piece's level as counted: unknown where it is missing, left TODO or not a level."""
    if piece is None or piece.level in (None, TODO):
        return UNKNOWN
    level = str(piece.level).upper()
    return level if level in levels else UNKNOWN


def count(root: Path, rev: str = "HEAD") -> Changes:
    """The declarations of the commits on the first-parent history of `rev`. Commits without a generation
    level (from before the policy) are not counted."""
    check_git()
    out = Changes()
    log = _git(root, "log", "--first-parent", f"--format={FORMAT}", rev)
    for sha, _parents, _subject, author, message in _records(log or ""):
        out.commits += 1
        body = message.split("\n", 1)[1] if "\n" in message else ""
        pieces, both = parse_message(body, author, f"commit {short(sha)}", landed=True)
        g = _level(pieces.get(0), GENERATION)
        if g == UNKNOWN:
            continue
        if both:
            out.problems.append(both)
        human, ai = pieces.get(1), pieces.get(2)
        if ai is not None and str(ai.level).upper() == "A-":  # "none" on the second policy's scale
            h, a = _level(human, HUMAN), "A0"
        else:
            h, a = _level(human, HUMAN), _level(ai, AI)
        if "pull request checkboxes" in pieces[0].source:
            out.boxes += 1
        elif human is None and ai is None and (v := _verification(body)):
            out.legacy += 1
            h = _V_HUMAN.get(v, UNKNOWN)
            a = _V_AI.get(v) or ("A0" if v == "V0" and g == "G0" else UNKNOWN)
        out.generation[g] += 1
        out.human[h] += 1
        out.ai[a] += 1
    return out


def summary_markdown(changes: Changes) -> str:
    """The job summary: how many commits are declared, and how."""
    lines = [f"### AI declarations\n\n{changes.declared} of {changes.commits} commits on the default branch are declared"]
    notes = [f"{changes.boxes} from the ticked questions of merged pull requests"] if changes.boxes else []
    if changes.legacy:
        notes.append(f"{changes.legacy} with the old V0-V3 trailers, mapped conservatively")
    if changes.trailers:
        notes.append(f"{changes.trailers} with \"Key: value\" lines")
    lines[0] += f" ({'; '.join(notes)}).\n" if notes else ".\n"
    lines.append("| Level | Commits |\n|---|---|")
    for counts in (changes.generation, changes.human, changes.ai):
        for k, n in sorted(counts.items()):
            lines.append(f"| {k} | {n} |")
    return "\n".join(lines) + "\n"
