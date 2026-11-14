import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from aisignoff import inline
from aisignoff.cli import badge_json, main, percentages
from aisignoff.config import ConfigError, load
from aisignoff.globbing import matches
from aisignoff.model import Declaration, Policy, parse_policy, validate
from aisignoff.project import Project


def write(root: Path, rel: str, text: str = "x\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


TOML_G0 = 'AI-Generation = "G0"\nHuman-Review = "H2"\nAI-Review = "A0"\nReviewed-by = "Jane"\n'
TOML_G2 = ('AI-Generation = "G2"\nHuman-Review = "H1"\nAI-Review = "A2"\nAssisted-by = ["Model A"]\n'
           'AI-Reviewed-by = "Model A, fresh session"\nReviewed-by = "Jane"\n')
HEAD = f"version = 3\n"
ARGS_G0 = ["-g", "G0", "-H", "H2", "-a", "A0", "--reviewed-by", "Jane"]
VALS_G0 = {"AI-Generation": "G0", "Human-Review": "H2", "AI-Review": "A0", "Reviewed-by": ["J"]}
INLINE_G0 = "# AI-Generation: G0\n# Human-Review: H2\n# AI-Review: A0\n# Reviewed-by: J\n"


# ------------------------------------------------------------------ globbing
@pytest.mark.parametrize("pattern,path,expected", [
    ("*.jl", "a.jl", True),
    ("*.jl", "src/a.jl", False),
    ("**/*.jl", "a.jl", True),
    ("**/*.jl", "src/deep/a.jl", True),
    ("src/**", "src/a/b.jl", True),
    ("src/**", "srcx/a.jl", False),
    ("**", "anything/at/all.txt", True),
    ("results/run?.csv", "results/run1.csv", True),
    ("results/run?.csv", "results/run10.csv", False),
    ("data/\\*.csv", "data/*.csv", True),
    ("data/\\*.csv", "data/a.csv", False),
    ("./README.md", "README.md", True),
])
def test_glob(pattern, path, expected):
    assert matches(pattern, path) is expected


# ------------------------------------------------------------------ rules
def d(**kw):
    m = {"AI-Generation": kw.get("g"), "Human-Review": kw.get("h"), "AI-Review": kw.get("a"),
         "Assisted-by": kw.get("assisted"), "Reviewed-by": kw.get("rev"), "AI-Reviewed-by": kw.get("airev")}
    return Declaration.from_mapping({k: v for k, v in m.items() if v}, "test")


@pytest.mark.parametrize("decl,ok", [
    (d(g="G0", h="H0", a="A0", rev="J"), True),
    (d(g="G0", h="H3", a="A2", rev="J", airev="M"), True),                  # human code, AI-reviewed
    (d(g="G0", h="H2", a="A0"), False),                                     # Reviewed-by always needed
    (d(g="G0", h="H2", a="A0", rev="J", assisted="X"), False),              # G0 with Assisted-by
    (d(g="G1", h="H1", a="A0", rev="J", assisted="X"), False),              # G1-G3 need >= A1
    (d(g="G1", h="H1", a="A1", rev="J", assisted="X", airev="X"), True),
    (d(g="G2", h="H1", a="A1", rev="J", assisted="X"), False),              # A1 needs AI-Reviewed-by
    (d(g="G2", h="H1", a="A0", rev="J", assisted="X", airev="X"), False),   # A0 with AI-Reviewed-by
    (d(g="G3", h="H2", a="A3", rev="J", assisted="X", airev="Y"), True),
    (d(g="G3", a="A2", rev="J", assisted="X", airev="Y"), False),           # missing Human-Review
    (d(g="G4", h="H0", a="A0", rev="J"), False),
    (d(g="G0", h="H4", a="A0", rev="J"), False),
    (d(g="G0", h="H0", a="A4", rev="J"), False),
])
def test_rules(decl, ok):
    assert (validate(decl) == []) is ok


def test_no_declaration():
    assert validate(Declaration()) == ["no declaration (not matched by SIGNOFF.toml and no inline tags)"]


# ------------------------------------------------------------------ policy
def test_policy_merge_and_floor():
    p = parse_policy({"*": {"human": "H1"}, "G3": {"human": "H2", "ai": "A2"}})
    assert p.minimum("G0") == ("H1", None)
    assert p.minimum("G2") == ("H1", "A1")          # built-in floor for AI-written content
    assert p.minimum("G3") == ("H2", "A2")
    assert Policy().minimum("G1") == (None, "A1")


def test_policy_enforced():
    p = parse_policy({"*": {"human": "H1"}, "G3": {"ai": "A3"}})
    ok = d(g="G3", h="H2", a="A3", rev="J", assisted="X", airev="Y")
    low_h = d(g="G0", h="H0", a="A0", rev="J")
    low_a = d(g="G3", h="H2", a="A2", rev="J", assisted="X", airev="Y")
    assert validate(ok, p) == []
    assert validate(low_h, p) == ["G0 requires at least H1 by policy (declared H0)"]
    assert "G3 requires at least A3" in validate(low_a, p)[0]


def test_g0_has_no_self_check():
    assert any("G0 has no generating AI session" in e
               for e in validate(d(g="G0", h="H1", a="A1", rev="J", airev="M")))
    assert validate(d(g="G0", h="H1", a="A2", rev="J", airev="M")) == []
    # a policy minimum of A1 means A2 for human-written content
    p = parse_policy({"*": {"ai": "A1"}})
    assert p.minimum("G0") == (None, "A2")
    assert validate(d(g="G0", h="H1", a="A0", rev="J"), p) == ["G0 requires at least A2 (by policy; declared A0)"]


def test_old_none_level_is_invalid(tmp_path):
    # A- (format version 2) is no longer read: it is an invalid level like any other
    assert any("invalid AI-Review 'A-'" in e for e in validate(d(g="G0", h="H1", a="A-", rev="J")))
    with pytest.raises(ValueError, match="must be one of"):
        parse_policy({"*": {"ai": "A-"}})
    write(tmp_path, "SIGNOFF.toml", HEAD + '[[annotations]]\npath = "**"\n' + TOML_G0.replace('"A0"', '"A-"'))
    with pytest.raises(ConfigError, match="invalid AI-Review 'A-'"):
        load(tmp_path)


@pytest.mark.parametrize("bad", [
    {"G9": {"human": "H1"}}, {"*": "H1"}, {"*": {"human": "H5"}}, {"*": {"ai": "A9"}}, {"*": {"robot": "A2"}},
])
def test_policy_errors(bad):
    with pytest.raises(ValueError):
        parse_policy(bad)


def test_policy_in_config(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + '[policy]\n"*" = { human = "H3" }\n'
          f'[[annotations]]\npath = "**"\n{TOML_G0}')
    write(tmp_path, "a.jl")
    (r,) = Project(tmp_path).results()
    assert r.errors == ["G0 requires at least H3 by policy (declared H2)"]


# ------------------------------------------------------------------ config
def test_config_errors(tmp_path):
    bad = {
        'version = 4\n': "version = 3",
        'version = true\n': "version = 3",
        'version = 3\n[[annotations]]\nAI-Generation = "G0"\n': "'path' is required",
        'version = 3\n[[annotations]]\npath = "**"\nAI-Generation = "G7"\n': "invalid AI-Generation",
        'version = 3\n[[annotations]]\npath = "**"\nAI-Review = "A5"\n': "invalid AI-Review",
        'version = 3\n[[annotations]]\npath = "**"\nAI-Verification = "V0"\n': "unknown key",
        'version = 3\n[[annotations]]\npath = "**"\nprecedence = "aggregate"\n': "precedence",
        'version = 3\n[[annotations]\n': "invalid TOML",
        'version = 3\nannotations = [1]\n': "annotations",
        'version = 3\n[[annotations]]\npath = []\n': "must not be empty",
        'version = 3\n[[annotations]]\npath = "**"\nHuman-Review = "H0"\nhuman-review = "H1"\n': "more than once",
        'version = 3\n[policy]\nG7 = { human = "H1" }\n': "unknown key 'G7'",
        'version = 2\n': "aisignoff==1.0.0rc1 migrate",
        'version = 1\n': "aisignoff==1.0.0rc1 migrate",
    }
    for text, message in bad.items():
        (tmp_path / "SIGNOFF.toml").write_text(text)
        with pytest.raises(ConfigError, match=message):
            load(tmp_path)


def test_unknown_settings_are_warnings(tmp_path):
    # a later 1.x may add optional settings: an older install warns about them instead of failing
    (tmp_path / "SIGNOFF.toml").write_text('version = 3\nfoo = 1\n[history]\nbar = 2\n')
    config = load(tmp_path)
    assert len(config.warnings) == 2 and "foo" in config.warnings[0] and "bar" in config.warnings[1]


def test_last_annotation_wins(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + f'[[annotations]]\npath = "**"\n{TOML_G0}'
                                         f'[[annotations]]\npath = "src/**"\n{TOML_G2}')
    write(tmp_path, "README.md")
    write(tmp_path, "src/a.jl")
    res = {r.path: r for r in Project(tmp_path).results()}
    assert res["README.md"].declaration.generation == "G0"
    assert res["src/a.jl"].declaration.generation == "G2"
    assert res["src/a.jl"].declaration.source == "SIGNOFF.toml [2]"
    assert all(not r.errors for r in res.values())
    assert "SIGNOFF.toml" not in res


def test_exclude(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + f'exclude = ["build/**"]\n[[annotations]]\npath = "*.md"\n{TOML_G0}')
    write(tmp_path, "README.md")
    write(tmp_path, "build/out.html")
    assert [r.path for r in Project(tmp_path).results()] == ["README.md"]


# ------------------------------------------------------------------ inline
def test_inline_closest_and_override(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + f'[[annotations]]\npath = "**"\n{TOML_G0}'
                                         f'[[annotations]]\npath = "locked/**"\nprecedence = "override"\n{TOML_G0}')
    header = ("# AI-Generation: G2\n# Human-Review: H3\n# AI-Review: A2\n# Assisted-by: A\n"
              "# AI-Reviewed-by: B\n# Reviewed-by: J\n")
    write(tmp_path, "src/a.jl", header + "f(x) = x\n")
    write(tmp_path, "locked/b.jl", header + "g(x) = x\n")
    res = {r.path: r for r in Project(tmp_path).results()}
    assert (res["src/a.jl"].declaration.short(), res["src/a.jl"].declaration.source) == ("G2 H3 A2", "inline")
    assert res["src/a.jl"].errors == []
    assert res["locked/b.jl"].declaration.source == "SIGNOFF.toml [2]"


@pytest.mark.parametrize("name,line,found", [
    ("f.jl", "# AI-Generation: G1", True),
    ("f.jl", "#= AI-Generation: G1 =#", True),
    ("f.rs", "// AI-Generation: G1", True),
    ("f.c", "/* AI-Generation: G1 */", True),
    ("f.tex", "% AI-Generation: G1", True),
    ("f.lua", "-- AI-Generation: G1", True),
    ("f.md", "<!-- AI-Generation: G1 -->", True),
    ("f.md", "# AI-Generation: G1", False),        # '#' is a heading in Markdown
    ("f.jl", "// AI-Generation: G1", False),       # not Julia comment syntax
    ("f.jl", "AI-Generation: G1", False),          # not a comment
    ("f.jl", "    # AI-Generation: G1", False),    # indented
    ("f.jl", "x = 1  # AI-Generation: G1", False), # trailing comment after code
    ("f.txt", "# AI-Generation: G1", False),       # unknown file type: SIGNOFF.toml only
    ("LICENSE", "-- AI-Generation: G1", False),
])
def test_inline_needs_comment(tmp_path, name, line, found):
    p = write(tmp_path, name, line + "\n")
    dd = inline.parse(p)
    assert (dd is not None and dd.generation == "G1") is found


@pytest.mark.parametrize("line", ["# Human-Review: H2", "# AI-Review: A0", "# AI-Review: A3"])
def test_inline_any_level_line_anchors(tmp_path, line):
    assert inline.parse(write(tmp_path, "f.jl", line + "\n")) is not None


def test_inline_markdown_a_minus(tmp_path):
    p = write(tmp_path, "f.md", "<!-- AI-Review: A0 -->\n")
    assert inline.parse(p).ai == "A0"


def test_inline_ignores_documentation(tmp_path):
    md = write(tmp_path, "README.md", "# Pkg\n\n```julia\n# AI-Generation: G2\n# Human-Review: H1\n```\n")
    assert inline.parse(md) is None
    py = write(tmp_path, "m.py", '"""Example:\n\n    # AI-Generation: G2\n    # Human-Review: H3\n"""\n')
    assert inline.parse(py) is None
    yml = write(tmp_path, "w.yml", "# Rules:\n#   AI-Generation: G0-G3   always\n#   Assisted-by: required for G1-G3\n")
    assert inline.parse(yml) is None


def test_inline_block_must_be_contiguous(tmp_path):
    p = write(tmp_path, "f.jl", "# AI-Generation: G1\n# Human-Review: H0\n# AI-Review: A1\n"
                                "# AI-Reviewed-by: X\n# Reviewed-by: J\n\n# Assisted-by: X\n")
    dd = inline.parse(p)
    assert dd.generation == "G1" and dd.assisted_by == ()
    assert validate(dd) == ["G1 needs Assisted-by (tool and model)"]


def test_inline_two_blocks(tmp_path):
    p = write(tmp_path, "f.jl", "# AI-Generation: G1\n\n# AI-Generation: G2\n")
    assert "more than one inline declaration block" in inline.parse(p).problems


def test_inline_c_block_comment(tmp_path):
    p = write(tmp_path, "k.c", "/*\n * AI-Generation: G1\n * Human-Review: H1\n * AI-Review: A2\n"
                               " * Assisted-by: X\n * AI-Reviewed-by: X, fresh session\n * Reviewed-by: J\n */\n")
    dd = inline.parse(p)
    assert dd.short() == "G1 H1 A2" and validate(dd) == []


def test_inline_only_header(tmp_path):
    assert inline.parse(write(tmp_path, "f.jl", "\n" * 40 + "# AI-Generation: G1\n")) is None


def test_inline_binary_ignored(tmp_path):
    p = tmp_path / "data.jl"
    p.write_bytes(b"\x00\x01# AI-Generation: G1\n")
    assert inline.parse(p) is None


def test_inline_duplicate(tmp_path):
    p = write(tmp_path, "f.py", "# AI-Generation: G1\n# AI-Generation: G2\n")
    assert "more than once" in inline.parse(p).problems[0]


def test_inline_old_v_levels_are_not_a_declaration(tmp_path):
    # AI-Verification (format version 1) is no longer read: the file has no inline declaration
    p = write(tmp_path, "f.jl", "# AI-Verification: V0\n# Tested-by: J\n")
    assert inline.parse(p) is None


def test_inline_write_roundtrip(tmp_path):
    p = write(tmp_path, "run.sh", "#!/bin/bash\necho hi\n")
    values = {"AI-Generation": "G1", "Human-Review": "H1", "AI-Review": "A1", "Assisted-by": ["Copilot"],
              "AI-Reviewed-by": ["Copilot"], "Reviewed-by": ["J"]}
    inline.write(p, values)
    text = p.read_text()
    assert text.startswith("#!/bin/bash\n# AI-Generation: G1\n")
    assert text.endswith("\necho hi\n")
    inline.write(p, {**values, "AI-Generation": "G2"})
    dd = inline.parse(p)
    assert dd.generation == "G2" and dd.problems == []
    assert p.read_text().count("AI-Generation") == 1


def test_inline_write_front_matter_and_markdown(tmp_path):
    p = write(tmp_path, "post.md", "---\ntitle: x\n---\n# Heading\n")
    inline.write(p, VALS_G0)
    lines = p.read_text().splitlines()
    assert lines[:3] == ["---", "title: x", "---"]
    assert lines[3] == "<!-- AI-Generation: G0 -->"
    assert inline.parse(p).short() == "G0 H2 A0"


def test_inline_write_unknown_type(tmp_path):
    p = write(tmp_path, "results.csv", "a,b\n")
    with pytest.raises(ValueError, match="SIGNOFF.toml"):
        inline.write(p, VALS_G0)


def test_inline_write_keeps_crlf_bom_and_other_breaks(tmp_path):
    p = tmp_path / "a.py"
    p.write_bytes("﻿#!x\r\ns = 'a b'\r\nform\ffeed\r\n".encode())
    inline.write(p, VALS_G0)
    out = p.read_bytes().decode()
    assert out.startswith("﻿#!x\r\n# AI-Generation: G0\r\n")
    assert "s = 'a b'\r\nform\ffeed\r\n" in out
    assert "\n" not in out.replace("\r\n", "")
    assert inline.parse(p).generation == "G0"


def test_inline_bom_first_line(tmp_path):
    p = tmp_path / "b.jl"
    p.write_bytes(("﻿" + INLINE_G0).encode())
    assert validate(inline.parse(p)) == []


def test_yaml_documents_are_not_front_matter(tmp_path):
    p = write(tmp_path, "multi.yml", "---\n" + "".join(f"k{i}: {i}\n" for i in range(35)) + "---\nz: 1\n")
    inline.write(p, VALS_G0)
    assert p.read_text().startswith("# AI-Generation: G0\n")
    inline.write(p, {**VALS_G0, "Human-Review": "H3"})
    assert p.read_text().count("AI-Generation") == 1 and inline.parse(p).human == "H3"


def test_long_front_matter_is_refused(tmp_path):
    p = write(tmp_path, "post.md", "---\n" + "a: 1\n" * 40 + "---\ntext\n")
    before = p.read_bytes()
    with pytest.raises(ValueError, match="SIGNOFF.toml"):
        inline.write(p, VALS_G0)
    assert p.read_bytes() == before


def test_inline_header_must_fit_completely(tmp_path):
    values = {"AI-Generation": "G2", "Human-Review": "H1", "AI-Review": "A2", "Assisted-by": ["C"],
              "AI-Reviewed-by": ["O"], "Reviewed-by": ["J"]}
    p = write(tmp_path, "edge.md", "---\n" + "a: 1\n" * 24 + "---\ntext\n")   # front matter ends at line 26
    before = p.read_bytes()
    with pytest.raises(ValueError, match="first 30 lines"):
        inline.write(p, values)
    assert p.read_bytes() == before


def test_markdown_fences(tmp_path):
    p = write(tmp_path, "README.md", "# X\n\n```markdown\n<!-- AI-Generation: G2 -->\n```\n")
    assert inline.parse(p) is None
    q = write(tmp_path, "r.md", "```\n~~~\n<!-- AI-Generation: G2 -->\n```\n")
    assert inline.parse(q) is None


def test_closest_fills_missing_axes(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + f'[[annotations]]\npath = "**"\n{TOML_G2}')
    write(tmp_path, "a.jl", "# Human-Review: H3\n# Reviewed-by: Bob\n\nf() = 1\n")
    (r,) = [r for r in Project(tmp_path).results() if r.path == "a.jl"]
    dd = r.declaration
    assert dd.short() == "G2 H3 A2"
    assert dd.reviewed_by == ("Bob",) and dd.assisted_by == ("Model A",)
    assert r.errors == [] and dd.source == "inline + SIGNOFF.toml [1]"


def test_inline_stray_list_keys_are_errors(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + f'[[annotations]]\npath = "**"\n{TOML_G0}')
    write(tmp_path, "a.jl", "# Human-Review: H1\n# Reviewed-by: J\n# Assisted-by: Copilot\n")
    (r,) = [r for r in Project(tmp_path).results() if r.path == "a.jl"]
    assert "inline Assisted-by without an inline AI-Generation line" in r.errors


# ------------------------------------------------------------------ git integration
def test_git_respects_gitignore(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".gitignore", "*.log\n")
    write(tmp_path, "a.jl")
    write(tmp_path, "debug.log")
    write(tmp_path, "SIGNOFF.toml", HEAD + f'[[annotations]]\npath = "**"\n{TOML_G0}')
    assert [r.path for r in Project(tmp_path).results()] == [".gitignore", "a.jl"]


def test_git_failure_is_an_error(tmp_path):
    (tmp_path / ".git").mkdir()
    write(tmp_path, "a.txt")
    assert main(["--root", str(tmp_path), "lint"]) == 2


# ------------------------------------------------------------------ CLI
def test_cli_workflow(tmp_path, capsys):
    root = str(tmp_path)
    write(tmp_path, "src/solver.jl")
    write(tmp_path, "results/run1.csv")
    write(tmp_path, "README.md")

    assert main(["--root", root, "lint"]) == 1
    assert main(["--root", root, "init", *ARGS_G0]) == 0
    assert main(["--root", root, "lint"]) == 0
    assert main(["--root", root, "init"]) == 2

    assert main(["--root", root, "annotate", "results/**", "-g", "G2", "-H", "H1", "-a", "A2",
                 "--reviewed-by", "Jane"]) == 2                                  # missing Assisted-by ...
    assert main(["--root", root, "annotate", "results/**", "-g", "G2", "-H", "H1", "-a", "A0",
                 "--assisted-by", "M", "--reviewed-by", "Jane"]) == 2           # G2 needs >= A1
    assert main(["--root", root, "annotate", "results/**", "-g", "G2", "-H", "H1", "-a", "A2",
                 "--assisted-by", "Model A", "--ai-reviewed-by", "Model A, fresh session",
                 "--reviewed-by", "Jane"]) == 0
    capsys.readouterr()
    assert main(["--root", root, "report", "--json"]) == 0
    data = {x["path"]: x for x in json.loads(capsys.readouterr().out)["files"]}
    assert data["results/run1.csv"]["AI-Review"] == "A2"
    assert data["src/solver.jl"]["Human-Review"] == "H2"

    out = tmp_path / "badges"
    assert main(["--root", root, "badge", "--out", str(out)]) == 0
    assert json.loads((out / "aisignoff-generation.json").read_text())["message"] == "G0 67% · G2 33%"
    assert json.loads((out / "aisignoff-human-review.json").read_text())["message"] == "H1 33% · H2 67%"
    assert json.loads((out / "aisignoff-ai-review.json").read_text())["message"] == "A0 67% · A2 33%"


def test_annotate_respects_policy(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + '[policy]\n"*" = { human = "H2" }\n')
    write(tmp_path, "a.txt")
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.txt"),
                 "-g", "G0", "-H", "H1", "-a", "A0", "--reviewed-by", "J"]) == 2
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.txt"), *ARGS_G0]) == 0


def test_cli_annotate_directory_and_quotes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "notebooks/a.ipynb", "{}")
    assert main(["annotate", "notebooks", "-g", "G1", "-H", "H0", "-a", "A1",
                 "--assisted-by", 'Model "X" \\ beta', "--ai-reviewed-by", "Model X",
                 "--reviewed-by", "Jürgen"]) == 0
    a = load(tmp_path).annotations[0]
    assert a.paths == ("notebooks/**",)
    assert a.values["Assisted-by"] == ('Model "X" \\ beta',)
    assert a.values["Reviewed-by"] == ("Jürgen",)


def test_annotate_keeps_escapes_and_escapes_literals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for n in ("what?.txt", "whatZ.txt", "star*.txt", "a[1].txt"):
        write(tmp_path, n)
    assert main(["annotate", "what?.txt", *ARGS_G0]) == 0
    assert main(["annotate", "star\\*.txt", *ARGS_G0]) == 0
    assert main(["annotate", "a[1].txt", *ARGS_G0]) == 0
    assert [a.paths[0] for a in load(tmp_path).annotations] == ["what\\?.txt", "star\\*.txt", "a[1].txt"]
    res = {r.path: r.declaration.source for r in Project(tmp_path).results()}
    assert res["whatZ.txt"] == "none" and res["star*.txt"] == "SIGNOFF.toml [2]"


def test_annotate_glob_relative_to_cwd(tmp_path, monkeypatch):
    write(tmp_path, "top.jl")
    write(tmp_path, "sub/inner.jl")
    monkeypatch.chdir(tmp_path / "sub")
    assert main(["--root", "..", "annotate", "*.jl", *ARGS_G0]) == 0
    assert load(tmp_path).annotations[0].paths == ("sub/*.jl",)


def test_annotate_bad_globs_refused(tmp_path, monkeypatch):
    write(tmp_path, "top.jl")
    write(tmp_path, "sub/inner.jl")
    monkeypatch.chdir(tmp_path / "sub")
    assert main(["--root", "..", "annotate", "../*.jl", *ARGS_G0]) == 2
    assert main(["--root", "..", "annotate", str(tmp_path) + "/*.jl", *ARGS_G0]) == 2
    assert main(["--root", "..", "annotate", "missing.jl", *ARGS_G0]) == 2
    assert not (tmp_path / "SIGNOFF.toml").exists()


def test_annotate_through_symlinked_root(tmp_path, monkeypatch):
    real = tmp_path / "real"
    write(real, "sub/a.jl")
    (tmp_path / "link").symlink_to(real)
    monkeypatch.chdir(tmp_path / "link" / "sub")
    link = str(tmp_path / "link")
    assert main(["--root", link, "annotate", "*.jl", *ARGS_G0]) == 0
    assert main(["--root", link, "annotate", "a.jl", *ARGS_G0]) == 0
    assert main(["--root", link, "annotate", link, *ARGS_G0]) == 0
    assert [a.paths[0] for a in load(real).annotations] == ["sub/*.jl", "sub/a.jl", "**"]


def test_annotate_symlink_not_followed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "real/t.txt")
    (tmp_path / "lnk.txt").symlink_to("real/t.txt")
    assert main(["annotate", "lnk.txt", *ARGS_G0]) == 0
    assert load(tmp_path).annotations[0].paths == ("lnk.txt",)


@pytest.mark.parametrize("bad", ["a\x7fb", "Jane\nimport os", "  "])
def test_annotate_rejects_control_characters(tmp_path, bad):
    write(tmp_path, "a.py", "x = 1\n")
    args = ["-g", "G0", "-H", "H2", "-a", "A0", "--reviewed-by", bad]
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"), *args]) == 2
    assert not (tmp_path / "SIGNOFF.toml").exists()
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"), "--inline", *args]) == 2
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_inline_with_precedence_refused(tmp_path):
    write(tmp_path, "a.py", "x = 1\n")
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"), "--inline",
                 "--precedence", "override", *ARGS_G0]) == 2


def test_lint_reports_undeclared_and_unused(tmp_path, capsys):
    write(tmp_path, "SIGNOFF.toml", HEAD + f'[[annotations]]\npath = "*.md"\n{TOML_G0}'
                                         f'[[annotations]]\npath = "nothing/**"\n{TOML_G0}')
    write(tmp_path, "README.md")
    write(tmp_path, "src/a.jl")
    assert main(["--root", str(tmp_path), "lint"]) == 1
    out = capsys.readouterr().out
    assert "no declaration" in out and "src/a.jl" in out
    assert "annotation [2] matches no file" in out
    write(tmp_path, "SIGNOFF.toml", HEAD + f'[[annotations]]\npath = "**"\n{TOML_G0}'
                                         f'[[annotations]]\npath = "nothing/**"\n{TOML_G0}')
    assert main(["--root", str(tmp_path), "lint"]) == 0
    assert main(["--root", str(tmp_path), "lint", "--strict"]) == 1


def test_lint_missing_root_and_empty(tmp_path):
    assert main(["--root", str(tmp_path / "missing"), "lint"]) == 2
    assert main(["--root", str(tmp_path), "lint"]) == 1
    assert main(["--root", str(tmp_path / "missing"), "init"]) == 2


def test_report_and_badge_agree(tmp_path, capsys):
    write(tmp_path, "SIGNOFF.toml", HEAD + '[[annotations]]\npath = "**"\nAI-Generation = "G2"\n'
                                         'Human-Review = "H1"\nAI-Review = "A1"\nReviewed-by = "J"\n')
    write(tmp_path, "a.txt")
    assert main(["--root", str(tmp_path), "report"]) == 0
    assert "undeclared" in capsys.readouterr().out
    assert main(["--root", str(tmp_path), "badge", "--out", str(tmp_path / "b")]) == 0
    assert "undeclared 100%" in (tmp_path / "b" / "aisignoff-generation.json").read_text()


# ------------------------------------------------------------------ badges
@pytest.mark.parametrize("counts", [
    dict(G0=4, G1=30, G2=39, G3=39, undeclared=1), dict(G1=3, G2=38, G3=38, undeclared=1),
    dict(G0=1, G1=1, G2=1), dict(G0=1, G1=998),
])
def test_percentages_sum_and_sign(counts):
    pct = percentages(counts)
    assert sum(pct.values()) == 100 and min(pct.values()) >= 0


def test_badge_small_share_shown():
    assert badge_json("x", Counter(G0=1, G1=998), ["G0", "G1"], "000")["message"] == "G0 <1% · G1 100%"


# ------------------------------------------------------------------ regressions from the G/H/A review
def test_policy_array_is_a_clean_error(tmp_path):
    (tmp_path / "SIGNOFF.toml").write_text('version = 3\n[policy]\n"*" = { human = ["H1"] }\n')
    with pytest.raises(ConfigError, match="human must be one of"):
        load(tmp_path)
    write(tmp_path, "a.txt")
    assert main(["--root", str(tmp_path), "lint"]) == 2


def test_badge_labels(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + f'[[annotations]]\npath = "**"\n{TOML_G0}')
    write(tmp_path, "a.txt")
    assert main(["--root", str(tmp_path), "badge", "--out", str(tmp_path / "b")]) == 0
    labels = [json.loads((tmp_path / "b" / f).read_text())["label"]
              for f in ("aisignoff-generation.json", "aisignoff-human-review.json", "aisignoff-ai-review.json")]
    assert labels == ["AI generation", "human review", "AI review"]


def test_annotate_inline_missing_file(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "nope.py"), "--inline", *ARGS_G0]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_todo_placeholder_in_toml(tmp_path, capsys):
    (tmp_path / "SIGNOFF.toml").write_text(
        'version = 3\n[[annotations]]\npath = "**"\nAI-Generation = "G3"\nHuman-Review = "TODO"\n'
        'AI-Review = "A2"\nAssisted-by = "M"\nAI-Reviewed-by = "M, fresh"\nReviewed-by = "TODO"\n')
    (tmp_path / "a.jl").write_text("x = 1\n")
    assert main(["--root", str(tmp_path), "lint"]) == 1
    out = capsys.readouterr()
    assert "Human-Review is still TODO" in out.out and "Reviewed-by is still TODO" in out.out
    assert "invalid" not in out.out + out.err



AGENT_TODO = ["-g", "G2", "-H", "TODO", "-a", "A1", "--assisted-by", "Model A",
              "--ai-reviewed-by", "Model A, generating session", "--reviewed-by", "TODO"]


def test_annotate_todo_placeholder(tmp_path, capsys):
    write(tmp_path, "SIGNOFF.toml", HEAD)
    write(tmp_path, "a.py")
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"), *AGENT_TODO]) == 0
    a = load(tmp_path).annotations[0]
    assert a.values["Human-Review"] == "TODO" and a.values["Reviewed-by"] == ("TODO",)
    capsys.readouterr()
    # lint fails until a person fills in the human review
    assert main(["--root", str(tmp_path), "lint"]) == 1
    out = capsys.readouterr().out
    assert "Human-Review is still TODO (to be filled in by a person)" in out
    assert "Reviewed-by is still TODO" in out and "migrate" not in out


def test_annotate_todo_without_reviewed_by(tmp_path):
    # -H TODO doesn't need --reviewed-by yet
    write(tmp_path, "a.py")
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"),
                 "-g", "G2", "-H", "TODO", "-a", "A1", "--assisted-by", "M", "--ai-reviewed-by", "M"]) == 0


def test_annotate_todo_still_checks_other_axes(tmp_path):
    write(tmp_path, "a.py")
    base = ["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"), "-H", "TODO"]
    # G2 without Assisted-by, G2 with A0, and G0 with A1 are still refused
    assert main([*base, "-g", "G2", "-a", "A1", "--ai-reviewed-by", "M"]) == 2
    assert main([*base, "-g", "G2", "-a", "A0", "--assisted-by", "M"]) == 2
    assert main([*base, "-g", "G0", "-a", "A1", "--ai-reviewed-by", "M"]) == 2
    assert not (tmp_path / "SIGNOFF.toml").exists()


def test_annotate_todo_respects_ai_policy(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + '[policy]\nG2 = { human = "H2", ai = "A2" }\n')
    write(tmp_path, "a.py")
    base = ["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"), "-g", "G2", "-H", "TODO",
            "--assisted-by", "M"]
    assert main([*base, "-a", "A1", "--ai-reviewed-by", "M"]) == 2   # AI minimum still applies
    assert main([*base, "-a", "A2", "--ai-reviewed-by", "M2"]) == 0  # human minimum waits for the person


def test_annotate_todo_inline(tmp_path, capsys):
    p = write(tmp_path, "a.py", "x = 1\n")
    assert main(["--root", str(tmp_path), "annotate", str(p), "--inline", *AGENT_TODO]) == 0
    text = p.read_text()
    assert "# Human-Review: TODO" in text and "# Reviewed-by: TODO" in text
    res = {r.path: r for r in Project(tmp_path).results()}
    assert res["a.py"].declaration.human == "TODO"
    assert any("Human-Review is still TODO" in e for e in res["a.py"].errors)
    # filling it in makes it pass
    p.write_text(text.replace("Human-Review: TODO", "Human-Review: H1").replace("Reviewed-by: TODO", "Reviewed-by: J"))
    assert main(["--root", str(tmp_path), "lint"]) == 0

def test_annotate_todo_human_adds_reviewed_by_todo(tmp_path):
    write(tmp_path, "a.py")
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"),
                 "-g", "G2", "-H", "TODO", "-a", "A1", "--assisted-by", "M", "--ai-reviewed-by", "M"]) == 0
    toml = (tmp_path / "SIGNOFF.toml").read_text()
    assert 'Reviewed-by = ["TODO"]' in toml
    # a name given on the command line is kept
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"), "-g", "G2", "-H", "TODO",
                 "-a", "A1", "--assisted-by", "M", "--ai-reviewed-by", "M", "--reviewed-by", "Jane"]) == 0
    assert 'Reviewed-by = ["Jane"]' in (tmp_path / "SIGNOFF.toml").read_text()


def test_annotate_inline_refuses_files_outside_root(tmp_path, monkeypatch, capsys):
    root = tmp_path / "p"
    root.mkdir()
    outside = write(tmp_path, "x.py")
    monkeypatch.chdir(tmp_path)
    assert main(["--root", "p", "annotate", "x.py", "--inline", *ARGS_G0]) == 1
    assert "outside the project root" in capsys.readouterr().err
    assert outside.read_text() == "x\n"
    inside = write(root, "y.py")
    assert main(["--root", "p", "annotate", "p/y.py", "--inline", *ARGS_G0]) == 0
    assert "AI-Generation: G0" in inside.read_text()


def test_init_suggests_excluding_reviews(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert "reviews/**" in (tmp_path / "SIGNOFF.toml").read_text()


# ------------------------------------------------------------------ AIDECL.toml (name before aisignoff)
def test_old_filename_is_refused(tmp_path, capsys):
    write(tmp_path, "AIDECL.toml", HEAD + '[[annotations]]\npath = "**"\n' + TOML_G0)
    write(tmp_path, "a.py")
    with pytest.raises(ConfigError, match="no longer read.*aisignoff==1.0.0rc1 migrate"):
        load(tmp_path)
    assert main(["--root", str(tmp_path), "lint"]) == 2
    assert "AIDECL.toml" in capsys.readouterr().err
    assert main(["--root", str(tmp_path), "init"]) == 2
    assert main(["--root", str(tmp_path), "annotate", str(tmp_path / "a.py"), *ARGS_G0]) == 2
    assert not (tmp_path / "SIGNOFF.toml").exists()


def test_migrate_is_gone(tmp_path):
    with pytest.raises(SystemExit):
        main(["--root", str(tmp_path), "migrate"])


# ------------------------------------------------------------------ version
def test_version_comes_from_pyproject():
    import tomllib
    from importlib.metadata import PackageNotFoundError, version
    import aisignoff
    try:
        installed = version("aisignoff")
    except PackageNotFoundError:
        pytest.skip("aisignoff is not installed")
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())["project"]["version"]
    assert aisignoff.__version__ == installed == pyproject
