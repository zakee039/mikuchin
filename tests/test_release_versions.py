"""Canonical product-version audit: shipped components agree with versions.json."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import versioning  # noqa: E402

WEB = ROOT / "frontend/web"


class ReleaseVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = versioning.manifest()
        cls.comp = cls.manifest["components"]
        cls.main = cls.comp["main"]["version"]
        cls.launcher = cls.comp["launcher"]["version"]
        cls.android = cls.comp["android"]["version"]
        cls.version_code = cls.comp["android"]["versionCode"]

    def test_every_versioned_source_is_synchronized(self):
        self.assertEqual(versioning.validate(self.manifest, write=False), 0)

    def test_manifest_is_valid_and_single_authority(self):
        self.assertEqual(self.manifest["release"], "v" + self.main)
        self.assertEqual(self.manifest["schema"], 1)
        android_nums = tuple(map(int, self.android.split(".")))
        self.assertEqual(self.version_code,
                         android_nums[0] * 10000 + android_nums[1] * 100 + android_nums[2])
        self.assertNotEqual(self.manifest["release"], self.manifest["previous_release"])
        self.assertTrue((ROOT / "AGENTS.md").is_file())
        self.assertTrue((ROOT / "docs/VERSION_HISTORY.md").is_file())

    def test_real_independent_version_sources(self):
        js = (WEB / "versions.js").read_text(encoding="utf-8")
        versions = dict(re.findall(
            r'^\s*(main|launcher|android):\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
            js, flags=re.M))
        self.assertEqual(versions, {"main": self.main, "launcher": self.launcher,
                                     "android": self.android})
        tauri = json.loads((ROOT / "frontend/launcher/src-tauri/tauri.conf.json")
                           .read_text(encoding="utf-8"))
        npm = json.loads((ROOT / "frontend/launcher/package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "frontend/launcher/package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(tauri["version"], self.launcher)
        self.assertEqual(npm["version"], self.launcher)
        self.assertEqual(lock["version"], self.launcher)
        self.assertEqual(lock["packages"][""]["version"], self.launcher)
        cargo = (ROOT / "frontend/launcher/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        self.assertRegex(cargo, r'(?m)^version = "'+re.escape(self.launcher)+r'"$')
        cargo_lock = (ROOT / "frontend/launcher/src-tauri/Cargo.lock").read_text(encoding="utf-8")
        self.assertRegex(cargo_lock, r'\[\[package\]\]\s+name = "mikuchin"\s+version = "'
                         +re.escape(self.launcher)+r'"')
        gradle = (ROOT / "frontend/android/app/build.gradle.kts").read_text(encoding="utf-8")
        self.assertIn('versionName = "'+self.android+'"', gradle)
        self.assertRegex(gradle, r'\bversionCode\s*=\s*'+str(self.version_code)+r'\b')
        apk_script = (ROOT / "frontend/android/build-apk.ps1").read_text(encoding="utf-8")
        self.assertIn('Mikuchin-v$versionName.apk', apk_script)
        self.assertNotIn('Mikuchin-v0.2.4.apk', apk_script)

    def test_about_page_loads_versions_before_app(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="web/versions.js?v='+self.main+'"', html)
        self.assertLess(html.index("web/versions.js"), html.index("web/app.js"))
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for key in ("main", "launcher", "android"):
            self.assertIn(f"v.{key}", app)
        for label in ("Main program version", "Desktop launcher version",
                      "Android client version"):
            self.assertIn(f'["{label}"', app)
            for language in ("zh-CN", "ja-JP", "en-US"):
                values = json.loads((ROOT / f"frontend/locales/{language}.json")
                                    .read_text(encoding="utf-8"))
                self.assertTrue(values[label])

    def test_three_localized_readmes_have_release_matrix(self):
        for file in ("README.md", "README.en-US.md", "README.ja-JP.md"):
            doc = (ROOT / file).read_text(encoding="utf-8")
            self.assertIn("Miku", doc)
            self.assertIn("https://zakee.fun", doc)
            self.assertIn("https://ifdian.net/a/zakee/plan", doc)
            self.assertIn("releases/tag/"+self.manifest["release"], doc)
            self.assertIn(chr(96)+self.launcher+chr(96), doc)
            self.assertIn(chr(96)+self.android+chr(96), doc)
            self.assertIn("versionCode "+str(self.version_code), doc)
            self.assertGreater(len(doc), 4500, file)

    def test_build_metadata_and_release_doc_present(self):
        self.assertTrue((ROOT / f"docs/RELEASE_{self.manifest['release']}.md").is_file())
        self.assertTrue((ROOT / "docs/VERSION_HISTORY.md").is_file())
        self.assertTrue((ROOT / "scripts/versioning.py").is_file())
        site = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.assertIn("v" + self.main, site)
        self.assertIn("v" + self.launcher, site)
        self.assertIn("v" + self.android, site)
        upstream = json.loads((ROOT / "backend/polystrata/manager/package.json")
                              .read_text(encoding="utf-8"))
        self.assertNotEqual(upstream["name"], "mikuchin")


if __name__ == "__main__":
    unittest.main()
