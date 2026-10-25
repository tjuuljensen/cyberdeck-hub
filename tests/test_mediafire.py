"""Author-linked PDF downloads: bounded HTML resolution, pinned bytes, no network."""
import io
import unittest
from unittest.mock import patch

import test_library as base

lib = base.lib
PAGE = 'https://www.mediafire.com/file/ip0q9cd29nlbd0o/kit.pdf/file'
CDN = 'https://download1478.mediafire.com/token/ip0q9cd29nlbd0o/kit.pdf'


class Response(io.BytesIO):
    def __init__(self, body, url, status=200, headers=None):
        super().__init__(body)
        self.url, self.status, self.headers = url, status, headers or {}

    def geturl(self):
        return self.url


class MediaFireTests(unittest.TestCase):
    setUp = base.LibraryTests.setUp
    tearDown = base.LibraryTests.tearDown
    save_manifest = base.LibraryTests.save_manifest

    def prepare(self):
        self.payload = b'%PDF-pinned-test'
        self.asset.update(url=PAGE, url_resolver='mediafire', expected_bytes=len(self.payload),
                          sha256=lib.hashlib.sha256(self.payload).hexdigest())
        self.save_manifest()

    def page(self, url=CDN):
        return Response(f'<a href="https://ads.invalid/">ad</a><a href="{url}" id="downloadButton">PDF</a>'.encode(), PAGE)

    def test_fetch_and_rerun_preserve_stable_provenance(self):
        self.prepare()
        with patch.object(lib.urllib.request, 'urlopen', side_effect=[
                self.page(), Response(self.payload, CDN)]) as call:
            lib.fetch(self.root, self.manifest)
            self.assertEqual(call.call_args_list[1].args[0].full_url, CDN)
        with patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('network on rerun')):
            lib.fetch(self.root, self.manifest)
            lock = lib.verify_manifest(self.root, self.manifest)
        self.assertEqual(lock[self.asset['path']]['asset']['url'], PAGE)
        self.assertNotIn(CDN, (self.root / 'acquired.json').read_text())

    def test_resume_resolves_fresh_link_and_keeps_original_manifest(self):
        self.prepare()
        with patch.object(lib.urllib.request, 'urlopen', side_effect=[self.page(), Response(self.payload[:6], CDN)]):
            with self.assertRaises(OSError):
                lib.fetch(self.root, self.manifest)
        fresh = CDN.replace('/token/', '/fresh-token/')
        with patch.object(lib.urllib.request, 'urlopen', side_effect=[self.page(fresh),
                Response(self.payload[6:], fresh, 206,
                         {'Content-Range': f'bytes 6-{len(self.payload)-1}/{len(self.payload)}'})]) as call:
            lib.fetch(self.root, self.manifest)
            request = call.call_args_list[1].args[0]
            self.assertEqual(request.full_url, fresh)
            self.assertEqual(request.get_header('Range'), 'bytes=6-')
        lib.verify_manifest(self.root, self.manifest)

    def test_invalid_resolver_or_unpinned_source_rejected(self):
        self.prepare()
        for changes in [{'sha256': None}, {'url_resolver': 'unknown'},
                        {'url': PAGE.replace('https:', 'http:')},
                        {'url': PAGE.replace('www.mediafire.com', 'evil.invalid')},
                        {'url': PAGE + '?redirect=other'}, {'path': 'public/kit.html'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                lib.validate_asset(dict(self.asset, **changes))

    def test_missing_ambiguous_or_oversized_page_rejected(self):
        self.prepare()
        for body in [b'<html>No button</html>', self.page().getvalue() * 2, b'x' * 2_000_001]:
            with patch.object(lib.urllib.request, 'urlopen', return_value=Response(body, PAGE)):
                with self.assertRaises(ValueError):
                    lib.download_url(self.asset)

    def test_page_and_payload_redirects_and_foreign_links_rejected(self):
        self.prepare()
        for url in [CDN.replace('https:', 'http:'), CDN.replace('.com/', '.com.evil.invalid/'),
                    CDN.replace('ip0q9cd29nlbd0o', 'anotherfile')]:
            with self.subTest(url=url), patch.object(lib.urllib.request, 'urlopen', return_value=self.page(url)):
                with self.assertRaises(ValueError):
                    lib.download_url(self.asset)
        with patch.object(lib.urllib.request, 'urlopen', return_value=Response(b'', 'https://other.invalid/')):
            with self.assertRaisesRegex(ValueError, 'landing-page redirect'):
                lib.download_url(self.asset)
        for resumable in [True, False]:
            asset = dict(self.asset)
            if not resumable:
                del asset['expected_bytes']
            with patch.object(lib.urllib.request, 'urlopen', side_effect=[self.page(),
                    Response(self.payload, 'https://other.invalid/kit.pdf')]):
                with self.assertRaisesRegex(ValueError, 'outside the selected'):
                    lib.stream_download(asset, self.base / 'rejected.part')

    def test_wrong_bytes_never_promoted(self):
        self.prepare()
        with patch.object(lib.urllib.request, 'urlopen', side_effect=[self.page(),
                Response(self.payload.replace(b'test', b'fake'), CDN)]):
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                lib.fetch(self.root, self.manifest)
        self.assertFalse((self.root / self.asset['path']).exists())


if __name__ == '__main__':
    unittest.main()
