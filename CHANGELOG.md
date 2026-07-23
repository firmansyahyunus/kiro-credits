# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project will use semantic versioning after the first public release.

## 0.1.1 - Unreleased

### Security

- Added safe-share path redaction for reports and diagnostics.
- Refused archive directories inside Git repositories and archive paths that
  use symlinks or Windows reparse points.
- Created archive files with private permissions from the first open and fail
  closed when POSIX privacy permissions cannot be applied.
- Bounded local JSON, JSONL, and classic SQLite record processing.
- Escaped Unicode format controls and formulas preceded by whitespace.
- Stopped the public release scanner from echoing paths or raw exception
  details into CI logs.

## 0.1.0 - 2026-07-23

### Added

- Python package metadata and a `kcredits` console command.
- Public GitHub CI, CodeQL, issue templates, and release-safety checks.
- Public security, contribution, and release documentation.
- MIT License.

### Security

- Public release checks reject local usage artifacts, common secret patterns,
  author-specific paths, unresolved placeholders, unsafe remotes, and unsafe
  repository history.
- Archive writes use a cross-platform lock, reject invalid credit values, use
  private POSIX permissions, and neutralize terminal/CSV control sequences.

- Initial public release of the local, read-only Kiro credit reporter.
