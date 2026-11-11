import json
import re

import pytest

from aisignoff import visualize
from aisignoff.cli import main
from aisignoff.project import Project

from test_aisignoff import HEAD, TOML_G0, TOML_G2, write


@pytest.fixture
def repo(tmp_path):
    """src/ mixes G0 and G2, lib/deep/er/ holds one G2 file, and one file is undeclared."""
    write(tmp_path, "SIGNOFF.toml", HEAD + '[[annotations]]\npath = "**"\n' + TOML_G0
          + '[[annotations]]\npath = ["src/gen*.py", "lib/**"]\n' + TOML_G2
          + '[[annotations]]\npath = "src/bad.py"\nAI-Generation = "G3"\n')
    write(tmp_path, "README.md", "a\nb\nc\n")
    write(tmp_path, "src/hand.py", "x\n" * 10)
    write(tmp_path, "src/gen1.py", "x\n" * 5)
    write(tmp_path, "src/gen2.py", "x\n" * 5)
    write(tmp_path, "src/bad.py", "x\n")
    write(tmp_path, "lib/deep/er/g.py", "x\n" * 2)
    return tmp_path


def tree_of(root):
    project = Project(root)
    return visualize.build_tree(project.root, project.results())


def child(node, name):
    return next(c for c in node["children"] if c["name"] == name)


def test_tree_counts_per_folder(repo):
    tree = tree_of(repo)
    assert tree["files"] == 6 and tree["lines"] == 3 + 10 + 5 + 5 + 1 + 2 and tree["errors"] == 1
    src = child(tree, "src")
    assert src["counts"]["AI-Generation"]["files"] == {"G0": 1, "G2": 2, "undeclared": 1}
    assert src["counts"]["AI-Generation"]["lines"] == {"G0": 10, "G2": 10, "undeclared": 1}
    assert src["counts"]["Human-Review"]["files"] == {"H1": 2, "H2": 1, "undeclared": 1}
    bad = child(src, "bad.py")
    assert bad["levels"] == {"AI-Generation": "undeclared", "Human-Review": "undeclared", "AI-Review": "undeclared"}
    assert bad["errors"] and bad["declaration"]["source"] == "SIGNOFF.toml [3]"


def test_tree_merges_single_folder_chains_and_sorts(repo):
    tree = tree_of(repo)
    assert [c["name"] for c in tree["children"]] == ["lib/deep/er", "src", "README.md"]
    assert child(tree, "lib/deep/er")["path"] == "lib/deep/er"
    assert child(child(tree, "lib/deep/er"), "g.py")["path"] == "lib/deep/er/g.py"


def test_tree_leaves_out_excluded_files(repo):
    text = (repo / "SIGNOFF.toml").read_text().replace("version = 3\n", 'version = 3\nexclude = ["src/bad.py"]\n')
    (repo / "SIGNOFF.toml").write_text(text)
    tree = tree_of(repo)
    assert tree["files"] == 5 and tree["errors"] == 0
    assert "bad.py" not in [c["name"] for c in child(tree, "src")["children"]]


def test_text_tree(repo):
    out = visualize.render_text(tree_of(repo))
    lines = out.splitlines()
    assert lines[0].split() == ["files", "Generation", "Human", "review", "AI", "review"]
    assert re.match(r"^\.\s+6\s+G0 33% · G2 50% · undeclared 17%", lines[1])
    assert any(line.startswith("├─ lib/deep/er/") for line in lines)
    # a file without a valid declaration is listed under its folder, even without --files
    assert any("bad.py" in line and "✗" in line for line in lines)
    assert not any("hand.py" in line for line in lines)
    assert "hand.py" in visualize.render_text(tree_of(repo), files=True)


def test_text_tree_depth_and_lines(repo):
    out = visualize.render_text(tree_of(repo), weight="lines", max_depth=0)
    assert len(out.splitlines()) == 2
    assert out.splitlines()[0].split()[0] == "lines"
    assert out.splitlines()[1].split()[1] == "26"


def test_markdown_tree(repo):
    out = visualize.render_markdown(tree_of(repo))
    assert out.startswith("| Folder | Files | Generation | Human review | AI review |")
    assert "**src/** ✗ 1 | 4 | G0 25% · G2 50% · undeclared 25%" in out
    assert "<details><summary>✗ 1 file(s) without a valid declaration</summary>" in out
    assert "- `src/bad.py`:" in out


def test_markdown_escapes_names(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + '[[annotations]]\npath = "**"\n' + TOML_G0)
    write(tmp_path, "a|b<c>/x.py")
    out = visualize.render_markdown(tree_of(tmp_path))
    assert "**a\\|b&lt;c&gt;/**" in out


def test_html_report_embeds_tree_safely(tmp_path):
    write(tmp_path, "SIGNOFF.toml", HEAD + '[[annotations]]\npath = "**"\n' + TOML_G0)
    write(tmp_path, "</script><!--.txt")
    out = tmp_path.parent / "new" / "dir" / "report.html"   # missing folders are created
    assert main(["--root", str(tmp_path), "report", "--html", str(out), "--title", "A & <B>"]) == 0
    html = out.read_text(encoding="utf-8")
    assert "<title>AI signoff · A &amp; &lt;B&gt;</title>" in html
    assert "__AISIGNOFF" not in html
    assert html.count("</script>") == 2   # only the two real ones: file names can't close the element
    data = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    parsed = json.loads(data)
    assert parsed["meta"]["title"] == "A & <B>"
    leaf = parsed["tree"]["children"][0]["children"][0]   # the folder "<" holds "script><!--.txt"
    assert leaf["path"] == "</script><!--.txt"
    assert [a["key"] for a in parsed["meta"]["axes"]] == ["AI-Generation", "Human-Review", "AI-Review"]


def test_html_links_to_github_on_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
    meta = visualize.report_meta(tmp_path)
    assert meta["title"] == "org/repo" and meta["commit"] == "abc123"
    assert meta["link"] == "https://github.com/org/repo/blob/abc123/"


def test_cli_tree_outputs(repo, capsys):
    assert main(["--root", str(repo), "report", "--tree", "--json"]) == 0
    tree = json.loads(capsys.readouterr().out)
    assert tree["files"] == 6 and tree["children"][0]["name"] == "lib/deep/er"
    assert main(["--root", str(repo), "report", "--tree", "--markdown", "--depth", "1"]) == 0
    assert capsys.readouterr().out.startswith("| Folder |")
    assert main(["--root", str(repo), "report", "--tree", "--weight", "lines"]) == 0
    assert capsys.readouterr().out.split()[0] == "lines"


@pytest.mark.parametrize("args", [["--markdown"], ["--depth", "1"], ["--tree", "--depth", "-1"],
                                  ["--tree", "--json", "--markdown"]])
def test_cli_tree_usage_errors(repo, capsys, args):
    assert main(["--root", str(repo), "report", *args]) == 2
    assert "aisignoff report:" in capsys.readouterr().err


def test_template_is_package_data():
    from importlib import resources
    text = resources.files("aisignoff").joinpath("report.html").read_text(encoding="utf-8")
    assert "__AISIGNOFF_DATA__" in text and "__AISIGNOFF_TITLE__" in text
