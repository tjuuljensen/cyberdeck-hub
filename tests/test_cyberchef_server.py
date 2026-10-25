"""Test path safety for the isolated CyberChef static file server."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from cyberchef_server import resolve_document


class CyberChefServerPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = (Path(self.temp.name) / 'cyberchef').resolve()
        self.root.mkdir()
        (self.root / 'index.html').write_text('CyberChef', encoding='utf-8')
        (self.root / 'assets').mkdir()
        (self.root / 'assets' / 'app.js').write_text('app', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_resolves_root_and_nested_files(self):
        self.assertEqual(resolve_document(self.root, '/'), self.root / 'index.html')
        self.assertEqual(resolve_document(self.root, '/assets/app.js'),
                         self.root / 'assets' / 'app.js')

    def test_rejects_encoded_traversal_backslashes_and_missing_files(self):
        for path in ('/%2e%2e/secret', '/assets%5c..%5csecret', '/missing.js'):
            with self.subTest(path=path):
                self.assertIsNone(resolve_document(self.root, path))

    def test_rejects_symlinks(self):
        outside = Path(self.temp.name) / 'outside.txt'
        outside.write_text('outside', encoding='utf-8')
        link = self.root / 'outside.txt'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is unavailable in this workstation')
        try:
            self.assertIsNone(resolve_document(self.root, '/outside.txt'))
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
