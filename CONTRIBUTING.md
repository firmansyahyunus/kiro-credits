# Contributing

Thank you for helping improve `kcredits`.

## Before opening an issue

- Search existing issues.
- Remove real project paths, session IDs, account data, prompts, and
  credentials.
- Use synthetic data for reproductions.
- Report vulnerabilities privately according to [SECURITY.md](SECURITY.md).

## Development setup

Use Python 3.12 or newer:

```bash
python -m unittest discover -s tests -v
python scripts/release_scan.py --strict
```

## Pull requests

1. Fork the public repository and create a focused branch.
2. Preserve read-only access to Kiro data.
3. Add or update synthetic fixtures and regression tests.
4. Run the full unit test suite and release scan.
5. Document the operating systems and Python versions tested.
6. Describe changes to filesystem access, writes, subprocesses, network
   behavior, output data, or retention.

Keep changes small and avoid unrelated refactoring.

## Data and dependency rules

- Never commit real Kiro sessions, databases, usage archives, scheduler logs,
  prompt content, account identifiers, or unsanitized local paths.
- Fixtures must be minimal, synthetic, and stored under `tests/fixtures/`.
- Runtime network access is out of scope unless the maintainers first approve a
  public security design and explicit opt-in behavior.
- New writes must default to a documented private user directory.
- Before adding a dependency, explain why the standard library is insufficient
  and document maintenance, licence, and security implications.

## Commit and review expectations

Use clear commit messages. A pull request should identify the Kiro storage
format being changed and include negative coverage for malformed or unexpected
input when relevant.

By contributing, you agree that your contribution will be distributed under
the project's MIT License.
