# Public release checklist

Do not publish this repository until every blocking item below is complete.

## 1. Ownership and licence

- [ ] The code owner has confirmed in writing that they have the right to
      publish every included file under the selected licence.
- [ ] The MIT licence selection and publication rights are confirmed.
- [ ] The complete MIT licence text is committed as `LICENSE`.
- [ ] The package metadata and README identify MIT accurately.

Public visibility is not a substitute for a licence. Without `LICENSE`, other
people can read the repository but do not receive permission to use, modify, or
redistribute it.

## 2. Create a fresh public history

The private source history may contain private hostnames, old paths, or
non-public documents even after those files are deleted. Do not push or
mirror its `.git` directory to GitHub.

Use a reviewed, sanitized commit as a source snapshot:

1. Complete and commit the public-facing changes in the private source repository.
2. Export only that commit's tracked files with `git archive`.
3. Extract the archive into a new empty directory outside the private clone.
4. Run the release scan and tests in the new directory.
5. Initialize a new Git repository there and create the first public commit.
6. Connect only the new repository to the new public GitHub repository.

Never copy `.git`, ignored files, local archives, logs, or real Kiro fixtures.

## 3. Replace public placeholders

- [ ] Confirm the public GitHub owner is `firmansyahyunus`.
- [ ] Confirm the final repository name.
- [ ] Confirm the PyPI distribution name before publishing a package.
- [ ] Add a public maintainer contact method without exposing a private address.

## 4. Validate the exported repository

Run on Windows:

```powershell
py -3.12 scripts\release_scan.py --strict --history `
  --forbid "<private-company-name>" `
  --forbid "<private-company-domain>"
py -3.12 -m unittest discover -s tests -v
py -3.12 -m pip install --require-hashes -r build-requirements.txt
py -3.12 -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .
$Wheel = Get-ChildItem dist\*.whl | Select-Object -First 1
py -3.12 -m pip install --force-reinstall --no-deps $Wheel.FullName
kcredits doctor
```

Run on macOS or Linux:

```bash
python3 scripts/release_scan.py --strict --history \
  --forbid "<private-company-name>" \
  --forbid "<private-company-domain>"
python3 -m unittest discover -s tests -v
python3 -m pip install --require-hashes -r build-requirements.txt
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .
python3 -m pip install --force-reinstall --no-deps dist/*.whl
kcredits doctor
```

Use the real private organization name and hostname for the two `--forbid`
values. The scanner reports only the rule label, not the forbidden value.

## 5. Configure the public GitHub repository

- [ ] Enable private vulnerability reporting.
- [ ] Enable secret scanning and push protection when available.
- [ ] Enable the dependency graph and Dependabot alerts.
- [ ] Protect `main`: require pull requests, CI, and CodeQL before merge.
- [ ] Limit GitHub Actions permissions to read-only by default.
- [ ] Require approval for workflows from first-time external contributors.
- [ ] Review the public repository's file list, commit history, releases,
      Actions logs, and configured remotes from a signed-out browser session.

## 6. First release

- [ ] GitHub Actions passes on Windows, macOS, and Ubuntu.
- [ ] A real Kiro smoke test is recorded for each supported OS.
- [ ] The README output and screenshots contain synthetic project names only.
- [ ] The release tag matches `pyproject.toml` and `CHANGELOG.md`.
- [ ] Release artifacts contain source/package files only and include checksums.
- [ ] The repository states clearly that it is community-maintained and is not
      affiliated with or endorsed by Kiro or AWS.
