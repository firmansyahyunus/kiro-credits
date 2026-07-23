#!/usr/bin/env python3
"""
kcredits - monitor real Kiro CLI credit usage across all projects.

Pure Python standard library. READ-ONLY on Kiro data. No network. No LLM.

Data sources (auto-detected):
  1) v3 session store (primary):
       ~/.kiro/sessions/<workspace-hash>/<session-id>/session.json   (workspacePaths, title, modelId)
       ~/.kiro/sessions/<workspace-hash>/<session-id>/messages.jsonl (usage_summary events)
     Real per-turn credit = payload.promptTurnSummaries[].usage  (unit "credit")
  2) classic store (secondary):
       %LOCALAPPDATA%/Kiro-Cli/data.sqlite3 -> conversations_v2
     Real credit = value.user_turn_metadata.usage_info[].value  (unit "credit")

Commands:
  kcredits [report] [today|week|month|all] [--project SUBSTR] [--json]
  kcredits today
  kcredits snapshot         # append current-project turns to usage.csv (dedup)
  kcredits snapshot-all     # append all projects' turns to usage.csv (dedup)
  kcredits migrate-archive  # copy a legacy repo-local CSV to the private data dir
  kcredits doctor           # show local prerequisite and data-path diagnostics
  kcredits help
"""

import os
import sys
import csv
import json
import shutil
import hashlib
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta

TOOL_DIR = Path(__file__).resolve().parent
# Archive data can contain project paths and usage metadata. Keep it outside a
# cloned repository, in the current user's private home directory by default.
DATA_DIR = Path(os.environ.get("KCREDITS_DATA_DIR", str(Path.home() / ".kcredits"))).expanduser()
CSV_PATH = DATA_DIR / "usage.csv"
LEGACY_CSV_PATH = TOOL_DIR / "usage.csv"
CSV_FIELDS = ["timestamp_iso", "date", "project", "session_id",
              "event_id", "credits", "model", "tools_count", "source"]

V3_SESSIONS_DIR = Path.home() / ".kiro" / "sessions"
CLASSIC_DB = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Kiro-Cli" / "data.sqlite3"


# ----------------------------- helpers -------------------------------------

def _parse_iso(ts):
    """Parse an ISO-8601 timestamp (possibly ending in Z) to aware datetime (local)."""
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()  # convert to local time
    except Exception:
        return None


def _norm_path(p):
    if not p:
        return ""
    return os.path.normcase(os.path.normpath(p))


def _credit_value(value):
    """Return a finite, non-negative credit value or None for invalid input."""
    try:
        credits = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(credits) or credits < 0:
        return None
    return credits


def _display_text(value):
    """Escape terminal control characters from locally sourced labels."""
    text = str(value or "")
    return "".join(
        ch if ord(ch) >= 32 and ord(ch) != 127 else f"\\x{ord(ch):02x}"
        for ch in text
    )


def _csv_text(value):
    """Neutralize spreadsheet formulas and control characters in CSV cells."""
    text = _display_text(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _private_mkdir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.chmod(0o700)
        except OSError:
            pass


def _private_file(path):
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass


@contextmanager
def _archive_lock():
    """Serialize archive updates with a cross-platform advisory file lock."""
    _private_mkdir(DATA_DIR)
    lock_path = CSV_PATH.with_name(CSV_PATH.name + ".lock")
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        _private_file(lock_path)
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


# ----------------------------- data readers --------------------------------

def iter_v3_turns():
    """Yield one dict per completed prompt turn from the v3 session store."""
    if not V3_SESSIONS_DIR.exists():
        return
    for session_json in V3_SESSIONS_DIR.glob("*/*/session.json"):
        sess_dir = session_json.parent
        try:
            meta = json.loads(session_json.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            meta = {}
        wps = meta.get("workspacePaths") or []
        project = wps[0] if wps else str(sess_dir.parent.name)
        model = meta.get("modelId") or ""
        session_id = meta.get("id") or sess_dir.name

        msgs = sess_dir / "messages.jsonl"
        if not msgs.exists():
            continue
        try:
            f = msgs.open("r", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with f:
            for line in f:
                line = line.strip()
                if not line or "usage_summary" not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                p = o.get("payload") or {}
                if p.get("type") != "usage_summary":
                    continue
                summaries = p.get("promptTurnSummaries") or []
                if not summaries:
                    continue
                ts = o.get("timestamp")
                dt = _parse_iso(ts)
                base_id = o.get("id") or ""
                # Kiro normally supplies an event id. If it does not, derive a
                # stable local id so distinct no-id events cannot collapse into
                # the same "#0" archive row.
                if not base_id:
                    digest = hashlib.sha256(
                        (session_id + "\0" + (ts or "") + "\0" + line).encode("utf-8")
                    ).hexdigest()[:32]
                    base_id = "synthetic-" + digest
                for idx, s in enumerate(summaries):
                    if s.get("unit") != "credit":
                        continue
                    credits = _credit_value(s.get("usage"))
                    if credits is None:
                        continue
                    yield {
                        "dt": dt,
                        "timestamp_iso": ts or "",
                        "project": project,
                        "session_id": session_id,
                        "event_id": f"{base_id}#{idx}",
                        "credits": credits,
                        "model": model,
                        "tools_count": len(s.get("usedTools") or []),
                        "source": "v3",
                    }


def iter_classic_turns():
    """Yield turns from the classic conversations_v2 sqlite store (if present)."""
    if not CLASSIC_DB.exists():
        return
    try:
        conn = sqlite3.connect(f"file:{CLASSIC_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except Exception:
        return
    turns = []
    try:
        rows = conn.execute(
            "SELECT conversation_id, key AS cwd, updated_at, value FROM conversations_v2"
        ).fetchall()
        for r in rows:
            try:
                data = json.loads(r["value"])
            except Exception:
                continue
            utm = data.get("user_turn_metadata") or {}
            usage = utm.get("usage_info") or []
            model = (data.get("model_info") or {}).get("model_name") or ""
            # updated_at is epoch ms or iso; try both
            ts_raw = r["updated_at"]
            dt = None
            if isinstance(ts_raw, (int, float)):
                try:
                    dt = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc).astimezone()
                except Exception:
                    dt = None
            elif isinstance(ts_raw, str):
                dt = _parse_iso(ts_raw)
            for idx, u in enumerate(usage):
                if not isinstance(u, dict) or u.get("unit") != "credit":
                    continue
                credits = _credit_value(u.get("value"))
                if credits is None:
                    continue
                turns.append({
                    "dt": dt,
                    "timestamp_iso": dt.isoformat() if dt else "",
                    "project": r["cwd"],
                    "session_id": r["conversation_id"],
                    "event_id": f"{r['conversation_id']}#{idx}",
                    "credits": credits,
                    "model": model,
                    "tools_count": 0,
                    "source": "classic",
                })
    except Exception:
        return
    finally:
        conn.close()

    yield from turns


def all_turns():
    yield from iter_v3_turns()
    yield from iter_classic_turns()


# ----------------------------- filtering -----------------------------------

def _cutoff(period):
    if period in (None, "all"):
        return None
    now = datetime.now().astimezone()
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    return None


def filtered_turns(period="all", project_substr=None):
    cut = _cutoff(period)
    psub = project_substr.lower() if project_substr else None
    for t in all_turns():
        if psub and psub not in (t["project"] or "").lower():
            continue
        if cut is not None:
            if t["dt"] is None or t["dt"] < cut:
                continue
        yield t


# ----------------------------- reporting -----------------------------------

def cmd_report(period="all", project_substr=None, as_json=False):
    turns = list(filtered_turns(period, project_substr))

    by_project = {}
    by_day = {}
    by_model = {}
    total_credits = 0.0
    for t in turns:
        total_credits += t["credits"]
        # group by normalized path so the same project isn't split by drive-letter case
        key = _norm_path(t["project"])
        pp = by_project.setdefault(key, {"turns": 0, "credits": 0.0, "name": t["project"]})
        pp["turns"] += 1
        pp["credits"] += t["credits"]
        day = t["dt"].strftime("%Y-%m-%d") if t["dt"] else "unknown"
        dd = by_day.setdefault(day, {"turns": 0, "credits": 0.0})
        dd["turns"] += 1
        dd["credits"] += t["credits"]
        mdl = t["model"] or "unknown"
        mm = by_model.setdefault(mdl, {"turns": 0, "credits": 0.0})
        mm["turns"] += 1
        mm["credits"] += t["credits"]

    if as_json:
        out = {
            "period": period,
            "project_filter": project_substr,
            "total_turns": len(turns),
            "total_credits": round(total_credits, 4),
            "by_project": {v["name"]: {"turns": v["turns"], "credits": round(v["credits"], 4)}
                           for v in by_project.values()},
            "by_model": {k: {"turns": v["turns"], "credits": round(v["credits"], 4)}
                         for k, v in by_model.items()},
            "by_day": {k: {"turns": v["turns"], "credits": round(v["credits"], 4)}
                       for k, v in by_day.items()},
        }
        print(json.dumps(out, indent=2))
        return

    label = {"today": "today", "week": "last 7 days",
             "month": "last 30 days", "all": "all time"}.get(period, period)
    print()
    print(f"  Kiro Credits - {label}" +
          (f"  (project ~ '{_display_text(project_substr)}')" if project_substr else ""))
    print("  " + "-" * 60)
    if not turns:
        print("  No credit data found for this filter.")
        print()
        return

    print(f"  {'Project':<42}{'Turns':>7}{'Credits':>11}")
    for proj in sorted(by_project, key=lambda k: -by_project[k]["credits"]):
        v = by_project[proj]
        display_name = _display_text(v["name"])
        name = display_name if len(display_name) <= 40 else "..." + display_name[-37:]
        print(f"  {name:<42}{v['turns']:>7}{v['credits']:>11.2f}")
    print("  " + "-" * 60)
    print(f"  {'TOTAL':<42}{len(turns):>7}{total_credits:>11.2f}")

    # Models used (right under TOTAL)
    print()
    print("  By model:")
    for mdl in sorted(by_model, key=lambda k: -by_model[k]["credits"]):
        v = by_model[mdl]
        safe_model = _display_text(mdl)
        print(f"    {safe_model:<24}{v['turns']:>4} turns   {v['credits']:>9.2f} credits")

    print()
    print("  By day:")
    for day in sorted(by_day, reverse=True):
        v = by_day[day]
        print(f"    {day}   {v['turns']:>4} turns   {v['credits']:>9.2f} credits")
    print()


# ----------------------------- csv archive ---------------------------------

def _load_existing_event_ids():
    ids = set()
    if CSV_PATH.exists():
        try:
            with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    ids.add(row.get("event_id", ""))
        except Exception:
            pass
    return ids


def _append_rows(turns):
    with _archive_lock():
        existing = _load_existing_event_ids()
        new = [t for t in turns if t["event_id"] not in existing]
        if not new:
            return 0
        write_header = not CSV_PATH.exists()
        with CSV_PATH.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if write_header:
                w.writeheader()
            for t in sorted(new, key=lambda x: x["timestamp_iso"]):
                w.writerow({
                    "timestamp_iso": _csv_text(t["timestamp_iso"]),
                    "date": t["dt"].strftime("%Y-%m-%d") if t["dt"] else "",
                    "project": _csv_text(t["project"]),
                    "session_id": _csv_text(t["session_id"]),
                    "event_id": _csv_text(t["event_id"]),
                    "credits": f"{t['credits']:.6f}",
                    "model": _csv_text(t["model"]),
                    "tools_count": t["tools_count"],
                    "source": _csv_text(t["source"]),
                })
        _private_file(CSV_PATH)
        return len(new)


def cmd_snapshot(all_projects=False):
    if all_projects:
        turns = list(all_turns())
        scope = "all projects"
    else:
        cwd = _norm_path(os.getcwd())
        turns = [t for t in all_turns() if _norm_path(t["project"]) == cwd]
        scope = f"project {os.getcwd()}"
    try:
        n = _append_rows(turns)
    except OSError as error:
        print(f"[kcredits] archive write failed: {_display_text(error)}", file=sys.stderr)
        return 1
    print(f"[kcredits] snapshot ({scope}): appended {n} new row(s) to {CSV_PATH}")
    return 0


def cmd_migrate_legacy_archive():
    """Copy a pre-release repo-local archive into the private data directory."""
    if LEGACY_CSV_PATH == CSV_PATH:
        print("[kcredits] legacy archive already uses the configured data directory.")
        return 0
    if not LEGACY_CSV_PATH.exists():
        print(f"[kcredits] no legacy archive found at {LEGACY_CSV_PATH}")
        return 0
    if CSV_PATH.exists():
        print(f"[kcredits] destination already exists; not overwriting {CSV_PATH}")
        return 1
    _private_mkdir(DATA_DIR)
    with _archive_lock():
        if CSV_PATH.exists():
            print(f"[kcredits] destination already exists; not overwriting {CSV_PATH}")
            return 1
        shutil.copy2(LEGACY_CSV_PATH, CSV_PATH)
        _private_file(CSV_PATH)
    print(f"[kcredits] copied legacy archive to {CSV_PATH}")
    return 0


def cmd_doctor(as_json=False):
    """Show local prerequisites and data locations without modifying anything."""
    sessions = list(V3_SESSIONS_DIR.glob("*/*/session.json")) if V3_SESSIONS_DIR.exists() else []
    details = {
        "python": sys.version.split()[0],
        "v3_sessions_dir": str(V3_SESSIONS_DIR),
        "v3_sessions_dir_exists": V3_SESSIONS_DIR.exists(),
        "v3_session_count": len(sessions),
        "classic_db": str(CLASSIC_DB),
        "classic_db_exists": CLASSIC_DB.exists(),
        "archive_dir": str(DATA_DIR),
        "archive_csv": str(CSV_PATH),
        "archive_csv_exists": CSV_PATH.exists(),
    }
    if as_json:
        print(json.dumps(details, indent=2))
        return 0

    print("kcredits doctor")
    print(f"  Python:          {details['python']}")
    print(f"  v3 sessions:     {details['v3_sessions_dir']} "
          f"({'found' if details['v3_sessions_dir_exists'] else 'not found'}; "
          f"{details['v3_session_count']} session file(s))")
    print(f"  Classic DB:      {details['classic_db']} "
          f"({'found' if details['classic_db_exists'] else 'not found'})")
    print(f"  Archive:         {details['archive_csv']} "
          f"({'found' if details['archive_csv_exists'] else 'not created'})")
    print("  Reporting reads Kiro data only. Snapshot writes only to the archive path above.")
    return 0


# ----------------------------- cli -----------------------------------------

HELP = __doc__


def main(argv=None):
    """Run the CLI and return a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    if as_json:
        args.remove("--json")

    project = None
    if "--project" in args:
        i = args.index("--project")
        if i + 1 < len(args):
            project = args[i + 1]
            del args[i:i + 2]
        else:
            # "--project" given with no following value: drop the flag instead
            # of letting it fall through and get misread as a period/command.
            del args[i:i + 1]

    cmd = args[0] if args else "report"

    if cmd in ("help", "-h", "--help"):
        print(HELP)
        return 0
    if cmd == "snapshot":
        return cmd_snapshot(all_projects=False)
    if cmd == "snapshot-all":
        return cmd_snapshot(all_projects=True)
    if cmd == "migrate-archive":
        return cmd_migrate_legacy_archive()
    if cmd == "doctor":
        return cmd_doctor(as_json)
    if cmd == "today":
        cmd_report("today", project, as_json)
        return 0
    if cmd == "report":
        period = args[1] if len(args) > 1 else "all"
        if period not in ("today", "week", "month", "all"):
            print(f"Unknown period '{period}'. Use: today|week|month|all")
            return 1
        cmd_report(period, project, as_json)
        return 0
    if cmd in ("today", "week", "month", "all"):
        cmd_report(cmd, project, as_json)
        return 0

    print(f"Unknown command '{cmd}'. Try: kcredits help")
    return 1


if __name__ == "__main__":
    sys.exit(main())
