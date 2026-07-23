#!/usr/bin/env python3
"""Offline safety scan for the public kcredits release surface.

This guardrail checks release files for common secrets, local artifacts,
author-specific paths, unresolved public placeholders, internal-only material,
unsafe Git remotes, and (optionally) unsafe Git history. It is not a substitute
for human review, GitHub secret scanning, CodeQL, or coordinated disclosure.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_NAMES = {"usage.csv", "usage.csv.lock", "scheduled.log", "PLAN.md", "README.txt"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "build", "dist"}
REQUIRED_FILES = {
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "HOW-TO.md",
    "PUBLIC-RELEASE-CHECKLIST.md",
    "README.md",
    "SECURITY.md",
    "SETUP.md",
    "build-requirements.txt",
    "kcredits.py",
    "pyproject.toml",
}
FORBIDDEN_PUBLIC_FILES = {
    "-".join(("NOTICE", "INTERNAL", "USE.md")),
    "OPERATIONS.md",
    "-".join(("PUBLISH", "GITLAB", "INTERNAL.md")),
    "RELEASE-CHECKLIST.md",
    "ci/gitlab-ci.yml.template",
}

# Sensitive prefixes are assembled so this scanner does not detect its own
# source as a secret.
SECRET_RULES = (
    ("AWS access key", re.compile("".join(("A", "K", "I", "A")) + r"[0-9A-Z]{16}")),
    ("GitHub classic token", re.compile("".join(("gh", "p", "_")) + r"[A-Za-z0-9]{36,255}")),
    (
        "GitHub fine-grained token",
        re.compile("".join(("github", "_pat", "_")) + r"[A-Za-z0-9_]{60,255}"),
    ),
    ("GitLab personal token", re.compile("".join(("gl", "pat", "-")) + r"[A-Za-z0-9_-]{20,}")),
    ("generic secret key", re.compile("".join(("sk", "-")) + r"[A-Za-z0-9]{20,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]+ PRI" + "VATE KEY-----")),
)
LOCAL_PATH_RULES = (
    (
        "author-specific Windows profile path",
        re.compile(r"C:" + r"\\Users\\(?!<you>)(?!<HOME>)[^\\\r\n]+", re.I),
    ),
    (
        "author-specific macOS profile path",
        re.compile(r"/Us" + r"ers/(?!<you>/)(?!<HOME>/)[^/\s]+"),
    ),
    (
        "author-specific Linux profile path",
        re.compile(r"/ho" + r"me/(?!<you>/)(?!<HOME>/)[^/\s]+"),
    ),
)
PUBLIC_CONTENT_RULES = (
    (
        "unresolved GitHub owner",
        re.compile("<" + "GITHUB_OWNER" + ">"),
    ),
    (
        "internal GitLab placeholder",
        re.compile("<" + "INTERNAL_GITLAB_URL" + ">", re.I),
    ),
    (
        "internal GitLab repository placeholder",
        re.compile("<" + "GITLAB_REPOSITORY_URL" + ">", re.I),
    ),
    (
        "internal-only publishing guide",
        re.compile("PUBLISH-" + "GITLAB-INTERNAL", re.I),
    ),
    (
        "internal-use release notice",
        re.compile("NOTICE-" + "INTERNAL-USE", re.I),
    ),
)


def _run_git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )


def git_candidates(root):
    """Return existing Git candidates or None outside a Git repository."""
    if not (root / ".git").exists():
        return None
    result = _run_git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if result.returncode != 0:
        return None
    return [root / line for line in result.stdout.splitlines() if line and (root / line).exists()]


def local_candidates(root):
    """Return intended release files before Git has been initialized."""
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in LOCAL_NAMES:
            continue
        candidates.append(path)
    return candidates


def scan_content(text, forbidden_values=()):
    """Return labels for sensitive patterns in decoded text."""
    findings = []
    for label, rule in SECRET_RULES + LOCAL_PATH_RULES + PUBLIC_CONTENT_RULES:
        if rule.search(text):
            findings.append((label, "remove or replace it before public release"))
    folded = text.casefold()
    for value in forbidden_values:
        if value and value.casefold() in folded:
            findings.append(("caller-supplied private value", "remove it before public release"))
    return findings


def scan_text(path, forbidden_values=()):
    """Return findings for one UTF-8 text file; unexpected binaries are rejected."""
    try:
        raw = path.read_bytes()
    except OSError:
        return [("unreadable file", "file could not be read")]
    if b"\0" in raw:
        return [("binary file", "binary files require a separate metadata and privacy review")]
    return scan_content(raw.decode("utf-8", errors="replace"), forbidden_values)


def git_remote_gates(root):
    """Return gates for configured remotes that are not public GitHub remotes."""
    if not (root / ".git").exists():
        return []
    result = _run_git(root, "remote")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    allowed_prefixes = (
        "https://github.com/",
        "git@github.com:",
        "ssh://git@github.com/",
    )
    gates = []
    for remote in result.stdout.splitlines():
        urls = _run_git(root, "remote", "get-url", "--all", remote.strip())
        if urls.returncode != 0:
            gates.append(f"remote '{remote.strip()}' could not be inspected")
            continue
        if not urls.stdout.strip() or not all(
            url.strip().startswith(allowed_prefixes) for url in urls.stdout.splitlines()
        ):
            gates.append(
                f"remote '{remote.strip()}' is not a public GitHub remote; create a fresh "
                "repository from a sanitized source archive instead of reusing this clone"
            )
    return gates


def scan_history(root, forbidden_values=()):
    """Return findings from every reachable Git commit."""
    if not (root / ".git").exists():
        return [("Git history", "not available; run again after initializing the fresh public repository")]
    result = _run_git(
        root,
        "log",
        "--all",
        "--format=fuller",
        "--patch",
        "--no-ext-diff",
        "--no-textconv",
    )
    if result.returncode != 0:
        return [("Git history", "could not be read")]
    return [
        ("Git history", f"{label}: {remediation}")
        for label, remediation in scan_content(result.stdout, forbidden_values)
    ]


def scan(root, forbidden_values=(), include_history=False):
    candidates = git_candidates(root)
    mode = "Git candidates" if candidates is not None else "pre-Git release candidates"
    if candidates is None:
        candidates = local_candidates(root)

    errors = []
    for required in REQUIRED_FILES:
        if not (root / required).exists():
            errors.append((required, "required public release file is missing"))
    for forbidden in FORBIDDEN_PUBLIC_FILES:
        if (root / forbidden).exists():
            errors.append((forbidden, "internal-only file must not be in the public release"))

    for path in candidates:
        try:
            relative = path.relative_to(root)
        except ValueError:
            errors.append((str(path), "candidate lies outside repository root"))
            continue
        if path.name in LOCAL_NAMES:
            errors.append((str(relative), "local data or planning artifact is a release candidate"))
            continue
        for label, remediation in scan_text(path, forbidden_values):
            errors.append((str(relative), f"{label}: {remediation}"))

    if include_history:
        errors.extend(scan_history(root, forbidden_values))

    gates = []
    if not (root / "LICENSE").exists():
        gates.append("approved public LICENSE is missing")
    gates.extend(git_remote_gates(root))
    return mode, candidates, errors, gates


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="fail when a public release gate remains open")
    parser.add_argument("--history", action="store_true", help="scan every reachable Git commit")
    parser.add_argument(
        "--forbid",
        action="append",
        default=[],
        metavar="PRIVATE_VALUE",
        help="also reject a private organization name, hostname, email domain, or identifier",
    )
    args = parser.parse_args(argv)

    invalid_forbidden = [value for value in args.forbid if not value or "<" in value or ">" in value]
    if invalid_forbidden:
        print("ERROR  --forbid: replace placeholder values with the real private value")
        return 1

    mode, candidates, errors, gates = scan(
        ROOT,
        forbidden_values=args.forbid,
        include_history=args.history,
    )
    print(f"kcredits public release scan: {mode}; {len(candidates)} file(s) inspected")
    for finding_number, _finding in enumerate(errors, start=1):
        # Do not echo paths, matched values, or exception details. This command
        # is commonly run in public CI, where logs remain visible after a fix.
        print(f"ERROR  finding-{finding_number:03d}: release safety rule failed")
    for gate in gates:
        print(f"GATE   {gate}")
    if not errors:
        print("PASS   no release-file, local-path, known-secret, or history violations found")
    if errors:
        return 1
    if gates and args.strict:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
