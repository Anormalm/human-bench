"""Separate read-only rater app: no workbench routes or environment-configured reports."""
from shuorenhua_bench.rater_site import load_rater_routes


def create_rater_app(directory):
    routes = load_rater_routes(directory)

    def app(environ, start_response):
        method = environ.get('REQUEST_METHOD', 'GET')
        path = environ.get('PATH_INFO', '/')
        status, mime, body = '404 Not Found', 'application/json', b'{"error":"use your assigned link"}'
        if method not in {'GET', 'HEAD'}:
            status, body = '405 Method Not Allowed', b'{"error":"export judgments from your browser"}'
        elif path == '/health':
            status, body = '200 OK', b'{"status":"ok","mode":"rater_only"}'
        elif path in routes:
            status, (mime, body) = '200 OK', routes[path]
        start_response(status, [
            ('Content-Type', mime + '; charset=utf-8'), ('Content-Length', str(len(body))),
            ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
            ('Referrer-Policy', 'no-referrer'),
            ('Content-Security-Policy', ("default-src 'self'; style-src 'self' 'unsafe-inline'; "
             "script-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; "
             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")),
        ])
        return [] if method == 'HEAD' else [body]

    return app
