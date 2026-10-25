"""HTTP bootstrap checks using mock handlers; no sockets, trust or host changes."""
import importlib.util
import io
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('http_redirect', Path(__file__).with_name('http-redirect.py'))
redirect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redirect)


class HttpRedirectTests(unittest.TestCase):
    def request(self, path, method='GET'):
        handler = redirect.Redirect.__new__(redirect.Redirect)
        handler.path, handler.command = path, method
        handler.wfile = io.BytesIO()
        for name in ('send_response', 'send_header', 'end_headers', 'send_error'):
            setattr(handler, name, Mock())
        getattr(handler, 'do_HEAD' if method == 'HEAD' else 'do_GET')()
        return handler

    def test_certificate_only_download_and_head(self):
        der = b'public-certificate-test-bytes'
        pem = ssl.DER_cert_to_PEM_cert(der).encode('ascii')
        with tempfile.TemporaryDirectory() as temp:
            certificate = Path(temp) / 'ca.crt'
            certificate.write_bytes(pem)
            with patch.dict(redirect.os.environ, {'CYBERDECK_CA_CERT_FILE': str(certificate)}):
                for extension, data in [('cer', der), ('crt', pem)]:
                    for method in ('GET', 'HEAD'):
                        result = self.request('/trust/ca.' + extension + '?download=1', method)
                        result.send_response.assert_called_once_with(200)
                        self.assertEqual(result.wfile.getvalue(), data if method == 'GET' else b'')
                        headers = dict(call.args for call in result.send_header.call_args_list)
                        self.assertEqual(headers['Content-Length'], str(len(data)))
                        self.assertEqual(headers['Cache-Control'], 'no-store')
                        self.assertNotIn('Location', headers)
                        self.assertNotIn('Set-Cookie', headers)

    def test_other_paths_keep_https_redirect_without_serving_files(self):
        with patch.object(redirect, 'TARGET_HOST', 'family-library.local'):
            for path in ('/admin', '/trust/ca.key', '/trust/../ca.key', '/trust/%2e%2e/ca.key'):
                result = self.request(path)
                result.send_response.assert_called_once_with(308)
                result.send_header.assert_any_call('Location', 'https://family-library.local' + path)
                self.assertEqual(result.wfile.getvalue(), b'')

    def test_missing_or_malformed_certificate_never_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            certificate = Path(temp) / 'missing.crt'
            with patch.dict(redirect.os.environ, {'CYBERDECK_CA_CERT_FILE': str(certificate)}):
                for content in (None, b'not a certificate', b'x' * 65537):
                    if content is not None:
                        certificate.write_bytes(content)
                    result = self.request('/trust/ca.cer')
                    result.send_error.assert_called_once_with(404, 'Library certificate unavailable')
                    result.send_response.assert_not_called()
                    self.assertEqual(result.wfile.getvalue(), b'')


if __name__ == '__main__':
    unittest.main()
