# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project will use semantic versioning after the first public release.

## Unreleased

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

## 0.1.0

- Initial private prototype for local, read-only Kiro credit reporting.
