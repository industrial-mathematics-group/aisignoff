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
AI = {
    "A0": "No AI review",
    "A1": "Self-check by the generating session",
    "A2": "Review by a new session",
    "A3": "Extensive review or benchmark by a different model",
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

# Keys of the first version of the scheme (V0-V3), recognised for migration only.
LEGACY_KEYS = ("AI-Verification", "Verified-by", "Tested-by")

# Version 2 used A-, A0-A3 for the AI review. The new scale shifts by one:
#   A- (none) -> A0, A0 (self-check) -> A1, A1 (new session, same model) -> A2,
#   A2 (different model) -> A2 (A3 now also requires an extensive review or benchmark),
#   A3 (different model with benchmark) -> A3.
LEGACY_AI_NONE = "A-"
# Where the old value turns up, SIGNOFF.toml is already version 3 (or absent), so 'aisignoff migrate'
# may refuse; say what to write instead.
LEGACY_AI_HINT = (" (A- is now A0; without SIGNOFF.toml, 'aisignoff migrate --from 2'"
                  " converts all old tags, otherwise convert them by hand: A- -> A0, A0 -> A1, A1 -> A2)")

ORDER = {k: i for i, k in enumerate([*HUMAN, *AI])}  # H0<H1<..., A0<A1<...

# Placeholder for a level or name that a person still has to fill in. 'aisignoff migrate' writes it
# where the old levels carry no information, and 'aisignoff annotate' accepts it (e.g. -H TODO).
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


# ------------------------------------------------------------------ policy
BUILTIN_MIN_AI_FOR_GENERATED = "A1"  # G1-G3 need at least a self-check by the AI


@dataclass(frozen=True)
class Policy:
    """Minimum review levels, per generation level ("*" = default for all)."""

    rules: dict = field(default_factory=dict)  # {"*"|"G0".."G3": {"human": "H1", "ai": "A2"}}

    def minimum(self, generation: str | None) -> tuple[str | None, str | None]:
        merged = dict(self.rules.get("*", {}))
        if generation:
            merged.update(self.rules.get(generation, {}))
        human, ai = merged.get("human"), merged.get("ai")
        if generation in ("G1", "G2", "G3") and (ai is None or not at_least(ai, BUILTIN_MIN_AI_FOR_GENERATED)):
            ai = BUILTIN_MIN_AI_FOR_GENERATED
        if generation == "G0" and ai == "A1":
            ai = "A2"  # human-written content has no generating session; any AI review of it is A2+
        return human, ai


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
            hint = " (A- is now A0)" if req["ai"] == LEGACY_AI_NONE else ""
            raise ValueError(f"{where}.{gen}.ai must be one of {', '.join(AI)}{hint}")
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
    source: str = "none"  # e.g. 'SIGNOFF.toml [2]', 'inline', 'none'
    problems: list[str] = field(default_factory=list)  # parse problems found while reading it

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
        return cls(**kwargs, source=source)

    def get(self, key: str):
        return getattr(self, self._FIELDS[key])

    def as_dict(self) -> dict:
        out = {}
        for key in KEYS:
            v = self.get(key)
            out[key] = list(v) if key in LIST_KEYS else v
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
        return ["no declaration (not matched by SIGNOFF.toml and no inline tags)"]
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
            hint = LEGACY_AI_HINT if key == AIR and v == LEGACY_AI_NONE else ""
            errors.append(f"invalid {key} '{v}' (use {', '.join(LEVELS[key])}){hint}")

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
    if g == "G0" and a == "A1":
        errors.append("G0 has no generating AI session that could check itself; "
                      "an AI review of human-written content is A2 or A3")

    if g in GENERATION and (h is None or h in HUMAN or h == TODO) and (a is None or a in AI or a == TODO):
        min_h, min_a = (policy or Policy()).minimum(g)
        if min_h and h in HUMAN and not at_least(h, min_h):
            errors.append(f"{g} requires at least {min_h} by policy (declared {h})")
        if min_a and a in AI and not at_least(a, min_a):
            reason = "AI-written content must at least be self-checked" if min_a == "A1" else "by policy"
            errors.append(f"{g} requires at least {min_a} ({reason}; declared {a})")
    return errors


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def printable(text: str) -> str:
    """text with control characters escaped (\\n, \\x1b, ...), for terminal and CI log output: a
    file name with a newline must not start a line of its own (GitHub reads "::command::" lines)."""
    return _CONTROL.sub(lambda m: repr(m.group(0))[1:-1], text)
