#!/usr/bin/env python3
"""seshpick: find any Claude Code session, live or closed, and pick up where you left off.

  seshpick [QUERY]                 picker (fzf). enter: open, or jump to it if it is running. ctrl-f: fork
  seshpick --json [QUERY]          the registry as JSON, ranked like the picker, for scripts and agents
  seshpick --open ID | --fork ID   no picker; ID may be a prefix
  seshpick --version | --help      (sp is the same command, installed as a short alias)

Options:
  --opener NAME              current | rex | tmux | kitty | wezterm | command (default: auto-detect)
  --rex-session LABEL        Rex only: put the tab in that Rex session instead of the guessed one

Reads ~/.claude read-only, only the head and tail of each transcript, and never prints
transcript content beyond a one-line title. No network, no daemon, no database.
Config (optional): $XDG_CONFIG_HOME/seshpick/config.toml, see README.
"""
__version__ = "0.2.2"

import json, os, re, shlex, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"
WINDOW = 256 * 1024          # bytes read from each end of a transcript; never the whole file
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TEMPLATES = {                # openers driven by a command line; {cwd} {title} {cmd} are shell-quoted
    "kitty": "kitty @ launch --type=tab --cwd {cwd} --tab-title {title} {cmd}",
    "wezterm": "wezterm cli spawn --cwd {cwd} -- {cmd}",
}

def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)

def rows_of(text, key):
    d = json.loads(text)
    return d if isinstance(d, list) else d.get(key, [])

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")

def parse(line):
    try:
        return json.loads(line)
    except ValueError:
        return None

def need(tool, hint):
    if not shutil.which(tool):
        sys.exit(f"seshpick needs {tool} on your PATH. {hint}")

def load_config():
    path = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "seshpick" / "config.toml"
    if not path.is_file():
        return {}
    import tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)

# ---- sources -------------------------------------------------------------

def add_name(row, name, first=False):
    """Make a row searchable by one more name. The first name is the title the row shows; the
    rest are aliases, displayed after it as "title / alias" and matched by rank() like the title."""
    if not name:
        return
    names = [n for n in [row["title"]] + list(row.get("aliases") or []) if n != name]
    names.insert(0 if first else len(names), name)
    row["title"], row["aliases"] = names[0], names[1:]

def merge_agents(entries):
    """One row per session id from `claude agents` entries. A session can be listed more than
    once (an interactive entry plus a stopped background one, or two tabs), and the names can
    differ: the interactive entry gives the state and pid, every name stays searchable."""
    out = {}
    for a in entries:
        sid = a.get("sessionId")
        if not sid:
            continue
        interactive = a.get("kind") == "interactive"
        state = "running" if interactive else "background:" + str(a.get("state") or a.get("status") or "?")
        started = a.get("startedAt")
        row = dict(id=sid, agent="claude", cwd=a.get("cwd") or "", title=a.get("name") or sid[:8], aliases=[],
                   updatedAt=iso(started / 1000) if isinstance(started, (int, float)) else "",
                   state=state, pid=a.get("pid"), titleKind="custom")
        if sid not in out:
            out[sid] = row
        elif interactive and out[sid]["state"] != "running":   # an interactive entry beats a background one
            names, out[sid] = [out[sid]["title"]] + out[sid]["aliases"], row
            for n in names:
                add_name(row, n)
        else:
            add_name(out[sid], row["title"])
    return out

def live_sessions():
    """Interactive and background sessions from `claude agents`, keyed by session id."""
    r = run(["claude", "agents", "--json", "--all"])
    return merge_agents(json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else [])

def transcript_meta(path):
    """(cwd, title, title kind, last timestamp) from the head and tail of a transcript, read defensively."""
    with open(path, "rb") as f:
        head = f.read(WINDOW)
        f.seek(0, 2)
        size = f.tell()
        if size > WINDOW:
            f.seek(size - WINDOW)
            tail = f.read(WINDOW)
        else:
            tail = head
    cwd = first = None
    for line in head.decode("utf-8", "replace").splitlines():
        o = parse(line)
        if not o:
            continue
        cwd = cwd or o.get("cwd")
        if first is None and o.get("type") == "user" and not o.get("isSidechain"):
            c = (o.get("message") or {}).get("content")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
            if isinstance(c, str) and c.strip() and not c.lstrip().startswith("<"):
                first = c.strip().splitlines()[0][:80]
        if cwd and first:
            break
    custom = ai = last_ts = None
    for line in tail.decode("utf-8", "replace").splitlines():
        o = parse(line)
        if not o:
            continue
        t = o.get("type")
        if t == "custom-title" and o.get("customTitle"):
            custom = o["customTitle"]                # /rename; the last one wins
        elif t == "ai-title" and o.get("aiTitle"):
            ai = o["aiTitle"]
        last_ts = o.get("timestamp") or last_ts
    title, kind = (custom, "custom") if custom else (ai, "ai") if ai else (first, "prompt")
    return cwd, title, kind, last_ts

def demo_registry(path):
    """A fixture instead of real sessions (SESHPICK_DEMO_REGISTRY), used to record the README demo."""
    now = datetime.now(timezone.utc).timestamp()
    with open(path) as f:
        rows = json.load(f)
    for r in rows:
        r["updatedAt"] = iso(now - r.pop("ago", 0))
        r["resumeCmd"] = f"cd {shlex.quote(r['cwd'])} && claude --resume {r['id']}"
        r["forkCmd"] = r["resumeCmd"] + " --fork-session"
    rows.sort(key=lambda r: r["updatedAt"], reverse=True)
    return rows

def registry(config):
    if os.environ.get("SESHPICK_DEMO_REGISTRY"):
        return demo_registry(os.environ["SESHPICK_DEMO_REGISTRY"])
    files = {p.stem: p for p in PROJECTS.glob("*/*.jsonl") if UUID_RE.match(p.stem)}
    live = live_sessions()
    rows = []
    for sid, row in live.items():
        if sid in files:
            row["updatedAt"] = iso(files[sid].stat().st_mtime)
            _, title, kind, _ = transcript_meta(files[sid])
            if kind != "prompt":                    # the /rename name is what Claude itself shows for it;
                add_name(row, title, first=kind == "custom")   # the registry name can lag behind or differ
        rows.append(row)
    for sid, p in files.items():
        if sid in live:
            continue
        st = p.stat()
        if st.st_size < 2048:                       # empty or aborted session
            continue
        cwd, title, kind, _ = transcript_meta(p)
        if not cwd:
            continue
        rows.append(dict(id=sid, agent="claude", cwd=cwd, title=title or sid[:8], aliases=[], titleKind=kind,
                         updatedAt=iso(st.st_mtime), state="closed", pid=None))
    labels = rex_sessions() if shutil.which("rex") else {}
    for r in rows:
        r["project"] = project_of(r["cwd"], config, labels)
        r["resumeCmd"] = f"cd {shlex.quote(r['cwd'])} && claude --resume {r['id']}"
        r["forkCmd"] = r["resumeCmd"] + " --fork-session"
    rows.sort(key=lambda r: r["updatedAt"], reverse=True)
    return rows

# ---- ranking -------------------------------------------------------------

KIND_RANK = {"custom": 0, "ai": 1, "prompt": 2}
STATE_RANK = {"running": 0, "closed": 2}          # background:* sits in between

def rank(rows, query):
    """Name-search order. Every word of the query must match a row; a row's place is the
    worst tier among its words, then the sum of tiers, then the kind of title (a name given
    with /rename beats an auto title beats a first prompt), then a running session beats a
    closed one with the same name, then recency (rows arrive newest first).
    Tiers: 0 title equals the word, 1 the word is a whole segment of the title (split on
    - _ / and space), 2 substring of the title, 3 substring of the project, folder or id.
    A row's aliases (other names the same session is listed under) count like its title.
    Scattered matches (letters spread through a name) never match."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return list(rows)
    scored = []
    for r in rows:
        names = [n.lower() for n in [r["title"]] + list(r.get("aliases") or [])]
        segments = {seg for n in names for seg in re.split(r"[-_/ ]+", n)}
        elsewhere = " ".join([r.get("project") or "", r["cwd"], r["id"]]).lower()
        tiers = []
        for t in terms:
            tier = (0 if t in names else 1 if t in segments else 2 if any(t in n for n in names)
                    else 3 if t in elsewhere else None)
            if tier is None:
                break
            tiers.append(tier)
        else:
            scored.append(((max(tiers), sum(tiers), KIND_RANK.get(r.get("titleKind"), 1),
                            STATE_RANK.get(r.get("state"), 1)), r))
    scored.sort(key=lambda x: x[0])
    return [r for _, r in scored]

# ---- projects and openers ------------------------------------------------

def project_of(cwd, config, labels):
    """A short project label for a folder: the config mapping first, then a Rex session whose
    label appears in the path, then the folder's own name."""
    low = cwd.lower()
    for needle, label in (config.get("projects") or {}).items():
        if needle.lower() in low:
            return label
    return next((l for l in labels if l.lower() in low), "") or Path(cwd).name

def detect_opener(env):
    for var, name in (("REX_SERVER", "rex"), ("TMUX", "tmux"), ("KITTY_WINDOW_ID", "kitty"), ("WEZTERM_PANE", "wezterm")):
        if env.get(var):
            return name
    return "current"

def ancestors(pid):
    seen = []
    while pid and pid > 1 and pid not in seen:
        seen.append(pid)
        r = run(["ps", "-o", "ppid=", "-p", str(pid)])
        pid = int(r.stdout.strip() or 0)
    return seen

def rex(*args):
    r = run(["rex", *args])
    if r.returncode:
        sys.exit(f"rex {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()}")
    return r.stdout

def rex_sessions():
    return {s["label"]: s["session_id"] for s in rows_of(rex("ls", "--json"), "sessions") if s.get("label")}

def rex_pick_session(cwd, config, labels, wanted):
    if wanted:
        return wanted
    label = project_of(cwd, config, labels)
    if label in labels:
        return label
    cur = os.environ.get("REX_SESSION")
    return next((l for l, sid in labels.items() if sid == cur), None) or (config.get("rex") or {}).get("default_session") or next(iter(labels))

def rex_focus(pid, labels):
    """Select the Rex pane whose shell is an ancestor of the claude process. True if found."""
    chain = set(ancestors(pid))
    for sid in labels.values():
        for b in rows_of(rex("block", "ls", "-s", sid, "--json"), "blocks"):
            if b.get("flavor") != "com.superlogical.terminal.shell":
                continue
            r = run(["rex", "block", "call", "-b", b["block_id"], "process"])
            info = parse(r.stdout) if r.returncode == 0 else None
            if not info:
                continue
            if chain & {(info.get("child") or {}).get("pid"), (info.get("foreground") or {}).get("pid")}:
                app = next((c for c in rows_of(rex("client", "ls", "--json"), "clients") if (c.get("info") or {}).get("kind") == "app"), None)
                if app:
                    run(["rex", "-C", app["client_id"], "do", "session.select", f"session_id={sid}"])
                rex("focus", b["block_id"])
                return True
    return False

def tmux_focus(pid):
    chain = set(ancestors(pid))
    for line in run(["tmux", "list-panes", "-a", "-F", "#{pane_pid}\t#{session_name}:#{window_index}.#{pane_index}"]).stdout.splitlines():
        pane_pid, target = line.split("\t")
        if int(pane_pid) in chain:
            run(["tmux", "select-window", "-t", target])
            run(["tmux", "select-pane", "-t", target])
            return True
    return False

def open_session(row, config, fork=False, opener=None, rex_label=None):
    if os.environ.get("SESHPICK_DEMO_REGISTRY"):          # the demo never launches anything
        print(f"{'forking' if fork else 'opening'} {row['title']}  in {row['cwd']}\n$ {row['forkCmd' if fork else 'resumeCmd'].split(' && ', 1)[1]}")
        return
    opener = opener or config.get("opener") or detect_opener(os.environ)
    if opener == "auto":
        opener = detect_opener(os.environ)
    if row["state"] == "running" and row.get("pid") and not fork:
        found = rex_focus(row["pid"], rex_sessions()) if opener == "rex" else tmux_focus(row["pid"]) if opener == "tmux" else False
        print(f"jumped to: {row['title']}" if found else f"already running: {row['title']}  pid {row['pid']}  in {row['cwd']}")
        return
    cwd = row["cwd"]
    if not os.path.isdir(cwd):
        sys.exit(f"folder no longer exists: {cwd} (a session only resumes safely in its own folder)")
    title = row["title"][:40] + (" (fork)" if fork else "")
    cmd = ["claude", "--resume", row["id"]] + (["--fork-session"] if fork else [])
    if opener == "current":
        os.chdir(cwd)
        os.execvp(cmd[0], cmd)                      # replaces seshpick with claude in this terminal
    elif opener == "rex":
        labels = rex_sessions()
        label = rex_pick_session(cwd, config, labels, rex_label)
        if label not in labels:
            sys.exit(f"no Rex session called {label!r}; have: {', '.join(labels)}")
        rex("window", "new", "-s", labels[label], "-c", cwd, title, "--", *cmd)
        print(f"opened: {title}  (Rex session {label}, {cwd})")
    elif opener == "tmux":
        run(["tmux", "new-window", "-c", cwd, "-n", title, " ".join(shlex.quote(c) for c in cmd)])
        print(f"opened: {title}  (tmux window, {cwd})")
    else:
        template = config.get("command") if opener == "command" else TEMPLATES.get(opener)
        if not template:
            sys.exit(f"unknown opener {opener!r}; use current, rex, tmux, kitty, wezterm or command (with a command template in the config)")
        line = template.format(cwd=shlex.quote(cwd), title=shlex.quote(title), cmd=" ".join(shlex.quote(c) for c in cmd))
        subprocess.run(line, shell=True, check=True)
        print(f"opened: {title}  ({opener}, {cwd})")

# ---- ui ------------------------------------------------------------------

def age(ts):
    if not ts:
        return "?"
    secs = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
    for unit, size in (("m", 60), ("h", 3600), ("d", 86400), ("w", 604800)):
        if secs < size * (60 if unit == "m" else 24 if unit == "h" else 7 if unit == "d" else 10**9):
            return f"{max(1, int(secs / size))}{unit}"
    return "old"

def widths():
    # pick() measures the terminal and passes the width to the reload command, which has no tty
    try:
        cols = int(os.environ.get("SESHPICK_COLUMNS") or 0)
    except ValueError:
        cols = 0  # garbage must not crash the picker; fall back to the terminal size
    cols = cols or shutil.get_terminal_size().columns
    title = max(20, min(44, int(cols * 0.42)))
    return title, max(16, min(48, cols - title - 32))

def short(cwd, width):
    s = cwd.replace(str(HOME), "~")
    return s if len(s) <= width else "…/" + "/".join(s.split("/")[-3:])[-(width - 2):].lstrip("/")

def line_of(r):
    tw, fw = widths()
    name = " / ".join([r["title"]] + list(r.get("aliases") or []))
    return "\t".join([name[:tw].ljust(tw), (r.get("project") or "-")[:10].ljust(10), short(r["cwd"], fw).ljust(fw),
                      age(r["updatedAt"]).rjust(4), r["state"], r["id"]])

def pick(rows, query):
    """fzf draws the list and takes keys; filtering and order come from rank() so that typing
    inside the picker gives the same result as `seshpick QUERY`. fzf runs in --disabled mode and
    reloads the list from this script (--rank-lines) on every change, with --no-sort."""
    cache = tempfile.NamedTemporaryFile("w", prefix="seshpick-", suffix=".json", delete=False)
    try:
        json.dump(rows, cache)
        cache.close()
        reload = " ".join(shlex.quote(x) for x in (sys.executable, os.path.abspath(sys.argv[0]), "--rank-lines", cache.name)) + " {q}"
        fzf = ["fzf", "--disabled", "--no-sort", "--layout=reverse", "--delimiter", "\t", "--with-nth", "1,2,3,4,5", "--tabstop", "1",
               "--expect", "ctrl-f", "--prompt", "session> ", "--query", query,
               "--header", "enter: open or jump to it     ctrl-f: fork     esc: quit",
               "--bind", "start:reload:" + reload, "--bind", "change:reload:" + reload]
        env = dict(os.environ, SESHPICK_COLUMNS=str(shutil.get_terminal_size().columns))
        r = subprocess.run(fzf, input="", capture_output=True, text=True, env=env)
    finally:
        os.unlink(cache.name)
    if r.returncode or not r.stdout.strip():
        return None, None
    key, _, sel = r.stdout.partition("\n")
    return key.strip(), sel.strip().split("\t")[-1]

def take_option(args, name):
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            sys.exit(f"{name} needs a value")
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return None

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if args[:1] in (["--help"], ["-h"]):
        print(__doc__.strip())
        return
    if args[:1] == ["--version"]:
        print(f"seshpick {__version__}")
        return
    if args[:1] == ["--rank-lines"] and len(args) > 1:         # fzf reload hook: rank the cached registry
        with open(args[1]) as f:
            sys.stdout.write("".join(line_of(r) + "\n" for r in rank(json.load(f), " ".join(args[2:]))))
        return
    rex_label, opener = take_option(args, "--rex-session"), take_option(args, "--opener")
    if not os.environ.get("SESHPICK_DEMO_REGISTRY"):
        need("claude", "Install Claude Code first: https://code.claude.com")
    config = load_config()
    rows = registry(config)
    if args[:1] == ["--json"]:
        print(json.dumps(rank(rows, " ".join(args[1:])), indent=2))
        return
    if args[:1] in (["--open"], ["--fork"]) and len(args) > 1:
        row = next((r for r in rows if r["id"].startswith(args[1])), None) or sys.exit(f"no session matching {args[1]}")
        open_session(row, config, fork=args[0] == "--fork", opener=opener, rex_label=rex_label)
        return
    need("fzf", "The picker uses fzf (brew install fzf, apt install fzf, ...). seshpick --json and --open work without it.")
    key, sid = pick(rows, " ".join(args))
    if sid:
        open_session(next(r for r in rows if r["id"] == sid), config, fork=key == "ctrl-f", opener=opener, rex_label=rex_label)

if __name__ == "__main__":
    main()
