"""Ranking tests against a fixture registry (no real session data)."""
import importlib.machinery, importlib.util, pathlib, unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "seshpick.py"
loader = importlib.machinery.SourceFileLoader("cs_module", str(SRC))
spec = importlib.util.spec_from_loader("cs_module", loader)
sp = importlib.util.module_from_spec(spec)
loader.exec_module(sp)

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
    return [r["title"] for r in sp.rank(FIXTURE, query)]

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

class LiveNameTests(unittest.TestCase):
    """A running session listed twice by `claude agents`, under two names, after a /rename."""
    SID = "0000aaaa-0000-4000-8000-000000000001"
    ENTRIES = [
        {"sessionId": SID, "kind": "background", "state": "stopped", "name": "lantern-sync",
         "cwd": "/home/u/work/lantern"},
        {"sessionId": SID, "kind": "interactive", "status": "idle", "name": "main-02", "pid": 4242,
         "cwd": "/home/u/work/lantern", "startedAt": 1767225600000},
    ]

    def test_interactive_entry_wins_and_every_name_stays(self):
        r = sp.merge_agents(self.ENTRIES)[self.SID]
        self.assertEqual((r["state"], r["pid"], r["title"], r["aliases"]), ("running", 4242, "main-02", ["lantern-sync"]))
        r = sp.merge_agents(list(reversed(self.ENTRIES)))[self.SID]
        self.assertEqual((r["state"], r["pid"], r["title"], r["aliases"]), ("running", 4242, "main-02", ["lantern-sync"]))

    def test_rename_name_from_the_transcript_becomes_the_title(self):
        r = sp.merge_agents(self.ENTRIES)[self.SID]
        sp.add_name(r, "lantern-sync", first=True)
        self.assertEqual((r["title"], r["aliases"]), ("lantern-sync", ["main-02"]))
        sp.add_name(r, "lantern-sync", first=True)                 # idempotent
        sp.add_name(r, "Sync the lantern feed")                    # an auto title: searchable, not first
        self.assertEqual((r["title"], r["aliases"]), ("lantern-sync", ["main-02", "Sync the lantern feed"]))
        self.assertTrue(sp.line_of(r).startswith("lantern-sync / main-02 /"))   # column is cut to the width

    def test_live_session_is_found_by_any_of_its_names_before_a_closed_one(self):
        live = dict(row("lantern-sync", cwd="/home/u/work/lantern", project="Lantern", day=30),
                    id=self.SID, state="running", pid=4242, aliases=["main-02"])
        # a closed session with the same name, touched more recently (opened by mistake)
        old = row("lantern-sync", cwd="/home/u/work/lantern", project="Lantern", day=31)
        rows = [old, live] + FIXTURE                              # newest first, as registry() delivers
        for query in ("sync", "lantern-sync", "main", "main-02"):
            got = [r["id"] for r in sp.rank(rows, query)]
            self.assertEqual(got[0], self.SID, query)
        self.assertEqual([r["id"] for r in sp.rank(rows, "sync")], [self.SID, old["id"]])
        self.assertEqual([r["id"] for r in sp.rank(rows, "main")], [self.SID])

class ProjectAndOpenerTests(unittest.TestCase):
    def test_config_mapping_wins_then_rex_label_then_folder_name(self):
        cfg = {"projects": {"work/acme": "Acme"}}
        self.assertEqual(sp.project_of("/home/u/work/acme/api", cfg, {"Other": "s1"}), "Acme")
        self.assertEqual(sp.project_of("/home/u/work/other/api", {}, {"Other": "s1"}), "Other")
        self.assertEqual(sp.project_of("/home/u/work/misc/api", {}, {}), "api")

    def test_opener_detection_order(self):
        self.assertEqual(sp.detect_opener({"REX_SERVER": "x", "TMUX": "y"}), "rex")
        self.assertEqual(sp.detect_opener({"TMUX": "y", "KITTY_WINDOW_ID": "1"}), "tmux")
        self.assertEqual(sp.detect_opener({"WEZTERM_PANE": "1"}), "wezterm")
        self.assertEqual(sp.detect_opener({}), "current")

if __name__ == "__main__":
    unittest.main()
