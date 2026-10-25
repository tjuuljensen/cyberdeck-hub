#!/usr/bin/env python3
"""Serve the optional CyberChef build on an isolated HTTPS origin and port."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path, PurePosixPath
import ssl
from urllib.parse import unquote, urlsplit


def resolve_document(root, request_path):
    """Resolve one regular, non-symlinked document beneath the module root."""
    path = unquote(urlsplit(request_path).path).lstrip('/') or 'index.html'
    if '\\' in path or '\x00' in path:
        return None
    parts = PurePosixPath(path).parts
    if not parts or any(part in {'', '.', '..'} for part in parts):
        return None
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return None
    except OSError:
        return None
    return resolved


class CyberChefHandler(BaseHTTPRequestHandler):
    server_version = 'CyberdeckCyberChef/1'

    def do_GET(self):
        self._serve(head_only=False)

    def do_HEAD(self):
        self._serve(head_only=True)

    def _serve(self, head_only):
        root = self.server.document_root
        resolved = resolve_document(root, self.path)
        if resolved is None:
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(resolved.name)[0] or 'application/octet-stream'
        payload_size = resolved.stat().st_size
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(payload_size))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy',
            "default-src 'self' data: blob:; script-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self' data:; worker-src 'self' blob:; "
            "connect-src 'self' http: https:; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        if not head_only:
            try:
                with resolved.open('rb') as source:
                    while block := source.read(1024 * 1024):
                        self.wfile.write(block)
            except OSError:
                self.close_connection = True

    def log_message(self, format, *args):
        # Avoid logging request query strings, which may contain user data.
        super().log_message('%s %s', self.command, urlsplit(self.path).path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--cert', required=True, type=Path)
    parser.add_argument('--key', required=True, type=Path)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', default=8445, type=int)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir() or not (root / 'index.html').is_file():
        parser.error('root must be a directory containing index.html')
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    server = ThreadingHTTPServer((args.host, args.port), CyberChefHandler)
    server.document_root = root
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
