#!/usr/bin/env python3
"""Unprivileged HTTPS compatibility redirect for the former Hub port."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import ssl
from urllib.parse import urlsplit

HOST = os.environ.get('CYBERDECK_HOSTNAME', 'cyberdeck.local')


class Redirect(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith('/') or self.path.startswith('//'):
            self.send_error(400, 'Invalid path')
            return
        if any(character in self.path for character in '\r\n#'):
            self.send_error(400, 'Invalid path')
            return
        target = 'https://' + HOST + self.path
        parsed = urlsplit(target)
        if parsed.scheme != 'https' or parsed.netloc != HOST:
            self.send_error(400, 'Invalid redirect target')
            return
        self.send_response(308)
        self.send_header('Location', target)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()

    do_HEAD = do_GET

    def log_message(self, _format, *_args):
        pass


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8443), Redirect)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('/etc/cyberdeck/tls/server.crt', '/etc/cyberdeck/tls/server.key')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
