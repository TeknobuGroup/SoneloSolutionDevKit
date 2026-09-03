#!/usr/bin/env python3
"""
worklog_agent.py  (v1.18)  -  per-repo work reporter for Claude Code

Lives at <repo>/.worklog/worklog_agent.py. Claude Code hooks run it at the start and end of every
session in this repo, and after each response (throttled). Each run:

  1. collects this repo's git commits and Claude Code sessions (with token usage) from the last 28 days,
  2. writes them as one slice into the central pot:   <pot>/slices/<project>__<repo>.json
  3. refreshes the machine slice (desk time from ActivityWatch, logon/lock/unlock presence),
  4. re-renders the pot's reports from ALL slices:
        dashboard.html                       interactive view of everything below (double-click it)
        morning.html                         yesterday + where you left off; pops up once a day on the first unlock or session
        latest-week.md                       this week so far
        latest-14-days.md                    rolling two weeks
        latest.md                            yesterday
        weekly/worklog-YYYY-Www-to-date.md   this week, rebuilt on every run
        weekly/worklog-YYYY-Www.md + .csv    each completed week, final

Commands (run from the repo root):
  python .worklog/worklog_agent.py install                 # pot: C:\\Users\\AccountA\\Worklog, project: the repo folder name,
                                                           # post-commit hook on, presence tasks registered once per machine
  python .worklog/worklog_agent.py install --auto          # once: every git repo you open in Claude Code gets the agent
  python .worklog/worklog_agent.py install --no-presence --no-git-hook   # opt out of either
  python .worklog/worklog_agent.py run --sync              # collect + render now, in the foreground
  python .worklog/worklog_agent.py render                  # rebuild the pot's reports from existing slices
  python .worklog/worklog_agent.py refresh                 # pull desk time + presence and re-render (also runs on lock/unlock)
  python .worklog/worklog_agent.py status
  python .worklog/worklog_agent.py uninstall [--presence]

Config:
  ~/.claude/worklog.json   shared by every repo on this machine:
        {"pot": ..., "idle_minutes": 15, "window_days": 28, "dashboard_reload_s": 180,
         "aw_url": "http://localhost:5600",
         "currency": "$", "prices": {"claude-sonnet-4-6": {"in": 3, "cache_create": 3.75, "cache_read": 0.3, "out": 15}}}
        prices are per million tokens, matched by model-name substring; leave empty for no cost column
        "agent_names": {"code-reviewer": "..."} overrides the built-in friendly display names for agents
  .worklog/worklog.json    this repo only: {"project": "Knecta"}

Python 3.8+, standard library only. Never blocks Claude Code: hook runs exit immediately and do the
work in a detached process; every error is logged to .worklog/agent.log, never raised to the session.
"""

import argparse
import bisect
import csv
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime, timezone
from pathlib import Path

VERSION = "1.19"
WHATS_NEW = "the report and the morning page now break cost down by context band and subagent share, and name this machine's model default and compaction cap"
WHATS_NEW_SHORT = "cost now shows by context band"   # header strip only; keep under ~60 chars
HERE = Path(__file__).resolve().parent          # <repo>/.worklog  (or <pot>/bin for the machine copy)
CENTRAL_CFG = Path("~/.claude/worklog.json").expanduser()
REPO_CFG = HERE / "worklog.json"
LOG = HERE / "agent.log"
MARK = "worklog_agent.py"                        # how we recognise our own hook entries
STOP_THROTTLE_S = 180                            # Stop hooks fire after every response; re-collect at most every 3 min
ATOMIC_RETRY_S = 5.0                             # two repos' agents can reach the same pot file at once; wait one out
DASHBOARD_RELOAD_S = 180                         # the open dashboard re-reads itself this often; 0 turns it off.
                                                 # Tied to STOP_THROTTLE_S on purpose: reloading faster than the
                                                 # collector can produce new data just costs the reader their place.
MACHINE_REFRESH_S = 600                          # ActivityWatch / presence refresh at most every 10 min
SYSLOG_REFRESH_S = 3600                          # Windows event log at most hourly
EDITOR_APPS = {"code.exe", "code - insiders.exe", "cursor.exe", "windsurf.exe", "code", "cursor", "windsurf"}
NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW: background git/powershell calls must not flash consoles
PRESENCE_ON = {"logon", "unlock"}               # only a person opens an interval; boot/wake alone don't (Windows wakes itself)
PRESENCE_OFF = {"lock", "logoff", "shutdown", "sleep"}
PRESENCE_ALL = PRESENCE_ON | PRESENCE_OFF | {"boot", "wake"}

DEFAULT_POT = str(Path("~/Worklog").expanduser())   # one pot per machine; change it in ~/.claude/worklog.json ("pot")

AGENT_NAMES = {                                  # friendly display names; raw ids stay as data keys ("agent_names" in the config overrides)
    "changelog-scribe": "Linda - Archives",
    "code-reviewer": "Stephen - Tech Nerd",
    "security-reviewer": "Dwayne - Security",
    "design-reviewer": "Chloe - Marketing",
    "docs-maintainer": "Archie - Writer",
    "impact-analyst": "Cautious Colin",
    "qa-runner": "Testing Tim",
    "test-runner": "Raymond the Runner",
    "test-writer": "Cautious Carl",
    "uat-plan-maintainer": "Account Manager Mavis",
    "uat-writer": "Key Account Manager Karen",
    "Explore": "Code Search Simon",
    "Plan": "Lead Architect Arthur",
    "general-purpose": "Gopher Greg",
    "claude": "Alan AI",
}


# ----------------------------------------------------------------------------- small helpers

def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


QUIET = False


def say(msg):
    if sys.stdout and not QUIET:
        try:
            print(msg)
        except Exception:
            pass


def local_tz():
    return datetime.now().astimezone().tzinfo


def parse_iso(s):
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", s)
    if m:
        frac = m.group(2) or ""
        if frac:
            frac = (frac + "000000")[:7]
        s = m.group(1) + frac + m.group(3)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(local_tz())


def fmt_dur(minutes):
    h, m = divmod(int(round(minutes)), 60)
    if h and m:
        return "%dh %02dm" % (h, m)
    if h:
        return "%dh" % h
    return "%dm" % m


def fmt_tok(n):
    n = int(n)
    if n >= 1000000:
        return "%.1fM" % (n / 1000000.0)
    if n >= 1000:
        return "%dk" % round(n / 1000.0)
    return str(n)


def day_label(d, year=False):
    return "%d %s" % (d.day, d.strftime("%b %Y" if year else "%b"))


def norm(p):
    return os.path.normcase(os.path.normpath(str(p)))


def within(path, root):
    p, r = norm(path), norm(root)
    return p == r or p.startswith(r + os.sep)


def day_window(d):
    return (datetime.combine(d, dtime.min).replace(tzinfo=local_tz()),
            datetime.combine(d, dtime(23, 59, 59)).replace(tzinfo=local_tz()))


def iso_week_label(d):
    y, w, _ = d.isocalendar()
    return "%d-W%02d" % (y, w)


def atomic_write(path, text):
    """Write through a temp file in the same directory, then replace. Two things the obvious
    version gets wrong on Windows, both seen in this pot:

      - os.replace raises PermissionError (WinError 32) while another process holds the
        target - two repos' agents rendering the same pot at once. That is contention, not
        failure, so it is retried; one of these left a project's slice stale for seven hours.
      - the temp file must not look like the thing being written. Path.glob("*.json") DOES
        match a leading dot, so `.tmp-x.json` was visible to load_slices, to cmd_status, and
        to collect_and_write's superseded-slice sweep - which unlinks by that same glob and
        could delete a half-written slice out from under its writer.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        deadline, delay = time.monotonic() + ATOMIC_RETRY_S, 0.05
        while True:
            try:
                os.replace(tmp, str(path))
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    log("atomic_write: %s held by another process for %gs, giving up" % (path, ATOMIC_RETRY_S))
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.5)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def clip_to_days(start, end):
    """Split an interval into (date, seconds) pieces on local-day boundaries."""
    out = []
    cur = start
    while cur < end:
        day_end = datetime.combine(cur.date(), dtime.min).replace(tzinfo=local_tz()) + timedelta(days=1)
        piece_end = min(end, day_end)
        out.append((cur.date(), (piece_end - cur).total_seconds()))
        cur = piece_end
    return out


def session_bursts(s):
    """A session's activity as (start, end) pairs. A slice written before bursts existed -
    and every session in the older tests - falls back to the span the report has always used
    for it: its start, running for active_min. Without that fallback a burstless session
    would contribute its whole idle span, which once showed 24h of Claude in a day."""
    out = []
    for pair in s.get("bursts") or []:
        try:
            a, b = parse_iso(pair[0]), parse_iso(pair[1])
        except (TypeError, IndexError):
            continue
        if a and b and b >= a:
            out.append((a, b))
    if out:
        return out
    st = parse_iso(s.get("start"))
    return [(st, st + timedelta(minutes=int(s.get("active_min") or 0)))] if st else []


def session_day_minutes(s, idle_minutes):
    """Split one session's effort across the local days it actually happened on.

    Effort is not burst time. The identity the whole report rests on is

        active_min == sum(bursts) + idle_minutes * (bursts - 1)

    because active_min charges every gap the idle cap. Splitting by burst seconds alone
    drops that second term and runs 20-40% below the Summary column, so each day is given
    a weight of its burst seconds plus one idle cap per gap - charged to the day the gap
    OPENS - and active_min is then apportioned by those weights. Largest remainder, so the
    per-day figures sum to exactly the session total printed everywhere else."""
    bursts = session_bursts(s)
    if not bursts:
        return {}
    weights = defaultdict(float)
    for a, b in bursts:
        weights[a.date()] += 0.0            # a single-event burst has no duration but still happened
        for day, secs in clip_to_days(a, b):
            weights[day] += secs
    for (_, end), (nxt, _) in zip(bursts, bursts[1:]):
        weights[end.date()] += max(min((nxt - end).total_seconds(), idle_minutes * 60), 0)
    days = sorted(weights)
    total = int(s.get("active_min") or 0)
    pool = sum(weights.values())
    if total <= 0 or pool <= 0:
        # conservation holds for any total, including a nonsensical negative one out of a
        # hand-edited slice: the days still sum to what the session claims
        return {d: (total if d == days[0] else 0) for d in days}
    exact = {d: total * weights[d] / pool for d in days}
    out = {d: int(exact[d]) for d in days}
    for d in sorted(days, key=lambda x: (-(exact[x] - int(exact[x])), x))[:total - sum(out.values())]:
        out[d] += 1
    return out


TOK_KEYS = ("in", "cache_create", "cache_read", "out")

# Context is the cost: a request's context is input + cache_create + cache_read tokens (what
# it re-reads, not just what it says), and that dwarfs output almost everywhere. Two thresholds,
# not three - the extra band earned its keep in a one-off analysis, not in a page read every
# morning. Boundaries avoid "400" specifically: build_report's own test slices the report text
# from "## Claude Code usage" to the end of the document and asserts an out-of-range session's
# total token count never appears in it, so any label containing that digit string is a trap.
CONTEXT_BANDS = ("normal", "elevated", "very high")


def context_band(ctx):
    if ctx < 150_000:
        return "normal"
    if ctx < 800_000:
        return "elevated"
    return "very high"


def session_tokens_in_range(s, per_day, in_range, since, until):
    """What this session spent inside the range, per model, and whether that is a measurement.

    From 1.18 the collector records tokens against the day they were spent, so a range takes
    exactly its own days. A slice written before that has one total for the whole session, and
    the only honest answer is to apportion it by the effort recorded on each day - returned
    with apportioned=True so the report can say so rather than print an estimate as fact."""
    by_day = s.get("tokens_by_day_by_model")
    if isinstance(by_day, dict) and by_day:
        share = {}
        for day_iso, models in by_day.items():
            try:
                d = datetime.strptime(str(day_iso), "%Y-%m-%d").date()
            except ValueError:
                continue
            if not (since.date() <= d <= until.date()) or not isinstance(models, dict):
                continue
            for model, tk in models.items():
                acc = share.setdefault(model, {k: 0 for k in TOK_KEYS})
                for k in TOK_KEYS:
                    acc[k] += int((tk or {}).get(k, 0) or 0)
        return share, False
    whole = sum(per_day.values())
    frac = (sum(in_range.values()) / whole) if whole else 1.0
    by_model = s.get("tokens_by_model")
    if not isinstance(by_model, dict) or not by_model:
        tot = s.get("tokens") or {}
        # A session that spent nothing must not stamp the range "partial pricing" for a model
        # it never used, nor "estimated" for a split that never happened. Both markers exist to
        # be believed; one crying wolf sends someone hunting for a missing price that is not there.
        if not any(int(tot.get(k, 0) or 0) for k in TOK_KEYS):
            return {}, False
        by_model = {"?": tot}                       # older still: a total with no model breakdown
    share = {}
    for model, tk in by_model.items():
        vals = {k: int(round(int((tk or {}).get(k, 0) or 0) * frac)) for k in TOK_KEYS}
        if any(vals.values()):   # a share that rounds to nothing must not list its model or mark the row
            share[model] = vals
    return share, bool(share) and frac < 1.0


def _day_map_in_range(by_day, since, until):
    for day_iso, inner in (by_day or {}).items():
        try:
            d = datetime.strptime(str(day_iso), "%Y-%m-%d").date()
        except ValueError:
            continue
        if since.date() <= d <= until.date() and isinstance(inner, dict):
            yield inner


def session_band_tokens_in_range(s, since, until):
    """Main-thread tokens in range, bucketed by context band and model. A session collected
    before 1.19 carries no per-request context and returns {} - there is no honest way to
    recover a high-water mark from totals that were already summed across a whole day."""
    out = {}
    for bands in _day_map_in_range(s.get("tokens_by_day_by_band_by_model"), since, until):
        for band, models in bands.items():
            if not isinstance(models, dict):
                continue
            acc = out.setdefault(band, {})
            for model, tk in models.items():
                macc = acc.setdefault(model, {k: 0 for k in TOK_KEYS})
                for k in TOK_KEYS:
                    macc[k] += int((tk or {}).get(k, 0) or 0)
    return out


def session_subagent_tokens_in_range(s, since, until):
    """Subagent tokens in range, by model - the counterpart to session_band_tokens_in_range
    for the requests that split excludes. Same 1.19 cutoff, same empty-if-uncollected rule."""
    out = {}
    for models in _day_map_in_range(s.get("subagent_tokens_by_day_by_model"), since, until):
        for model, tk in models.items():
            acc = out.setdefault(model, {k: 0 for k in TOK_KEYS})
            for k in TOK_KEYS:
                acc[k] += int((tk or {}).get(k, 0) or 0)
    return out


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


# ----------------------------------------------------------------------------- config / repo

def repo_root():
    root = HERE.parent
    if (root / ".git").exists():
        return root
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             **NOWIN, capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return root


def central_cfg():
    cfg = {"pot": DEFAULT_POT, "idle_minutes": 15, "window_days": 28,
           "aw_url": "http://localhost:5600", "currency": "$", "prices": {},
           "brief_popup": True, "brief_after": "05:00"}
    cfg.update({k: v for k, v in read_json(CENTRAL_CFG, {}).items() if v is not None})
    return cfg


def agent_name_map(cfg):
    m = dict(AGENT_NAMES)
    over = cfg.get("agent_names")
    if isinstance(over, dict):                   # a malformed config must not kill report runs
        m.update({k: " ".join(str(v).replace("|", "/").split()) for k, v in over.items() if v})
    return m


def project_name(root):
    return read_json(REPO_CFG, {}).get("project") or root.name


def python_for_hooks():
    return Path(sys.executable).as_posix()  # forward slashes work in Git Bash on Windows too


def pythonw():
    cand = Path(sys.executable).with_name("pythonw.exe")
    return cand if cand.exists() else Path(sys.executable)


def window_start(cfg, now=None):
    now = now or datetime.now(local_tz())
    return (now - timedelta(days=int(cfg["window_days"]))).replace(hour=0, minute=0, second=0, microsecond=0)


# ----------------------------------------------------------------------------- collect: repo

def collect_commits(root, since):
    fmt = "%H%x1f%an%x1f%ae%x1f%aI%x1f%s"
    cmd = ["git", "-C", str(root), "log", "--all", "--no-merges",
           "--since=" + (since - timedelta(days=90)).isoformat(), "--pretty=format:" + fmt]
    try:
        out = subprocess.run(cmd, **NOWIN, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        log("git log failed: %s" % e)
        return []
    if out.returncode != 0:
        log("git log failed: %s" % out.stderr.strip()[:200])
        return []
    commits = []
    for line in out.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue
        t = parse_iso(parts[3])
        if not t or t < since:
            continue
        commits.append({"time": t.isoformat(), "hash": parts[0][:12], "author": parts[1],
                        "subject": "\x1f".join(parts[4:]).strip()})
    commits.sort(key=lambda c: c["time"])
    return commits


def uncommitted_count(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                             **NOWIN, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if out.returncode == 0:
            return len([l for l in out.stdout.splitlines() if l.strip()])
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def encode_cwd(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def user_text(obj):
    msg = obj.get("message") or {}
    content = msg.get("content")
    text = None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        for blk in content:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") == "tool_result":
                return None
            if blk.get("type") == "text" and isinstance(blk.get("text"), str):
                text = blk["text"]
                break
    if not text:
        return None
    text = " ".join(text.split())
    if text.startswith("<") or text.startswith("[Request interrupted") or text.startswith("Caveat:"):
        return None
    return text


def _new_rec():
    return {"branch": None, "times": [], "prompts": 0, "title": None, "usage": {},
            "tools": {}, "commands": {}, "agent_calls": {}, "sub_files": []}


def _blocks(msg):
    c = msg.get("content") if isinstance(msg, dict) else None
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def collect_sessions(root, since, idle_minutes):
    proj_dir = Path("~/.claude/projects").expanduser()
    if not proj_dir.is_dir():
        return []
    enc = encode_cwd(root).lower()  # case-insensitive: VS Code's terminal reports c:\ while other launches say C:\
    dirs = [d for d in proj_dir.iterdir() if d.is_dir() and (d.name.lower() == enc or d.name.lower().startswith(enc + "-"))]
    if not dirs:  # encoding changed, or sessions started elsewhere: fall back to everything
        dirs = [d for d in proj_dir.iterdir() if d.is_dir()]
    enc_filtered = any(d.name.lower() == enc or d.name.lower().startswith(enc + "-") for d in dirs)
    cutoff = (since - timedelta(days=1)).timestamp()
    idle = timedelta(minutes=idle_minutes)
    sessions = {}
    for d in dirs:
        for f in d.rglob("*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            rel = f.relative_to(d).parts
            forced_key = None
            if "subagents" in rel:
                i = rel.index("subagents")
                forced_key = rel[i - 1] if i > 0 else None
            try:
                fh = open(f, encoding="utf-8", errors="replace")
            except OSError:
                continue
            local, belongs = {}, None  # belongs: None until a cwd is seen, then True/False
            with fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    cwd = obj.get("cwd")
                    if belongs is None and isinstance(cwd, str):
                        belongs = within(cwd, root)
                        if not belongs:
                            break  # another repo's transcript: stop reading
                    t = parse_iso(obj.get("timestamp"))
                    if t is None:
                        continue
                    sid = forced_key or obj.get("sessionId") or f.stem
                    rec = local.get(sid)
                    if rec is None:
                        rec = local[sid] = _new_rec()
                    if not rec["branch"] and isinstance(obj.get("gitBranch"), str):
                        rec["branch"] = obj["gitBranch"]
                    if t < since:
                        continue
                    rec["times"].append(t)
                    msg = obj.get("message") or {}
                    if obj.get("type") == "user" and forced_key:
                        if not rec["sub_files"] or rec["sub_files"][-1]["file"] != f.name:
                            rec["sub_files"].append({"file": f.name, "first": t, "usage": {}, "prompt": ""})
                        if not rec["sub_files"][-1]["prompt"]:
                            c = msg.get("content")
                            txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in _blocks(msg) if b.get("type") == "text")
                            rec["sub_files"][-1]["prompt"] = (txt or "").strip()[:300]
                    if obj.get("type") == "user" and not forced_key:
                        for b in _blocks(msg):
                            if b.get("type") == "tool_result" and b.get("tool_use_id") in rec["agent_calls"]:
                                rec["agent_calls"][b["tool_use_id"]]["end"] = t
                        raw_text = msg.get("content") if isinstance(msg.get("content"), str) else ""
                        m = re.search(r"<command-name>\s*(/[\w:-]+)\s*</command-name>", raw_text or "")
                        if m:
                            rec["commands"][m.group(1)] = rec["commands"].get(m.group(1), 0) + 1
                        elif not obj.get("isMeta"):
                            text = user_text(obj)
                            if text:
                                rec["prompts"] += 1
                                if not rec["title"]:
                                    rec["title"] = text
                    elif obj.get("type") == "assistant":
                        for b in _blocks(msg):
                            if b.get("type") != "tool_use":
                                continue
                            name = b.get("name") or "?"
                            rec["tools"][name] = rec["tools"].get(name, 0) + 1
                            if name in ("Task", "Agent") and not forced_key:
                                inp = b.get("input") or {}
                                atype = inp.get("subagent_type") or inp.get("agent_type") or inp.get("name") or "general-purpose"
                                rec["agent_calls"][b.get("id") or obj.get("uuid")] = {"type": str(atype), "start": t, "end": None,
                                                                                      "prompt": str(inp.get("prompt") or "")[:300]}
                        if isinstance(msg.get("usage"), dict):
                            u = msg["usage"]
                            key = obj.get("requestId") or msg.get("id") or obj.get("uuid")
                            model = msg.get("model") or "?"
                            # the local day rides INSIDE the entry: rec["usage"] is keyed by
                            # requestId and merged with dict.update across transcripts, so a
                            # resumed or sidechained record appears more than once. Bucketing
                            # by day at parse time would count those twice; after the merge
                            # each request is present once and carries the day it was spent.
                            entry = (model, int(u.get("input_tokens") or 0),
                                     int(u.get("cache_creation_input_tokens") or 0),
                                     int(u.get("cache_read_input_tokens") or 0),
                                     int(u.get("output_tokens") or 0), t.date().isoformat())
                            rec["usage"][key] = entry
                            if forced_key:
                                if not rec["sub_files"] or rec["sub_files"][-1]["file"] != f.name:
                                    rec["sub_files"].append({"file": f.name, "first": t, "usage": {}, "prompt": ""})
                                rec["sub_files"][-1]["usage"][key] = entry
            if belongs is False or (belongs is None and not enc_filtered):
                continue
            for sid, rec in local.items():
                tgt = sessions.get(sid)
                if tgt is None:
                    sessions[sid] = dict(rec, id=sid)
                else:
                    tgt["times"].extend(rec["times"])
                    tgt["prompts"] += rec["prompts"]
                    tgt["branch"] = tgt["branch"] or rec["branch"]
                    tgt["title"] = tgt["title"] or rec["title"]
                    tgt["usage"].update(rec["usage"])
                    for k, v in rec["tools"].items():
                        tgt["tools"][k] = tgt["tools"].get(k, 0) + v
                    for k, v in rec["commands"].items():
                        tgt["commands"][k] = tgt["commands"].get(k, 0) + v
                    tgt["agent_calls"].update(rec["agent_calls"])
                    tgt["sub_files"].extend(rec["sub_files"])
    out = []
    for rec in sessions.values():
        ts = sorted(rec["times"])
        if not ts:
            continue
        active = timedelta()
        for a, b in zip(ts, ts[1:]):
            active += min(b - a, idle)
        bursts, b_start, prev = [], ts[0], ts[0]
        for t in ts[1:]:
            if t - prev > idle:
                bursts.append([b_start.isoformat(), prev.isoformat()])
                b_start = t
            prev = t
        bursts.append([b_start.isoformat(), prev.isoformat()])
        # A subagent transcript's own requests are written into rec["usage"] AND into that
        # sub_file's own "usage" dict (see the write above); everything else in rec["usage"]
        # is main thread. That set membership, not the file a request came from, is what
        # splits "main" from "subagent" below - it has to run here, after every file for this
        # session has already been merged, or a resumed/sidechained request gets counted once
        # per file it appears in instead of once.
        sub_keys = {k for sf in rec["sub_files"] for k in sf["usage"]}
        by_model, by_day = {}, {}
        context_max = 0
        band_by_day, sub_by_day = {}, {}
        for key, (model, i, cc, cr, o, day) in rec["usage"].items():
            m = by_model.setdefault(model, {"in": 0, "cache_create": 0, "cache_read": 0, "out": 0})
            m["in"] += i; m["cache_create"] += cc; m["cache_read"] += cr; m["out"] += o
            dm = by_day.setdefault(day, {}).setdefault(model, {"in": 0, "cache_create": 0, "cache_read": 0, "out": 0})
            dm["in"] += i; dm["cache_create"] += cc; dm["cache_read"] += cr; dm["out"] += o
            if key in sub_keys:
                sm = sub_by_day.setdefault(day, {}).setdefault(model, {"in": 0, "cache_create": 0, "cache_read": 0, "out": 0})
                sm["in"] += i; sm["cache_create"] += cc; sm["cache_read"] += cr; sm["out"] += o
            else:
                context_max = max(context_max, i + cc + cr)
                bm = band_by_day.setdefault(day, {}).setdefault(context_band(i + cc + cr), {}).setdefault(
                    model, {"in": 0, "cache_create": 0, "cache_read": 0, "out": 0})
                bm["in"] += i; bm["cache_create"] += cc; bm["cache_read"] += cr; bm["out"] += o
        tot = {"in": 0, "cache_create": 0, "cache_read": 0, "out": 0}
        for m in by_model.values():
            for k in tot:
                tot[k] += m[k]
        agents = {}
        calls = sorted(rec["agent_calls"].values(), key=lambda c: c["start"])
        for c in calls:
            a = agents.setdefault(c["type"], {"runs": 0, "wall_s": 0, "tokens": {"in": 0, "cache_create": 0, "cache_read": 0, "out": 0}})
            a["runs"] += 1
            end = c["end"] or min(c["start"] + idle, ts[-1])
            a["wall_s"] += int(max((end - c["start"]).total_seconds(), 0))
        for c in calls:
            c["taken"] = False
        for sf in sorted(rec["sub_files"], key=lambda x: x["first"]):
            # a subagent transcript belongs to the Task call whose prompt it starts with; else the earliest unclaimed call
            # whose window holds its first event (parallel calls are spawned in message order); else the last call before it
            owner = None
            if sf.get("prompt"):
                for c in calls:
                    if c.get("prompt") and not c["taken"] and sf["prompt"].startswith(c["prompt"][:120]):
                        owner = c
                        break
            if owner is None:
                for c in calls:
                    end = c["end"] or (c["start"] + idle)
                    if not c["taken"] and c["start"] - timedelta(seconds=5) <= sf["first"] <= end + timedelta(seconds=60):
                        owner = c
                        break
            if owner is None:
                for c in calls:
                    end = c["end"] or (c["start"] + idle)
                    if c["start"] - timedelta(seconds=5) <= sf["first"] <= end + timedelta(seconds=60):
                        owner = c
            if owner is None and calls:
                before = [c for c in calls if c["start"] <= sf["first"]]
                owner = before[-1] if before else None
            if owner is not None:
                owner["taken"] = True
            a = agents.setdefault(owner["type"] if owner else "general-purpose",
                                  {"runs": 0, "wall_s": 0, "tokens": {"in": 0, "cache_create": 0, "cache_read": 0, "out": 0}})
            for model, i, cc, cr, o, _day in sf["usage"].values():
                a["tokens"]["in"] += i; a["tokens"]["cache_create"] += cc; a["tokens"]["cache_read"] += cr; a["tokens"]["out"] += o
        out.append({"id": rec["id"], "start": ts[0].isoformat(), "end": ts[-1].isoformat(),
                    "active_min": int(active.total_seconds() // 60), "prompts": rec["prompts"],
                    "title": rec["title"] or "", "branch": rec["branch"] or "",
                    "bursts": bursts, "tokens": tot, "tokens_by_model": by_model,
                    "tokens_by_day_by_model": by_day,
                    "context_max": context_max,
                    "tokens_by_day_by_band_by_model": band_by_day,
                    "subagent_tokens_by_day_by_model": sub_by_day,
                    "agents": agents, "tools": rec["tools"], "commands": rec["commands"]})
    out.sort(key=lambda r: r["start"])
    return out


def slice_path(pot, project, repo):
    return Path(pot) / "slices" / ("%s__%s.json" % (safe_name(project), safe_name(repo)))


def collect_and_write(cfg, root):
    now = datetime.now(local_tz())
    since = window_start(cfg, now)
    project = project_name(root)
    data = {
        "version": VERSION, "project": project, "repo": root.name, "path": str(root),
        "machine": platform.node(), "updated": now.isoformat(), "since": since.isoformat(),
        "uncommitted": uncommitted_count(root),
        "commits": collect_commits(root, since),
        "sessions": collect_sessions(root, since, int(cfg["idle_minutes"])),
    }
    mine = slice_path(cfg["pot"], project, root.name)
    atomic_write(mine, json.dumps(data, indent=1))
    for f in mine.parent.glob("*.json"):  # an older slice for this same repo under a previous project name
        if f == mine or f.name.startswith("_machine__"):
            continue
        old = read_json(f, {})
        if isinstance(old, dict) and old.get("path") and norm(old["path"]) == norm(root):
            try:
                f.unlink()
                log("removed superseded slice %s" % f.name)
            except OSError:
                pass
    return data


# ----------------------------------------------------------------------------- collect: machine (ActivityWatch, presence)

def machine_slice_path(pot):
    return Path(pot) / "slices" / ("_machine__%s.json" % safe_name(platform.node()))


def aw_get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def aw_events(base, bucket_id, start, end):
    q = urllib.parse.urlencode({"start": start.astimezone(timezone.utc).isoformat(),
                                "end": end.astimezone(timezone.utc).isoformat(), "limit": 200000})
    return aw_get("%s/api/0/buckets/%s/events?%s" % (base, urllib.parse.quote(bucket_id), q), timeout=60)


def editor_key(title):
    parts = [p.strip() for p in title.split(" - ") if p.strip()]
    if len(parts) >= 3:
        return " - ".join(parts[1:-1])  # drop the file name and the app name, keep folder (+ profile)
    if len(parts) == 2:
        return parts[0]
    return title.strip() or "?"


def aw_days(cfg, refresh_from, now):
    """Per-day desk time and editor time from ActivityWatch, for days >= refresh_from.date()."""
    base = (cfg.get("aw_url") or "").rstrip("/")
    if not base:
        return None, "disabled"
    buckets = aw_get(base + "/api/0/buckets/", timeout=5)
    afk_id = next((b for b in buckets if b.startswith("aw-watcher-afk_")), None)
    win_id = next((b for b in buckets if b.startswith("aw-watcher-window_")), None)
    if not afk_id:
        return None, "no aw-watcher-afk bucket"
    q_start = refresh_from - timedelta(days=1)
    not_afk = []
    for ev in aw_events(base, afk_id, q_start, now):
        if (ev.get("data") or {}).get("status") != "not-afk":
            continue
        s = parse_iso(ev.get("timestamp"))
        if not s:
            continue
        e = s + timedelta(seconds=float(ev.get("duration") or 0))
        if e > refresh_from:
            not_afk.append((max(s, refresh_from), e))
    not_afk.sort()
    starts = [s for s, _ in not_afk]
    days = {}

    def day(d):
        return days.setdefault(d.isoformat(), {"desk_s": 0, "editor_s": 0, "editor": {}})

    for s, e in not_afk:
        for d, secs in clip_to_days(s, e):
            day(d)["desk_s"] += secs
    if win_id:
        for ev in aw_events(base, win_id, q_start, now):
            data = ev.get("data") or {}
            app = str(data.get("app") or "").lower()
            if app not in EDITOR_APPS:
                continue
            s = parse_iso(ev.get("timestamp"))
            if not s:
                continue
            e = s + timedelta(seconds=float(ev.get("duration") or 0))
            if e <= refresh_from:
                continue
            key = editor_key(str(data.get("title") or ""))
            i = max(bisect.bisect_left(starts, s) - 1, 0)
            while i < len(not_afk) and not_afk[i][0] < e:
                os_, oe = max(s, not_afk[i][0]), min(e, not_afk[i][1])
                if oe > os_:
                    for d, secs in clip_to_days(os_, oe):
                        dd = day(d)
                        dd["editor_s"] += secs
                        dd["editor"][key] = dd["editor"].get(key, 0) + secs
                i += 1
    for d in days.values():
        d["desk_s"] = int(d["desk_s"]); d["editor_s"] = int(d["editor_s"])
        d["editor"] = {k: int(v) for k, v in d["editor"].items() if v >= 60}
    return days, None


def presence_file(pot):
    return Path(pot) / "presence" / ("%s.jsonl" % safe_name(platform.node()))


def read_presence(pot, since):
    out = []
    for f in (Path(pot) / "presence").glob("*.jsonl"):
        try:
            for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                t = parse_iso(o.get("time"))
                if t and t >= since and o.get("event"):
                    out.append({"time": t.isoformat(), "event": o["event"], "source": "stamp"})
        except OSError:
            continue
    return out


def syslog_events(since):
    """Boot / shutdown / sleep / wake from the Windows System log (readable without admin)."""
    if os.name != "nt":
        return []
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
          "Get-WinEvent -FilterHashtable @{LogName='System'; Id=1,42,1074,6005,6006; StartTime=(Get-Date).AddDays(-%d)} "
          "-ErrorAction SilentlyContinue | Select-Object @{n='t';e={$_.TimeCreated.ToString('o')}}, Id, ProviderName "
          "| ConvertTo-Json -Compress" % (int((datetime.now(local_tz()) - since).days) + 1))
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             **NOWIN, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        raw = out.stdout.strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
    except Exception as e:
        log("syslog read failed: %s" % e)
        return []
    events = []
    for r in data:
        t = parse_iso(str(r.get("t") or ""))
        if not t or t < since:
            continue
        pid, prov = int(r.get("Id") or 0), str(r.get("ProviderName") or "")
        kind = None
        if pid == 6005:
            kind = "boot"
        elif pid == 6006 or pid == 1074:
            kind = "shutdown"
        elif pid == 42 and "Kernel-Power" in prov:
            kind = "sleep"
        elif pid == 1 and "Power-Troubleshooter" in prov:
            kind = "wake"
        if kind:
            events.append({"time": t.isoformat(), "event": kind, "source": "syslog"})
    return events


def collect_machine(cfg, force=False):
    path = machine_slice_path(cfg["pot"])
    existing = read_json(path, {}) if path.exists() else {}
    now = datetime.now(local_tz())
    since = window_start(cfg, now)
    upd = parse_iso(existing.get("updated"))
    if not force and upd and (now - upd).total_seconds() < MACHINE_REFRESH_S:
        return existing

    # ActivityWatch: keep finished days, recompute from yesterday (or everything the first time)
    aw = existing.get("aw") or {}
    days = {k: v for k, v in (aw.get("days") or {}).items() if k >= since.date().isoformat()}
    last = parse_iso(aw.get("refreshed"))
    if days and last:
        refresh_from = day_window(min(now.date() - timedelta(days=1), last.date()))[0]  # cover the gap since the last refresh
    else:
        refresh_from = since
    refresh_from = max(refresh_from, since)
    err, refreshed = None, aw.get("refreshed")
    try:
        fresh, err = aw_days(cfg, refresh_from, now)
        if fresh is not None:
            days = {k: v for k, v in days.items() if k < refresh_from.date().isoformat()}
            days.update(fresh)
            refreshed = now.isoformat()
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    aw_out = {"ok": err is None, "error": err, "refreshed": refreshed, "days": days}

    # presence: stamps written by the scheduled tasks + boot/shutdown/sleep/wake from the event log
    sys_part = existing.get("syslog") or {}
    checked = parse_iso(sys_part.get("checked"))
    if force or not checked or (now - checked).total_seconds() > SYSLOG_REFRESH_S:
        sys_part = {"checked": now.isoformat(), "events": syslog_events(since)}
    events = read_presence(cfg["pot"], since) + [e for e in sys_part.get("events", [])
                                                 if parse_iso(e["time"]) and parse_iso(e["time"]) >= since]
    seen, merged = set(), []
    for e in sorted(events, key=lambda e: e["time"]):
        k = (e["time"][:16], e["event"])
        if k not in seen:
            seen.add(k)
            merged.append(e)

    data = {"kind": "machine", "version": VERSION, "machine": platform.node(), "updated": now.isoformat(),
            "since": since.isoformat(), "aw": aw_out, "presence": {"events": merged}, "syslog": sys_part}
    atomic_write(path, json.dumps(data, indent=1))
    return data


def presence_days(events, now):
    """{date: {"first": dt, "last": dt, "on_s": seconds}} from an ordered on/off event stream."""
    intervals, on_since = [], None
    for e in sorted(events, key=lambda e: e["time"]):
        t = parse_iso(e["time"])
        if not t:
            continue
        if e["event"] in PRESENCE_ON:
            if on_since is None:
                on_since = t
        elif e["event"] in PRESENCE_OFF and on_since is not None:
            intervals.append((on_since, min(t, on_since + timedelta(hours=16))))
            on_since = None
    if on_since is not None:
        intervals.append((on_since, min(now, on_since + timedelta(hours=16))))
    out = {}
    for s, e in intervals:
        cur = s
        for d, secs in clip_to_days(s, e):
            rec = out.setdefault(d, {"first": cur, "last": cur, "on_s": 0})
            rec["on_s"] += secs
            piece_end = cur + timedelta(seconds=secs)
            rec["first"] = min(rec["first"], cur)
            rec["last"] = max(rec["last"], piece_end)
            cur = piece_end
    return out


# ----------------------------------------------------------------------------- render

def shorten(text, n=90):
    return text if len(text) <= n else text[: n - 1].rstrip() + "\u2026"


def load_slices(pot):
    repos, machines = [], []
    for f in sorted((Path(pot) / "slices").glob("*.json")):
        d = read_json(f, None)
        if not isinstance(d, dict):
            continue
        if d.get("kind") == "machine":
            machines.append(d)
        elif "project" in d:
            repos.append(d)
    return repos, machines


def price_for(model, prices):
    for key, p in (prices or {}).items():
        if key.lower() in (model or "").lower():
            return p
    return None


def _priced(by_model, prices):
    cost, priced = 0.0, True
    for model, tk in by_model.items():
        p = price_for(model, prices)
        if p:
            cost += sum(tk.get(k, 0) * float(p.get(k, 0)) for k in TOK_KEYS) / 1e6
        else:
            priced = False
    return cost, priced


def cost_and_context(slices, since, until, cfg):
    """Cost by context band across every session active in [since, until], and the
    subagent share alongside it - the two questions the 2026-09-03 usage review couldn't
    answer from the report as it stood: how much of the spend sat in a request re-reading
    a huge context, and how much was the main thread versus something it spawned.

    bands_available is False when nothing in range was collected under 1.19 (band and
    subagent maps didn't exist before it) - callers show that as "not collected", not as
    zero, the same way an apportioned-token session is marked rather than presented as exact."""
    prices = cfg.get("prices")
    bands = {b: {"tok": {k: 0 for k in TOK_KEYS}, "cost": 0.0} for b in CONTEXT_BANDS}
    sub = {"tok": {k: 0 for k in TOK_KEYS}, "cost": 0.0}
    priced = True
    bands_available = False
    high = []
    for sl in slices:
        for s in sl.get("sessions", []):
            band_share = session_band_tokens_in_range(s, since, until)
            sub_share = session_subagent_tokens_in_range(s, since, until)
            if band_share or sub_share:
                bands_available = True
            for band, by_model in band_share.items():
                for k in TOK_KEYS:
                    bands[band]["tok"][k] += sum(tk.get(k, 0) for tk in by_model.values())
                c, p = _priced(by_model, prices)
                bands[band]["cost"] += c
                priced = priced and p
            c, p = _priced(sub_share, prices)
            for tk in sub_share.values():
                for k in TOK_KEYS:
                    sub["tok"][k] += tk.get(k, 0)
            sub["cost"] += c
            priced = priced and p
            en = parse_iso(s.get("end"))
            cmax = s.get("context_max") or 0
            if cmax >= 150_000 and en and since <= en <= until:
                high.append((sl.get("project") or "?", s.get("title") or "", cmax))
    total_cost = sum(b["cost"] for b in bands.values()) + sub["cost"]
    return {"bands": bands, "subagent": sub, "total_cost": total_cost, "priced": priced,
            "bands_available": bands_available,
            "high_context_sessions": sorted(high, key=lambda x: -x[2])}


def cost_context_line(cc, cfg):
    """One line summarising a cost_and_context() result - shared by the weekly report and
    the morning page so the two figures are never worded two different ways."""
    if not cc["bands_available"] or not cc["total_cost"]:
        return None
    cur = cfg.get("currency", "$")
    tot = cc["total_cost"]

    def pct(x):
        return (100 * x / tot) if tot else 0.0

    elevated = cc["bands"]["elevated"]["cost"] + cc["bands"]["very high"]["cost"]
    very_high = cc["bands"]["very high"]["cost"]
    return "%s%.2f%s · %.0f%% elevated context (%.0f%% very high) · %.0f%% subagents" % (
        cur, tot, "" if cc["priced"] else "*", pct(elevated), pct(very_high), pct(cc["subagent"]["cost"]))


def machine_context_note(settings_path=None):
    """One line on this machine's model default and compaction cap, from
    ~/.claude/settings.json (or settings_path, for tests). A missing or unparsable file is
    nothing to report, not a failure - the report and the morning page just omit the line,
    the same way they omit cost when a repo carries no `prices`."""
    d = read_json(settings_path or USER_SETTINGS, None)
    if not isinstance(d, dict):
        return None
    model = d.get("model")
    window = d.get("autoCompactWindow")
    env = d.get("env") if isinstance(d.get("env"), dict) else {}
    disabled_1m = str(env.get("CLAUDE_CODE_DISABLE_1M_CONTEXT") or "") == "1"
    bits = ["model default `%s`" % model if model else "no model default set"]
    bits.append(("compaction cap %s" % window) if window else "no compaction cap set")
    if not disabled_1m and (window or model):
        bits.append("1M context not disabled")
    return "This machine: " + "; ".join(bits) + "."


def build_report(slices, machines, since, until, cfg):
    now = datetime.now(local_tz())
    buckets = {}

    def bucket(label):
        if label not in buckets:
            buckets[label] = {"repos": set(), "days": defaultdict(list), "day_active": defaultdict(int), "bursts": defaultdict(list), "session_objs": [],
                              "commits": 0, "sessions": 0, "active": 0, "branches": set(), "uncommitted": {},
                              "tok": {"in": 0, "cache_create": 0, "cache_read": 0, "out": 0}, "models": set(),
                              "cost": 0.0, "priced": True, "apportioned": False}
        return buckets[label]

    for sl in slices:
        b = bucket(sl["project"])
        b["repos"].add(sl.get("repo") or "?")
        if sl.get("uncommitted"):
            b["uncommitted"][sl.get("repo") or "?"] = sl["uncommitted"]
        for c in sl.get("commits", []):
            t = parse_iso(c.get("time"))
            if not t or t < since or t > until:
                continue
            b["commits"] += 1
            b["days"][t.date()].append((t, "commit", "`%s` %s" % (c["hash"][:7], shorten(c["subject"], 110)), c["subject"], t))
        for s in sl.get("sessions", []):
            st, en = parse_iso(s.get("start")), parse_iso(s.get("end"))
            if not st:
                continue
            en = en or st
            # A session is reported where it WORKED, not where it opened. Claude Code keeps one
            # session id until you exit, so the session answering today may have opened last
            # week; selecting on start time hid whole days of work behind that, and piled the
            # week's effort onto the opening day of any range that did include it.
            per_day = session_day_minutes(s, int(cfg["idle_minutes"]))
            in_range = {d: m for d, m in per_day.items() if since.date() <= d <= until.date()}
            if not in_range:
                continue
            b["sessions"] += 1
            b["active"] += sum(in_range.values())
            for d, m in in_range.items():
                b["day_active"][d] += m
            if s.get("branch"):
                b["branches"].add(s["branch"])
            b["session_objs"].append(s)
            # Same clamp as the dashboard: without it a burstless session contributes its whole
            # span to the elapsed column, which is how 18-19 Aug came to read 24h of Claude.
            day_spans = {}
            for bs, be in session_bursts(s):
                cur = bs
                for d, secs in clip_to_days(bs, be + timedelta(seconds=1)):
                    piece = (cur, cur + timedelta(seconds=secs))
                    b["bursts"][d].append(piece)
                    lo, hi = day_spans.get(d, piece)
                    day_spans[d] = (min(lo, piece[0]), max(hi, piece[1]))
                    cur = piece[1]
            share, apportioned = session_tokens_in_range(s, per_day, in_range, since, until)
            if apportioned:
                b["apportioned"] = True
            for model, tk in share.items():
                b["models"].add(model)
                for k in b["tok"]:
                    b["tok"][k] += int(tk.get(k, 0) or 0)
                p = price_for(model, cfg.get("prices"))
                if p:
                    b["cost"] += sum(tk.get(k, 0) * float(p.get(k, 0)) for k in ("in", "cache_create", "cache_read", "out")) / 1e6
                else:
                    b["priced"] = False
            title = shorten(s.get("title") or "(no prompt text)", 100)
            opened = min(per_day) if per_day else st.date()
            for d in sorted(in_range):
                lo, hi = day_spans.get(d, (st, en))
                # prompts are counted per session, not per day, so only the day it opened can
                # honestly claim them; the rest say what they are - the same session, still going
                whose = ("%d prompt%s" % (s.get("prompts") or 0, "" if s.get("prompts") == 1 else "s")
                         if d == opened else "continued")
                b["days"][d].append(
                    (lo, "claude", "**Claude Code** %s\u2013%s \u00b7 ~%s active \u00b7 %s \u00b7 \u201c%s\u201d" % (
                        lo.strftime("%H:%M"), hi.strftime("%H:%M"), fmt_dur(in_range[d]), whose, title),
                     s.get("title") or "", hi))

    active = {k: v for k, v in buckets.items() if v["commits"] or v["sessions"]}
    quiet = sorted(k for k, v in buckets.items() if not (v["commits"] or v["sessions"]))
    ordered = sorted(active.items(), key=lambda kv: (-(kv[1]["commits"] + kv[1]["sessions"]), kv[0].lower()))
    span = (until.date() - since.date()).days + 1
    days = [since.date() + timedelta(days=i) for i in range(span)]

    # machine data: ActivityWatch days + presence
    aw_days_all, presence_events = {}, []
    for m in machines:
        aw = m.get("aw") or {}
        aw_days_all.update(aw.get("days") or {})
        presence_events += (m.get("presence") or {}).get("events", [])
    pres = presence_days(presence_events, now) if presence_events else {}
    have_pres = any(d in pres for d in days)
    have_aw = any(d.isoformat() in aw_days_all for d in days)

    def trace_span(day):
        ts = []
        for _, b in ordered:
            for it in b["days"].get(day, []):
                ts.append(it[0]); ts.append(it[4])
        return (min(ts), max(ts)) if ts else None

    def wall_clock(day):
        """Minutes with any Claude Code session active on this day (bursts merged across projects)."""
        d0, d1 = day_window(day)
        d1 = d1 + timedelta(seconds=1)
        iv = []
        for _, b in ordered:
            for s, e in b["bursts"].get(day, []):
                iv.append((max(s, d0), min(e, d1)))
        iv.sort()
        total, cur_s, cur_e = 0.0, None, None
        for s, e in iv:
            if e <= s:
                continue
            if cur_e is None or s > cur_e:
                if cur_e is not None:
                    total += (cur_e - cur_s).total_seconds()
                cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        if cur_e is not None:
            total += (cur_e - cur_s).total_seconds()
        return total / 60

    def editor_for(day, label, b):
        rec = aw_days_all.get(day.isoformat()) or {}
        total = 0
        names = {label} | b["repos"]
        for key, secs in (rec.get("editor") or {}).items():
            segs = [x.strip() for x in key.split(" - ")]
            if any(seg in names for seg in segs):
                total += secs
        return total

    L = []
    if span == 1:
        L.append("# Work log \u00b7 %s %s" % (since.strftime("%a"), day_label(since, year=True)))
    else:
        L.append("# Work log \u00b7 %s \u2013 %s" % (day_label(since), day_label(until, year=True)))
    L.append("")
    newest = max((parse_iso(s.get("updated")) for s in slices if parse_iso(s.get("updated"))), default=None)
    L.append("Rendered %s \u00b7 %d repo%s reporting \u00b7 newest slice %s \u00b7 Claude Code idle cap %d min%s" % (
        datetime.now().strftime("%d %b %Y %H:%M"), len(slices), "" if len(slices) == 1 else "s",
        newest.strftime("%d %b %H:%M") if newest else "\u2013", int(cfg["idle_minutes"]),
        "" if have_aw else " \u00b7 ActivityWatch: no data"))
    L.append("")

    if span == 1:
        d = since.date()
        bits = []
        tr = trace_span(d)
        if tr:
            bits.append("first trace %s, last %s" % (tr[0].strftime("%H:%M"), tr[1].strftime("%H:%M")))
        wc = wall_clock(d)
        if wc >= 1:
            bits.append("%s elapsed with Claude Code active (concurrent sessions count once)" % fmt_dur(wc))
        if d in pres:
            bits.append("unlocked %s\u2013%s (%s)" % (pres[d]["first"].strftime("%H:%M"), pres[d]["last"].strftime("%H:%M"),
                                                    fmt_dur(pres[d]["on_s"] / 60)))
        rec = aw_days_all.get(d.isoformat())
        if rec:
            bits.append("%s at the desk" % fmt_dur(rec["desk_s"] / 60))
            if rec.get("editor_s"):
                bits.append("%s in the editor" % fmt_dur(rec["editor_s"] / 60))
        if bits:
            L.append("**Day:** " + " \u00b7 ".join(bits))
            L.append("")

    L.append("## Summary")
    L.append("")
    L.append("| Project | Commits | Claude Code sessions | Est. active (parallel sessions add up) | Days |")
    L.append("|---|---:|---:|---:|---:|")
    tc = ts = ta = 0
    for label, b in ordered:
        tc += b["commits"]; ts += b["sessions"]; ta += b["active"]
        L.append("| %s | %d | %d | %s | %d |" % (label, b["commits"], b["sessions"], fmt_dur(b["active"]), len(b["days"])))
    L.append("| **Total** | **%d** | **%d** | **%s** | |" % (tc, ts, fmt_dur(ta)))
    L.append("")

    if 2 <= span <= 14 and ordered:
        L.append("## At a glance")
        L.append("")
        L.append("Cells show commits (c) and estimated active Claude Code time.")
        L.append("")
        L.append("| Project | " + " | ".join(d.strftime("%a %d") for d in days) + " |")
        L.append("|---|" + "---:|" * span)
        for label, b in ordered:
            cells = []
            for d in days:
                n_c = sum(1 for it in b["days"].get(d, []) if it[1] == "commit")
                act = b["day_active"].get(d, 0)
                parts = (["%dc" % n_c] if n_c else []) + ([fmt_dur(act)] if act else [])
                cells.append(" \u00b7 ".join(parts))
            L.append("| %s | %s |" % (label, " | ".join(cells)))
        L.append("")
        if have_aw:
            L.append("## Editor time")
            L.append("")
            L.append("VS Code window in front while you were at the keyboard (ActivityWatch), matched to repos by window title.")
            L.append("")
            L.append("| Project | " + " | ".join(d.strftime("%a %d") for d in days) + " |")
            L.append("|---|" + "---:|" * span)
            for label, b in ordered:
                cells = []
                for d in days:
                    secs = editor_for(d, label, b)
                    cells.append(fmt_dur(secs / 60) if secs >= 60 else "")
                L.append("| %s | %s |" % (label, " | ".join(cells)))
            L.append("")

    if span >= 2:
        cols = ["Day"] + (["At desk"] if have_aw else []) + (["Unlocked"] if have_pres else []) + \
               ["First \u2013 last trace", "Claude Code (elapsed)"] + (["Editor"] if have_aw else []) + ["Commits"]
        L.append("## Days")
        L.append("")
        if have_aw or have_pres:
            L.append("At desk = keyboard/mouse active (ActivityWatch). Unlocked = between unlock/logon and lock/sleep.")
        # Always printed: on a machine with neither ActivityWatch nor presence data this used to
        # ship with no explanation, leaving an elapsed column looking like an effort one.
        L.append("Trace = first and last commit or Claude Code event. Claude Code (elapsed) = wall-clock time with any "
                 "session active, so concurrent sessions count once. The per-project figures above add parallel sessions "
                 "together - that is the effort number - and they can exceed this.")
        L.append("")
        L.append("| " + " | ".join(cols) + " |")
        L.append("|---|" + "---:|" * (len(cols) - 1))
        for d in days:
            if d > now.date():
                continue
            rec = aw_days_all.get(d.isoformat()) or {}
            tr = trace_span(d)
            row = [d.strftime("%a %d %b")]
            if have_aw:
                row.append(fmt_dur(rec["desk_s"] / 60) if rec else "")
            if have_pres:
                row.append("%s\u2013%s (%s)" % (pres[d]["first"].strftime("%H:%M"), pres[d]["last"].strftime("%H:%M"),
                                               fmt_dur(pres[d]["on_s"] / 60)) if d in pres else "")
            row.append("%s \u2013 %s" % (tr[0].strftime("%H:%M"), tr[1].strftime("%H:%M")) if tr else "")
            act = wall_clock(d)
            row.append(fmt_dur(act) if act >= 1 else "")
            if have_aw:
                row.append(fmt_dur(rec["editor_s"] / 60) if rec and rec.get("editor_s") else "")
            n_c = sum(1 for _, b in ordered for it in b["days"].get(d, []) if it[1] == "commit")
            row.append(str(n_c) if n_c else "")
            L.append("| " + " | ".join(row) + " |")
        L.append("")

    if any(b["tok"]["in"] or b["tok"]["out"] for _, b in ordered):
        show_cost = bool(cfg.get("prices"))
        L.append("## Claude Code usage")
        L.append("")
        L.append("| Project | Sessions | Input | Cache read | Output" + (" | Est. cost" if show_cost else "") + " | Models |")
        L.append("|---|---:|---:|---:|---:|" + ("---:|" if show_cost else "") + "---|")
        tot = {"in": 0, "cache_read": 0, "out": 0}; tot_cost = 0.0
        for label, b in ordered:
            t = b["tok"]
            if not (t["in"] or t["cache_create"] or t["cache_read"] or t["out"]):
                continue
            tot["in"] += t["in"] + t["cache_create"]; tot["cache_read"] += t["cache_read"]; tot["out"] += t["out"]
            tot_cost += b["cost"]
            models = ", ".join(sorted(m.replace("claude-", "") for m in b["models"] if m != "?"))
            marks = ("" if b["priced"] else "*") + ("†" if b["apportioned"] else "")
            cost = ("%s%.2f%s" % (cfg.get("currency", "$"), b["cost"], marks)) if show_cost else None
            L.append("| %s | %d | %s | %s | %s%s | %s |" % (label, b["sessions"], fmt_tok(t["in"] + t["cache_create"]),
                                                          fmt_tok(t["cache_read"]), fmt_tok(t["out"]),
                                                          (" | " + cost) if cost else "", models))
        L.append("| **Total** | | **%s** | **%s** | **%s**%s | |" % (
            fmt_tok(tot["in"]), fmt_tok(tot["cache_read"]), fmt_tok(tot["out"]),
            (" | **%s%.2f**" % (cfg.get("currency", "$"), tot_cost)) if show_cost else ""))
        if show_cost and any(not b["priced"] for _, b in ordered):
            L.append("")
            L.append("\\* some models had no entry in `prices`, so the figure is partial.")
        if show_cost and any(b["apportioned"] for _, b in ordered):
            L.append("")
            L.append("† an estimated cost, not a measured one. These sessions were collected before the agent "
                     "recorded tokens per day, when one total covered a whole session however many days it ran; "
                     "their spend is split across days in proportion to the effort recorded on each. Sessions "
                     "collected since are exact, and re-collecting a repo replaces the estimate.")
        L.append("")
        if show_cost:
            cc = cost_and_context(slices, since, until, cfg)
            line = cost_context_line(cc, cfg)
            if line:
                L.append("## Cost and context")
                L.append("")
                L.append(line + ".")
                if cc["high_context_sessions"]:
                    L.append("")
                    L.append("Sessions that reached elevated context (150k+ tokens) in this range:")
                    for proj, title, mx in cc["high_context_sessions"][:10]:
                        L.append("- %s — %s (%s tokens)" % (proj, shorten(title or "(no prompt text)", 80), fmt_tok(mx)))
                L.append("")

    an = agent_name_map(cfg)
    agg_projs, agg_cmds, agg_tools = {}, {}, {}
    for label, b in ordered:
        for s_ in b.get("session_objs", []):
            for name, a in (s_.get("agents") or {}).items():
                g = agg_projs.setdefault(label, {}).setdefault(name, {"runs": 0, "wall_s": 0, "in": 0, "out": 0})
                g["runs"] += a.get("runs", 0); g["wall_s"] += a.get("wall_s", 0)
                g["in"] += (a.get("tokens") or {}).get("in", 0) + (a.get("tokens") or {}).get("cache_create", 0)
                g["out"] += (a.get("tokens") or {}).get("out", 0)
            for k, v in (s_.get("commands") or {}).items():
                agg_cmds[k] = agg_cmds.get(k, 0) + v
            for k, v in (s_.get("tools") or {}).items():
                agg_tools[k] = agg_tools.get(k, 0) + v
    if agg_projs or agg_cmds:
        L.append("## Agents and commands")
        L.append("")
        if agg_projs:
            L.append("| Project / agent | Runs | Time | Input | Output |")
            L.append("|---|---:|---:|---:|---:|")
            for label, pa in sorted(agg_projs.items(), key=lambda kv: -sum(g["wall_s"] for g in kv[1].values())):
                tot = {k: sum(g[k] for g in pa.values()) for k in ("runs", "wall_s", "in", "out")}
                L.append("| **%s** | **%d** | **%s** | **%s** | **%s** |" % (label, tot["runs"], fmt_dur(tot["wall_s"] / 60),
                                                                            fmt_tok(tot["in"]) if tot["in"] else "-", fmt_tok(tot["out"]) if tot["out"] else "-"))
                for name, g in sorted(pa.items(), key=lambda kv: -kv[1]["wall_s"]):
                    L.append("| \u00b7 %s | %d | %s | %s | %s |" % (an.get(name, name), g["runs"], fmt_dur(g["wall_s"] / 60),
                                                                   fmt_tok(g["in"]) if g["in"] else "-", fmt_tok(g["out"]) if g["out"] else "-"))
            L.append("")
        if agg_cmds:
            L.append("Commands: " + ", ".join("%s x%d" % (k, v) for k, v in sorted(agg_cmds.items(), key=lambda kv: -kv[1])))
            L.append("")
        if agg_tools:
            top = sorted(agg_tools.items(), key=lambda kv: -kv[1])[:8]
            L.append("Tools: " + ", ".join("%s %d" % (k, v) for k, v in top))
            L.append("")

    for label, b in ordered:
        L.append("## %s" % label)
        meta = "repos: " + ", ".join(sorted(b["repos"]))
        if b["branches"]:
            meta += " \u00b7 branches: " + ", ".join(sorted(b["branches"]))
        if b["uncommitted"]:
            meta += " \u00b7 **uncommitted:** " + ", ".join("%s (%d file%s)" % (r, n, "" if n == 1 else "s")
                                                            for r, n in sorted(b["uncommitted"].items()))
        L.append(meta)
        pa = {}
        for s_ in b.get("session_objs", []):
            for name, a in (s_.get("agents") or {}).items():
                g = pa.setdefault(name, [0, 0]); g[0] += a.get("runs", 0); g[1] += a.get("wall_s", 0)
        if pa:
            L.append("Agents: " + ", ".join("%s x%d (%s)" % (an.get(n, n), g[0], fmt_dur(g[1] / 60)) for n, g in sorted(pa.items(), key=lambda kv: -kv[1][1])))
        L.append("")
        for day in sorted(b["days"]):
            L.append("### %s" % day.strftime("%a %d %b"))
            for it in sorted(b["days"][day], key=lambda it: it[0]):
                L.append("- %s %s" % (it[0].strftime("%H:%M"), it[2]))
            L.append("")

    if quiet:
        L.append("---")
        L.append("")
        L.append("Reporting but no activity in this window: " + ", ".join(quiet))
        L.append("")

    rows = []
    for label, b in ordered:
        # The union is belt-and-braces: every in-range effort day also appends a "claude" item
        # above, so today the two key sets match. It guards the coupling - the moment a day gets
        # minutes without a detail line, that day's effort would vanish from the archived weekly
        # CSV, which the dashboard's trend chart reads back and would then sit below the report.
        # Note claude_sessions now counts session-DAYS, so a session spanning three days is 3.
        for day in sorted(set(b["days"]) | set(b["day_active"])):
            items = b["days"].get(day, [])
            rows.append([label, day.isoformat(),
                         sum(1 for it in items if it[1] == "commit"),
                         sum(1 for it in items if it[1] == "claude"),
                         b["day_active"].get(day, 0),
                         int(editor_for(day, label, b) / 60) if have_aw else "",
                         " | ".join(it[3] for it in items if it[1] == "commit"),
                         " | ".join(it[3] for it in items if it[1] == "claude" and it[3])])
    return "\n".join(L), rows, (tc, ts, ta)


def write_csv(path, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["project", "date", "commits", "claude_sessions", "active_minutes", "editor_minutes",
                "commit_subjects", "session_titles"])
    w.writerows(rows)
    atomic_write(path, buf.getvalue())


def whatsnew_note(pot, days, text=None):
    """The what's-new line while the running version is younger than `days` in this pot, else ""."""
    text = WHATS_NEW if text is None else text
    d = read_json(Path(pot) / ".whats-new.json", {})
    if not isinstance(d, dict) or d.get("version") != VERSION:
        return text                               # first render of this version not recorded yet
    t = parse_iso(d.get("first_render"))
    return text if t is None or (datetime.now(local_tz()) - t) < timedelta(days=days) else ""


def render(cfg):
    pot = Path(cfg["pot"])
    slices, machines = load_slices(pot)
    if not slices:
        log("render: no slices in %s yet" % pot)
        return None
    now = datetime.now(local_tz())
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    try:
        wn = read_json(pot / ".whats-new.json", {})
        wn = wn if isinstance(wn, dict) else {}
        seen = str(wn.get("version") or "0")
        # only a NEWER version restamps (an older agent on a shared pot must not reset the clock);
        # a matching version with an unreadable date restamps so the window can ever close
        stale = (not re.match(r"^[0-9.]+$", seen)
                 or tuple(int(x) for x in seen.split(".") if x) < tuple(int(x) for x in VERSION.split(".")))
        if stale or (seen == VERSION and parse_iso(wn.get("first_render")) is None):
            atomic_write(pot / ".whats-new.json", json.dumps({"version": VERSION, "first_render": now.isoformat()}) + "\n")
    except Exception:
        log("whats-new state write failed\n" + traceback.format_exc())

    y_since, y_until = day_window(today - timedelta(days=1))
    md, _, _ = build_report(slices, machines, y_since, y_until, cfg)
    atomic_write(pot / "latest.md", md)

    w_since, _ = day_window(monday)
    md, _, totals = build_report(slices, machines, w_since, now, cfg)
    atomic_write(pot / "weekly" / ("worklog-%s-to-date.md" % iso_week_label(monday)), md)
    atomic_write(pot / "latest-week.md", md)

    f_since, _ = day_window(today - timedelta(days=13))
    md, _, _ = build_report(slices, machines, f_since, now, cfg)
    atomic_write(pot / "latest-14-days.md", md)

    window_start_dt = min((parse_iso(sl.get("since")) for sl in slices if parse_iso(sl.get("since"))), default=None)
    wk_mon = monday - timedelta(days=7)
    while window_start_dt is not None and wk_mon >= window_start_dt.date():
        w_since, _ = day_window(wk_mon)
        _, w_until = day_window(wk_mon + timedelta(days=6))
        md, rows, _ = build_report(slices, machines, w_since, w_until, cfg)
        label = iso_week_label(wk_mon)
        atomic_write(pot / "weekly" / ("worklog-%s.md" % label), md)
        write_csv(pot / "weekly" / ("worklog-%s.csv" % label), rows)
        stale = pot / "weekly" / ("worklog-%s-to-date.md" % label)
        if stale.exists():
            try:
                stale.unlink()
            except OSError:
                pass
        wk_mon -= timedelta(days=7)
    try:
        write_dashboard(slices, machines, cfg, pot)
        atomic_write(pot / "morning.html", build_morning(slices, machines, cfg, pot))
    except Exception:
        log("dashboard failed\n" + traceback.format_exc())
    return totals


# ----------------------------------------------------------------------------- dashboard

def read_weekly_csvs(pot):
    """Per-week, per-project totals from the archived weekly CSVs (completed weeks only)."""
    weeks = []
    for f in sorted((Path(pot) / "weekly").glob("worklog-*.csv")):
        m = re.match(r"worklog-(\d{4}-W\d{2})\.csv$", f.name)
        if not m:
            continue
        label = m.group(1)
        try:
            start = datetime.strptime(label + "-1", "%G-W%V-%u").date().isoformat()
            rows = list(csv.DictReader(open(f, encoding="utf-8", newline="")))
        except (OSError, ValueError):
            continue
        per = {}
        for r in rows:
            p = per.setdefault(r.get("project") or "?", {"commits": 0, "sessions": 0, "active_min": 0, "editor_min": 0})
            for key, col in (("commits", "commits"), ("sessions", "claude_sessions"),
                             ("active_min", "active_minutes"), ("editor_min", "editor_minutes")):
                try:
                    p[key] += int(float(r.get(col) or 0))
                except ValueError:
                    pass
        weeks.append({"week": label, "start": start, "projects": per})
    return weeks


def dashboard_data(slices, machines, cfg, pot, whats_new=""):
    projects = {}
    for sl in sorted(slices, key=lambda x: (x["project"].lower(), x.get("repo") or "")):
        projects.setdefault(sl["project"], []).append({
            "repo": sl.get("repo") or "?", "path": sl.get("path"), "updated": sl.get("updated"),
            "uncommitted": sl.get("uncommitted") or 0,
            "commits": sl.get("commits", []), "sessions": sl.get("sessions", [])})
    aw_days, presence = {}, []
    for m in machines:
        aw_days.update((m.get("aw") or {}).get("days") or {})
        presence += (m.get("presence") or {}).get("events", [])
    window_start_dt = min((parse_iso(sl.get("since")) for sl in slices if parse_iso(sl.get("since"))), default=None)
    return {
        "generated": datetime.now(local_tz()).isoformat(), "pot": str(pot),
        "window_days": int(cfg["window_days"]), "window_start": window_start_dt.isoformat() if window_start_dt else None,
        "idle_minutes": int(cfg["idle_minutes"]), "currency": cfg.get("currency", "$"), "prices": cfg.get("prices") or {},
        "agent_names": agent_name_map(cfg),
        "version": VERSION, "whats_new": whats_new,
        "reload_s": min(max(int(cfg.get("dashboard_reload_s", DASHBOARD_RELOAD_S) or 0), 0), 86400),
        "repo_count": len(slices),
        "projects": [{"project": k, "repos": v} for k, v in projects.items()],
        "machine": {"aw_days": aw_days, "presence": presence},
        "weeks": read_weekly_csvs(pot),
    }


def write_dashboard(slices, machines, cfg, pot):
    payload = json.dumps(dashboard_data(slices, machines, cfg, pot, whatsnew_note(pot, 7, WHATS_NEW_SHORT)), separators=(",", ":")).replace("<", "\\u003c")
    atomic_write(Path(pot) / "dashboard.html", DASHBOARD_HTML.replace("__DATA__", payload))


DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Worklog</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#f4f5f7;--card:#fff;--ink:#1b1f24;--muted:#6b7280;--line:#e5e7eb;--accent:#00AF9F;--unl:#e0ecff;--soft:#f3f4f6}
*{box-sizing:border-box}
html,body{margin:0}
body{font:14px/1.45 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
header{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;padding:12px 20px;background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
h1{font-size:17px;margin:0;letter-spacing:.2px}
h1 span{color:var(--muted);font-weight:400;margin-left:8px;font-size:13px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);margin:0 0 12px;font-weight:600}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{border:0;background:#fff;padding:6px 12px;cursor:pointer;font:inherit;color:var(--ink)}
.seg button+button{border-left:1px solid var(--line)}
.seg button.on{background:var(--ink);color:#fff}
.nav{display:inline-flex;align-items:center;gap:6px}
.nav button{border:1px solid var(--line);background:#fff;border-radius:8px;width:30px;height:30px;cursor:pointer;font-size:16px;line-height:1}
.nav button:disabled{opacity:.35;cursor:default}
#rangeLabel{min-width:190px;text-align:center;font-weight:600}
.meta{margin-left:auto;color:var(--muted);font-size:12px}
main{padding:16px 20px 40px;display:grid;gap:16px;max-width:1400px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.kpi .v{font-size:24px;font-weight:650;letter-spacing:-.3px}
.kpi .l{color:var(--muted);font-size:12px;margin-top:2px}
.kpi .s{color:var(--muted);font-size:11px;margin-top:4px}
.note{color:var(--muted);font-size:12px;margin:-6px 0 10px}
.empty{color:var(--muted);padding:10px 0}
/* days */
.dayrow{display:grid;grid-template-columns:96px 1fr 300px;gap:12px;align-items:center;padding:6px 0;border-top:1px solid var(--soft)}
.dayrow:first-child{border-top:0}
.dayrow.axis{color:var(--muted);font-size:11px;padding:0 0 2px}
.dayrow.axis .track{height:14px;background:none;border:0;overflow:visible}
.dayrow.axis .tick{position:absolute;top:0;transform:translateX(-50%)}
.dayrow.today .dl{color:var(--accent)}
.dl{font-weight:600}
.dl small{display:block;color:var(--muted);font-weight:400;font-size:12px}
.track{position:relative;height:28px;background:var(--soft);border-radius:6px;overflow:hidden}
.track .gl{position:absolute;top:0;bottom:0;width:1px;background:#e3e5e8}
.track .unl{position:absolute;top:0;bottom:0;background:var(--unl)}
.track .sess{position:absolute;top:7px;height:14px;border-radius:3px;opacity:.9;min-width:3px}
.track .ct{position:absolute;top:2px;width:2px;height:24px;border-radius:1px}
.figs{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;font-size:12px;color:var(--muted);text-align:right}
.figs b{display:block;color:var(--ink);font-size:13px;font-weight:600}
/* projects */
table{border-collapse:collapse;width:100%}
th{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:600;text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
td{padding:7px 8px;border-bottom:1px solid var(--soft);text-align:right;white-space:nowrap}
tr.p{cursor:pointer}
tr.p:hover td{background:#fafafa}
tr.p.sel td{background:#f0fdfa;box-shadow:inset 3px 0 0 var(--accent)}
#scope{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--accent);border-radius:4px;padding:3px 8px;font-size:12px}
#scope[hidden]{display:none}
#scope button{border:0;background:none;cursor:pointer;font:inherit;color:var(--muted);padding:0;line-height:1}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px;vertical-align:-1px}
.bar{height:8px;border-radius:4px;background:var(--soft);position:relative;min-width:120px;overflow:hidden}
.bar i{position:absolute;left:0;top:0;bottom:0;border-radius:4px}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:#fff7ed;color:#c2410c;border:1px solid #fed7aa;margin-left:8px;font-weight:500}
.muted{color:var(--muted)}
/* grid */
.gridwrap{overflow-x:auto}
.grid td{text-align:center;font-size:12px;min-width:66px}
.grid td.c{border-radius:6px}
.grid th{text-align:center}
.grid th:first-child,.grid td:first-child{text-align:left}
/* usage */
.tokbar{display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--soft);min-width:160px}
.tokbar i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--muted);margin-top:10px}
.legend span i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
/* trend */
svg.trend{width:100%;height:220px;display:block}
svg.trend text{font-size:11px;fill:var(--muted)}
/* log */
.log h3{font-size:14px;margin:14px 0 4px}
.log h3:first-child{margin-top:0}
.log h4{font-size:12px;color:var(--muted);margin:10px 0 2px;font-weight:600}
.log ul{list-style:none;margin:0;padding:0}
.log li{padding:3px 0;border-bottom:1px solid var(--soft);display:grid;grid-template-columns:46px 1fr;gap:10px}
.log li .t{color:var(--muted);font-variant-numeric:tabular-nums}
.log code{background:var(--soft);padding:1px 5px;border-radius:4px;font-size:12px}
.log .cc{color:#0f766e;font-weight:600}
@media (max-width:820px){.dayrow{grid-template-columns:80px 1fr}.figs{display:none}.meta{display:none}}
</style>
</head>
<body>
<header>
  <h1>Worklog<span id="potName"></span></h1>
  <div class="seg" id="presets"></div>
  <div class="nav"><button id="prev" title="earlier">&#8249;</button><span id="rangeLabel"></span><button id="next" title="later">&#8250;</button></div>
  <span id="scope" hidden></span>
  <div class="meta" id="meta"></div>
</header>
<main>
  <section class="kpis" id="kpis"></section>
  <section class="card"><h2>Days</h2><div class="note" id="daysNote"></div><div id="days"></div></section>
  <section class="card"><h2>Projects</h2><div class="note">Click a project to focus the other sections on it.</div><div id="projects"></div></section>
  <section class="card"><h2>At a glance</h2><div class="note">Commits and Claude Code active time per project per day; shading is Claude plus editor time.</div><div class="gridwrap" id="grid"></div></section>
  <section class="card" id="usageCard"><h2>Claude Code usage</h2><div id="usage"></div></section>
  <section class="card" id="agentsCard"><h2>Agents</h2><div class="note">Subagent runs from every session that worked in this range, counted whole - including any part of that session outside the range. Run counts are integers and are not apportioned. Below: slash commands and the tools Claude used.</div><div id="agents"></div></section>
  <section class="card" id="trendCard"><h2>Weeks</h2><div class="note">Hours per week by project: Claude Code active time plus editor time. Completed weeks from the archive, the current week to date.</div><div id="trend"></div></section>
  <section class="card"><h2>Log</h2><div class="log" id="log"></div></section>
</main>
<script id="worklog-data" type="application/json">__DATA__</script>
<script>
(function () {
  'use strict';
  var DATA = JSON.parse(document.getElementById('worklog-data').textContent);
  var PALETTE = ['#00AF9F', '#6366f1', '#f59e0b', '#ef4444', '#0ea5e9', '#8b5cf6', '#10b981', '#f97316', '#ec4899', '#64748b', '#84cc16', '#14b8a6'];
  var ON = { logon: 1, unlock: 1 }, OFF = { lock: 1, logoff: 1, shutdown: 1, sleep: 1 };
  var H = 3600000, D = 86400000;
  var now = new Date();
  var today = startOfDay(now);

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function startOfDay(d) { var x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
  function addDays(d, n) { var x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function dateKey(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function monday(d) { var x = startOfDay(d); var w = (x.getDay() + 6) % 7; return addDays(x, -w); }
  function hm(d) { return pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  function fmtDur(min) { min = Math.round(min); var h = Math.floor(min / 60), m = min % 60; if (h && m) return h + 'h ' + pad(m) + 'm'; if (h) return h + 'h'; return m + 'm'; }
  function fmtH(min) { return (min / 60).toFixed(1) + 'h'; }
  function fmtTok(n) { if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'; if (n >= 1e3) return Math.round(n / 1e3) + 'k'; return String(n); }
  function dayLabel(d) { return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }); }
  function shortDay(d) { return d.toLocaleDateString('en-GB', { weekday: 'short' }) + ' ' + d.getDate(); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function el(id) { return document.getElementById(id); }
  function sum(a, f) { var t = 0; for (var i = 0; i < a.length; i++) t += f ? f(a[i]) : a[i]; return t; }
  function overlap(a0, a1, b0, b1) { var s = Math.max(a0, b0), e = Math.min(a1, b1); return e > s ? e - s : 0; }
  function unionMinutes(intervals) {  // [[startMs, endMs], ...] -> minutes covered
    intervals = intervals.filter(function (iv) { return iv[1] > iv[0]; }).sort(function (x, y) { return x[0] - y[0]; });
    var total = 0, cs = null, ce = null;
    intervals.forEach(function (iv) {
      if (ce === null || iv[0] > ce) { if (ce !== null) total += ce - cs; cs = iv[0]; ce = iv[1]; }
      else if (iv[1] > ce) ce = iv[1];
    });
    if (ce !== null) total += ce - cs;
    return total / 60000;
  }
  function wallClock(focus, d) {  // minutes with any Claude Code session active on day d, across the focused projects
    var d0 = +d, d1 = +addDays(d, 1), iv = [];
    focus.forEach(function (x) { x.sessions.forEach(function (s) { s.bursts.forEach(function (pr) { var a = Math.max(+pr[0], d0), b = Math.min(+pr[1] + 1000, d1); if (b > a) iv.push([a, b]); }); }); });
    return unionMinutes(iv);
  }
  function isoWeek(d) {
    var x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    var day = x.getUTCDay() || 7; x.setUTCDate(x.getUTCDate() + 4 - day);
    var y = x.getUTCFullYear(); var w = Math.ceil((((x - Date.UTC(y, 0, 1)) / D) + 1) / 7);
    return y + '-W' + pad(w);
  }

  // ---------- static prep
  var projects = DATA.projects.map(function (p, i) {
    var names = {}; names[p.project] = 1;
    p.repos.forEach(function (r) { names[r.repo] = 1; });
    var commits = [], sessions = [], uncommitted = [];
    p.repos.forEach(function (r) {
      r.commits.forEach(function (c) { var t = new Date(c.time); if (!isNaN(t)) commits.push({ t: t, hash: c.hash, subject: c.subject, repo: r.repo }); });
      r.sessions.forEach(function (s) {
        var a = new Date(s.start), b = new Date(s.end); if (isNaN(a)) return; if (isNaN(b)) b = a;
        // A session with no bursts (an older slice) used to fall back to its whole span, so a
        // session left open for three days counted as three days of activity. Clamp the stand-in
        // to the active minutes it did record - never more than the session itself claims.
        var raw = s.bursts && s.bursts.length ? s.bursts : [[s.start, new Date(+new Date(s.start) + (s.active_min || 0) * 60000).toISOString()]];
        var bursts = raw.map(function (pr) { return [new Date(pr[0]), new Date(pr[1])]; }).filter(function (pr) { return !isNaN(pr[0]) && !isNaN(pr[1]) && pr[1] >= pr[0]; });
        sessions.push({ a: a, b: b, bursts: bursts, active: s.active_min || 0, prompts: s.prompts || 0, title: s.title || '', branch: s.branch || '', byModel: s.tokens_by_model || {}, byDay: s.tokens_by_day_by_model || null, repo: r.repo, agents: s.agents || {}, tools: s.tools || {}, commands: s.commands || {} });
      });
      if (r.uncommitted) uncommitted.push(r.repo + ' (' + r.uncommitted + ')');
    });
    return { name: p.project, names: names, repos: p.repos.map(function (r) { return r.repo; }), commits: commits, sessions: sessions, uncommitted: uncommitted, color: PALETTE[i % PALETTE.length] };
  });
  var aw = (DATA.machine && DATA.machine.aw_days) || {};
  var unlocked = (function () {
    var ev = ((DATA.machine && DATA.machine.presence) || []).map(function (e) { return { t: new Date(e.time), e: e.event }; })
      .filter(function (x) { return !isNaN(x.t); }).sort(function (a, b) { return a.t - b.t; });
    var out = [], on = null;
    ev.forEach(function (x) {
      if (ON[x.e]) { if (on === null) on = x.t; }
      else if (OFF[x.e] && on !== null) { out.push([on, new Date(Math.min(+x.t, +on + 16 * H))]); on = null; }
    });
    if (on !== null) out.push([on, new Date(Math.min(+now, +on + 16 * H))]);
    return out;
  })();
  function editorFor(p, key) {
    var rec = aw[key]; if (!rec || !rec.editor) return 0;
    var t = 0;
    Object.keys(rec.editor).forEach(function (k) {
      var segs = k.split(' - ');
      for (var i = 0; i < segs.length; i++) if (p.names[segs[i].trim()]) { t += rec.editor[k]; return; }
    });
    return t;
  }
  function priceFor(model) {
    var prices = DATA.prices || {}; var keys = Object.keys(prices);
    for (var i = 0; i < keys.length; i++) if (model.toLowerCase().indexOf(keys[i].toLowerCase()) >= 0) return prices[keys[i]];
    return null;
  }
  var haveAw = Object.keys(aw).length > 0, havePres = unlocked.length > 0, havePrices = Object.keys(DATA.prices || {}).length > 0;

  // ---------- state
  var PRESETS = [
    { id: 'week', label: 'This week', start: function () { return monday(today); }, n: 7, step: 7 },
    { id: 'last', label: 'Last week', start: function () { return addDays(monday(today), -7); }, n: 7, step: 7 },
    { id: 'd14', label: '14 days', start: function () { return addDays(today, -13); }, n: 14, step: 14 },
    { id: 'd28', label: '28 days', start: function () { return addDays(today, -27); }, n: 28, step: 28 }
  ];
  var state = { preset: PRESETS[0], start: PRESETS[0].start(), n: 7, filter: null };
  var windowStart = DATA.window_start ? startOfDay(new Date(DATA.window_start)) : addDays(today, -(DATA.window_days || 28));

  // Mirrors session_day_minutes() in the Python: a session's effort split across the days it
  // happened on. Effort is bursts PLUS one idle cap per gap (that is what active_min counts),
  // so each day is weighted by its burst time plus any gap opening on it, and active_min is
  // apportioned by those weights - largest remainder, so the days sum to the session total.
  // Both sides must agree: the projects table is the Python's Summary column.
  function dayMinutes(s) {
    var idleMs = (DATA.idle_minutes || 15) * 60000, w = {}, order = [];
    function add(k, v) { if (!(k in w)) { w[k] = 0; order.push(k); } w[k] += v; }
    s.bursts.forEach(function (pr, i) {
      add(dateKey(pr[0]), 0);
      var cur = +pr[0], end = +pr[1];
      while (cur < end) {
        var stop = Math.min(end, +addDays(startOfDay(new Date(cur)), 1));
        add(dateKey(new Date(cur)), stop - cur);
        cur = stop;
      }
      if (i + 1 < s.bursts.length) add(dateKey(pr[1]), Math.max(Math.min(+s.bursts[i + 1][0] - +pr[1], idleMs), 0));
    });
    var total = s.active || 0, pool = 0, out = {};
    order.forEach(function (k) { pool += w[k]; });
    if (total <= 0 || pool <= 0) { order.forEach(function (k, i) { out[k] = !i ? total : 0; }); return out; }
    var used = 0, rem = [];
    order.forEach(function (k) { var e = total * w[k] / pool; out[k] = Math.floor(e); used += out[k]; rem.push({ k: k, f: e - Math.floor(e) }); });
    rem.sort(function (a, b) { return b.f - a.f || (a.k < b.k ? -1 : 1); });
    // bounded: a non-integer active_min out of a hand-edited slice must not walk off the end
    // and throw inside compute(), which would blank the whole page rather than one card
    for (var i = 0, n = Math.min(total - used, rem.length); i < n; i++) out[rem[i].k] += 1;
    return out;
  }

  var TOKK = ['in', 'cache_create', 'cache_read', 'out'];

  // ---------- compute for the current range
  function compute() {
    var start = state.start, end = addDays(start, state.n);
    var days = [];
    for (var i = 0; i < state.n; i++) { var d = addDays(start, i); if (d > today) break; days.push(d); }
    var per = projects.map(function (p) {
      var commits = p.commits.filter(function (c) { return c.t >= start && c.t < end; });
      // Selected by where the session WORKED, not where it opened: one session id can stay
      // open for days, and filtering on its start hid every later day's work behind it.
      var byDay = {}, editorByDay = {}, active = 0, editor = 0;
      days.forEach(function (d) { var k = dateKey(d); byDay[k] = { commits: [], sessions: [], active: 0 }; editorByDay[k] = editorFor(p, k); editor += editorByDay[k]; });
      commits.forEach(function (c) { var k = dateKey(c.t); if (byDay[k]) byDay[k].commits.push(c); });
      var sel = [];
      p.sessions.forEach(function (s) {
        var dm = dayMinutes(s), mine = {}, inr = 0, whole = 0, any = false;
        Object.keys(dm).forEach(function (k) { whole += dm[k]; });
        days.forEach(function (d) { var k = dateKey(d); if (k in dm) { mine[k] = dm[k]; inr += dm[k]; any = true; } });
        if (any) sel.push({ s: s, mine: mine, inr: inr, whole: whole, first: Object.keys(dm).sort()[0] });
      });
      var sessions = sel.map(function (x) { return x.s; });
      sel.forEach(function (x) {
        // A day gets a per-day VIEW of the session, not the session itself: the same object in
        // five days' buckets made the Log print one session's whole span, active time and prompt
        // count five times, under days where minutes of it happened. Inherited through the
        // prototype so every existing reader (bursts, title, colour) still sees the session.
        Object.keys(x.mine).forEach(function (k) {
          if (!byDay[k]) return;
          var d0 = +startOfDay(new Date(k + 'T00:00:00')), d1 = +addDays(new Date(d0), 1), lo = null, hi = null;
          x.s.bursts.forEach(function (pr) {
            var a = Math.max(+pr[0], d0), b = Math.min(+pr[1], d1);
            if (b < a) return;
            if (lo === null || a < lo) lo = a;
            if (hi === null || b > hi) hi = b;
          });
          var view = Object.create(x.s);
          view.dayMin = x.mine[k];
          view.dayLo = new Date(lo === null ? Math.max(+x.s.a, d0) : lo);
          view.dayHi = new Date(hi === null ? +view.dayLo : hi);
          view.continued = k !== x.first;
          byDay[k].sessions.push(view);
          byDay[k].active += x.mine[k];
        });
        active += x.inr;
      });
      var tok = { inp: 0, cr: 0, out: 0 }, cost = 0, priced = true, models = {}, apportioned = false;
      sel.forEach(function (x) {
        var s = x.s, share = {};
        function acc(m) { return share[m] || (share[m] = { 'in': 0, cache_create: 0, cache_read: 0, out: 0 }); }
        if (s.byDay && Object.keys(s.byDay).length) {   // v1.18: this range takes its own days.
          // the length check matters: {} is truthy here but falsy on the Python side, and the
          // two must branch identically or they annotate the same cost differently
          Object.keys(s.byDay).forEach(function (k) {
            if (!(k in x.mine)) return;
            Object.keys(s.byDay[k]).forEach(function (m) {
              var a = acc(m), t = s.byDay[k][m] || {};
              TOKK.forEach(function (kk) { a[kk] += t[kk] || 0; });
            });
          });
        } else {                             // older slice: one total for the whole session
          var frac = x.whole ? x.inr / x.whole : 1;
          Object.keys(s.byModel).forEach(function (m) {
            // a model whose apportioned share rounds to nothing must not list itself in the
            // Models column, nor stamp the row "partial" for a contribution of zero tokens
            var t = s.byModel[m] || {}, v = {}, any = false;
            TOKK.forEach(function (kk) { v[kk] = Math.round((t[kk] || 0) * frac); if (v[kk]) any = true; });
            if (!any) return;
            var a = acc(m);
            TOKK.forEach(function (kk) { a[kk] += v[kk]; });
          });
          if (frac < 1 && Object.keys(share).length) apportioned = true;
        }
        Object.keys(share).forEach(function (m) {
          models[m] = 1; var t = share[m], pr = priceFor(m);
          tok.inp += (t['in'] || 0) + (t.cache_create || 0); tok.cr += t.cache_read || 0; tok.out += t.out || 0;
          if (pr) cost += ((t['in'] || 0) * (pr['in'] || 0) + (t.cache_create || 0) * (pr.cache_create || 0) + (t.cache_read || 0) * (pr.cache_read || 0) + (t.out || 0) * (pr.out || 0)) / 1e6;
          else priced = false;
        });
      });
      var branches = {}; sessions.forEach(function (s) { if (s.branch) branches[s.branch] = 1; });
      return { p: p, commits: commits, sessions: sessions, byDay: byDay, editorByDay: editorByDay, active: active, editorMin: editor / 60, tok: tok, cost: cost, priced: priced, apportioned: apportioned, models: Object.keys(models).filter(function (m) { return m !== '?'; }), branches: Object.keys(branches) };
    }).filter(function (x) { return x.commits.length || x.sessions.length || x.editorMin >= 1; });
    per.sort(function (a, b) { return (b.active + b.editorMin + b.commits.length * 5) - (a.active + a.editorMin + a.commits.length * 5); });
    return { start: start, end: end, days: days, per: per };
  }

  // ---------- render
  function render() {
    var R = compute();
    var focus = state.filter ? R.per.filter(function (x) { return x.p.name === state.filter; }) : R.per;
    if (state.filter && !focus.length) { state.filter = null; focus = R.per; }
    renderHeader(R);
    renderKpis(R, focus);
    renderDays(R, focus);
    renderProjects(R);
    renderGrid(R, focus);
    renderUsage(R, focus); renderAgents(R, focus);
    renderLog(R, focus);
  }

  function renderHeader(R) {
    var last = R.days.length ? R.days[R.days.length - 1] : R.start;
    var a = R.start.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }), b = last.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    el('rangeLabel').textContent = state.n === 7 ? isoWeek(R.start) + ' · ' + a + ' – ' + b : a + ' – ' + b;
    // the filter now survives reloads and overnight, so it has to be legible as scope rather
    // than as a faint tint on one table row that most of the page never mentions
    var sc = el('scope');
    if (state.filter) {
      sc.innerHTML = 'Showing ' + esc(state.filter) + ' <button id="clearScope" title="show all projects">&#10005;</button>';
      sc.hidden = false;
      el('clearScope').onclick = function () { this.blur(); state.filter = null; render(); };
    } else { sc.hidden = true; sc.innerHTML = ''; }
    el('prev').disabled = addDays(R.start, -state.preset.step) < addDays(windowStart, -6);
    el('next').disabled = addDays(R.start, state.preset.step) > today;
    var seg = el('presets');
    if (!seg.childNodes.length) PRESETS.forEach(function (ps) {
      var b = document.createElement('button'); b.textContent = ps.label; b.dataset.id = ps.id;
      b.onclick = function () { this.blur(); state.preset = ps; state.start = ps.start(); state.n = ps.n; render(); };
      seg.appendChild(b);
    });
    Array.prototype.forEach.call(seg.childNodes, function (b) { b.className = b.dataset.id === state.preset.id ? 'on' : ''; });
  }

  function renderKpis(R, focus) {
    var commits = sum(focus, function (x) { return x.commits.length; }), sessions = sum(focus, function (x) { return x.sessions.length; });
    var active = sum(R.days, function (d) { return wallClock(focus, d); }), editor = sum(focus, function (x) { return x.editorMin; });
    // Effort, not elapsed: x.active is the project's summed session active_min, the same number
    // the projects table below renders and the report's Summary column totals. Do NOT compute it
    // by unioning bursts - active_min also carries idle_minutes per burst gap, so a union runs
    // tens of percent low and the dashboard would disagree with the report.
    var agent = sum(focus, function (x) { return x.active; });
    var desk = 0, unl = 0, ed = 0;
    R.days.forEach(function (d) {
      var k = dateKey(d); if (aw[k]) { desk += aw[k].desk_s / 60; ed += (aw[k].editor_s || 0) / 60; }
      var d0 = +d, d1 = +addDays(d, 1); unlocked.forEach(function (iv) { unl += overlap(+iv[0], +iv[1], d0, d1) / 60000; });
    });
    var cards = [
      { v: commits, l: 'commits' },
      { v: sessions, l: 'Claude Code sessions' },
      { v: fmtDur(agent), l: state.filter ? 'agent-hours \u00b7 ' + state.filter : 'agent-hours',
        s: 'effort: parallel sessions add up' + (state.filter ? '' : '; equals the per-project totals below') },
      { v: fmtDur(active), l: 'elapsed', s: 'wall clock, any session; concurrent sessions count once; idle cap ' + DATA.idle_minutes + ' min' }
    ];
    if (haveAw) cards.push({ v: fmtDur(state.filter ? editor : ed), l: state.filter ? 'editor time · ' + state.filter : 'editor time', s: 'VS Code in front, at the keyboard' });
    if (haveAw) cards.push({ v: fmtDur(desk), l: 'at the desk', s: 'any app, keyboard or mouse active' });
    if (havePres) cards.push({ v: fmtDur(unl), l: 'unlocked', s: 'logon/unlock to lock/sleep' });
    el('kpis').innerHTML = cards.map(function (c) { return '<div class="kpi"><div class="v">' + esc(c.v) + '</div><div class="l">' + esc(c.l) + '</div>' + (c.s ? '<div class="s">' + esc(c.s) + '</div>' : '') + '</div>'; }).join('');
  }

  function renderDays(R, focus) {
    var notes = ['Bars are stretches of Claude Code activity, ticks are commits, coloured by project. The Claude figure is wall-clock time with any session active.'];
    if (havePres) notes.push('Light blue is the machine unlocked.');
    if (!haveAw) notes.push('Install ActivityWatch for desk and editor time.');
    el('daysNote').textContent = notes.join(' ');
    var html = '<div class="dayrow axis"><div></div><div class="track">' + [0, 3, 6, 9, 12, 15, 18, 21, 24].map(function (h) { return '<span class="tick" style="left:' + (h / 24 * 100) + '%">' + pad(h) + '</span>'; }).join('') + '</div><div class="figs">' +
      (haveAw ? '<span>desk</span><span>editor</span>' : '<span></span><span></span>') + '<span>Claude (elapsed)</span><span>commits</span></div></div>';
    var days = R.days.slice().reverse();
    days.forEach(function (d) {
      var k = dateKey(d), d0 = +d, d1 = +addDays(d, 1);
      var parts = [];
      [3, 6, 9, 12, 15, 18, 21].forEach(function (h) { parts.push('<i class="gl" style="left:' + (h / 24 * 100) + '%"></i>'); });
      unlocked.forEach(function (iv) {
        var s = Math.max(+iv[0], d0), e = Math.min(+iv[1], d1); if (e <= s) return;
        parts.push('<i class="unl" style="left:' + ((s - d0) / D * 100) + '%;width:' + ((e - s) / D * 100) + '%" title="unlocked ' + hm(new Date(s)) + '–' + hm(new Date(e)) + '"></i>');
      });
      var nC = 0, act = 0;
      focus.forEach(function (x) {
        var dd = x.byDay[k]; if (!dd) return;
        dd.sessions.forEach(function (s) {
          s.bursts.forEach(function (pr) {
            var a = Math.max(+pr[0], d0), b = Math.min(+pr[1], d1); if (b < a) return;
            var w = Math.max((b - a) / D * 100, 0.4);
            // ~active is THIS day's share; the session's own span stays labelled as the session,
            // or a bar on day three of a long session claims the whole session's hours
            parts.push('<i class="sess" style="left:' + ((a - d0) / D * 100) + '%;width:' + w + '%;background:' + x.p.color + '" title="' + esc(x.p.name + ' · ' + hm(pr[0]) + '–' + hm(pr[1]) + ' · ~' + fmtDur(s.dayMin) + ' active this day · session ' + hm(s.a) + '–' + hm(s.b) + (s.continued ? ' (continued)' : '') + ' · ' + s.title) + '"></i>');
          });
        });
        dd.commits.forEach(function (c) {
          parts.push('<i class="ct" style="left:' + ((+c.t - d0) / D * 100) + '%;background:' + x.p.color + '" title="' + esc(x.p.name + ' · ' + hm(c.t) + ' · ' + c.subject) + '"></i>');
        });
        nC += dd.commits.length;
      });
      act = wallClock(focus, d);
      var rec = aw[k], ed = 0;
      if (state.filter) focus.forEach(function (x) { ed += (x.editorByDay[k] || 0) / 60; }); else ed = rec ? (rec.editor_s || 0) / 60 : 0;
      var first = null, last = null;
      // clamped to the day: a session that opened last week must not drag this day's first
      // trace back to the day it opened
      focus.forEach(function (x) {
        var dd = x.byDay[k]; if (!dd) return;
        dd.sessions.forEach(function (s) {
          s.bursts.forEach(function (pr) {
            var a = Math.max(+pr[0], d0), b = Math.min(+pr[1], d1); if (b < a) return;
            if (!first || a < +first) first = new Date(a);
            if (!last || b > +last) last = new Date(b);
          });
        });
        dd.commits.forEach(function (c) { if (!first || c.t < first) first = c.t; if (!last || c.t > last) last = c.t; });
      });
      html += '<div class="dayrow' + (+d === +today ? ' today' : '') + '"><div class="dl">' + esc(dayLabel(d)) + '<small>' + (first ? hm(first) + ' – ' + hm(last) : '&nbsp;') + '</small></div><div class="track">' + parts.join('') + '</div><div class="figs">' +
        (haveAw ? '<span><b>' + (rec ? fmtDur(rec.desk_s / 60) : '–') + '</b>desk</span><span><b>' + (ed >= 1 ? fmtDur(ed) : '–') + '</b>editor</span>' : '<span></span><span></span>') +
        '<span><b>' + (act ? fmtDur(act) : '–') + '</b>Claude</span><span><b>' + (nC || '–') + '</b>commits</span></div></div>';
    });
    el('days').innerHTML = days.length ? html : '<div class="empty">Nothing in this range yet.</div>';
  }

  function renderProjects(R) {
    if (!R.per.length) { el('projects').innerHTML = '<div class="empty">No activity in this range.</div>'; return; }
    var max = Math.max.apply(null, R.per.map(function (x) { return x.active + x.editorMin; }).concat([1]));
    var html = '<table><thead><tr><th>Project</th><th>Commits</th><th>Sessions</th><th title="active time summed over this project\'s sessions; parallel sessions add up">Claude Code</th>' + (haveAw ? '<th>Editor</th>' : '') + '<th style="text-align:left">Time</th>' + (havePrices ? '<th>Est. cost</th>' : '') + '</tr></thead><tbody>';
    R.per.forEach(function (x) {
      var a = x.active / max * 100, e = x.editorMin / max * 100;
      html += '<tr class="p' + (state.filter === x.p.name ? ' sel' : '') + '" data-p="' + esc(x.p.name) + '"><td><span class="sw" style="background:' + x.p.color + '"></span>' + esc(x.p.name) +
        (x.p.repos.length > 1 || x.p.repos[0] !== x.p.name ? ' <span class="muted">' + esc(x.p.repos.join(', ')) + '</span>' : '') +
        (x.p.uncommitted.length ? '<span class="badge" title="files changed but not committed">uncommitted: ' + esc(x.p.uncommitted.join(', ')) + '</span>' : '') + '</td>' +
        '<td>' + x.commits.length + '</td><td>' + x.sessions.length + '</td><td>' + (x.active ? fmtDur(x.active) : '–') + '</td>' + (haveAw ? '<td>' + (x.editorMin >= 1 ? fmtDur(x.editorMin) : '–') + '</td>' : '') +
        '<td style="text-align:left"><div class="bar"><i style="width:' + (a + e) + '%;background:' + x.p.color + ';opacity:.35"></i><i style="width:' + a + '%;background:' + x.p.color + '"></i></div></td>' +
        (havePrices ? '<td>' + (x.cost ? DATA.currency + x.cost.toFixed(2) + (x.priced ? '' : '*') : '–') + '</td>' : '') + '</tr>';
    });
    html += '</tbody></table><div class="legend">' + (haveAw ? '<span><i style="background:#999"></i>Claude Code active</span><span><i style="background:#ccc"></i>plus editor time</span>' : '') + '<span>Claude Code here is effort per project: parallel sessions add up, so the column can exceed the day. The Days rows and the elapsed card show wall-clock time.</span></div>';
    el('projects').innerHTML = html;
    Array.prototype.forEach.call(el('projects').querySelectorAll('tr.p'), function (tr) {
      tr.onclick = function () { state.filter = state.filter === tr.dataset.p ? null : tr.dataset.p; render(); };
    });
  }

  function renderGrid(R, focus) {
    if (!focus.length || !R.days.length) { el('grid').innerHTML = '<div class="empty">No activity in this range.</div>'; return; }
    var max = 1;
    focus.forEach(function (x) { R.days.forEach(function (d) { var k = dateKey(d); max = Math.max(max, (x.byDay[k] ? x.byDay[k].active : 0) + (x.editorByDay[k] || 0) / 60); }); });
    var html = '<table class="grid"><thead><tr><th>Project</th>' + R.days.map(function (d) { return '<th>' + esc(shortDay(d)) + '</th>'; }).join('') + '</tr></thead><tbody>';
    focus.forEach(function (x) {
      html += '<tr><td><span class="sw" style="background:' + x.p.color + '"></span>' + esc(x.p.name) + '</td>';
      R.days.forEach(function (d) {
        var k = dateKey(d), dd = x.byDay[k], ed = (x.editorByDay[k] || 0) / 60;
        var act = dd ? dd.active : 0, nC = dd ? dd.commits.length : 0;
        var bits = []; if (nC) bits.push(nC + 'c'); if (act) bits.push(fmtDur(act));
        var alpha = Math.min((act + ed) / max, 1) * 0.55;
        html += '<td class="c" style="background:' + hexA(x.p.color, alpha) + '" title="' + esc((ed >= 1 ? 'editor ' + fmtDur(ed) : '')) + '">' + (bits.join(' · ') || (ed >= 1 ? '<span class="muted">' + fmtDur(ed) + '</span>' : '')) + '</td>';
      });
      html += '</tr>';
    });
    el('grid').innerHTML = html + '</tbody></table>';
  }
  function hexA(hex, a) { var n = parseInt(hex.slice(1), 16); return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a.toFixed(3) + ')'; }

  function renderUsage(R, focus) {
    var rows = focus.filter(function (x) { return x.tok.inp || x.tok.cr || x.tok.out; });
    if (!rows.length) { el('usageCard').style.display = 'none'; return; }
    el('usageCard').style.display = '';
    var max = Math.max.apply(null, rows.map(function (x) { return x.tok.inp + x.tok.cr + x.tok.out; }));
    var tot = { inp: 0, cr: 0, out: 0, cost: 0, priced: true };
    var html = '<table><thead><tr><th>Project</th><th>Sessions</th><th>Input</th><th>Cache read</th><th>Output</th><th style="text-align:left">Share</th>' + (havePrices ? '<th>Est. cost</th>' : '') + '<th style="text-align:left">Models</th></tr></thead><tbody>';
    rows.forEach(function (x) {
      var t = x.tok.inp + x.tok.cr + x.tok.out; tot.inp += x.tok.inp; tot.cr += x.tok.cr; tot.out += x.tok.out; tot.cost += x.cost; if (!x.priced) tot.priced = false;
      html += '<tr><td><span class="sw" style="background:' + x.p.color + '"></span>' + esc(x.p.name) + '</td><td>' + x.sessions.length + '</td><td>' + fmtTok(x.tok.inp) + '</td><td>' + fmtTok(x.tok.cr) + '</td><td>' + fmtTok(x.tok.out) + '</td>' +
        '<td style="text-align:left"><div class="tokbar" style="width:' + (t / max * 100) + '%"><i style="width:' + (x.tok.inp / t * 100) + '%;background:' + x.p.color + '"></i><i style="width:' + (x.tok.cr / t * 100) + '%;background:' + x.p.color + ';opacity:.35"></i><i style="width:' + (x.tok.out / t * 100) + '%;background:#1b1f24"></i></div></td>' +
        (havePrices ? '<td>' + DATA.currency + x.cost.toFixed(2) + (x.priced ? '' : '*') + (x.apportioned ? '†' : '') + '</td>' : '') + '<td style="text-align:left" class="muted">' + esc(x.models.map(function (m) { return m.replace('claude-', ''); }).join(', ')) + '</td></tr>';
    });
    html += '<tr><td><b>Total</b></td><td></td><td><b>' + fmtTok(tot.inp) + '</b></td><td><b>' + fmtTok(tot.cr) + '</b></td><td><b>' + fmtTok(tot.out) + '</b></td><td></td>' + (havePrices ? '<td><b>' + DATA.currency + tot.cost.toFixed(2) + (tot.priced ? '' : '*') + '</b></td>' : '') + '<td></td></tr></tbody></table>' +
      '<div class="legend"><span><i style="background:#888"></i>input (incl. cache writes)</span><span><i style="background:#ccc"></i>cache read</span><span><i style="background:#1b1f24"></i>output</span>' +
      (havePrices ? (tot.priced ? '' : '<span>* some models have no price in the config</span>') : '<span>add prices to ~/.claude/worklog.json for a cost column</span>') + '</div>';
    // a caveat about which cost figures can be trusted is not a colour key: it marks the rows
    // it applies to, exactly as * marks unpriced ones, and explains itself under the table
    if (havePrices && rows.some(function (x) { return x.apportioned; }))
      html += '<div class="note" style="max-width:70ch">† an estimated cost, not a measured one. These sessions were collected before you upgraded, when one token total covered the whole session however many days it ran; their spend is split across days in proportion to the effort recorded on each. Sessions collected since are exact, and re-collecting a repo replaces the estimate.</div>';
    el('usage').innerHTML = html;
  }

  function renderAgents(R, focus) {
    var nameOf = function (n) { var m = DATA.agent_names || {}; return Object.prototype.hasOwnProperty.call(m, n) ? m[n] : n; };
    var byProj = [], cmds = {}, tools = {};
    focus.forEach(function (x) {
      var agents = {};
      x.sessions.forEach(function (s) {
        Object.keys(s.agents).forEach(function (k) { var a = s.agents[k], g = agents[k] = agents[k] || { runs: 0, wall: 0, inp: 0, out: 0 };
          g.runs += a.runs || 0; g.wall += a.wall_s || 0; g.inp += ((a.tokens || {}).in || 0) + ((a.tokens || {}).cache_create || 0); g.out += (a.tokens || {}).out || 0; });
        Object.keys(s.commands).forEach(function (k) { cmds[k] = (cmds[k] || 0) + s.commands[k]; });
        Object.keys(s.tools).forEach(function (k) { tools[k] = (tools[k] || 0) + s.tools[k]; });
      });
      var names = Object.keys(agents);
      if (names.length) byProj.push({ p: x.p, agents: agents, names: names });
    });
    if (!byProj.length && !Object.keys(cmds).length) { el('agentsCard').style.display = 'none'; return; }
    el('agentsCard').style.display = '';
    var html = '';
    if (byProj.length) {
      var max = 1;
      byProj.forEach(function (b) {
        b.total = { runs: 0, wall: 0, inp: 0, out: 0 };
        b.names.forEach(function (n) { var g = b.agents[n]; b.total.runs += g.runs; b.total.wall += g.wall; b.total.inp += g.inp; b.total.out += g.out; if (g.wall > max) max = g.wall; });
        b.names.sort(function (n1, n2) { return b.agents[n2].wall - b.agents[n1].wall; });
      });
      byProj.sort(function (b1, b2) { return b2.total.wall - b1.total.wall; });
      html += '<table><thead><tr><th style="text-align:left">Project / agent</th><th>Runs</th><th>Time</th><th style="text-align:left">Share</th><th>Input</th><th>Output</th></tr></thead><tbody>';
      byProj.forEach(function (b) {
        html += '<tr><td style="text-align:left"><span class="sw" style="background:' + b.p.color + '"></span><b>' + esc(b.p.name) + '</b></td><td><b>' + b.total.runs + '</b></td><td><b>' + fmtDur(b.total.wall / 60) + '</b></td><td></td><td><b>' + (b.total.inp ? fmtTok(b.total.inp) : '\u2013') + '</b></td><td><b>' + (b.total.out ? fmtTok(b.total.out) : '\u2013') + '</b></td></tr>';
        b.names.forEach(function (n) { var g = b.agents[n];
          html += '<tr><td style="text-align:left;padding-left:36px" title="' + esc(n) + '">' + esc(nameOf(n)) + '</td><td>' + g.runs + '</td><td>' + fmtDur(g.wall / 60) + '</td><td style="text-align:left"><div class="bar"><i style="width:' + (g.wall / max * 100) + '%;background:#1b1f24"></i></div></td><td>' + (g.inp ? fmtTok(g.inp) : '\u2013') + '</td><td>' + (g.out ? fmtTok(g.out) : '\u2013') + '</td></tr>'; });
      });
      html += '</tbody></table>';
    }
    var ck = Object.keys(cmds).sort(function (a, b) { return cmds[b] - cmds[a]; });
    var tk = Object.keys(tools).sort(function (a, b) { return tools[b] - tools[a]; }).slice(0, 10);
    html += '<div class="legend">' + (ck.length ? '<span><b>Commands</b>&nbsp; ' + esc(ck.map(function (k) { return k + ' \u00d7' + cmds[k]; }).join(' \u00b7 ')) + '</span>' : '') + (tk.length ? '<span><b>Tools</b>&nbsp; ' + esc(tk.map(function (k) { return k + ' ' + tools[k]; }).join(' \u00b7 ')) + '</span>' : '') + '</div>';
    el('agents').innerHTML = html;
  }

  function renderTrend() {
    // completed weeks from the archive + current week to date from the slices
    var weeks = (DATA.weeks || []).slice();
    var cur = { week: isoWeek(today), start: dateKey(monday(today)), projects: {}, partial: true };
    var ms = monday(today), me = addDays(ms, 7);
    projects.forEach(function (p) {
      // by the day the work happened, like every other figure on the page. Filtering the
      // current week by session START while the archived weeks below it use day attribution
      // made the last bar read 19.4h against the KPI's 29.4h for the same week.
      var act = 0;
      p.sessions.forEach(function (s) {
        var dm = dayMinutes(s);
        for (var d = ms; d < me && d <= today; d = addDays(d, 1)) { var k = dateKey(d); if (k in dm) act += dm[k]; }
      });
      var ed = 0; for (var d = ms; d < me && d <= today; d = addDays(d, 1)) ed += editorFor(p, dateKey(d)) / 60;
      var c = p.commits.filter(function (x) { return x.t >= ms && x.t < me; }).length;
      if (act || ed >= 1 || c) cur.projects[p.name] = { active_min: act, editor_min: ed, commits: c };
    });
    weeks = weeks.filter(function (w) { return w.week !== cur.week; });
    weeks.push(cur);
    weeks.sort(function (a, b) { return a.week < b.week ? -1 : 1; });
    if (weeks.length < 2) { el('trendCard').style.display = 'none'; return; }
    var names = {};
    weeks.forEach(function (w) { Object.keys(w.projects).forEach(function (n) { names[n] = (names[n] || 0) + (w.projects[n].active_min || 0) + (w.projects[n].editor_min || 0); }); });
    var order = Object.keys(names).sort(function (a, b) { return names[b] - names[a]; });
    var colorOf = {}; projects.forEach(function (p) { colorOf[p.name] = p.color; });
    order.forEach(function (n, i) { if (!colorOf[n]) colorOf[n] = PALETTE[(projects.length + i) % PALETTE.length]; });
    var W = 900, Hh = 220, padL = 40, padB = 26, padT = 10, bw = (W - padL - 10) / weeks.length;
    var maxH = Math.max.apply(null, weeks.map(function (w) { return sum(order, function (n) { var x = w.projects[n]; return x ? ((x.active_min || 0) + (x.editor_min || 0)) / 60 : 0; }); }).concat([1]));
    var step = maxH > 40 ? 10 : maxH > 16 ? 5 : maxH > 8 ? 2 : 1; var top = Math.ceil(maxH / step) * step;
    var y = function (h) { return padT + (Hh - padT - padB) * (1 - h / top); };
    var svg = '<svg class="trend" viewBox="0 0 ' + W + ' ' + Hh + '" preserveAspectRatio="none">';
    for (var g = 0; g <= top; g += step) svg += '<line x1="' + padL + '" x2="' + W + '" y1="' + y(g) + '" y2="' + y(g) + '" stroke="#eee"/><text x="' + (padL - 6) + '" y="' + (y(g) + 4) + '" text-anchor="end">' + g + 'h</text>';
    weeks.forEach(function (w, i) {
      var x0 = padL + i * bw + bw * 0.15, wd = bw * 0.7, acc = 0;
      order.forEach(function (n) {
        var p = w.projects[n]; if (!p) return; var h = ((p.active_min || 0) + (p.editor_min || 0)) / 60; if (!h) return;
        svg += '<rect x="' + x0 + '" y="' + y(acc + h) + '" width="' + wd + '" height="' + (y(acc) - y(acc + h)) + '" fill="' + colorOf[n] + '"' + (w.partial ? ' opacity=".6"' : '') + '><title>' + esc(w.week + ' · ' + n + ' · ' + h.toFixed(1) + 'h' + (p.commits ? ' · ' + p.commits + ' commits' : '')) + '</title></rect>';
        acc += h;
      });
      svg += '<text x="' + (x0 + wd / 2) + '" y="' + (Hh - 8) + '" text-anchor="middle">' + esc(w.week.slice(5)) + (w.partial ? '·' : '') + '</text>';
    });
    svg += '</svg>';
    el('trend').innerHTML = svg + '<div class="legend">' + order.slice(0, 12).map(function (n) { return '<span><i style="background:' + colorOf[n] + '"></i>' + esc(n) + '</span>'; }).join('') + '<span>· = week to date</span></div>';
  }

  function renderLog(R, focus) {
    if (!focus.length) { el('log').innerHTML = '<div class="empty">Nothing to list.</div>'; return; }
    var html = '';
    focus.forEach(function (x) {
      if (!x.commits.length && !x.sessions.length) return;
      html += '<h3><span class="sw" style="background:' + x.p.color + '"></span>' + esc(x.p.name) + ' <span class="muted" style="font-weight:400">' + esc(x.p.repos.join(', ')) + (x.branches.length ? ' · ' + x.branches.join(', ') : '') + '</span></h3>';
      R.days.slice().reverse().forEach(function (d) {
        var dd = x.byDay[dateKey(d)]; if (!dd || (!dd.commits.length && !dd.sessions.length)) return;
        var items = dd.commits.map(function (c) { return { t: c.t, html: '<code>' + esc(c.hash.slice(0, 7)) + '</code> ' + esc(c.subject) }; })
          .concat(dd.sessions.map(function (s) {
            // this day's share of the session, clamped to this day - the same wording the
            // Markdown report uses, so the two never tell different stories about one session
            return { t: s.dayLo, html: '<span class="cc">Claude Code</span> ' + hm(s.dayLo) + '–' + hm(s.dayHi) + ' · ~' + fmtDur(s.dayMin) + ' active · ' + (s.continued ? 'continued' : s.prompts + ' prompt' + (s.prompts === 1 ? '' : 's')) + (s.title ? ' · “' + esc(s.title) + '”' : '') };
          }));
        items.sort(function (a, b) { return a.t - b.t; });
        html += '<h4>' + esc(dayLabel(d)) + '</h4><ul>' + items.map(function (it) { return '<li><span class="t">' + hm(it.t) + '</span><span>' + it.html + '</span></li>'; }).join('') + '</ul>';
      });
    });
    el('log').innerHTML = html || '<div class="empty">Nothing to list.</div>';
  }

  // ---------- keep the view across a reload
  // The page is opened as a file:// URL, so it cannot fetch its own data - reloading is the
  // only way to pick up a re-render. That is fine as long as it comes back to the same view:
  // sessionStorage where it is allowed, window.name where it is not (an opaque file origin).
  function saveView() {
    var g = el('grid'), f = document.activeElement;
    var v = JSON.stringify({ p: state.preset.id, s: dateKey(state.start), n: state.n, f: state.filter,
                             // a preset whose start is still "now" must be recomputed on load, or a
                             // page left open across midnight comes back lit "This week" showing last week
                             rel: dateKey(state.start) === dateKey(state.preset.start()),
                             y: Math.round(window.pageYOffset || 0), x: Math.round(window.pageXOffset || 0),
                             gx: g ? Math.round(g.scrollLeft) : 0,
                             fid: (f && f !== document.body && f.id) ? f.id : null });
    try { sessionStorage.setItem('worklog-view', v); return; } catch (e) { }
    try { window.name = 'worklog:' + v; } catch (e) { }
  }
  function loadView() {
    var raw = null;
    try { raw = sessionStorage.getItem('worklog-view'); } catch (e) { }
    if (!raw && typeof window.name === 'string' && window.name.indexOf('worklog:') === 0) raw = window.name.slice(8);
    if (!raw) return null;
    try {
      var v = JSON.parse(raw), ps = null;
      PRESETS.forEach(function (x) { if (x.id === v.p) ps = x; });
      if (ps) { state.preset = ps; state.n = v.n || ps.n; }
      var d = v.rel && ps ? ps.start() : (v.s ? startOfDay(new Date(v.s + 'T00:00:00')) : null);
      if (d && !isNaN(+d)) state.start = d;
      state.filter = v.f || null;
      return v;
    } catch (e) { return null; }
  }
  // Reloading is how this page stays current, so it must never land mid-read. It defers while
  // the tab is hidden, while anything is selected (the Log is the copy-out surface), while a
  // control has focus, and for a few seconds after any pointer or key activity - a day bar's
  // detail lives in a native title attribute, which takes a deliberate hover to read.
  var lastAct = 0, dueAt = 0;
  ['mousemove', 'keydown', 'wheel', 'touchstart'].forEach(function (ev) {
    window.addEventListener(ev, function () { lastAct = Date.now(); }, { passive: true });
  });
  function busy() {
    if (document.hidden) return true;
    if (Date.now() - lastAct < 5000) return true;
    var ae = document.activeElement;
    if (ae && (/^(INPUT|TEXTAREA)$/.test(ae.tagName) || ae.isContentEditable)) return true;
    try { var s = getSelection(); if (s && !s.isCollapsed) return true; } catch (e) { }
    return false;
  }
  function reloadNow() { saveView(); location.reload(); }
  function scheduleReload() {
    if (!DATA.reload_s) return;
    dueAt = Date.now() + DATA.reload_s * 1000;
    setTimeout(function tick() {
      if (Date.now() < dueAt) { setTimeout(tick, Math.min(dueAt - Date.now(), 5000)); return; }
      if (busy()) { setTimeout(tick, 2000); return; }
      reloadNow();
    }, DATA.reload_s * 1000);
  }
  // coming back to a tab that was hidden for an hour should not mean another full interval of
  // stale data - and a hidden tab's timers are throttled hard, so the tick above may not be due
  document.addEventListener('visibilitychange', function () {
    if (!DATA.reload_s || document.hidden) return;
    if (Date.now() >= dueAt && !busy()) reloadNow();
  });

  // ---------- wire up
  el('prev').onclick = function () { this.blur(); state.start = addDays(state.start, -state.preset.step); render(); };
  el('next').onclick = function () { this.blur(); state.start = addDays(state.start, state.preset.step); render(); };
  el('potName').textContent = DATA.pot || '';
  el('meta').textContent = 'rendered ' + new Date(DATA.generated).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) + ' · ' + DATA.repo_count + ' repo' + (DATA.repo_count === 1 ? '' : 's') + ' reporting' + (haveAw ? '' : ' · no ActivityWatch data') + (DATA.reload_s ? ' · reloads itself every ' + (DATA.reload_s >= 60 ? Math.round(DATA.reload_s / 60) + ' min' : DATA.reload_s + 's') : ' · refresh the page after a run') + (DATA.version ? ' · worklog v' + DATA.version : '') + (DATA.whats_new ? ' · new: ' + DATA.whats_new : '');
  var view = loadView();
  try { history.scrollRestoration = 'manual'; } catch (e) { }   // or the browser races our restore
  renderTrend();
  render();
  if (view) {
    if (view.y || view.x) window.scrollTo(view.x || 0, view.y || 0);
    var g = el('grid'); if (g && view.gx) g.scrollLeft = view.gx;
    if (view.fid) { var f = el(view.fid); if (f && f.focus) f.focus(); }
  }
  window.addEventListener('beforeunload', saveView);
  scheduleReload();
})();
</script>
</body>
</html>
'''


# ----------------------------------------------------------------------------- morning brief (first run of the day)

def build_morning(slices, machines, cfg, pot):
    """A one-screen page: yesterday (or the last day with activity), where each project was left, this week so far."""
    now = datetime.now(local_tz())
    today = now.date()
    idle = int(cfg["idle_minutes"])
    # This page opens itself every morning, so it reads a day the same way the report does:
    # by the work done that day, not by which sessions happened to open on it.
    # last day before today with any trace, within a week
    candidate = None
    for back in range(1, 8):
        d = today - timedelta(days=back)
        d0, d1 = day_window(d)
        hit = False
        for sl in slices:
            if any(d0 <= (parse_iso(c.get("time")) or d0 - timedelta(1)) <= d1 for c in sl.get("commits", [])) or \
               any(d in session_day_minutes(x, idle) for x in sl.get("sessions", [])):
                hit = True
                break
        if hit:
            candidate = d
            break
    y = candidate or (today - timedelta(days=1))
    y0, y1 = day_window(y)
    _, _, _ = build_report(slices, machines, y0, y1, cfg)  # keeps the same filters; output unused
    rows = []
    for sl in slices:
        commits = [c for c in sl.get("commits", []) if parse_iso(c.get("time")) and y0 <= parse_iso(c["time"]) <= y1]
        sessions, active = [], 0
        for x in sl.get("sessions", []):
            mins = session_day_minutes(x, idle).get(y)
            if not mins:            # a stray single-event burst is not a day's work
                continue
            sessions.append(x)
            active += mins
        if not commits and not sessions and not sl.get("uncommitted"):
            continue
        last = max(sessions, key=lambda x: x.get("end") or "", default=None)
        last_end = None
        if last is not None:
            ends = [min(b, y1) for a, b in session_bursts(last) if b >= y0 and a <= y1]
            last_end = max(ends) if ends else None
        rows.append({"project": sl["project"], "repo": sl.get("repo") or "", "commits": len(commits),
                     "active": active, "sessions": len(sessions),
                     "last_title": (last or {}).get("title") or "", "last_end": last_end,
                     "last_commit": commits[-1]["subject"] if commits else "", "uncommitted": sl.get("uncommitted") or 0,
                     "branch": (last or {}).get("branch") or ""})
    rows.sort(key=lambda r: (-(r["active"] + r["commits"] * 5), r["project"].lower()))
    # week so far
    monday = today - timedelta(days=today.weekday())
    w0, _ = day_window(monday)
    week = {}
    for sl in slices:
        w = week.setdefault(sl["project"], {"commits": 0, "active": 0})
        w["commits"] += sum(1 for c in sl.get("commits", []) if parse_iso(c.get("time")) and parse_iso(c["time"]) >= w0)
        for x in sl.get("sessions", []):
            for d, mins in session_day_minutes(x, idle).items():
                if d >= monday:
                    w["active"] += mins
    week_rows = sorted(((k, v) for k, v in week.items() if v["commits"] or v["active"]), key=lambda kv: -(kv[1]["active"] + kv[1]["commits"] * 5))
    # machine facts for that day
    aw_days, presence = {}, []
    for m in machines:
        aw_days.update((m.get("aw") or {}).get("days") or {})
        presence += (m.get("presence") or {}).get("events", [])
    rec = aw_days.get(y.isoformat()) or {}
    pres = presence_days(presence, now).get(y) if presence else None
    facts = []
    if rec:
        facts.append("%s at the desk" % fmt_dur(rec.get("desk_s", 0) / 60))
        if rec.get("editor_s"):
            facts.append("%s in the editor" % fmt_dur(rec["editor_s"] / 60))
    if pres:
        facts.append("unlocked %s\u2013%s" % (pres["first"].strftime("%H:%M"), pres["last"].strftime("%H:%M")))

    def esc(t):
        return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))

    def short(t, n=110):
        return t if len(t) <= n else t[: n - 1].rstrip() + "\u2026"

    day_name = "Yesterday" if y == today - timedelta(days=1) else y.strftime("%A")
    L = []
    L.append('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Morning \u00b7 %s</title>' % today.strftime("%a %d %b"))
    L.append('<meta name="viewport" content="width=device-width, initial-scale=1"><style>'
             'body{margin:0;font:15px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1b1f24;background:#f7f7f5}'
             'main{max-width:820px;margin:0 auto;padding:36px 28px 48px}'
             '.date{color:#6b7280;font-size:13px;letter-spacing:.3px}h1{font-size:26px;font-weight:600;margin:4px 0 6px;letter-spacing:-.3px}'
             '.facts{color:#6b7280;margin-bottom:26px}.facts+.facts{margin-top:-18px}h2{font-size:12px;text-transform:uppercase;letter-spacing:.7px;color:#6b7280;margin:26px 0 10px;font-weight:600}'
             '.p{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:12px 16px;margin-bottom:10px;display:grid;grid-template-columns:1fr auto;gap:4px 16px}'
             '.p .n{font-weight:600}.p .n small{color:#6b7280;font-weight:400;margin-left:8px}.p .m{color:#6b7280;font-size:13px;text-align:right;white-space:nowrap}'
             '.p .t{grid-column:1/-1;color:#374151;font-size:14px}.p .t b{color:#0f766e;font-weight:600}'
             '.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:#fff7ed;color:#c2410c;border:1px solid #fed7aa;margin-left:8px;font-weight:500;vertical-align:1px}'
             'table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden}'
             'td{padding:8px 14px;border-top:1px solid #f3f4f6}td:not(:first-child){text-align:right;color:#374151;white-space:nowrap}tr:first-child td{border-top:0}'
             '.quiet{color:#6b7280}a.btn{display:inline-block;margin-top:28px;padding:9px 16px;border-radius:8px;background:#1b1f24;color:#fff;text-decoration:none;font-size:14px}'
             '.foot{color:#9ca3af;font-size:12px;margin-top:22px}</style></head><body><main>')
    L.append('<div class="date">%s</div>' % today.strftime("%A \u00b7 %d %B %Y"))
    if not rows:
        L.append("<h1>Nothing left half-done.</h1><p class=\"quiet\">No commits or Claude Code sessions in the last week.</p>")
    else:
        top = rows[0]
        L.append("<h1>%s: %d project%s, %d commit%s.</h1>" % (
            day_name, len(rows), "" if len(rows) == 1 else "s", sum(r["commits"] for r in rows), "" if sum(r["commits"] for r in rows) == 1 else "s"))
    if facts:
        L.append('<div class="facts">%s \u00b7 %s</div>' % (esc(day_name), esc(" \u00b7 ".join(facts))))
    if cfg.get("prices"):
        y_line = cost_context_line(cost_and_context(slices, y0, y1, cfg), cfg)
        if y_line:
            L.append('<div class="facts">%s</div>' % esc(y_line))
    wn = whatsnew_note(pot, 3)
    if wn:
        L.append('<div class="facts">Worklog upgraded to v%s \u2014 %s.</div>' % (VERSION, esc(wn)))
    if rows:
        L.append("<h2>Where you left off</h2>")
        for r in rows:
            meta = []
            if r["commits"]:
                meta.append("%d commit%s" % (r["commits"], "" if r["commits"] == 1 else "s"))
            if r["active"]:
                meta.append("%s Claude Code" % fmt_dur(r["active"]))
            if r["last_end"]:
                meta.append("until %s" % r["last_end"].strftime("%H:%M"))
            L.append('<div class="p"><div class="n">%s<small>%s</small>%s</div><div class="m">%s</div>' % (
                esc(r["project"]), esc(r["repo"] if r["repo"] != r["project"] else ""),
                ('<span class="badge">%d uncommitted</span>' % r["uncommitted"]) if r["uncommitted"] else "", esc(" \u00b7 ".join(meta))))
            if r["last_title"]:
                L.append('<div class="t"><b>Working on:</b> \u201c%s\u201d</div>' % esc(short(r["last_title"])))
            elif r["last_commit"]:
                L.append('<div class="t"><b>Last commit:</b> %s</div>' % esc(short(r["last_commit"])))
            L.append("</div>")
    if week_rows:
        L.append("<h2>This week so far</h2>")
        if cfg.get("prices"):
            w_line = cost_context_line(cost_and_context(slices, w0, now, cfg), cfg)
            if w_line:
                L.append('<div class="facts">%s</div>' % esc(w_line))
        L.append("<table>")
        for k, v in week_rows[:8]:
            L.append("<tr><td>%s</td><td>%s</td><td>%d commit%s</td></tr>" % (esc(k), fmt_dur(v["active"]) if v["active"] else "\u2013", v["commits"], "" if v["commits"] == 1 else "s"))
        L.append("</table>")
    L.append('<a class="btn" href="%s">Open the dashboard</a>' % (Path(pot) / "dashboard.html").resolve().as_uri())
    machine = machine_context_note(cfg.get("settings_path"))
    foot = "Rendered %s from %s. Shows once a day on the first unlock or session; <code>worklog_agent.py brief</code> opens it any time." % (
        now.strftime("%H:%M"), esc(str(pot)))
    if machine:
        foot += " " + esc(machine)
    L.append('<div class="foot">%s</div>' % foot)
    L.append("</main></body></html>")
    return "\n".join(L)


def write_morning(cfg):
    pot = Path(cfg["pot"])
    slices, machines = load_slices(pot)
    if not slices:
        return None
    path = pot / "morning.html"
    atomic_write(path, build_morning(slices, machines, cfg, pot))
    return path


def open_popup(path):
    """Open the page in a frameless browser app window (Chrome or Edge), else the default browser."""
    if os.environ.get("WORKLOG_NO_OPEN"):
        return "skipped (WORKLOG_NO_OPEN)"
    url = Path(path).resolve().as_uri()
    if os.name == "nt":
        roots = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("LocalAppData", "")]
        for rel in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            for r in roots:
                exe = Path(r) / rel if r else None
                if exe and exe.exists():
                    try:
                        subprocess.Popen([str(exe), "--app=" + url, "--window-size=900,820", "--new-window"],
                                         creationflags=0x00000008 | 0x00000200, close_fds=True)
                        return "app window (%s)" % exe.name
                    except OSError:
                        continue
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            return "default browser"
        except OSError as e:
            return "failed: %s" % e
    try:
        import webbrowser
        webbrowser.open(url)
        return "default browser"
    except Exception as e:
        return "failed: %s" % e


def maybe_brief(cfg, event):
    """First trigger of the day (unlock, logon or session start) after brief_after: render the morning page and pop it up."""
    try:
        if not cfg.get("brief_popup", True):
            return
        now = datetime.now(local_tz())
        hh, mm = (str(cfg.get("brief_after") or "05:00").split(":") + ["0"])[:2]
        if now.time() < dtime(int(hh), int(mm)):
            return
        marker = Path(cfg["pot"]) / ".brief-date"
        if (read(marker) or "").strip() == now.date().isoformat():
            return
        path = write_morning(cfg)
        if not path:
            return
        atomic_write(marker, now.date().isoformat() + "\n")
        log("brief(%s): %s" % (event, open_popup(path)))
    except Exception:
        log("brief failed\n" + traceback.format_exc())


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def cmd_brief(args):
    cfg = central_cfg()
    path = write_morning(cfg)
    if not path:
        say("nothing to show yet (no slices in %s)" % cfg["pot"])
        return
    if args.render:
        say("rendered %s" % path)
    else:
        say("rendered %s \u00b7 %s" % (path, open_popup(path)))


# ----------------------------------------------------------------------------- hooks install

def hook_command(shared):
    py = "python" if shared else python_for_hooks()
    return '%s "$CLAUDE_PROJECT_DIR/.worklog/worklog_agent.py" run' % (py if " " not in py else '"%s"' % py)


def settings_file(root, shared):
    return root / ".claude" / ("settings.json" if shared else "settings.local.json")


def _is_ours(entry):
    return any(MARK in (h.get("command") or "") for h in entry.get("hooks", []))


def install_hooks(root, shared):
    path = settings_file(root, shared)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            sys.exit("cannot parse %s (%s); fix it first so nothing gets overwritten" % (path, e))
    hooks = data.setdefault("hooks", {})
    cmd = hook_command(shared)
    for event in ("SessionStart", "Stop", "SessionEnd"):
        entries = hooks.setdefault(event, [])
        entries[:] = [e for e in entries if not _is_ours(e)]
        entries.append({"hooks": [{"type": "command", "command": cmd, "timeout": 20}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(data, indent=2) + "\n")
    return path


def remove_hooks(root):
    removed = []
    for shared in (False, True):
        path = settings_file(root, shared)
        if not path.exists():
            continue
        data = read_json(path, {})
        hooks = data.get("hooks") or {}
        changed = False
        for event in list(hooks):
            kept = [e for e in hooks[event] if not _is_ours(e)]
            if len(kept) != len(hooks[event]):
                changed = True
                if kept:
                    hooks[event] = kept
                else:
                    del hooks[event]
        if changed:
            if not hooks:
                data.pop("hooks", None)
            atomic_write(path, json.dumps(data, indent=2) + "\n")
            removed.append(path)
    return removed


def hooks_installed(root):
    found = []
    for shared in (False, True):
        path = settings_file(root, shared)
        hooks = (read_json(path, {}) or {}).get("hooks") or {}
        events = [ev for ev, entries in hooks.items() if any(_is_ours(e) for e in entries)]
        if events:
            found.append((path, events))
    return found


def git_dir_path(root, rel):
    """Worktree-safe path under the repo's git dir (in a worktree, .git is a pointer file, not a directory)."""
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-path", rel],
                             **NOWIN, capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            p = Path(out.stdout.strip())
            return p if p.is_absolute() else root / p
    except (OSError, subprocess.TimeoutExpired):
        pass
    return root / ".git" / rel


def install_git_hook(root):
    hook = git_dir_path(root, "hooks/post-commit")
    hook.parent.mkdir(parents=True, exist_ok=True)
    py = python_for_hooks()
    line = '"%s" "$(git rev-parse --show-toplevel)/.worklog/worklog_agent.py" run --event post-commit >/dev/null 2>&1 &' % py
    if hook.exists():
        text = hook.read_text(encoding="utf-8", errors="replace")
        if MARK in text:
            return hook
        text = text.rstrip("\n") + "\n" + line + "\n"
    else:
        text = "#!/bin/sh\n" + line + "\n"
    hook.write_text(text, encoding="utf-8")
    try:
        hook.chmod(hook.stat().st_mode | 0o111)
    except OSError:
        pass
    return hook


def exclude_locally(root, rel):
    """Hide a path from git for this clone only (.git/info/exclude), without touching the shared .gitignore."""
    ex = git_dir_path(root, "info/exclude")
    try:
        ex.parent.mkdir(parents=True, exist_ok=True)
        text = ex.read_text(encoding="utf-8") if ex.exists() else ""
        if rel not in text.splitlines():
            ex.write_text(text.rstrip("\n") + ("\n" if text else "") + rel + "\n", encoding="utf-8")
    except OSError:
        pass


def machine_copy(pot):
    """A copy of this script inside the pot, so scheduled tasks don't depend on any one repo."""
    dst = Path(pot) / "bin" / "worklog_agent.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve()
    if src != dst.resolve():
        # atomic: the self-upgrade in cmd_run reads this file concurrently and must never see a torn copy
        fd, tmp = tempfile.mkstemp(prefix=".tmp-bin-", suffix=".py", dir=str(dst.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(src.read_bytes())
            os.replace(tmp, str(dst))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return dst


PRESENCE_PS = r'''
$ErrorActionPreference = 'Stop'
$py = '{PY}'
$script = '{SCRIPT}'
$ns = 'Root/Microsoft/Windows/TaskScheduler'
$user = "$env:USERDOMAIN\$env:USERNAME"
# Triggers scoped to this user only: the any-user forms need administrator rights, these don't.
function SessionTrigger($state) {
  $c = Get-CimClass -Namespace $ns -ClassName MSFT_TaskSessionStateChangeTrigger
  $t = New-CimInstance -CimClass $c -ClientOnly
  $t.StateChange = $state
  $t.UserId = $user
  $t
}
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances Parallel
$jobs = @(
  @{ Name = 'Worklog presence logon';  Event = 'logon';  Trigger = (New-ScheduledTaskTrigger -AtLogOn -User $user) },
  @{ Name = 'Worklog presence lock';   Event = 'lock';   Trigger = (SessionTrigger 7) },
  @{ Name = 'Worklog presence unlock'; Event = 'unlock'; Trigger = (SessionTrigger 8) }
)
foreach ($j in $jobs) {
  $action = New-ScheduledTaskAction -Execute $py -Argument ('"{0}" stamp {1}' -f $script, $j.Event)
  Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $j.Trigger -Settings $settings -Principal $principal -Force | Out-Null
  Write-Output ('registered ' + $j.Name)
}
'''

UNPRESENCE_PS = r'''
Get-ScheduledTask -TaskName 'Worklog presence *' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
Write-Output 'removed Worklog presence tasks'
'''


def run_powershell(script):
    fd, tmp = tempfile.mkstemp(suffix=".ps1")
    with os.fdopen(fd, "w", encoding="utf-8-sig") as fh:
        fh.write(script)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", tmp],
                             **NOWIN, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        return out.returncode, (out.stdout + out.stderr).strip()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


PRESENCE_TASKS = ("Worklog presence logon", "Worklog presence lock", "Worklog presence unlock")


def presence_registered():
    """True when all three Task Scheduler tasks exist (schtasks is available on every Windows)."""
    if os.name != "nt":
        return False
    try:
        for name in PRESENCE_TASKS:
            out = subprocess.run(["schtasks", "/Query", "/TN", name], **NOWIN, capture_output=True, timeout=30)
            if out.returncode != 0:
                return False
        return True
    except Exception:
        return False


def install_presence(pot):
    if os.name != "nt":
        return False, "presence stamps via Task Scheduler are Windows-only"
    dst = machine_copy(pot)
    script = PRESENCE_PS.replace("{PY}", str(pythonw())).replace("{SCRIPT}", str(dst))
    code, text = run_powershell(script)
    return code == 0, text


def uninstall_presence():
    if os.name != "nt":
        return False, "Windows-only"
    code, text = run_powershell(UNPRESENCE_PS)
    return code == 0, text


def aw_reachable(cfg):
    try:
        aw_get((cfg.get("aw_url") or "").rstrip("/") + "/api/0/buckets/", timeout=2)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------- auto-install (user-level hook)

USER_SETTINGS = Path("~/.claude/settings.json").expanduser()


def version_of(path):
    try:
        m = re.search(r'^VERSION\s*=\s*"([0-9.]+)"', Path(path).read_text(encoding="utf-8", errors="replace"), re.M)
        return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)
    except (OSError, ValueError):
        return (0,)


def global_hook_command(pot):
    py = python_for_hooks()
    return '%s "%s" bootstrap' % (py if " " not in py else '"%s"' % py, (Path(pot) / "bin" / "worklog_agent.py").as_posix())


def install_global_hook(pot):
    data = read_json(USER_SETTINGS, None) if USER_SETTINGS.exists() else {}
    if data is None:
        return None, "cannot parse %s; fix it first" % USER_SETTINGS
    hooks = data.setdefault("hooks", {})
    entries = hooks.setdefault("SessionStart", [])
    entries[:] = [e for e in entries if not _is_ours(e)]
    entries.append({"hooks": [{"type": "command", "command": global_hook_command(pot), "timeout": 20}]})
    atomic_write(USER_SETTINGS, json.dumps(data, indent=2) + "\n")
    return USER_SETTINGS, None


def remove_global_hook():
    data = read_json(USER_SETTINGS, None) if USER_SETTINGS.exists() else None
    if not data:
        return False
    hooks = data.get("hooks") or {}
    changed = False
    for event in list(hooks):
        kept = [e for e in hooks[event] if not _is_ours(e)]
        if len(kept) != len(hooks[event]):
            changed = True
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if changed:
        if not hooks:
            data.pop("hooks", None)
        atomic_write(USER_SETTINGS, json.dumps(data, indent=2) + "\n")
    return changed


def global_hook_installed():
    hooks = (read_json(USER_SETTINGS, {}) or {}).get("hooks") or {}
    return any(_is_ours(e) for e in hooks.get("SessionStart", []))


def cmd_bootstrap(args):
    """User-level SessionStart hook. Installs the agent into a git repo that has none, upgrades an older copy,
    and otherwise does nothing. Prints nothing (SessionStart stdout is injected into the session)."""
    try:
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
        if not (root / ".git").exists() or (root / ".noworklog").exists():
            return
        target = root / ".worklog" / "worklog_agent.py"
        me = Path(__file__).resolve()
        if target.exists():
            if target.resolve() == me:
                return
            mine = tuple(int(x) for x in VERSION.split("."))
            if version_of(target) >= mine:
                return
            reason = "upgrade %s -> %s" % (".".join(map(str, version_of(target))), VERSION)
        else:
            reason = "new repo"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(me), str(target))
        spawn_detached(["install", "--quiet"], script=target)
        log("bootstrap: %s in %s (install started)" % (reason, root))
        # SessionStart stdout reaches the session, so say it once, only when something changed
        if reason == "new repo":
            say("Worklog agent v%s installed in this repo; it now reports to %s." % (VERSION, central_cfg()["pot"]))
        else:
            say("Worklog agent %s in this repo - new: %s." % (reason.replace("upgrade ", "upgraded v").replace(" -> ", " to v"), WHATS_NEW))
    except Exception:
        log("bootstrap failed\n" + traceback.format_exc())


# ----------------------------------------------------------------------------- commands

def cmd_install(args):
    global QUIET
    QUIET = bool(getattr(args, "quiet", False))
    root = repo_root()
    cfg = central_cfg()
    if args.pot:
        cfg["pot"] = str(Path(os.path.expanduser(args.pot)))
    if args.idle_minutes:
        cfg["idle_minutes"] = args.idle_minutes
    cfg["window_days"] = args.window_days or max(int(cfg.get("window_days") or 0), 28)
    if args.aw_url is not None:
        cfg["aw_url"] = args.aw_url
    if args.brief is not None:
        cfg["brief_popup"] = args.brief
    CENTRAL_CFG.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(CENTRAL_CFG, json.dumps(cfg, indent=2) + "\n")
    Path(cfg["pot"]).mkdir(parents=True, exist_ok=True)
    machine_copy(cfg["pot"])

    repo_cfg = read_json(REPO_CFG, {})
    repo_cfg["project"] = args.project or repo_cfg.get("project") or root.name
    atomic_write(REPO_CFG, json.dumps(repo_cfg, indent=2) + "\n")

    settings = install_hooks(root, args.shared)
    if not args.shared:
        exclude_locally(root, ".worklog/")
        exclude_locally(root, ".claude/settings.local.json")
    git_hook = install_git_hook(root) if args.git_hook else None

    say("repo      %s" % root)
    say("project   %s" % repo_cfg["project"])
    say("pot       %s" % cfg["pot"])
    say("hooks     SessionStart, Stop, SessionEnd  ->  %s" % settings.relative_to(root))
    if git_hook:
        say("git hook  %s" % git_hook.relative_to(root))
    say("desk time ActivityWatch %s at %s" % (
        "reachable" if aw_reachable(cfg) else "not running (desk and editor time appear once it is)", cfg["aw_url"]))
    say("brief     %s" % ("pops up once a day on the first unlock or session after %s (--no-brief to turn off)" % cfg.get("brief_after", "05:00")
                          if cfg.get("brief_popup", True) else "off (--brief to turn on)"))
    if args.auto:
        path, err = install_global_hook(cfg["pot"])
        say("auto      %s" % (("every repo you open in Claude Code gets the agent  ->  %s" % path) if path else "FAILED: " + err))
    if args.presence and os.name == "nt":
        if presence_registered():
            say("presence  Task Scheduler tasks already registered (logon, lock, unlock)")
        else:
            ok, text = install_presence(cfg["pot"])
            say("presence  %s" % (text.replace("\n", "; ") if ok else "FAILED: %s  (retry: python \"%s\" presence)" % (text[:200], Path(cfg["pot"]) / "bin" / "worklog_agent.py")))
    say("")
    say("first collection...")
    data = collect_and_write(cfg, root)
    collect_machine(cfg, force=True)
    totals = render(cfg)
    say("  %d commits, %d Claude Code sessions for this repo since %s (%d-day window)" % (
        len(data["commits"]), len(data["sessions"]), parse_iso(data["since"]).strftime("%d %b"), int(cfg["window_days"])))
    if totals:
        say("  pot this week: %d commits, %d sessions, ~%s active  ->  %s" % (
            totals[0], totals[1], fmt_dur(totals[2]), Path(cfg["pot"]) / "latest-week.md"))
        say("  dashboard: %s  (double-click to open; refresh after a run)" % (Path(cfg["pot"]) / "dashboard.html"))
    say("")
    say("Done. Restart any open Claude Code session in this repo so it picks up the hooks.")
    log("installed v%s (project=%s, pot=%s)" % (VERSION, repo_cfg["project"], cfg["pot"]))


def cmd_setup(args):
    """Machine-level setup without a repo: pot, machine copy, auto-install hook, presence tasks, brief."""
    cfg = central_cfg()
    if args.pot:
        cfg["pot"] = str(Path(os.path.expanduser(args.pot)))
    cfg["window_days"] = max(int(cfg.get("window_days") or 0), 28)
    if args.brief is not None:
        cfg["brief_popup"] = args.brief
    CENTRAL_CFG.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(CENTRAL_CFG, json.dumps(cfg, indent=2) + "\n")
    Path(cfg["pot"]).mkdir(parents=True, exist_ok=True)
    machine_copy(cfg["pot"])
    say("pot       %s" % cfg["pot"])
    path, err = install_global_hook(cfg["pot"])
    say("auto      %s" % (("every git repo you open in Claude Code gets the agent  ->  %s" % path) if path else "FAILED: " + err))
    if args.presence and os.name == "nt":
        if presence_registered():
            say("presence  Task Scheduler tasks already registered")
        else:
            ok, text = install_presence(cfg["pot"])
            say("presence  %s" % (text.replace("\n", "; ") if ok else "FAILED: %s  (retry: python \"%s\" presence)" % (text[:200], Path(cfg["pot"]) / "bin" / "worklog_agent.py")))
    say("brief     %s" % ("on, first unlock or session after %s" % cfg.get("brief_after", "05:00") if cfg.get("brief_popup", True) else "off"))
    say("desk time ActivityWatch %s at %s" % ("reachable" if aw_reachable(cfg) else "not running", cfg["aw_url"]))
    log("setup v%s (pot=%s)" % (VERSION, cfg["pot"]))


def cmd_presence(args):
    """(Re)register or remove the Task Scheduler presence tasks on their own."""
    cfg = central_cfg()
    if args.remove:
        ok, text = uninstall_presence()
        say(text if ok else "FAILED: " + text[:300])
        return
    if os.name != "nt":
        say("Windows only")
        return
    if presence_registered() and not args.force:
        say("already registered: %s" % ", ".join(PRESENCE_TASKS))
        return
    ok, text = install_presence(cfg["pot"])
    if ok:
        say(text)
    else:
        say("FAILED: " + text[:600])
        if "denied" in text.lower():
            say("")
            say("If it still says access denied, run the same command once from an elevated PowerShell:")
            say('  python "%s" presence --force' % (Path(cfg["pot"]) / "bin" / "worklog_agent.py"))


def cmd_uninstall(args):
    root = repo_root()
    removed = remove_hooks(root)
    hook = git_dir_path(root, "hooks/post-commit")
    if hook.exists() and MARK in hook.read_text(encoding="utf-8", errors="replace"):
        lines = [l for l in hook.read_text(encoding="utf-8", errors="replace").splitlines() if MARK not in l]
        if len([l for l in lines if l.strip() and not l.startswith("#!")]) == 0:
            hook.unlink()
        else:
            hook.write_text("\n".join(lines) + "\n", encoding="utf-8")
        say("git hook  cleaned")
    for p in removed:
        say("hooks     removed from %s" % p.relative_to(root))
    if not removed:
        say("hooks     none found")
    if args.presence:
        ok, text = uninstall_presence()
        say("presence  %s" % (text if ok else "FAILED: " + text[:300]))
    if args.auto:
        say("auto      %s" % ("global hook removed from %s" % USER_SETTINGS if remove_global_hook() else "no global hook found"))
    say("The slice in the pot and .worklog/ itself are left in place; delete them if you want them gone.")
    log("uninstalled")


def cmd_status(args):
    root = repo_root()
    cfg = central_cfg()
    say("agent     v%s at %s" % (VERSION, HERE))
    say("repo      %s" % root)
    say("project   %s" % project_name(root))
    say("pot       %s%s" % (cfg["pot"], "" if Path(cfg["pot"]).is_dir() else "  (not created yet)"))
    found = hooks_installed(root)
    if found:
        for path, events in found:
            say("hooks     %s: %s" % (path.relative_to(root), ", ".join(events)))
    else:
        say("hooks     not installed (run: python .worklog/worklog_agent.py install)")
    sp = slice_path(cfg["pot"], project_name(root), root.name)
    if sp.exists():
        d = read_json(sp, {})
        say("slice     %s  (%d commits, %d sessions, updated %s)" % (
            sp.name, len(d.get("commits", [])), len(d.get("sessions", [])),
            (parse_iso(d.get("updated")) or datetime.now()).strftime("%d %b %H:%M")))
        others = [f.name for f in sp.parent.glob("*.json") if f != sp and not f.name.startswith("_machine__")]
        say("others    %d other repo%s reporting to this pot" % (len(others), "" if len(others) == 1 else "s"))
    else:
        say("slice     none yet")
    say("auto      %s" % ("on: new and outdated repos pick up the agent at session start" if global_hook_installed()
                           else "off (install --auto to turn on)"))
    say("desk time ActivityWatch %s at %s" % ("reachable" if aw_reachable(cfg) else "not reachable", cfg["aw_url"]))
    mp = machine_slice_path(cfg["pot"])
    if mp.exists():
        m = read_json(mp, {})
        aw = m.get("aw") or {}
        pe = (m.get("presence") or {}).get("events", [])
        last = parse_iso(pe[-1]["time"]) if pe else None
        say("machine   %d days of desk time%s \u00b7 %d presence events%s" % (
            len(aw.get("days") or {}), (" (last error: %s)" % aw["error"]) if aw.get("error") else "",
            len(pe), (", last %s %s" % (pe[-1]["event"], last.strftime("%d %b %H:%M"))) if last else ""))
    say("log       %s" % LOG)


def cmd_render(args):
    cfg = central_cfg()
    totals = render(cfg)
    say("rendered %s" % (Path(cfg["pot"]) / "latest-week.md") if totals else "nothing to render yet")


def spawn_detached(argv, script=None):
    """Run this script (or another copy of it) with argv in a detached process; output goes to the log, never to the caller."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    logfh = open(LOG, "a", encoding="utf-8")
    subprocess.Popen([sys.executable, str(script or Path(__file__).resolve())] + list(argv),
                     stdin=subprocess.DEVNULL, stdout=logfh, stderr=logfh, **kwargs)


def cmd_refresh(args):
    """Machine-level refresh + render, no repo slice: used after presence stamps and by hand."""
    try:
        cfg = central_cfg()
        if not Path(cfg["pot"]).is_dir():
            return
        m = collect_machine(cfg, force=True)
        totals = render(cfg)
        if args.event in ("unlock", "logon", "manual", None):
            maybe_brief(cfg, args.event or "manual")
        aw = m.get("aw") or {}
        log("refresh(%s): machine aw=%s; pot week %s" % (
            args.event or "manual", "ok" if aw.get("ok") else (aw.get("error") or "n/a"),
            ("%dc %ds %s" % (totals[0], totals[1], fmt_dur(totals[2]))) if totals else "-"))
        if sys.stdout and sys.stdout.isatty():
            say("refreshed %s" % (Path(cfg["pot"]) / "dashboard.html"))
    except Exception:
        log("refresh failed\n" + traceback.format_exc())


def cmd_stamp(args):
    """Called by the Task Scheduler presence tasks: append one timestamped event, then refresh the pot
    in the background so the dashboard is current when you sit down. Never fails loudly."""
    try:
        cfg = central_cfg()
        t = parse_iso(args.time) if args.time else datetime.now(local_tz())
        pf = presence_file(cfg["pot"])
        pf.parent.mkdir(parents=True, exist_ok=True)
        with open(pf, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": t.isoformat(), "event": args.event, "machine": platform.node()}) + "\n")
        if not args.no_refresh:
            spawn_detached(["refresh", "--event", args.event])
    except Exception:
        log("stamp failed\n" + traceback.format_exc())


def cmd_run(args):
    """Hook entry point. Parent: read the hook payload, throttle, spawn a detached worker, exit 0 at once.
    Worker (--sync): collect this repo's slice, refresh the machine slice, re-render the pot, log the outcome."""
    event = args.event
    if not args.sync:
        payload = {}
        try:
            if sys.stdin and not sys.stdin.isatty():
                raw = sys.stdin.read()
                if raw.strip():
                    payload = json.loads(raw)
        except Exception:
            payload = {}
        event = event or payload.get("hook_event_name") or "manual"
        try:
            cfg = central_cfg()
            if event == "Stop":
                sp = slice_path(cfg["pot"], project_name(repo_root()), repo_root().name)
                if sp.exists() and time.time() - sp.stat().st_mtime < STOP_THROTTLE_S:
                    return
            spawn_detached(["run", "--sync", "--event", event])
        except Exception:
            log("spawn failed\n" + traceback.format_exc())
        return

    try:
        cfg = central_cfg()
        root = repo_root()
        try:
            Path(cfg["pot"]).mkdir(parents=True, exist_ok=True)
        except OSError:
            log("run(%s): pot not reachable: %s" % (event, cfg["pot"]))
            return
        data = collect_and_write(cfg, root)
        m = collect_machine(cfg, force=(event == "manual"))
        totals = render(cfg)
        if event in ("SessionStart", "manual", "post-commit", "Stop", "SessionEnd"):
            maybe_brief(cfg, event)
        aw = m.get("aw") or {}
        log("run(%s): %s slice %d commits / %d sessions; machine aw=%s; pot week %s" % (
            event or "manual", data["project"], len(data["commits"]), len(data["sessions"]),
            "ok" if aw.get("ok") else (aw.get("error") or "n/a"),
            ("%dc %ds %s" % (totals[0], totals[1], fmt_dur(totals[2]))) if totals else "-"))
        # self-upgrade: long-lived sessions never hit SessionStart, so each worker run adopts a newer
        # machine copy for the NEXT run; atomic replace so a spawning worker can't read a torn file
        try:
            bin_copy = Path(cfg["pot"]) / "bin" / "worklog_agent.py"
            me = Path(__file__).resolve()
            mine = tuple(int(x) for x in VERSION.split("."))
            if bin_copy.exists() and me != bin_copy.resolve() and version_of(bin_copy) > mine:
                fd, tmp = tempfile.mkstemp(prefix=".tmp-upgrade-", suffix=".py", dir=str(me.parent))
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(bin_copy.read_bytes())
                    compile(Path(tmp).read_text(encoding="utf-8", errors="replace"), tmp, "exec")   # never promote a torn copy
                    os.replace(tmp, str(me))
                except BaseException:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                log("self-upgrade %s -> %s from %s (next run uses it)" % (VERSION, ".".join(map(str, version_of(me))), bin_copy))
        except Exception:
            log("self-upgrade skipped\n" + traceback.format_exc())
        if event == "manual" and sys.stdout and sys.stdout.isatty():
            say("%s: %d commits, %d sessions -> %s" % (data["project"], len(data["commits"]), len(data["sessions"]),
                                                       Path(cfg["pot"]) / "latest-week.md"))
    except Exception:
        log("run(%s) failed\n%s" % (event, traceback.format_exc()))


def main():
    ap = argparse.ArgumentParser(description="Per-repo work reporter for Claude Code (v%s)" % VERSION)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("install", help="register hooks in this repo and do a first collection")
    p.add_argument("--pot", help="central folder for slices and reports (default: %s; remembered for later repos)"
                   % DEFAULT_POT.replace("%", "%%"))
    p.add_argument("--project", help="name this repo reports under (default: the repo folder name)")
    p.add_argument("--idle-minutes", type=int, help="cap between transcript events when estimating active time")
    p.add_argument("--window-days", type=int, help="how far back each repo reports (default 28)")
    p.add_argument("--aw-url", default=None, help="ActivityWatch server (default http://localhost:5600; empty string disables)")
    p.add_argument("--presence", dest="presence", action="store_true", default=True,
                   help="register logon/lock/unlock stamps in Task Scheduler (default; Windows only)")
    p.add_argument("--no-presence", dest="presence", action="store_false", help="skip the Task Scheduler tasks")
    p.add_argument("--git-hook", dest="git_hook", action="store_true", default=True,
                   help="also report after every git commit via a post-commit hook (default)")
    p.add_argument("--no-git-hook", dest="git_hook", action="store_false", help="skip the post-commit hook")
    p.add_argument("--auto", action="store_true",
                   help="also register a user-level Claude Code hook that installs or upgrades the agent in any git repo you open")
    p.add_argument("--brief", dest="brief", action="store_true", default=None, help="morning brief pop-up on (default)")
    p.add_argument("--no-brief", dest="brief", action="store_false", help="no morning brief pop-up")
    p.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--shared", action="store_true",
                   help="put hooks in .claude/settings.json (committed) instead of settings.local.json (personal)")
    p.set_defaults(fn=cmd_install)
    p = sub.add_parser("setup", help="machine-level setup with no repo: pot, auto-install hook, presence tasks")
    p.add_argument("--pot")
    p.add_argument("--no-presence", dest="presence", action="store_false", default=True)
    p.add_argument("--brief", dest="brief", action="store_true", default=None)
    p.add_argument("--no-brief", dest="brief", action="store_false")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("presence", help="(re)register the lock/unlock Task Scheduler tasks on their own")
    p.add_argument("--force", action="store_true", help="re-register even if they exist")
    p.add_argument("--remove", action="store_true")
    p.set_defaults(fn=cmd_presence)
    p = sub.add_parser("run", help="collect + render (what the hooks call)")
    p.add_argument("--sync", action="store_true", help="do the work in the foreground")
    p.add_argument("--event", default=None)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("stamp", help="record a presence event (used by the scheduled tasks)")
    p.add_argument("event", choices=sorted(PRESENCE_ALL))
    p.add_argument("--time", help=argparse.SUPPRESS)
    p.add_argument("--no-refresh", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_stamp)
    p = sub.add_parser("refresh", help="refresh desk time and presence, re-render the pot (no repo needed)")
    p.add_argument("--event", default=None)
    p.set_defaults(fn=cmd_refresh)
    sub.add_parser("render", help="re-render the pot from existing slices").set_defaults(fn=cmd_render)
    p = sub.add_parser("brief", help="render the morning page (yesterday, where you left off, this week) and open it")
    p.add_argument("--render", action="store_true", help="render only, don't open")
    p.set_defaults(fn=cmd_brief)
    sub.add_parser("status", help="show configuration and last slice").set_defaults(fn=cmd_status)
    p = sub.add_parser("uninstall", help="remove this repo's hooks")
    p.add_argument("--presence", action="store_true", help="also remove the Task Scheduler presence tasks")
    p.add_argument("--auto", action="store_true", help="also remove the user-level auto-install hook")
    p.set_defaults(fn=cmd_uninstall)
    sub.add_parser("bootstrap", help="what the user-level hook calls: install or upgrade the agent in the current repo").set_defaults(fn=cmd_bootstrap)
    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return
    if args.cmd == "run" and args.sync and args.event is None:
        args.event = "manual"
    args.fn(args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
