"""Core file scanning and change detection logic."""
import hashlib
import os
from pathlib import Path


def sha256_file(path: str) -> str:
    """计算文件内容 hash"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return ""


def should_ignore(name: str, path: str, ignore_patterns: set, ignore_exts: set, monitor_exts: set) -> bool:
    """判断是否应该忽略该文件"""
    parts = Path(path).parts
    for pattern in ignore_patterns:
        if name == pattern or pattern in parts:
            return True

    ext = os.path.splitext(name)[1].lower()
    if ext in ignore_exts:
        return True

    if monitor_exts and ext not in monitor_exts:
        return True
    return False


def scan_directory(root: str, ignore_patterns: set, ignore_exts: set, monitor_exts: set) -> dict[str, tuple[float, int, str]]:
    """
    全量扫描目录，返回 {文件路径: (mtime, file_size, sha256)} 字典
    仅用于首次基线建立
    """
    result = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if not should_ignore(d, os.path.join(dirpath, d), ignore_patterns, ignore_exts, monitor_exts)
        ]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            if os.path.islink(fpath):
                continue
            if should_ignore(fname, fpath, ignore_patterns, ignore_exts, monitor_exts):
                continue
            try:
                stat = os.stat(fpath)
                file_hash = sha256_file(fpath)
                result[fpath] = (stat.st_mtime, stat.st_size, file_hash)
            except OSError:
                continue
    return result


def fast_scan(root: str, ignore_patterns: set, ignore_exts: set, monitor_exts: set) -> dict[str, tuple[float, int]]:
    """
    快速扫描目录，仅返回 {文件路径: (mtime, file_size)} 字典
    不读取文件内容，开销极低，用于轮询阶段
    """
    result = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if not should_ignore(d, os.path.join(dirpath, d), ignore_patterns, ignore_exts, monitor_exts)
        ]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            if os.path.islink(fpath):
                continue
            if should_ignore(fname, fpath, ignore_patterns, ignore_exts, monitor_exts):
                continue
            try:
                stat = os.stat(fpath)
                result[fpath] = (stat.st_mtime, stat.st_size)
            except OSError:
                continue
    return result


def detect_changes(old_state: dict, fast_state: dict, watch_dir: str) -> list[str]:
    """
    两阶段变化检测：
    1. 先用 mtime/size 快速判断疑似变化文件
    2. 仅对疑似文件计算 sha256，确认内容是否真正改变
    """
    changes = []
    old_keys = set(old_state.keys())
    new_keys = set(fast_state.keys())

    for fpath in sorted(new_keys - old_keys):
        _, size = fast_state[fpath]
        rel = os.path.relpath(fpath, watch_dir)
        changes.append(f"[新增] {rel} ({fmt_size(size)})")

    for fpath in sorted(old_keys - new_keys):
        rel = os.path.relpath(fpath, watch_dir)
        changes.append(f"[删除] {rel}")

    suspected = []
    for fpath in old_keys & new_keys:
        old_mtime, old_size, _ = old_state[fpath]
        new_mtime, new_size = fast_state[fpath]
        if old_mtime != new_mtime or old_size != new_size:
            suspected.append((fpath, old_mtime, old_size))

    for fpath, old_mtime, old_size in suspected:
        new_mtime, new_size = fast_state[fpath]
        new_hash = sha256_file(fpath)
        old_hash = old_state[fpath][2]

        if new_hash and old_hash == new_hash:
            old_state[fpath] = (new_mtime, new_size, new_hash)
            continue

        rel = os.path.relpath(fpath, watch_dir)
        diff = fmt_size_diff(new_size - old_size)
        changes.append(f"[修改] {rel} ({diff})")
        old_state[fpath] = (new_mtime, new_size, new_hash)

    return changes


def fmt_size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes}B"
    elif nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f}KB"
    else:
        return f"{nbytes / 1024 / 1024:.1f}MB"


def fmt_size_diff(diff: int) -> str:
    if diff > 0:
        return f"+{fmt_size(diff)}"
    elif diff < 0:
        return f"-{fmt_size(abs(diff))}"
    return "0B"
