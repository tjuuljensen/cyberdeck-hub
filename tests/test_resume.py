"""Small HTTP-response fixtures: no public network or real archives."""
import io
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_library as base

lib = base.lib


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None, failure=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}
        self.failure = failure

    def geturl(self):
        return 'https://mirror.example.invalid/sample.zim'

    def read(self, count=-1):
        result = super().read(count)
        if not result and self.failure:
            raise self.failure
        return result


class ResumeTests(unittest.TestCase):
    setUp = base.LibraryTests.setUp
    tearDown = base.LibraryTests.tearDown
    save_manifest = base.LibraryTests.save_manifest

    def prepare(self):
        self.payload = b'ZIM\x04' + b'abcdef' * 20
        self.asset.update(path='zim/sample.zim', expected_bytes=len(self.payload),
                          max_bytes=len(self.payload), sha256=lib.hashlib.sha256(self.payload).hexdigest())
        self.save_manifest()
        self.partial = self.root / 'zim/sample.zim.part'
        self.metadata = self.partial.with_name(self.partial.name + '.json')
        self.dest = self.root / 'zim/sample.zim'

    def interrupt(self, failure=None, etag='"edition-1"'):
        self.prepare()
        self.offset = 20
        response = Response(self.payload[:self.offset], headers={'Content-Length': str(len(self.payload)), 'ETag': etag},
                            failure=failure)
        with patch.object(lib.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises((OSError, KeyboardInterrupt, lib.http.client.HTTPException)):
                lib.fetch(self.root, self.manifest)
        self.assertEqual(self.partial.read_bytes(), self.payload[:self.offset])
        self.assertFalse(self.dest.exists())
        self.assertTrue(self.metadata.exists())

    def remainder(self, **overrides):
        headers = {'Content-Range': f'bytes {self.offset}-{len(self.payload)-1}/{len(self.payload)}',
                   'Content-Length': str(len(self.payload)-self.offset), 'ETag': '"edition-1"'}
        headers.update(overrides)
        return Response(self.payload[self.offset:], status=206, headers=headers)

    def test_disconnect_then_resume_fetches_only_remaining_and_cleans_state(self):
        self.interrupt(OSError('connection reset'))
        with patch.object(lib.urllib.request, 'urlopen', return_value=self.remainder()) as call:
            lib.fetch(self.root, self.manifest)
        request = call.call_args.args[0]
        self.assertEqual(request.get_header('Range'), f'bytes={self.offset}-')
        self.assertEqual(request.get_header('If-range'), '"edition-1"')
        self.assertEqual(request.get_header('Accept-encoding'), 'identity')
        self.assertEqual(self.dest.read_bytes(), self.payload)
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.metadata.exists())
        lib.verify_manifest(self.root, self.manifest)

    def test_short_eof_keyboard_interrupt_and_http_error_preserve_bytes(self):
        for failure in [None, KeyboardInterrupt(), lib.http.client.IncompleteRead(b'lost')]:
            with self.subTest(failure=type(failure).__name__):
                if self.root.exists():
                    lib.shutil.rmtree(self.root)
                self.interrupt(failure)

    def test_invalid_resume_responses_never_append_or_restart(self):
        self.interrupt()
        cases = [Response(self.payload), self.remainder(**{'Content-Range': 'bytes 0-123/124'}),
                 self.remainder(**{'Content-Range': 'bytes 20-123/999'}),
                 self.remainder(**{'Content-Range': 'bytes 20-99/124'}),
                 self.remainder(**{'Content-Range': 'nonsense'}),
                 self.remainder(**{'Content-Length': '999'}),
                 self.remainder(**{'ETag': '"changed"'}),
                 self.remainder(**{'Content-Encoding': 'gzip'})]
        for response in cases:
            with self.subTest(headers=response.headers), \
                 patch.object(lib.urllib.request, 'urlopen', return_value=response) as call:
                with self.assertRaises(ValueError):
                    lib.fetch(self.root, self.manifest)
                self.assertEqual(self.partial.read_bytes(), self.payload[:self.offset])
                self.assertFalse(self.dest.exists())
                self.assertEqual(call.call_count, 1)

    def test_416_and_http_redirect_to_plaintext_preserve_partial(self):
        self.interrupt()
        with patch.object(lib.urllib.request, 'urlopen', side_effect=lib.urllib.error.HTTPError(
                self.asset['url'], 416, 'range not satisfiable', {}, None)):
            with self.assertRaises(OSError):
                lib.fetch(self.root, self.manifest)
        response = self.remainder()
        response.geturl = lambda: 'http://example.invalid/file'
        with patch.object(lib.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'non-HTTPS'):
                lib.fetch(self.root, self.manifest)
        self.assertEqual(self.partial.read_bytes(), self.payload[:self.offset])

    def test_changed_manifest_or_missing_metadata_refused_without_network(self):
        self.interrupt()
        self.asset['url'] += '?changed'
        self.save_manifest()
        with patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('no network')):
            with self.assertRaisesRegex(ValueError, 'metadata differs'):
                lib.fetch(self.root, self.manifest)
            self.metadata.unlink()
            with self.assertRaisesRegex(ValueError, 'Untracked partial'):
                lib.fetch(self.root, self.manifest)

    def test_corrupt_resumed_bytes_fail_full_hash_and_are_preserved(self):
        self.interrupt()
        self.partial.write_bytes(b'ZIM\x04' + b'x' * (self.offset-4))
        with patch.object(lib.urllib.request, 'urlopen', return_value=self.remainder()):
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                lib.fetch(self.root, self.manifest)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.partial.stat().st_size, len(self.payload))
        with patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('no redownload')):
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                lib.fetch(self.root, self.manifest)

    def test_complete_partial_after_crash_finishes_without_network(self):
        self.interrupt()
        self.partial.write_bytes(self.payload)
        with patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('no network')):
            lib.fetch(self.root, self.manifest)
        self.assertEqual(self.dest.read_bytes(), self.payload)

    def test_crash_after_rename_recovers_record_without_network(self):
        self.interrupt()
        self.partial.write_bytes(self.payload)
        self.partial.rename(self.dest)
        with patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('no network')):
            lib.fetch(self.root, self.manifest)
        lib.verify_manifest(self.root, self.manifest)
        self.assertFalse(self.metadata.exists())

    def test_space_gate_counts_only_missing_bytes_and_keeps_reserve(self):
        self.interrupt()
        needed = len(self.payload) - self.offset + 1_000_000_000
        with patch.object(lib.shutil, 'disk_usage', return_value=SimpleNamespace(free=needed-1)), \
             patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('no network')):
            with self.assertRaisesRegex(ValueError, 'all missing assets'):
                lib.fetch(self.root, self.manifest)
        with patch.object(lib.shutil, 'disk_usage', return_value=SimpleNamespace(free=needed)), \
             patch.object(lib.urllib.request, 'urlopen', return_value=self.remainder()):
            lib.fetch(self.root, self.manifest)
        self.assertEqual(self.dest.read_bytes(), self.payload)

    def test_resume_without_strong_etag_still_requires_pinned_hash(self):
        self.interrupt(etag='W/"weak"')
        with patch.object(lib.urllib.request, 'urlopen', return_value=self.remainder()) as call:
            lib.fetch(self.root, self.manifest)
        self.assertIsNone(call.call_args.args[0].get_header('If-range'))
        lib.verify_manifest(self.root, self.manifest)

    def test_crash_before_first_byte_reuses_metadata(self):
        self.interrupt()
        self.partial.unlink()
        with patch.object(lib.urllib.request, 'urlopen', return_value=Response(self.payload)) as call:
            lib.fetch(self.root, self.manifest)
        self.assertIsNone(call.call_args.args[0].get_header('Range'))
        lib.verify_manifest(self.root, self.manifest)

    def test_second_interruption_advances_offset_without_losing_prefix(self):
        self.interrupt()
        response = self.remainder()
        response.close()
        response = Response(self.payload[self.offset:40], status=206, headers=response.headers)
        with patch.object(lib.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises(OSError):
                lib.fetch(self.root, self.manifest)
        self.assertEqual(self.partial.read_bytes(), self.payload[:40])
        self.offset = 40
        with patch.object(lib.urllib.request, 'urlopen', return_value=self.remainder()) as call:
            lib.fetch(self.root, self.manifest)
        self.assertEqual(call.call_args.args[0].get_header('Range'), 'bytes=40-')
        lib.verify_manifest(self.root, self.manifest)

    def test_oversized_body_is_not_written_past_expected_size(self):
        self.prepare()
        with patch.object(lib.urllib.request, 'urlopen', return_value=Response(self.payload + b'excess')):
            with self.assertRaisesRegex(ValueError, 'exceeds expected'):
                lib.fetch(self.root, self.manifest)
        self.assertLessEqual(self.partial.stat().st_size, len(self.payload))
        self.assertFalse(self.dest.exists())

    def test_backup_restore_preserves_incomplete_resume_state(self):
        self.interrupt()
        # A valid bundle needs at least one acquired asset; this is the existing small shelf.
        self.asset = {'path': 'public/sample.pdf', 'url': 'https://example.invalid/file.pdf',
                      'max_bytes': 10000, 'sha256': None, 'title': 'Existing'}
        original_manifest = self.manifest.read_bytes()
        self.save_manifest()
        with patch.object(lib, 'stream_download', side_effect=lambda a, p: p.write_bytes(b'%PDF-test')):
            lib.fetch(self.root, self.manifest)
        self.manifest.write_bytes(original_manifest)
        bundle = self.base / 'bundle'
        lib.shutil.copytree(self.root, bundle / 'data')
        lib.write_json(bundle / 'checksums.json', lib.tree_hashes(bundle))
        destination = self.base / 'restored'
        with patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('offline restore')):
            lib.restore(bundle, destination)
        self.assertEqual((destination / 'zim/sample.zim.part').read_bytes(), self.payload[:self.offset])
        with patch.object(lib.urllib.request, 'urlopen', return_value=self.remainder()):
            lib.fetch(destination, self.manifest)
        lib.verify_manifest(destination, self.manifest)

    def test_real_loopback_http_interruption_and_range_transfer(self):
        self.prepare()
        payload = b'ZIM\x04' + b'x' * (2 * 1024 * 1024)
        self.asset.update(expected_bytes=len(payload), max_bytes=len(payload),
                          sha256=lib.hashlib.sha256(payload).hexdigest())
        self.save_manifest()
        requests = []
        cutoff = 1024 * 1024 + 64

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requested = self.headers.get('Range')
                requests.append(requested)
                offset = int(requested.removeprefix('bytes=').removesuffix('-')) if requested else 0
                self.send_response(206 if requested else 200)
                self.send_header('Content-Length', str(len(payload) - offset))
                self.send_header('ETag', '"fixture"')
                if requested:
                    self.send_header('Content-Range', f'bytes {offset}-{len(payload)-1}/{len(payload)}')
                self.end_headers()
                # First response closes before its advertised length; second serves the remainder.
                self.wfile.write(payload[offset:] if requested else payload[:cutoff])
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = lib.urllib.request.build_opener(lib.urllib.request.ProxyHandler({}))

        def local_transport(request, timeout):
            # Only the test transport is HTTP; production still requires HTTPS.
            local = lib.urllib.request.Request(f'http://127.0.0.1:{server.server_port}/fixture',
                                              headers=dict(request.header_items()))
            response = opener.open(local, timeout=timeout)
            response.geturl = lambda: self.asset['url']
            return response

        try:
            with patch.object(lib.urllib.request, 'urlopen', side_effect=local_transport):
                with self.assertRaises((OSError, lib.http.client.HTTPException)):
                    lib.fetch(self.root, self.manifest)
                self.assertEqual(self.partial.read_bytes(), payload[:cutoff])
                lib.fetch(self.root, self.manifest)
            self.assertEqual(requests, [None, f'bytes={cutoff}-'])
            self.assertEqual(self.dest.read_bytes(), payload)
            lib.verify_manifest(self.root, self.manifest)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
