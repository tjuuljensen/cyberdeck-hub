"""Kiwix HTTPS boundary and streaming tests; all backend connections are mocked."""
import http.client
import unittest
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import kiwix_https as proxy


class KiwixHttpsTests(unittest.TestCase):
    def setUp(self):
        self.client = proxy.app.test_client()
        self.upstream = Mock(status=200)
        self.upstream.getheaders.return_value = [('Content-Type', 'text/html')]
        self.upstream.getheader.return_value = ''
        self.upstream.read.side_effect = [b'<html>Kiwix</html>', b'']
        self.connection = Mock()
        self.connection.getresponse.return_value = self.upstream
        self.factory = patch.object(proxy.http.client, 'HTTPConnection', return_value=self.connection).start()
        self.addCleanup(patch.stopall)

    def test_stream_preserves_encoded_path_and_query_without_forwarding_credentials(self):
        self.client.set_cookie('session', 'private-admin-session')
        response = self.client.get('/content/book/A/R%C3%B8d?q=first%20aid', headers={
            'Authorization': 'Bearer private', 'X-CSRF-Token': 'private',
            'Range': 'bytes=0-99', 'Accept-Encoding': 'gzip', 'Host': 'untrusted.example'})
        self.assertEqual(response.data, b'<html>Kiwix</html>')
        self.factory.assert_called_once_with('127.0.0.1', 8080, timeout=30)
        self.connection.request.assert_called_once_with('GET', '/content/book/A/R%C3%B8d?q=first%20aid',
            headers={'Accept-Encoding': 'gzip', 'Range': 'bytes=0-99'})
        self.assertNotIn('Set-Cookie', response.headers)
        self.connection.close.assert_called()

    def test_container_backend_and_prefix_are_configurable(self):
        with patch.dict(proxy.os.environ, {'CYBERDECK_KIWIX_BACKEND': 'http://kiwix:8081'}):
            response = self.client.get('/kiwix/viewer?q=one')
        self.assertEqual(response.status_code, 200)
        self.factory.assert_called_once_with('kiwix', 8081, timeout=30)
        self.connection.request.assert_called_once_with('GET', '/kiwix/viewer?q=one', headers={})

        self.connection.request.reset_mock()
        with patch.dict(proxy.os.environ, {'CYBERDECK_KIWIX_BACKEND': 'http://kiwix:8081/base'}):
            self.client.get('/kiwix/search')
        self.connection.request.assert_called_once_with('GET', '/base/kiwix/search', headers={})

    def test_backend_redirect_to_service_is_rewritten_to_public_host(self):
        self.upstream.status = 302
        self.upstream.getheaders.return_value = [('Location', 'http://kiwix:8080/viewer#book')]
        with patch.dict(proxy.os.environ, {'CYBERDECK_KIWIX_BACKEND': 'http://kiwix:8080',
                                           'CYBERDECK_HOSTNAME': 'hub.example.test'}):
            result = self.client.get('/kiwix/viewer')
        self.assertEqual(result.headers['Location'], 'https://hub.example.test/kiwix/viewer#book')

    def test_range_compression_and_head_headers(self):
        self.upstream.status = 206
        self.upstream.getheaders.return_value = [('Content-Type', 'application/octet-stream'),
            ('Content-Length', '4'), ('Content-Range', 'bytes 1-4/10'), ('Content-Encoding', 'gzip'),
            ('Accept-Ranges', 'bytes'), ('ETag', 'test'), ('Set-Cookie', 'session=untrusted'),
            ('Access-Control-Allow-Origin', '*'), ('Transfer-Encoding', 'chunked')]
        self.upstream.read.side_effect = [b'data', b'']
        result = self.client.get('/content/book/file')
        self.assertEqual(result.status_code, 206)
        self.assertEqual(result.data, b'data')
        for name in ('Content-Length', 'Content-Range', 'Content-Encoding', 'Accept-Ranges', 'ETag'):
            self.assertIn(name, result.headers)
        for name in ('Set-Cookie', 'Access-Control-Allow-Origin', 'Transfer-Encoding'):
            self.assertNotIn(name, result.headers)
        self.upstream.read.reset_mock()
        head = self.client.head('/content/book/file')
        self.assertEqual(head.data, b'')
        self.assertEqual(head.headers['Content-Length'], '4')
        self.upstream.read.assert_not_called()

    def test_redirects_use_new_https_hostname_and_never_follow_backend_redirects(self):
        self.upstream.status = 302
        with patch.dict(proxy.os.environ, {'CYBERDECK_HOSTNAME': 'family-library.local'}):
            self.upstream.getheaders.return_value = [('Location', 'http://127.0.0.1:8080/viewer#book')]
            result = self.client.get('/book')
            self.assertEqual(result.headers['Location'], 'https://family-library.local/kiwix/viewer#book')
            self.assertEqual(self.connection.request.call_count, 1)
            self.assertEqual(proxy.location_for_client('/viewer#book'), '/viewer#book')
            self.assertEqual(proxy.location_for_client('//family-library.local:8080/search?q=a'),
                             'https://family-library.local/kiwix/search?q=a')

    def test_backend_failure_is_safe_and_write_methods_are_not_proxied(self):
        self.connection.request.side_effect = OSError('private backend detail')
        result = self.client.get('/')
        self.assertEqual(result.status_code, 503)
        self.assertNotIn(b'private backend detail', result.data)
        self.connection.close.assert_called()
        self.connection.request.reset_mock()
        for method in ('POST', 'PUT', 'DELETE', 'OPTIONS'):
            self.assertEqual(self.client.open('/', method=method).status_code, 405)
        self.connection.request.assert_not_called()

    def test_disconnect_closes_stream_and_invalid_target_cannot_change_backend(self):
        result = self.client.get('/content/book')
        result.close()
        self.connection.close.assert_called()
        self.connection.request.reset_mock()
        for uri in ('http://external.example/', '//external.example/', '/bad\r\nHeader:x'):
            response = self.client.get('/', environ_overrides={'RAW_URI': uri})
            self.assertEqual(response.status_code, 400)
        self.connection.request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
