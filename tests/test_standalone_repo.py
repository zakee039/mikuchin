"""Verify Native main uses the clean upstream official PolyStrata gitlink.

The old mixed branch and its vendored-engine policy are preserved separately.
"""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PINNED_SHA = "3e1642161198c50ff1abed4046f4e4f476099dbb"


class NativeRepositoryTests(unittest.TestCase):
    def test_official_engine_is_the_only_pinned_submodule(self):
        modules = (ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertIn('[submodule "backend/polystrata"]', modules)
        self.assertIn("path = backend/polystrata", modules)
        self.assertIn("url = https://github.com/simplexai-labs/PolyStrata.git", modules)
        entries = subprocess.check_output(
            ["git", "ls-files", "--stage", "-z"], cwd=ROOT).split(b"\0")
        gitlinks = []
        for item in entries:
            if not item:
                continue
            head, path = item.decode("utf-8").split("\t", 1)
            mode, commit, _stage = head.split()
            if mode == "160000":
                gitlinks.append((path, commit))
        self.assertEqual(gitlinks, [("backend/polystrata", PINNED_SHA)])
        self.assertTrue((ROOT / "backend/gateway/app.py").is_file())
        self.assertTrue((ROOT / "backend/gateway/supervisor.py").is_file())

    def test_clone_instructions_initialize_official_submodule(self):
        for name in ("README.md", "README.en-US.md", "README.ja-JP.md"):
            readme = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("git clone --recurse-submodules https://github.com/zakee039/mikuchin.git", readme)
            self.assertIn("git submodule update --init --recursive", readme)
            self.assertIn("docs/NATIVE_V040_MAIN_MIGRATION_2026-11-21.md", readme)
        notes = (ROOT / "docs/NATIVE_V040_MAIN_MIGRATION_2026-11-21.md").read_text(
            encoding="utf-8")
        self.assertIn("old-mixed", notes)
        self.assertIn("v0.1.45-poly.10", notes)
        self.assertIn("不包含完整运行环境", notes)
        self.assertTrue((ROOT / "THIRD_PARTY_NOTICES.md").is_file())


if __name__ == "__main__":
    unittest.main()