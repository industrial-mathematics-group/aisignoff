"""aisignoff guide: the role guides for AI agents, the AGENTS.md section and the Claude skills."""
from pathlib import Path

import pytest

from aisignoff import __version__, guide
from aisignoff.cli import main
from aisignoff.guide import MARK_BEGIN, MARK_END


@pytest.mark.parametrize("role,must", [
    ("dev", ["Human-Review: TODO", "AI-Review: A0", "Never declare A1, A2 or A3", "AI-Review-Findings:"]),
    ("review", ["Read-only", "critical", "major", "minor", "trivial", "AI-Review-Findings:", "F0", "F3", "F-"]),
])
def test_guide_text(role, must):
    text = guide.text(role)
    assert f"aisignoff {__version__}" in text
    assert "{{version}}" not in text
    for phrase in must:
        assert phrase in text


def test_guide_unknown_role():
    with pytest.raises(ValueError):
        guide.text("boss")


def test_guide_prints_repository_settings(tmp_path, capsys):
    (tmp_path / "SIGNOFF.toml").write_text(
        'version = 4\nexclude = ["reviews/**"]\n[history]\nenabled = true\nmerge-method = "squash"\n'
        '[policy]\n"*" = { human = "H1" }\nG3 = { human = "H2", ai = "A1" }\n', encoding="utf-8")
    assert main(["--root", str(tmp_path), "guide", "--role", "dev"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# aisignoff guide for the developing agent")
    assert "land as a squash: **the pull request description declares the change**" in out
    assert "every level: at least H1; G3: at least H2, A1" in out
    assert "`reviews/**`" in out


def test_guide_rebase_and_no_history(tmp_path, capsys):
    (tmp_path / "SIGNOFF.toml").write_text('version = 4\n[history]\nenabled = true\nmerge-method = "rebase"\n',
                                           encoding="utf-8")
    main(["--root", str(tmp_path), "guide", "--role", "review"])
    assert "every commit message declares its own lines" in capsys.readouterr().out
    (tmp_path / "SIGNOFF.toml").write_text("version = 4\n", encoding="utf-8")
    main(["--root", str(tmp_path), "guide", "--role", "review"])
    assert "No `[history]`" in capsys.readouterr().out


def test_guide_without_or_with_broken_signoff_toml(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "guide", "--role", "dev"]) == 0
    assert "No `SIGNOFF.toml` here" in capsys.readouterr().out
    (tmp_path / "SIGNOFF.toml").write_text("version = 1\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "guide", "--role", "dev"]) == 0
    assert "doesn't load" in capsys.readouterr().out


def test_guide_needs_something_to_do(tmp_path):
    assert main(["--root", str(tmp_path), "guide"]) == 2


def test_init_points_agents_md(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "aisignoff guide --role dev" in text and "aisignoff guide --role review" in text
    assert not (tmp_path / "CLAUDE.md").exists()  # only added to when it exists


def test_init_no_agents_md(tmp_path):
    assert main(["--root", str(tmp_path), "init", "--no-agents-md"]) == 0
    assert not (tmp_path / "AGENTS.md").exists()


def test_agents_md_appended_once_and_updated(tmp_path):
    agents, claude = tmp_path / "AGENTS.md", tmp_path / "CLAUDE.md"
    agents.write_text("# Ours\n\nRun the tests.", encoding="utf-8")
    claude.write_text("Be brief.\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "guide", "--agents-md"]) == 0
    first = agents.read_text(encoding="utf-8")
    assert first.startswith("# Ours\n\nRun the tests.\n\n" + MARK_BEGIN)
    assert MARK_BEGIN in claude.read_text(encoding="utf-8")
    assert main(["--root", str(tmp_path), "guide", "--agents-md"]) == 0
    assert agents.read_text(encoding="utf-8") == first  # idempotent
    # an old section is replaced, what surrounds it is kept
    agents.write_text(f"before\n{MARK_BEGIN}\nold text\n{MARK_END}\nafter\n", encoding="utf-8")
    assert guide.add_pointer(agents, create=True) == "updated"
    text = agents.read_text(encoding="utf-8")
    assert text.startswith("before\n") and text.endswith(f"{MARK_END}\nafter\n") and "old text" not in text


def test_skills(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "guide", "--skills"]) == 0
    for role in guide.ROLES:
        skill = (tmp_path / ".claude" / "skills" / f"aisignoff-{role}" / "SKILL.md").read_text(encoding="utf-8")
        head, body = skill.split("\n---\n", 1)
        assert head.startswith(f"---\nname: aisignoff-{role}\ndescription: \"")  # quoted: the text has colons
        assert f"aisignoff guide --role {role}" in body
        assert guide.text(role) in body  # the same text as the command, so the two can't drift
    other = tmp_path / "elsewhere"
    assert main(["--root", str(tmp_path), "guide", "--skills", str(other)]) == 0
    assert (other / "aisignoff-dev" / "SKILL.md").exists()
