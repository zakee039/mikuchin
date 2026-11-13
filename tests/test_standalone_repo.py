"""The main repository must carry backend source without fetching another Git repo."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StandaloneRepositoryTests(unittest.TestCase):
    def test_engine_is_tracked_as_regular_source_in_main(self):
        self.assertFalse((ROOT / ".gitmodules").exists())
        self.assertFalse((ROOT / "backend/polystrata/.git").exists())
        staged = subprocess.check_output(["git", "ls-files", "--stage", "-z"],
                                          cwd=ROOT).split(b"\0")
        entries = [p.decode("utf-8", errors="replace").split("\t", 1)
                   for p in staged if p]
        self.assertFalse([path for mode, path in entries if mode.split()[0] == "160000"])
        included = [path for _, path in entries if path.startswith("backend/polystrata/")]
        self.assertGreater(len(included), 3500)
        self.assertIn("backend/polystrata/LICENSE", included)
        self.assertIn("backend/polystrata/serve/server.py", included)

    def test_clone_documentation_has_no_submodule_dependency(self):
        for name in ("README.md", "README.en-US.md", "README.ja-JP.md"):
            readme = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("git clone https://github.com/zakee039/mikuchin.git", readme)
            self.assertNotIn("git clone --recurse-submodules", readme)
            self.assertNotIn("git submodule update --init", readme)
        script = (ROOT / "scripts/package-main-release.py").read_text(encoding="utf-8")
        self.assertNotIn('SUBMODULE =', script)
        self.assertNotIn('HEAD:backend/polystrata', script)
        self.assertTrue((ROOT / "THIRD_PARTY_NOTICES.md").is_file())


if __name__ == "__main__":
    unittest.main()
