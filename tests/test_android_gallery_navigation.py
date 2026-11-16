"""Ensure the native Android navigation exposes the web gallery tab."""
import re
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class AndroidGalleryNavigationTests(unittest.TestCase):
    def test_native_shell_has_image_and_gallery_navigation(self):
        js = (ROOT / "frontend/android/app/src/main/assets/android-shell.js").read_text("utf-8")
        self.assertIn('images: "生图"', js)
        self.assertIn('gallery: "画廊"', js)
        items = re.findall(r'^\s*\["(images|gallery|characters|settings|monitor|about)", "([^"]+)", "([^"]+)"\],?', js, re.M)
        self.assertEqual([item[0] for item in items],
                         ["images","gallery","characters","settings","monitor","about"])
        self.assertEqual(items[1][1], "i-layers")
        self.assertIn('showTab(target)', js)
        self.assertIn('data-target-tab', js)
        self.assertIn('updateTopBarAndNav()', js)

    def test_six_buttons_fit_android_drawer(self):
        css=(ROOT / "frontend/android/app/src/main/assets/android-shell.css").read_text("utf-8")
        self.assertRegex(css, r'#mk-android-drawer-nav\s*\{[^}]*grid-template-columns:\s*repeat\(6,')
        html=(ROOT / "frontend/web/index.html").read_text("utf-8")
        self.assertIn('id="view-gallery"', html)
        self.assertIn('id="tab-btn-gallery"', html)
        self.assertIn('web/gallery.js', html)

if __name__=="__main__":
    unittest.main()
