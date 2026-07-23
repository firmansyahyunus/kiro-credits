# How to use kcredits

Run `kcredits doctor` first. It reports which local Kiro stores are present and
where an optional archive would be written.

Examples below use the installed `kcredits` command. When running from source,
use `py -3.12 .\kcredits.py` on Windows or `python3 ./kcredits.py` on
macOS/Linux instead.

## Reports

```text
kcredits report today
kcredits report week
kcredits report month
kcredits report all
```

The periods mean:

- `today`: the current local calendar day;
- `week`: the last seven days;
- `month`: the last 30 days; and
- `all`: every locally available usage record.

Filter by a case-insensitive project path substring:

```text
kcredits report all --project example-project
```

Produce structured JSON:

```text
kcredits report month --json
```

Reports group usage by project, model, and day. Credit values come from Kiro's
local usage records; `kcredits` does not estimate or convert them.

## Live refresh

Open another terminal while Kiro is running.

### Windows PowerShell

```powershell
while ($true) {
  Clear-Host
  py -3.12 .\kcredits.py report today
  Start-Sleep -Seconds 5
}
```

Press `Ctrl+C` to stop.

### macOS or Linux

```bash
watch -n 5 python3 ./kcredits.py report today
```

If `watch` is unavailable:

```bash
while true; do
  clear
  python3 ./kcredits.py report today
  sleep 5
done
```

## Optional private archive

Live Kiro files may change or be cleaned up over time. These commands maintain
a deduplicated local archive:

```text
kcredits snapshot
kcredits snapshot-all
```

The default archive is `~/.kcredits/usage.csv`. It contains timestamps, project
paths, session identifiers, models, tool counts, and credit values. It does not
contain prompt or response text.

To use another private directory:

```powershell
$env:KCREDITS_DATA_DIR = "$HOME\private-kcredits"
kcredits snapshot-all
```

```bash
export KCREDITS_DATA_DIR="$HOME/private-kcredits"
kcredits snapshot-all
```

Never point this variable at a Git repository, shared folder, public cloud
folder, or web-served directory.

For an older installation that stored `usage.csv` beside the script:

```text
kcredits migrate-archive
```

Migration copies the old archive only when the new destination does not already
exist. It never overwrites either archive.

## Hook and scheduler templates

Files under `hook-template/` and `run-snapshot.cmd` are opt-in examples. Review
their command paths and the current Kiro hook documentation before enabling
them. Kiro hook formats can change between CLI versions.

Enabling a hook or scheduled snapshot creates or updates the private archive.
It is not required for reporting.

## Data flow

```text
Kiro CLI
   |
   +-- ~/.kiro/sessions/.../session.json
   |      project metadata and model
   |
   +-- ~/.kiro/sessions/.../messages.jsonl
   |      completed-turn usage summaries
   |
   +-- Windows classic data.sqlite3 (secondary, when present)
          |
          v
     kcredits (local, read-only parser)
          |
          +-- terminal or JSON report
          |
          +-- optional ~/.kcredits/usage.csv archive
```

Each Kiro workspace is read independently and combined only in memory for the
report. Deduplication uses the usage event identifier.

## Safe diagnostics

`kcredits doctor --json` contains local filesystem paths. Before posting it to
a public issue:

1. replace the home directory with `<HOME>`;
2. replace all project names with synthetic names;
3. remove account identifiers if a future Kiro format adds them; and
4. never attach the underlying session or database files.

For suspected vulnerabilities, follow [SECURITY.md](SECURITY.md) and do not
open a public issue.
