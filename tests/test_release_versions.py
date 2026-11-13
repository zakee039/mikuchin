"""Three independent release versions and the About page agree with source manifests."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend/web"
MAIN_VERSION = "0.2.7"


class ReleaseVersionTests(unittest.TestCase):
    def test_independent_version_sources(self):
        js = (WEB / "versions.js").read_text(encoding="utf-8")
        versions = dict(re.findall(r'^\s*(main|launcher|android):\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
                                   js, flags=re.M))
        self.assertEqual(versions, {"main": MAIN_VERSION, "launcher": "0.2.4", "android": "0.2.4"})
        tauri = json.loads((ROOT / "frontend/launcher/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        npm = json.loads((ROOT / "frontend/launcher/package.json").read_text(encoding="utf-8"))
        npm_lock = json.loads((ROOT / "frontend/launcher/package-lock.json").read_text(encoding="utf-8"))
        cargo = (ROOT / "frontend/launcher/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        gradle = (ROOT / "frontend/android/app/build.gradle.kts").read_text(encoding="utf-8")
        self.assertEqual(tauri["version"], versions["launcher"])
        self.assertEqual(npm["version"], versions["launcher"])
        self.assertEqual(npm_lock["version"], versions["launcher"])
        self.assertEqual(npm_lock["packages"][""]["version"], versions["launcher"])
        self.assertRegex(cargo, r'(?m)^version = "0\.2\.4"$')
        self.assertIn('versionName = "0.2.4"', gradle)
        self.assertRegex(gradle, r'\bversionCode\s*=\s*204\b')

    def test_about_page_loads_versions_before_app(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="web/versions.js?v=0.2.7"', html)
        self.assertLess(html.index("web/versions.js"), html.index("web/app.js"))
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for key in ("main", "launcher", "android"):
            self.assertIn(f"v.{key}", app)
        for label in ("Main program version", "Desktop launcher version", "Android client version"):
            self.assertIn(f'["{label}"', app)
            for language in ("zh-CN", "ja-JP", "en-US"):
                values = json.loads((ROOT / f"frontend/locales/{language}.json").read_text(encoding="utf-8"))
                self.assertTrue(values[label])

    def test_three_complete_readmes_use_main_release_link(self):
        for name in ("README.md", "README.en-US.md", "README.ja-JP.md"):
            doc = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("Miku亲", doc)
            self.assertIn("https://zakee.fun", doc)
            self.assertIn("https://ifdian.net/a/zakee/plan", doc)
            self.assertIn("releases/tag/v0.2.7", doc)
            self.assertIn("0.2.4", doc)
            self.assertGreater(len(doc), 4500, name)


if __name__ == "__main__":
    unittest.main()
