"""Ranking tests against a fixture registry (no real session data)."""
import importlib.machinery, importlib.util, pathlib, unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "seshpick.py"
loader = importlib.machinery.SourceFileLoader("cs_module", str(SRC))
spec = importlib.util.spec_from_loader("cs_module", loader)
cs = importlib.util.module_from_spec(spec)
loader.exec_module(cs)

def row(title, cwd="/home/u/work/app", project="App", day=1, kind="custom"):
    return dict(id=f"{day:08x}-0000-0000-0000-000000000000", agent="claude", cwd=cwd, title=title,
                project=project, titleKind=kind, updatedAt=f"2026-01-{day:02d}T00:00:00+00:00", state="closed")

# newest first, as registry() delivers them
FIXTURE = [
    row("weekly-retriage", day=30),                                   # "triage" only as a substring
    row("notes", cwd="/home/u/work/triage-tools", project="Tools", day=29),  # folder match
    row("app-triage", day=20),                                        # whole segment
    row("trace-image", day=28),                                       # letters t r i a g e scattered
    row("triage", day=10),                                            # exact
    row("three-things", day=27),                                      # "hr" inside "three"
    row("payroll-hr", day=15),                                        # segment "hr"
    row("c-orchestrator", day=26),
    row("b-orchestrator", day=25),
    row("a-orchestrator", day=24),
    row("daily", cwd="/home/u/work/orchard", project="Orchard", day=23),
    row("harbor-development", day=12),
    row("harbor-durability", day=22),
    row("dev-tools", day=21),
    row("Draft the HR handbook for the new office", day=31, kind="prompt"),  # newer, but a first prompt
]

def titles(query):
    return [r["title"] for r in cs.rank(FIXTURE, query)]

class RankTests(unittest.TestCase):
    def test_segment_beats_substring_and_folder(self):
        self.assertEqual(titles("triage")[:4], ["triage", "app-triage", "weekly-retriage", "notes"])

    def test_scattered_letters_never_match(self):
        self.assertNotIn("trace-image", titles("triage"))

    def test_short_word_prefers_whole_segment(self):
        self.assertEqual(titles("hr")[0], "payroll-hr")
        self.assertIn("three-things", titles("hr"))

    def test_same_tier_orders_by_recency(self):
        self.assertEqual(titles("orch")[:3], ["c-orchestrator", "b-orchestrator", "a-orchestrator"])
        self.assertEqual(titles("orch")[3], "daily")   # folder match comes after all title matches

    def test_two_word_query_requires_every_word(self):
        self.assertEqual(titles("harbor dev"), ["harbor-development"])

    def test_named_session_beats_prompt_title_in_same_tier(self):
        self.assertEqual(titles("hr")[:2], ["payroll-hr", "Draft the HR handbook for the new office"])

    def test_nothing_matches_gives_empty_list(self):
        self.assertEqual(titles("zzzz"), [])

    def test_empty_query_keeps_recency_order(self):
        self.assertEqual(titles(""), [r["title"] for r in FIXTURE])

    def test_case_insensitive(self):
        self.assertEqual(titles("TRIAGE")[0], "triage")

class ProjectAndOpenerTests(unittest.TestCase):
    def test_config_mapping_wins_then_rex_label_then_folder_name(self):
        cfg = {"projects": {"work/acme": "Acme"}}
        self.assertEqual(cs.project_of("/home/u/work/acme/api", cfg, {"Other": "s1"}), "Acme")
        self.assertEqual(cs.project_of("/home/u/work/other/api", {}, {"Other": "s1"}), "Other")
        self.assertEqual(cs.project_of("/home/u/work/misc/api", {}, {}), "api")

    def test_opener_detection_order(self):
        self.assertEqual(cs.detect_opener({"REX_SERVER": "x", "TMUX": "y"}), "rex")
        self.assertEqual(cs.detect_opener({"TMUX": "y", "KITTY_WINDOW_ID": "1"}), "tmux")
        self.assertEqual(cs.detect_opener({"WEZTERM_PANE": "1"}), "wezterm")
        self.assertEqual(cs.detect_opener({}), "current")

if __name__ == "__main__":
    unittest.main()
