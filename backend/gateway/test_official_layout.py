import tempfile
import unittest
from pathlib import Path
from backend.gateway.official_layout import serving_root

class OfficialLayoutTests(unittest.TestCase):
    def test_new_and_legacy_layout(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            with self.assertRaises(FileNotFoundError):serving_root(root)
            legacy=root/"serve/server.py";legacy.parent.mkdir();legacy.touch()
            self.assertEqual(serving_root(root),root)
            modern=root/"terminal/serve/server.py";modern.parent.mkdir(parents=True);modern.touch()
            self.assertEqual(serving_root(root),root/"terminal")
