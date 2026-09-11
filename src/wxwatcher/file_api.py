"""Lightweight file serving API for wxwatcher.

Runs as a background thread inside the wxwatcher process.
Endpoints:
  GET /api/file?path=<abs_path>        → serve file content as JSON
  GET /api/recent?dir=<dir>&ext=<ext>&minutes=<n> → list recent files
  GET /api/health                      → {"status":"ok","hostname":"..."}

Auth: Bearer token (same as push_token).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

logger = logging.getLogger("wxwatcher.file_api")

_token = ""
_hostname = ""
_server = None


class FileAPIHandler(BaseHTTPRequestHandler):
    """Handle file API requests."""

    def log_message(self, format, *args):
        """Suppress default HTTP access logs."""
        pass

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return auth[7:] == _token

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._check_auth():
            self._json_response(401, {"error": "unauthorized"})
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/api/health":
            self._json_response(200, {"status": "ok", "hostname": _hostname})
            return

        if parsed.path == "/api/file":
            self._handle_file(params)
            return

        if parsed.path == "/api/recent":
            self._handle_recent(params)
            return

        self._json_response(404, {"error": "not found"})

    def _handle_file(self, params: dict):
        path = params.get("path", [""])[0]
        if not path:
            self._json_response(400, {"error": "path required"})
            return

        path = os.path.expanduser(path)
        path = os.path.abspath(path)

        if not os.path.exists(path):
            self._json_response(404, {"error": f"not found: {path}"})
            return
        if os.path.isdir(path):
            self._json_response(400, {"error": "is a directory, use /api/recent"})
            return

        # Size limit: 5MB
        size = os.path.getsize(path)
        if size > 5 * 1024 * 1024:
            self._json_response(413, {"error": f"file too large: {size} bytes"})
            return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            self._json_response(500, {"error": str(e)})
            return

        stat = os.stat(path)
        self._json_response(200, {
            "path": path,
            "content": content,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "mtime_str": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _handle_recent(self, params: dict):
        directory = params.get("dir", [""])[0]
        ext_filter = params.get("ext", [""])[0]
        minutes = int(params.get("minutes", ["0"])[0])
        limit = int(params.get("limit", ["20"])[0])

        if not directory:
            self._json_response(400, {"error": "dir required"})
            return

        directory = os.path.expanduser(directory)
        directory = os.path.abspath(directory)

        if not os.path.isdir(directory):
            self._json_response(404, {"error": f"not a directory: {directory}"})
            return

        cutoff = time.time() - (minutes * 60) if minutes > 0 else 0
        results = []
        skip = {".git", "node_modules", "__pycache__", ".venv", ".cache", ".trash", "dist", "build"}

        for root, dirs, files in os.walk(directory):
            # Prune skipped directories
            dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
            for fname in files:
                if fname.startswith("."):
                    continue
                if ext_filter and not fnmatch.fnmatch(fname, f"*{ext_filter}*"):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    stat = os.stat(fpath)
                except OSError:
                    continue
                if cutoff and stat.st_mtime < cutoff:
                    continue
                results.append({
                    "path": fpath,
                    "name": fname,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "mtime_str": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })

        # Sort by mtime descending (newest first)
        results.sort(key=lambda x: x["mtime"], reverse=True)
        results = results[:limit]

        self._json_response(200, {"files": results, "count": len(results)})


def start_file_api(port: int, token: str, hostname: str):
    """Start the file API server in a background daemon thread."""
    global _token, _hostname, _server
    _token = token
    _hostname = hostname

    try:
        _server = HTTPServer(("0.0.0.0", port), FileAPIHandler)
        t = threading.Thread(target=_server.serve_forever, daemon=True)
        t.start()
        logger.info(f"File API listening on :{port}")
    except Exception as e:
        logger.error(f"Failed to start file API: {e}")


def stop_file_api():
    """Stop the file API server."""
    global _server
    if _server:
        _server.shutdown()
        _server = None
