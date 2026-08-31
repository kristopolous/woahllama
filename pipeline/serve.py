"""Dev server for the site.

The page loads its data with fetch(), which file:// URLs block, so it has to be
served. Cache-Control: no-store because stale JS silently hides every edit.
"""
import functools, http.server, pathlib, socketserver, sys


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    root = pathlib.Path(__file__).resolve().parent.parent / "site"
    socketserver.TCPServer.allow_reuse_address = True
    print(f"woah...llama on http://localhost:{port}")
    socketserver.TCPServer(
        ("", port), functools.partial(Handler, directory=str(root))
    ).serve_forever()
