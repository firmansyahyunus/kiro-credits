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
           [--redact-paths|--safe-share]
  kcredits today
  kcredits snapshot         # append current-project turns to usage.csv (dedup)
  kcredits snapshot-all     # append all projects' turns to usage.csv (dedup)
  kcredits migrate-archive  # copy a legacy repo-local CSV to the private data dir
  kcredits doctor [--safe-share]  # local prerequisite and data-path diagnostics
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
import stat
import unicodedata
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

MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_MESSAGE_LINE_BYTES = 8 * 1024 * 1024
MAX_CLASSIC_VALUE_BYTES = 8 * 1024 * 1024
MAX_CLASSIC_ROWS = 250_000


class ArchiveSafetyError(OSError):
    """Raised when an archive path cannot be used without following links."""


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
    """Escape terminal and Unicode format controls from locally sourced labels."""
    text = str(value or "")
    escaped = []
    for ch in text:
        codepoint = ord(ch)
        if ch.isprintable() and not unicodedata.category(ch).startswith("C"):
            escaped.append(ch)
        elif codepoint <= 0xFF:
            escaped.append(f"\\x{codepoint:02x}")
        elif codepoint <= 0xFFFF:
            escaped.append(f"\\u{codepoint:04x}")
        else:
            escaped.append(f"\\U{codepoint:08x}")
    return "".join(escaped)


def _csv_text(value):
    """Neutralize spreadsheet formulas and control characters in CSV cells."""
    text = _display_text(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _is_link_or_reparse(path):
    """Return True for symlinks and Windows reparse points."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _repository_ancestor(path):
    """Return a containing Git worktree, if one exists."""
    resolved = path.resolve(strict=False)
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _private_mkdir(path):
    if _is_link_or_reparse(path):
        raise ArchiveSafetyError("archive directory must not be a link or reparse point")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise ArchiveSafetyError("archive path is not a directory")
    if os.name != "nt":
        path.chmod(0o700)
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ArchiveSafetyError("archive directory permissions are not private")


def _private_file(path):
    if _is_link_or_reparse(path):
        raise ArchiveSafetyError("archive file must not be a link or reparse point")
    if os.name != "nt":
        path.chmod(0o600)
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ArchiveSafetyError("archive file permissions are not private")


def _secure_open_flags(flags):
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _open_private_rw(path):
    fd = os.open(path, _secure_open_flags(os.O_RDWR | os.O_CREAT), 0o600)
    try:
        _private_file(path)
        return os.fdopen(fd, "r+b")
    except Exception:
        os.close(fd)
        raise


def _open_private_append_text(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(path, _secure_open_flags(flags), 0o600)
    try:
        _private_file(path)
        return os.fdopen(fd, "a", encoding="utf-8", newline="")
    except Exception:
        os.close(fd)
        raise


def _open_private_exclusive_binary(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, _secure_open_flags(flags), 0o600)
    try:
        _private_file(path)
        return os.fdopen(fd, "wb")
    except Exception:
        os.close(fd)
        raise


def _ensure_archive_location():
    repo = _repository_ancestor(DATA_DIR)
    if repo is not None:
        raise ArchiveSafetyError("archive directory must be outside a Git repository")
    _private_mkdir(DATA_DIR)
    for path in (CSV_PATH, CSV_PATH.with_name(CSV_PATH.name + ".lock")):
        if _is_link_or_reparse(path):
            raise ArchiveSafetyError("archive files must not be links or reparse points")


def _bounded_text(path, limit):
    """Read a UTF-8 text file only when it is within the configured limit."""
    try:
        if path.stat().st_size > limit:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _bounded_lines(path, limit):
    """Yield decoded lines without allowing one line to consume unbounded memory."""
    try:
        handle = path.open("rb")
    except OSError:
        return
    with handle:
        while True:
            raw = handle.readline(limit + 1)
            if not raw:
                return
            if len(raw) > limit:
                while raw and not raw.endswith(b"\n"):
                    raw = handle.readline(limit + 1)
                continue
            yield raw.decode("utf-8", errors="ignore")


@contextmanager
def _archive_lock():
    """Serialize archive updates with a cross-platform advisory file lock."""
    _ensure_archive_location()
    lock_path = CSV_PATH.with_name(CSV_PATH.name + ".lock")
    with _open_private_rw(lock_path) as lock_file:
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
            metadata_text = _bounded_text(session_json, MAX_METADATA_BYTES)
            meta = json.loads(metadata_text) if metadata_text is not None else {}
        except Exception:
            meta = {}
        wps = meta.get("workspacePaths") or []
        project = wps[0] if wps else str(sess_dir.parent.name)
        model = meta.get("modelId") or ""
        session_id = meta.get("id") or sess_dir.name

        msgs = sess_dir / "messages.jsonl"
        if not msgs.exists():
            continue
        for line in _bounded_lines(msgs, MAX_MESSAGE_LINE_BYTES):
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
    try:
        rows = conn.execute(
            "SELECT conversation_id, key AS cwd, updated_at, value, "
            "length(CAST(value AS BLOB)) AS value_bytes FROM conversations_v2 "
            "LIMIT ?",
            (MAX_CLASSIC_ROWS + 1,),
        )
        for row_number, r in enumerate(rows):
            if row_number >= MAX_CLASSIC_ROWS:
                print(
                    "[kcredits] warning: classic store row limit reached; "
                    "the report may be incomplete.",
                    file=sys.stderr,
                )
                break
            if (r["value_bytes"] or 0) > MAX_CLASSIC_VALUE_BYTES:
                continue
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
                yield {
                    "dt": dt,
                    "timestamp_iso": dt.isoformat() if dt else "",
                    "project": r["cwd"],
                    "session_id": r["conversation_id"],
                    "event_id": f"{r['conversation_id']}#{idx}",
                    "credits": credits,
                    "model": model,
                    "tools_count": 0,
                    "source": "classic",
                }
    except Exception:
        return
    finally:
        conn.close()


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

def cmd_report(period="all", project_substr=None, as_json=False, redact_paths=False):
    by_project = {}
    by_day = {}
    by_model = {}
    total_turns = 0
    total_credits = 0.0
    for t in filtered_turns(period, project_substr):
        total_turns += 1
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

    project_order = sorted(
        by_project,
        key=lambda key: (-by_project[key]["credits"], key),
    )
    redacted_names = {
        key: f"project-{index}"
        for index, key in enumerate(project_order, start=1)
    }

    if as_json:
        out = {
            "period": period,
            "project_filter": "<redacted>" if redact_paths and project_substr else project_substr,
            "safe_share": redact_paths,
            "total_turns": total_turns,
            "total_credits": round(total_credits, 4),
            "by_project": {
                (redacted_names[key] if redact_paths else by_project[key]["name"]): {
                    "turns": by_project[key]["turns"],
                    "credits": round(by_project[key]["credits"], 4),
                }
                for key in project_order
            },
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
          (
              "  (project filter redacted)"
              if redact_paths and project_substr
              else f"  (project ~ '{_display_text(project_substr)}')"
              if project_substr
              else ""
          ))
    print("  " + "-" * 60)
    if not total_turns:
        print("  No credit data found for this filter.")
        print()
        return

    print(f"  {'Project':<42}{'Turns':>7}{'Credits':>11}")
    for proj in project_order:
        v = by_project[proj]
        display_name = redacted_names[proj] if redact_paths else _display_text(v["name"])
        name = display_name if len(display_name) <= 40 else "..." + display_name[-37:]
        print(f"  {name:<42}{v['turns']:>7}{v['credits']:>11.2f}")
    print("  " + "-" * 60)
    print(f"  {'TOTAL':<42}{total_turns:>7}{total_credits:>11.2f}")

    # Models used (right under TOTAL)
    print()
    print("  By model:")
    for mdl in sorted(by_model, key=lambda k: -by_model[k]["credits"]):
        v = by_model[mdl]
        safe_model = _display_text(mdl)
        if len(safe_model) > 64:
            safe_model = safe_model[:61] + "..."
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
        if _is_link_or_reparse(CSV_PATH):
            raise ArchiveSafetyError("archive CSV must not be a link or reparse point")
        with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                ids.add(row.get("event_id", ""))
    return ids


def _append_rows(turns):
    with _archive_lock():
        existing = _load_existing_event_ids()
        handle = None
        writer = None
        appended = 0
        try:
            for t in turns:
                event_id = t["event_id"]
                if event_id in existing:
                    continue
                if handle is None:
                    write_header = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
                    handle = _open_private_append_text(CSV_PATH)
                    writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
                    if write_header:
                        writer.writeheader()
                writer.writerow({
                    "timestamp_iso": _csv_text(t["timestamp_iso"]),
                    "date": t["dt"].strftime("%Y-%m-%d") if t["dt"] else "",
                    "project": _csv_text(t["project"]),
                    "session_id": _csv_text(t["session_id"]),
                    "event_id": _csv_text(event_id),
                    "credits": f"{t['credits']:.6f}",
                    "model": _csv_text(t["model"]),
                    "tools_count": t["tools_count"],
                    "source": _csv_text(t["source"]),
                })
                existing.add(event_id)
                appended += 1
        finally:
            if handle is not None:
                handle.close()
        return appended


def cmd_snapshot(all_projects=False):
    if all_projects:
        turns = all_turns()
        scope = "all projects"
    else:
        cwd = _norm_path(os.getcwd())
        turns = (t for t in all_turns() if _norm_path(t["project"]) == cwd)
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
    if _is_link_or_reparse(LEGACY_CSV_PATH):
        print("[kcredits] migration refused: legacy archive must not be a link.", file=sys.stderr)
        return 1
    try:
        with _archive_lock():
            if CSV_PATH.exists():
                print(f"[kcredits] destination already exists; not overwriting {CSV_PATH}")
                return 1
            created = False
            try:
                with LEGACY_CSV_PATH.open("rb") as source:
                    with _open_private_exclusive_binary(CSV_PATH) as destination:
                        created = True
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
            except Exception:
                if created:
                    CSV_PATH.unlink(missing_ok=True)
                raise
    except OSError as error:
        print(f"[kcredits] migration failed: {_display_text(error)}", file=sys.stderr)
        return 1
    print(f"[kcredits] copied legacy archive to {CSV_PATH}")
    return 0


def cmd_doctor(as_json=False, redact_paths=False):
    """Show local prerequisites and data locations without modifying anything."""
    session_count = (
        sum(1 for _ in V3_SESSIONS_DIR.glob("*/*/session.json"))
        if V3_SESSIONS_DIR.exists()
        else 0
    )
    details = {
        "python": sys.version.split()[0],
        "v3_sessions_dir": "<KIRO_SESSIONS_DIR>" if redact_paths else str(V3_SESSIONS_DIR),
        "v3_sessions_dir_exists": V3_SESSIONS_DIR.exists(),
        "v3_session_count": session_count,
        "classic_db": "<KIRO_CLASSIC_DB>" if redact_paths else str(CLASSIC_DB),
        "classic_db_exists": CLASSIC_DB.exists(),
        "archive_dir": "<KCREDITS_ARCHIVE_DIR>" if redact_paths else str(DATA_DIR),
        "archive_csv": "<KCREDITS_ARCHIVE_CSV>" if redact_paths else str(CSV_PATH),
        "archive_csv_exists": CSV_PATH.exists(),
        "safe_share": redact_paths,
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
    redact_paths = "--redact-paths" in args or "--safe-share" in args
    for flag in ("--redact-paths", "--safe-share"):
        while flag in args:
            args.remove(flag)

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
        return cmd_doctor(as_json, redact_paths)
    if cmd == "today":
        cmd_report("today", project, as_json, redact_paths)
        return 0
    if cmd == "report":
        period = args[1] if len(args) > 1 else "all"
        if period not in ("today", "week", "month", "all"):
            print(f"Unknown period '{_display_text(period)}'. Use: today|week|month|all")
            return 1
        cmd_report(period, project, as_json, redact_paths)
        return 0
    if cmd in ("today", "week", "month", "all"):
        cmd_report(cmd, project, as_json, redact_paths)
        return 0

    print(f"Unknown command '{_display_text(cmd)}'. Try: kcredits help")
    return 1


if __name__ == "__main__":
    sys.exit(main())
