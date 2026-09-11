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
_allow_roots: list = []

# 敏感路径黑名单：即使落在 allow_roots 内也一律拒绝。
# 用规范化后的绝对路径做前缀/精确匹配。
_DENY_DIRS = {
    ".ssh", ".gnupg", ".aws", ".kube", ".docker", ".config/gcloud",
    ".password-store", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
}
_DENY_BASENAMES = {
    ".netrc", ".npmrc", ".pypirc", ".git-credentials", "id_rsa", "id_ed25519",
    "id_ecdsa", "id_dsa", "credentials", ".env", "shadow", "sudoers",
}
_DENY_ABS_PREFIXES = (
    "/etc", "/var/root", "/private/etc", "/private/var/root",
    "/proc", "/sys", "/dev", "/boot",
)


def _canonical(path: str) -> str:
    """展开 ~、转绝对路径、解析符号链接，返回规范路径。"""
    p = os.path.expanduser(path)
    p = os.path.abspath(p)
    # realpath 解析符号链接，防止用软链接绕过白名单
    return os.path.realpath(p)


def _is_within(path: str, root: str) -> bool:
    """判断 path 是否位于 root 之内（含 root 本身）。"""
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        # 不同盘符（Windows）等情况
        return False


def _check_path_allowed(path: str) -> tuple:
    """校验路径是否被沙箱允许。

    返回 (ok, canonical_path, error_message)。
    规则：必须落在 allow_roots 之一内；且不得命中敏感目录/文件名。
    allow_roots 为空时拒绝所有请求（fail-closed）。
    """
    canonical = _canonical(path)

    if not _allow_roots:
        return False, canonical, "file API 未配置 allow_roots，已拒绝所有访问（fail-closed）"

    # 必须先确认在白名单内，再谈黑名单（避免泄漏黑名单本身的信息）
    if not any(_is_within(canonical, r) for r in _allow_roots):
        return False, canonical, f"path outside allowed roots: {canonical}"

    # 敏感绝对路径前缀
    for pref in _DENY_ABS_PREFIXES:
        if canonical == pref or canonical.startswith(pref + os.sep):
            return False, canonical, f"sensitive path denied: {canonical}"

    # 敏感目录 / 文件名
    parts = canonical.split(os.sep)
    for part in parts:
        if part in _DENY_DIRS:
            return False, canonical, f"sensitive directory denied: {part}"
    if os.path.basename(canonical) in _DENY_BASENAMES:
        return False, canonical, f"sensitive file denied: {os.path.basename(canonical)}"

    return True, canonical, ""


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

        ok, canonical, err = _check_path_allowed(path)
        if not ok:
            logger.warning(f"file API denied: {err}")
            self._json_response(403, {"error": err})
            return

        path = canonical

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

        ok, canonical, err = _check_path_allowed(directory)
        if not ok:
            logger.warning(f"file API denied (recent): {err}")
            self._json_response(403, {"error": err})
            return

        directory = canonical

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


def start_file_api(port: int, token: str, hostname: str, allow_roots: list = None):
    """Start the file API server in a background daemon thread.

    allow_roots: 允许访问的根目录白名单（规范化后）。为空时 API 拒绝所有请求。
    """
    global _token, _hostname, _server, _allow_roots
    _token = token
    _hostname = hostname
    _allow_roots = [os.path.realpath(os.path.expanduser(os.path.abspath(r)))
                    for r in (allow_roots or []) if r]

    if not _allow_roots:
        logger.warning("file API 未配置 allow_roots：所有 /api/file 与 /api/recent 请求都会被拒绝")
    else:
        logger.info(f"file API allow_roots: {_allow_roots}")

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
