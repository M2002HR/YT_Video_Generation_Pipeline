#!/usr/bin/env python3
"""Read-only websocket bridge used while the main panel owns a live pipeline child.

The normal control-panel service can be restarted after its current runner exits, at which
point it serves ``/api/ws`` itself.  This narrow listener lets the UI receive the same
notifications now without restarting that parent process (which would terminate its cgroup).
"""
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from video_control_panel import Handler, style_catalog_entries


class WebsocketBridge(Handler):
    """Expose only the passive websocket endpoint; no pipeline control routes exist here."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/ws":
            self.handle_websocket(parse_qs(parsed.query))
            return
        if parsed.path == "/api/style-catalog":
            content_project = str((parse_qs(parsed.query).get("content_project") or ["question_harvest"])[0])
            self.send_json(HTTPStatus.OK, {"content_project": content_project, "styles": style_catalog_entries(content_project)})
            return
        if parsed.path.startswith("/api/styles/"):
            parts = parsed.path.split("/")
            if len(parts) == 6:
                self.serve_style_preview(parts[3], parts[4], parts[5])
                return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4145)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), WebsocketBridge).serve_forever()


if __name__ == "__main__":
    main()
