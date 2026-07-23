# Security policy

## Supported versions

Until the first stable release, only the latest release on the default branch
receives security fixes.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub's **Security → Report a vulnerability** flow. Repository owners must
enable private vulnerability reporting before making the repository public.
If that flow is not available, contact a maintainer privately through a contact
method listed on the maintainer's GitHub profile.

Include only:

- the affected `kcredits` version or commit;
- operating system and Python version;
- impact and reproduction steps using synthetic data; and
- sanitized diagnostic output with local paths removed.

Do not send real Kiro session files, databases, archives, prompt content,
credentials, account identifiers, or unsanitized screenshots.

Maintainers should acknowledge a complete report within seven days, keep
discussion private while a fix is prepared, and publish a GitHub security
advisory when coordinated disclosure is appropriate.

## Security and privacy boundary

`kcredits` reads Kiro usage data belonging to the current OS user.

The project must not:

- send session data, project paths, usage metadata, or archives to a network
  service;
- read another OS user's home directory by default;
- modify Kiro's own files or databases;
- report, archive, or log prompt/response content;
- execute data extracted from a Kiro session as code or a shell command; or
- silently broaden filesystem access.

`report` and `doctor` are read-only. `snapshot`, `snapshot-all`, and
`migrate-archive` write only under `~/.kcredits/` by default. A custom
`KCREDITS_DATA_DIR` must remain private and outside a source repository.
Archive updates use an advisory lock. Archive directories inside Git
repositories and archive paths using symlinks or Windows reparse points are
refused. POSIX archive permissions fail closed if they cannot be restricted.
New rows written to CSV are neutralized against spreadsheet formulas, and
terminal output escapes ASCII and Unicode format controls.
`migrate-archive` preserves legacy content byte-for-byte, so review an old CSV
before opening it in spreadsheet software.

Use `--safe-share` or `--redact-paths` before posting report or diagnostic
output. Redaction reduces accidental disclosure but is not a substitute for
reviewing the final text or screenshot.

To limit denial-of-service risk from corrupt local stores, oversized metadata,
JSONL lines, and SQLite values are ignored, classic SQLite row processing is
capped, and report aggregation streams records instead of retaining every turn.
If a safety cap is reached, treat the resulting report as incomplete.

## Sensitive local artifacts

Never commit or attach:

- Kiro `messages.jsonl`, `session.json`, or SQLite files;
- `usage.csv` or scheduler logs;
- output containing real project paths or session identifiers; or
- credentials, access tokens, environment dumps, or home-directory listings.

Only synthetic fixtures under `tests/fixtures/` are acceptable in the public
repository.

## Release security

Every public release must pass:

```text
python scripts/release_scan.py --strict --history
python -m unittest discover -s tests -v
```

The public GitHub repository must use a fresh sanitized history. Never mirror
the private source repository's `.git` directory or reuse a private remote.

This lightweight scanner is a guardrail, not proof that the repository is safe.
Use protected branches, review, GitHub secret scanning and push protection,
CodeQL, Dependabot, and private vulnerability reporting as additional layers.
