"""Probe: the grammar of contract 4.3 / docs/history.md "The exact form" against what lint reads.

usage: python probe_grammar.py /path/to/aisignoff /scratch/dir"""
import sys
from pathlib import Path

from lib import DECL, Repo, show

exe, work = sys.argv[1], Path(sys.argv[2])

TEMPLATE = """## AI declaration

- [ ] **G0** Human-written
- [x] **G3** AI-autonomous: an agent produced it largely end to end
- [x] **Claude Opus** (Anthropic)
- [ ] **Other:**
{h}
- [x] **A0** No independent AI review
- [ ] **A1** A new AI session, without the generating conversation, checked the final change
"""


def check(name, description, *extra):
    r = Repo(work / "grammar", exe)
    r.g("switch", "-qc", "feature")
    r.write("a.txt", "one\n")
    r.commit("add a")
    (work / "description.md").write_text(description)
    code, out, err = r.cli("lint", "--base", "main", "--declare-from", str(work / "description.md"),
                           "--author", "Dev", *extra)
    show(name, code, out, err)
    code, out, err = r.cli("report", "--json", "--base", "main", "--declare-from", str(work / "description.md"),
                           "--author", "Dev")
    import json
    f = next(f for f in json.loads(out)["files"] if f["path"] == "a.txt")
    print("   a.txt:", f["AI-Generation"], f["Human-Review"], f["AI-Review"], f["Reviewed-by"], "\n")


# 1. contract 4.3: "Human review: the highest ticked H box. ... A ticked box above an unticked one is an error."
check("G1: H2 ticked, H0 and H1 unticked (the contract: an error)",
      TEMPLATE.format(h="- [ ] **H0** I checked the result as a whole\n- [ ] **H1** I ran the tests\n"
                        "- [x] **H2** I read every line"))
check("control: H0, H1, H2 all ticked",
      TEMPLATE.format(h="- [x] **H0** I checked the result as a whole\n- [x] **H1** I ran the tests\n"
                        "- [x] **H2** I read every line"))

# 2. key lines: "has the form `Key: value`, with no space before the colon"
check("G2a: key lines without a space after the colon", DECL.replace(": ", ":"))
check("G2b: key line with a space before the colon (must declare nothing)", DECL.replace("Human-Review:", "Human-Review :"))
check("G2c: indented key lines (must declare nothing)", "".join("  " + line + "\n" for line in DECL.splitlines()))
check("G2d: lower-case level (an invalid level, an error)", DECL.replace("G3", "g3"))
check("G2e: the first line of a description is not a subject line",
      "AI-Generation: G3\nHuman-Review: H1\nAI-Review: A0\nAssisted-by: Claude Opus 5.5 (Anthropic)\nReviewed-by: Dev\n")
# 3. boxes: "+" and numbered markers aren't boxes
check("G3: '+' list markers are not boxes",
      TEMPLATE.format(h="- [x] **H1** I ran the tests").replace("- [", "+ ["))
# 4. unclosed fence / comment opens none
check("G4: an unclosed fence before the declaration hides nothing", "```\nsome code\n\n" + DECL)
check("G5: a declaration inside a closed HTML comment declares nothing", "<!--\n" + DECL + "-->\n")
# 5. findings line: looser form, most severe counts, invalid is an error
A1 = DECL.replace("AI-Review: A0", "AI-Review: A1\nAI-Reviewed-by: Claude Opus 5.5 (Anthropic), new session")
check("G6: two findings lines, the most severe counts", A1 + "- **AI-Review-Findings:** minor\nai-review-findings: major\n")
check("G7: an invalid findings value is an error", A1 + "AI-Review-Findings: some\n")
