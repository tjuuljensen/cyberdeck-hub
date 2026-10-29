"""Unprivileged, read-only Kiwix proxy; Gunicorn supplies TLS on a separate origin.

The backend is fixed to loopback. Never forward library cookies or credentials,
and never let archive responses set cookies for the administration hostname.
"""
import http.client
import os
import urllib.parse

from flask import Flask, Response, request

app = Flask(__name__, static_folder=None)
REQUEST_HEADERS = ('Accept', 'Accept-Language', 'Accept-Encoding', 'Range',
                   'If-Range', 'If-None-Match', 'If-Modified-Since')
RESPONSE_HEADERS = {'content-type', 'content-length', 'content-encoding',
                    'content-range', 'accept-ranges', 'etag', 'last-modified',
                    'cache-control', 'expires', 'vary', 'content-language',
                    'content-disposition', 'content-security-policy', 'location'}


def backend_address():
    """Return the configured internal Kiwix HTTP backend address and path prefix."""
    value = os.environ.get('CYBERDECK_KIWIX_BACKEND', 'http://127.0.0.1:8080')
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password or
            parsed.query or parsed.fragment):
        raise ValueError('Kiwix backend must be an internal HTTP URL')
    return parsed.hostname, parsed.port or 80, parsed.path.rstrip('/')


def location_for_client(location):
    host = os.environ.get('CYBERDECK_HOSTNAME', 'cyberdeck.local')
    parsed = urllib.parse.urlsplit(location)
    try:
        backend_host, backend_port, _prefix = backend_address()
    except ValueError:
        backend_host, backend_port = '127.0.0.1', 8080
    if (parsed.hostname in {backend_host, '127.0.0.1', 'localhost', host} and
            parsed.port in (None, backend_port, 8080)):
        path = parsed.path if parsed.path.startswith('/kiwix/') else '/kiwix/' + parsed.path.lstrip('/')
        return urllib.parse.urlunsplit(('https', host, path, parsed.query, parsed.fragment))
    return location


@app.route('/', defaults={'path': ''}, methods=['GET', 'HEAD'], provide_automatic_options=False)
@app.route('/<path:path>', methods=['GET', 'HEAD'], provide_automatic_options=False)
def proxy(path):
    if os.environ.get('CYBERDECK_LEGACY_KIWIX_REDIRECT') == '1':
        target = request.environ.get('RAW_URI', request.path)
        if not target.startswith('/') or target.startswith('//') or any(c in target for c in '\r\n#'):
            return Response('Invalid Kiwix URL.', status=400, mimetype='text/plain')
        if not target.startswith('/kiwix/'):
            target = '/kiwix/' + target.lstrip('/')
        host = os.environ.get('CYBERDECK_HOSTNAME', 'cyberdeck.local')
        from flask import redirect
        return redirect('https://' + host + target, code=308)
    # RAW_URI retains percent-encoded article names and the exact search query.
    target = request.environ.get('RAW_URI')
    if target is None:
        target = urllib.parse.quote(request.path, safe='/')
        if request.query_string:
            target += '?' + request.query_string.decode('ascii')
    if (len(target) > 16384 or not target.startswith('/') or target.startswith('//')
            or any(character in target for character in '\r\n#')):
        return Response('Invalid Kiwix URL.', status=400, mimetype='text/plain')
    try:
        backend_host, backend_port, prefix = backend_address()
        connection = http.client.HTTPConnection(backend_host, backend_port, timeout=30)
        if prefix:
            target = prefix + target
        headers = {name: request.headers[name] for name in REQUEST_HEADERS if name in request.headers}
        connection.request(request.method, target, headers=headers)
        upstream = connection.getresponse()
        connection_headers = {name.strip().lower() for name in upstream.getheader('Connection', '').split(',')}
        outgoing = [(name, location_for_client(value) if name.lower() == 'location' else value)
                    for name, value in upstream.getheaders()
                    if name.lower() in RESPONSE_HEADERS and name.lower() not in connection_headers]
    except (OSError, http.client.HTTPException, ValueError):
        if 'connection' in locals():
            connection.close()
        return Response('Kiwix is temporarily unavailable. Return to the library and try again shortly.',
                        status=503, mimetype='text/plain', headers={'Retry-After': '5'})

    def close():
        upstream.close()
        connection.close()

    def chunks():
        try:
            while chunk := upstream.read(64 * 1024):
                yield chunk
        finally:
            close()

    if request.method == 'HEAD':
        close()
        response = Response(status=upstream.status, headers=outgoing)
    else:
        response = Response(chunks(), status=upstream.status, headers=outgoing)
        response.call_on_close(close)
    return response


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response
