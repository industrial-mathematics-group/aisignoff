"""The G/H/A declaration scheme: levels, keys, policy and completeness rules."""
from __future__ import annotations

import re

from dataclasses import dataclass, field

GENERATION = {
    "G0": "Human",
    "G1": "AI-assisted",
    "G2": "AI-generated",
    "G3": "AI-autonomous",
}
HUMAN = {
    "H0": "Plausibility check",
    "H1": "Tested",
    "H2": "Reviewed line by line",
    "H3": "Independently validated",
}
# AI review counts only what is independent of the generating session: what that session checks
# itself is part of generating (expected from G2 on), so it is A0. Each level includes the one below.
AI = {
    "A0": "No independent AI review",
    "A1": "Context-free check",
    "A2": "Check by a different model",
    "A3": "Validated by a different model",
}

# Canonical key names, as the PR check shows them in its job summary.
GEN, HUM, AIR = "AI-Generation", "Human-Review", "AI-Review"
ASSISTED, AI_REVIEWED, REVIEWED = "Assisted-by", "AI-Reviewed-by", "Reviewed-by"
LEVEL_KEYS = (GEN, HUM, AIR)
LIST_KEYS = (ASSISTED, AI_REVIEWED, REVIEWED)
KEYS = LEVEL_KEYS + LIST_KEYS
LEVELS = {GEN: GENERATION, HUM: HUMAN, AIR: AI}

# The three axes: each level key together with the list key that names who/what did it.
AXES = ((GEN, ASSISTED), (HUM, REVIEWED), (AIR, AI_REVIEWED))

ORDER = {k: i for i, k in enumerate([*HUMAN, *AI])}  # H0<H1<..., A0<A1<...

# Placeholder for a level or name that a person still has to fill in. 'aisignoff annotate' accepts it
# (e.g. -H TODO).
# It blocks the per-axis fallback to SIGNOFF.toml and fails lint until a person fills it in.
TODO = "TODO"


def canonical_key(name: str, keys=KEYS) -> str | None:
    """Return the canonical spelling of a declaration key (case-insensitive), or None."""
    for key in keys:
        if key.lower() == name.strip().lower():
            return key
    return None


def at_least(level: str, minimum: str) -> bool:
    return ORDER[level] >= ORDER[minimum]


# How severe a review's finding is, lowest first (docs/levels.md, after IEEE Std 1044-2009). A
# commit message or pull request description that declares A2 or A3 says the highest severity the
# review found in the change itself, in a line "AI-Review-Findings: minor" ("none": no finding).
# The reviewer only reviews: it records what it found and changes nothing. A finding blocks
# nothing; it becomes the findings level of the lines that review covered (FINDINGS_LEVELS).
SEVERITIES = ("trivial", "minor", "major", "critical")
FINDINGS = "AI-Review-Findings"
NO_FINDINGS = "none"

# The findings axis of reports: the highest finding that the last independent AI review (A2 or A3)
# of a line left open. F- is the default: no such review has covered the line since it last
# changed. A trivial finding has no effect on results or behaviour, so it counts as F0.
UNREVIEWED = "F-"
FINDINGS_AXIS = "Findings"  # its key in reports (AI-Review-Findings is the value a review gives)
FINDINGS_LEVELS = {
    "F0": "Reviewed, nothing open",
    "F1": "Minor finding open",
    "F2": "Major finding open",
    "F3": "Critical finding open",
}
_FINDINGS_OF = {NO_FINDINGS: "F0", "trivial": "F0", "minor": "F1", "major": "F2", "critical": "F3"}


def findings_value(value: str) -> str:
    """A findings value as written, the way it is compared: "**None.**" is "none"."""
    return value.strip().strip("*_`").strip().rstrip(".!").strip().lower()


def valid_findings(value: str | None) -> bool:
    return value is not None and findings_value(value) in _FINDINGS_OF


def findings_level_of(value: str | None) -> str:
    """The findings level a valid findings value gives (F0-F3), else F-."""
    return _FINDINGS_OF.get(findings_value(value), UNREVIEWED) if value else UNREVIEWED


def findings_problems(level: str | None, value: str | None, required: bool = False) -> list[str]:
    """What is wrong with the AI-Review-Findings line VALUE (None: there is none) next to the AI
    review LEVEL. The line belongs to a review of A2 or A3: next to a lower level it isn't read, so
    a template's line filled in with "n/a" does no harm. required: A2 and A3 must give it (the
    check before the merge). Any severity is valid: a finding is recorded, it blocks nothing."""
    if level not in ("A2", "A3"):
        return []
    if not value:
        if required:
            return [f"{level} needs a line '{FINDINGS}:' with the highest severity the review found in this change "
                    f"({NO_FINDINGS}, {', '.join(SEVERITIES)})"]
        return []
    if not valid_findings(value):
        return [f"invalid {FINDINGS} {value!r}: must be one of {NO_FINDINGS}, {', '.join(SEVERITIES)}"]
    return []


def worst_findings(values: list[str]) -> str:
    """The value that counts among several findings lines: an invalid one (so that it is reported),
    else the most severe. A line left empty counts only when no line is filled in."""
    filled = [v for v in values if v.strip()]
    if not filled:
        return values[-1] if values else ""
    rank = {NO_FINDINGS: 0, **{s: i + 1 for i, s in enumerate(SEVERITIES)}}
    return max(filled, key=lambda v: rank.get(findings_value(v), len(rank) + 1))


# ------------------------------------------------------------------ the AI review scale of version 3
def from_version_3(level, names=()):
    """An AI review level (with its names) of the scale before SIGNOFF.toml version 4, on today's
    scale. There, A1 was the self-check of the generating session, which is no review now (A0, and
    A0 has no reviewer); A2, a new session, is A1; A3, a different model, stays A3."""
    if level == "A1":
        return "A0", ()
    if level == "A2":
        return "A1", tuple(names)
    return level, tuple(names)


def policy_from_version_3(rules: dict) -> dict:
    """[policy] of the scale before version 4, on today's scale. There, G1-G3 always needed A1 (now
    A0, so nothing), and a minimum of A1 for G0 meant A2 (now A1)."""
    out = {gen: dict(req) for gen, req in rules.items()}
    star = out.get("*", {}).get("ai")
    for gen, req in out.items():
        if "ai" in req:
            if gen == "G0":
                req["ai"] = {"A1": "A1", "A2": "A1"}.get(req["ai"], req["ai"])
            else:
                req["ai"] = from_version_3(req["ai"])[0]
    if star == "A1" and "ai" not in out.get("G0", {}):
        out.setdefault("G0", {})["ai"] = "A1"
    return out


# ------------------------------------------------------------------ policy
@dataclass(frozen=True)
class Policy:
    """Minimum review levels, per generation level ("*" = default for all)."""

    rules: dict = field(default_factory=dict)  # {"*"|"G0".."G3": {"human": "H1", "ai": "A2"}}

    def minimum(self, generation: str | None) -> tuple[str | None, str | None]:
        merged = dict(self.rules.get("*", {}))
        if generation:
            merged.update(self.rules.get(generation, {}))
        return merged.get("human"), merged.get("ai")


def parse_policy(data, where: str = "policy") -> Policy:
    """Validate a [policy] table; raises ValueError with a readable message."""
    if data is None:
        return Policy()
    if not isinstance(data, dict):
        raise ValueError(f"{where} must be a table")
    rules = {}
    for gen, req in data.items():
        if gen != "*" and gen not in GENERATION:
            raise ValueError(f"{where}: unknown key '{gen}' (use \"*\", G0, G1, G2 or G3)")
        if not isinstance(req, dict):
            raise ValueError(f"{where}.{gen} must be a table like {{ human = \"H1\", ai = \"A2\" }}")
        unknown = set(req) - {"human", "ai"}
        if unknown:
            raise ValueError(f"{where}.{gen}: unknown key(s) {', '.join(sorted(unknown))} (use human, ai)")
        if "human" in req and (not isinstance(req["human"], str) or req["human"] not in HUMAN):
            raise ValueError(f"{where}.{gen}.human must be one of {', '.join(HUMAN)}")
        if "ai" in req and (not isinstance(req["ai"], str) or req["ai"] not in AI):
            raise ValueError(f"{where}.{gen}.ai must be one of {', '.join(AI)}")
        rules[gen] = dict(req)
    return Policy(rules)


# ------------------------------------------------------------------ declarations
@dataclass
class Declaration:
    """The resolved declaration of one file or change."""

    generation: str | None = None
    human: str | None = None
    ai: str | None = None
    assisted_by: tuple[str, ...] = ()
    reviewed_by: tuple[str, ...] = ()
    ai_reviewed_by: tuple[str, ...] = ()
    source: str = "none"  # e.g. 'SIGNOFF.toml [2]', 'none'
    problems: list[str] = field(default_factory=list)  # parse problems found while reading it
    # the AI-Review-Findings value of the last independent AI review (A2 or A3) that covered it, as
    # written ("none", "minor", ...); None: there is none (findings level F-)
    findings: str | None = None

    _FIELDS = {GEN: "generation", HUM: "human", AIR: "ai",
               ASSISTED: "assisted_by", REVIEWED: "reviewed_by", AI_REVIEWED: "ai_reviewed_by"}

    @classmethod
    def from_mapping(cls, values: dict, source: str) -> "Declaration":
        def as_tuple(v):
            if v is None:
                return ()
            if isinstance(v, str):
                v = [v]
            return tuple(str(s).strip() for s in v if str(s).strip())

        kwargs = {}
        for key, attr in cls._FIELDS.items():
            v = values.get(key)
            kwargs[attr] = as_tuple(v) if key in LIST_KEYS else (v or None)
        findings = values.get(FINDINGS)
        return cls(**kwargs, source=source, findings=findings if isinstance(findings, str) and findings else None)

    def get(self, key: str):
        return getattr(self, self._FIELDS[key])

    def as_dict(self) -> dict:
        out = {}
        for key in KEYS:
            v = self.get(key)
            out[key] = list(v) if key in LIST_KEYS else v
        if self.findings is not None:
            out[FINDINGS] = self.findings
        out["source"] = self.source
        return out

    def short(self) -> str:
        return " ".join(v or "--" for v in (self.generation, self.human, self.ai))


def validate(d: Declaration, policy: Policy | None = None, allow_todo: bool = False) -> list[str]:
    """Return the rule violations of a declaration (empty list = valid).

    With allow_todo, TODO placeholders are not reported themselves (used by 'annotate', so an
    agent can leave e.g. the human review for a person); the other rules still apply to the
    axes that are filled in.
    """
    if d.source == "none":
        return ["no declaration (not matched by SIGNOFF.toml)"]
    errors = list(d.problems)
    for key in KEYS:
        v = d.get(key)
        if not allow_todo and (v == TODO or (key in LIST_KEYS and TODO in v)):
            errors.append(f"{key} is still TODO (to be filled in by a person)")
    for key in LEVEL_KEYS:
        v = d.get(key)
        if v == TODO:
            continue
        if v is None:
            errors.append(f"missing {key}")
        elif v not in LEVELS[key]:
            errors.append(f"invalid {key} '{v}' (use {', '.join(LEVELS[key])})")

    # Checks below involve specific axes; a TODO axis is skipped (it is not in the level
    # sets), while the axes that are filled in are still checked.
    g, h, a = d.generation, d.human, d.ai
    if g in ("G1", "G2", "G3") and not d.assisted_by:
        errors.append(f"{g} needs {ASSISTED} (tool and model)")
    if g == "G0" and d.assisted_by:
        errors.append(f"G0 means no AI was used, but {ASSISTED} is set")
    if h in HUMAN and not d.reviewed_by:
        errors.append(f"{HUM} needs {REVIEWED} (the responsible human)")
    if a in ("A1", "A2", "A3") and not d.ai_reviewed_by:
        errors.append(f"{a} needs {AI_REVIEWED} (reviewing model and session)")
    if a == "A0" and d.ai_reviewed_by:
        errors.append(f"A0 means no AI review, but {AI_REVIEWED} is set")
    reviewers = [n for n in d.ai_reviewed_by if n != TODO]
    if a in ("A1", "A2", "A3") and reviewers and all(mentions_self_check(n) for n in reviewers):
        errors.append(f"{a} names only a self-check in {AI_REVIEWED}: what the generating session checks itself "
                      "is no AI review (A0, the scale before version 4 called it A1)")
    elif a in ("A2", "A3") and reviewers and all(_same_model(n, d.assisted_by) for n in reviewers):
        errors.append(f"{a} is a review by a different model, but {AI_REVIEWED} names only models that wrote it: "
                      "a new session of a model that wrote it is A1")

    # The minimum for every generation level ("*") doesn't depend on the generation: it is also
    # checked when that is missing or still TODO.
    known = g in GENERATION
    if (known or g is None or g == TODO) and (h is None or h in HUMAN or h == TODO) and (a is None or a in AI or a == TODO):
        min_h, min_a = (policy or Policy()).minimum(g if known else None)
        what = g if known else "every generation level"
        if min_h and h in HUMAN and not at_least(h, min_h):
            errors.append(f"{what} requires at least {min_h} by policy (declared {h})")
        if min_a and a in AI and not at_least(a, min_a):
            errors.append(f"{what} requires at least {min_a} by policy (declared {a})")
    return errors


_SELF_CHECK = re.compile(r"self[- ]?check|same session|generating session", re.I)
# "not the same session", "independent of the generating session", "without access to the ...": the
# words that say a review was *not* a self-check
_NEGATED = re.compile(r"\b(?:not|no|never|without|independent(?:ly)?\s+of|outside(?:\s+of)?|other\s+than|separate(?:ly)?\s+from|"
                      r"different\s+from|apart\s+from|instead\s+of|isn't|wasn't|rather\s+than)\b"
                      r"(?:\s+(?:the|a|an|any|that|of|to|from|access|its|their|in|with|by))*\s*$", re.I)


def mentions_self_check(text: str, pattern: re.Pattern = _SELF_CHECK) -> bool:
    """Whether TEXT says it is a self-check: the words of PATTERN, not negated."""
    return any(not _NEGATED.search(text[:m.start()]) for m in pattern.finditer(text))


_VERSION = re.compile(r"^v?\d[\w.]*$", re.I)
# words that don't tell models apart: vendors, tools, modes ("Claude Code (Claude Opus 5.5), thinking")
_FILLER = frozenset("""anthropic openai google deepmind meta microsoft github xai mistralai ai inc
    code cli app desktop web api via with using in on by and the model agent mode thinking extended reasoning
    high medium low max effort preview latest""".split())
# a family name alone doesn't name one model: "Claude" may be any of them
_FAMILY = frozenset("claude gpt chatgpt gemini llama mistral grok deepseek qwen".split())


def _model_words(name: str) -> set[str]:
    """The words that name a model in "Claude Opus 5.5 (Anthropic), new session": what comes before
    the first comma, split at spaces, hyphens and slashes, without vendors, tools and version
    numbers. "claude-opus-5-5" and "anthropic/claude-opus-5.5" are "claude opus" as well."""
    name = name.split(",")[0].casefold()
    return {w for w in re.findall(r"[^\W_]+(?:\.[^\W_]+)*", name) if not _VERSION.match(w) and w not in _FILLER}


def _same_model(reviewer: str, assisted: tuple[str, ...]) -> bool:
    """Whether an AI-Reviewed-by entry names a model of Assisted-by. Names are compared by their
    words, without vendor, tool and version: "Claude Opus (Anthropic)" wrote it, so "Claude Opus 5.5
    (Anthropic), new session", "Opus 5.5, new session", "claude-opus-5-5" and "Claude Opus 5.5
    Thinking" review it as the same model, and "Claude Fable" or "Claude Opus Pro" as a different one. Another version
    of a model is the same model. An Assisted-by value can list several models, separated by commas."""
    r = _model_words(reviewer)
    if not r:
        return False
    for m in (part for value in assisted for part in value.split(",")):
        words = _model_words(m)
        if not words:
            continue
        if r <= words:  # the same words, or a short form of them ("Opus")
            return True
        if words <= r and r - words <= _FAMILY and words - _FAMILY:  # "Opus" wrote it, "Claude Opus" reviews
            return True
    return False


UNDECLARED = "undeclared"
_AXIS_WORDS = (
    (AIR, re.compile(rf"{AI_REVIEWED}|{AIR}|requires at least A\d")),
    (HUM, re.compile(rf"(?<!AI-){REVIEWED}|{HUM}|requires at least H\d")),
    (GEN, re.compile(rf"{ASSISTED}|{GEN}|generation level")),
)


def error_axes(error: str) -> tuple[str, ...]:
    """The axes an error of validate (or a problem found while reading a declaration) is about;
    all three when it doesn't say."""
    found = tuple(key for key, words in _AXIS_WORDS if words.search(error))
    return found or LEVEL_KEYS


def counted_level(d: Declaration, errors: list[str], key: str) -> str:
    """The level of one axis as report, diff and the badges count it: the declared level, or
    'undeclared' when that axis has none (missing, TODO, invalid) or an error is about it. An
    error about another axis leaves this one as declared."""
    level = d.get(key)
    if level not in LEVELS[key] or any(key in error_axes(e) for e in errors):
        return UNDECLARED
    return level


def counted_findings(d: Declaration, errors: list[str]) -> str:
    """The findings level as reports count it: F0-F3 from the findings of the last independent AI
    review, F- when there is none, or the AI review isn't a valid A2 or A3."""
    if counted_level(d, errors, AIR) not in ("A2", "A3"):
        return UNREVIEWED
    return findings_level_of(d.findings)


def axis_level(d: Declaration, errors: list[str], key: str) -> str:
    """The level of one axis as reports count it: counted_level, or counted_findings for FINDINGS_AXIS."""
    return counted_findings(d, errors) if key == FINDINGS_AXIS else counted_level(d, errors, key)


def unset(key: str) -> str:
    """What an axis counts where it has no level: undeclared, or for the findings F- (unreviewed)."""
    return UNREVIEWED if key == FINDINGS_AXIS else UNDECLARED


def counted_short(d: Declaration, errors: list[str]) -> str:
    return " ".join("--" if (v := counted_level(d, errors, key)) == UNDECLARED else v for key in LEVEL_KEYS)


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def printable(text: str) -> str:
    """text with control characters escaped (\\n, \\x1b, ...), for terminal and CI log output: a
    file name with a newline must not start a line of its own (GitHub reads "::command::" lines)."""
    return _CONTROL.sub(lambda m: repr(m.group(0))[1:-1], text)
