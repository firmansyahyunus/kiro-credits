## What changed

Describe the user-visible change and the Kiro data format it affects.

## Validation

- [ ] `python -m unittest discover -s tests -v`
- [ ] `python scripts/release_scan.py --strict`
- [ ] New or changed behavior has synthetic fixture coverage.
- [ ] I did not include real Kiro sessions, prompt content, usage archives,
      account identifiers, credentials, or unsanitized local paths.
- [ ] I documented the operating systems and Python versions I tested.

## Security and privacy

Explain any change to filesystem reads, filesystem writes, subprocesses,
network behavior, report output, or data retention. Write `None` only when the
change does not affect any of those boundaries.
