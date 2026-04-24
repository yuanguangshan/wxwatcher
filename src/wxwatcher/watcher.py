"""Core file scanning and change detection logic."""
import hashlib
import json
import os
from pathlib import Path

STATE_FILE = os.path.expanduser("~/.wxwatcher/state.json")


def sha256_file(path: str, max_size: int = 10 * 1024 * 1024) -> str:
    """计算文件内容 hash，超大文件返回特殊标记"""
    try:
        size = os.path.getsize(path)
        if size > max_size:
            return f"LARGE:{size}"
        h = hashlib.sha256()
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


def _walk_files(root: str, ignore_patterns: set, ignore_exts: set, monitor_exts: set):
    """生成器：遍历需要监控的文件路径和 stat 结果。"""
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
                stat_result = os.stat(fpath)
                yield fpath, stat_result
            except OSError:
                continue


def scan_directory(root: str, ignore_patterns: set, ignore_exts: set, monitor_exts: set) -> dict[str, tuple[float, int, str]]:
    """全量扫描目录，返回 {文件路径: (mtime, file_size, sha256)}"""
    result = {}
    for fpath, stat in _walk_files(root, ignore_patterns, ignore_exts, monitor_exts):
        file_hash = sha256_file(fpath)
        result[fpath] = (stat.st_mtime, stat.st_size, file_hash)
    return result


def fast_scan(root: str, ignore_patterns: set, ignore_exts: set, monitor_exts: set) -> dict[str, tuple[float, int]]:
    """快速扫描目录，仅返回 {文件路径: (mtime, file_size)}，不读取文件内容"""
    return {
        fpath: (stat.st_mtime, stat.st_size)
        for fpath, stat in _walk_files(root, ignore_patterns, ignore_exts, monitor_exts)
    }


def detect_changes(old_state: dict, fast_state: dict, watch_dir: str) -> list[str]:
    """
    两阶段变化检测（纯函数，不修改 old_state）：
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

    for fpath in old_keys & new_keys:
        old_mtime, old_size, _ = old_state[fpath]
        new_mtime, new_size = fast_state[fpath]
        if old_mtime != new_mtime or old_size != new_size:
            new_hash = sha256_file(fpath)
            old_hash = old_state[fpath][2]

            # 大文件标记：仅比较 mtime/size 变化
            is_large = new_hash.startswith("LARGE:")

            if new_hash and old_hash == new_hash:
                continue  # 假阳性，内容未变

            rel = os.path.relpath(fpath, watch_dir)
            diff = fmt_size_diff(new_size - old_size)
            changes.append(f"[修改] {rel} ({diff})")

    return changes


def save_state(state: dict, watch_dir: str) -> None:
    """将状态持久化到文件"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    serializable = {k: list(v) for k, v in state.items()}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"watch_dir": watch_dir, "files": serializable}, f)


def load_state() -> tuple[dict, str | None]:
    """从文件加载状态，返回 (state_dict, watch_dir)"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return {k: tuple(v) for k, v in data["files"].items()}, data.get("watch_dir")
        except (OSError, json.JSONDecodeError, KeyError):
            return {}, None
    return {}, None


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
