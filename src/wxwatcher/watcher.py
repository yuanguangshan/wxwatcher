"""Core file scanning and change detection logic."""
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple

STATE_FILE = os.path.expanduser("~/.wxwatcher/state.json")


def sha256_file(path: str, max_size: int = 10 * 1024 * 1024) -> str:
    """
    计算文件内容 hash。

    超大文件（超过 max_size）返回特殊格式 "LARGE:{size}:{partial_hash}"，
    其中 partial_hash 是文件前 8KB 的哈希值，用于近似判断变化。

    Args:
        path: 文件路径
        max_size: 超过此大小（字节）视为大文件，默认 10MB

    Returns:
        完整 SHA256 哈希，或大文件的 "LARGE:{size}:{partial_hash}" 格式
    """
    try:
        size = os.path.getsize(path)
        if size == 0:
            return "EMPTY"

        if size > max_size:
            # 对超大文件，只计算前 8KB 的哈希作为近似指纹
            h = hashlib.sha256()
            with open(path, "rb") as f:
                chunk = f.read(8192)
                h.update(chunk)
            partial_hash = h.hexdigest()
            return f"LARGE:{size}:{partial_hash}"

        # 正常文件，计算完整哈希
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return "ERROR"


def should_ignore(
    name: str,
    path: str,
    ignore_patterns: Set[str],
    ignore_exts: Set[str],
    monitor_exts: Set[str]
) -> bool:
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


def _walk_files(
    root: str,
    ignore_patterns: Set[str],
    ignore_exts: Set[str],
    monitor_exts: Set[str]
):
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


def scan_directory(
    root: str,
    ignore_patterns: Set[str],
    ignore_exts: Set[str],
    monitor_exts: Set[str]
) -> Dict[str, Tuple[float, int, str]]:
    """全量扫描目录，返回 {文件路径: (mtime, file_size, sha256)}"""
    result = {}
    for fpath, stat in _walk_files(root, ignore_patterns, ignore_exts, monitor_exts):
        file_hash = sha256_file(fpath)
        result[fpath] = (stat.st_mtime, stat.st_size, file_hash)
    return result


def fast_scan(
    root: str,
    ignore_patterns: Set[str],
    ignore_exts: Set[str],
    monitor_exts: Set[str]
) -> Dict[str, Tuple[float, int]]:
    """快速扫描目录，仅返回 {文件路径: (mtime, file_size)}，不读取文件内容"""
    return {
        fpath: (stat.st_mtime, stat.st_size)
        for fpath, stat in _walk_files(root, ignore_patterns, ignore_exts, monitor_exts)
    }


def detect_changes(
    old_state: Dict[str, Tuple[float, int, str]],
    fast_state: Dict[str, Tuple[float, int]],
    watch_dir: str
) -> List[str]:
    """
    两阶段变化检测（纯函数，不修改 old_state）：
    1. 先用 mtime/size 快速判断疑似变化文件
    2. 仅对疑似文件计算 sha256，确认内容是否真正改变

    处理特殊情况：
    - 大文件（LARGE: 前缀）：基于前 8KB 近似哈希判断
    - 空文件（EMPTY）：大小为 0 的文件
    - 读取错误（ERROR）：跳过哈希比较，仅依赖 mtime/size
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
        old_mtime, old_size, old_hash = old_state[fpath]
        new_mtime, new_size = fast_state[fpath]

        # 如果 mtime 和 size 都没变，直接跳过
        if old_mtime == new_mtime and old_size == new_size:
            continue

        new_hash = sha256_file(fpath)

        # 错误处理：如果哈希计算失败，跳过这个文件
        if new_hash == "ERROR" or old_hash == "ERROR":
            logger = logging.getLogger(__name__)
            logger.warning(f"无法计算哈希: {fpath}")
            continue

        # 特殊值处理
        if old_hash == new_hash:
            continue  # 假阳性，内容未变

        # 对于大文件和空文件，如果部分哈希相同，也视为未变
        # 只有当 mtime 确实变化时才报告变更
        if old_mtime != new_mtime:
            rel = os.path.relpath(fpath, watch_dir)
            diff = fmt_size_diff(new_size - old_size)
            changes.append(f"[修改] {rel} ({diff})")

    return changes


def save_state(state: Dict[str, Tuple[float, int, str]], watch_dir: str) -> None:
    """将状态持久化到文件"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    serializable = {k: list(v) for k, v in state.items()}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"watch_dir": watch_dir, "files": serializable}, f)


def load_state() -> Tuple[Dict[str, Tuple[float, int, str]], str | None]:
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
