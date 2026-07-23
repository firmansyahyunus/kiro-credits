import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_scan", ROOT / "scripts" / "release_scan.py")
release_scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_scan)


class ReleaseScanTests(unittest.TestCase):
    def test_known_secret_and_local_path_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "candidate.txt"
            fake_key = "".join(("A", "K", "I", "A", "0123456789ABCDEF"))
            fake_path = "C:" + "\\Users\\alice"
            path.write_text("token " + fake_key + " at " + fake_path, encoding="utf-8")

            labels = [label for label, _ in release_scan.scan_text(path)]

            self.assertIn("AWS access key", labels)
            self.assertIn("author-specific Windows profile path", labels)

    def test_public_placeholder_and_caller_forbidden_value_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "candidate.txt"
            github_placeholder = "<" + "GITHUB_OWNER" + ">"
            path.write_text(
                f"https://github.com/{github_placeholder}/repo private.example",
                encoding="utf-8",
            )

            labels = [
                label
                for label, _ in release_scan.scan_text(
                    path,
                    forbidden_values=["private.example"],
                )
            ]

            self.assertIn("unresolved GitHub owner", labels)
            self.assertIn("caller-supplied private value", labels)

    def test_github_tokens_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "candidate.txt"
            fake_classic = "".join(("gh", "p", "_", "A" * 36))
            fake_fine_grained = "".join(("github", "_pat_", "B" * 82))
            path.write_text(f"{fake_classic}\n{fake_fine_grained}", encoding="utf-8")

            labels = [label for label, _ in release_scan.scan_text(path)]

            self.assertIn("GitHub classic token", labels)
            self.assertIn("GitHub fine-grained token", labels)

    def test_local_candidates_exclude_legacy_private_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("safe", encoding="utf-8")
            (root / "usage.csv").write_text("private", encoding="utf-8")
            (root / "scheduled.log").write_text("private", encoding="utf-8")

            names = {path.name for path in release_scan.local_candidates(root)}

            self.assertEqual({"README.md"}, names)

    def test_non_github_origin_is_a_public_release_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()

            original = release_scan._run_git
            try:
                class Result:
                    def __init__(self, stdout):
                        self.returncode = 0
                        self.stdout = stdout

                def fake_git(_root, *args):
                    if args == ("remote",):
                        return Result("origin\n")
                    return Result("https://git.example.invalid/team/repo.git\n")

                release_scan._run_git = fake_git
                gates = release_scan.git_remote_gates(root)
            finally:
                release_scan._run_git = original

            self.assertEqual(1, len(gates))
            self.assertIn("fresh repository", gates[0])


if __name__ == "__main__":
    unittest.main()
