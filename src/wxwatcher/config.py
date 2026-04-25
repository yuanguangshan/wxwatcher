"""Configuration management for wxwatcher."""
import os
from dataclasses import dataclass, field
from typing import Set

# --- 默认配置 ---
DEFAULT_POLL_INTERVAL = 30
DEFAULT_MAX_BATCH = 50
DEFAULT_TO_USER = "@all"

IGNORE_PATTERNS: Set[str] = {
    ".git", "__pycache__", ".venv", "node_modules", ".cache",
    ".DS_Store",
}
IGNORE_EXTS: Set[str] = {".pyc", ".pyo"}
MONITOR_EXTS: Set[str] = set()


@dataclass
class AppConfig:
    """应用配置数据类。"""

    watch_dir: str = ""
    """监控的根目录路径"""

    poll_interval: int = DEFAULT_POLL_INTERVAL
    """轮询间隔（秒）"""

    push_url: str = ""
    """微信推送 API 地址（必须配置）"""

    to_user: str = DEFAULT_TO_USER
    """接收人，默认 @all"""

    max_batch: int = DEFAULT_MAX_BATCH
    """单批最大变更数量"""

    ignore_patterns: Set[str] = field(default_factory=lambda: IGNORE_PATTERNS.copy())
    """要忽略的目录/文件名模式"""

    ignore_exts: Set[str] = field(default_factory=lambda: IGNORE_EXTS.copy())
    """要忽略的文件扩展名"""

    monitor_exts: Set[str] = field(default_factory=set)
    """仅监控的文件扩展名（空集合表示监控所有）"""

    log_file: str = ""
    """日志文件路径"""


def load_config(args) -> AppConfig:
    """
    加载配置，合并 CLI 参数、环境变量和默认值。

    优先级：CLI 参数 > 环境变量 > 默认值

    Args:
        args: 命令行参数对象（来自 argparse）

    Returns:
        完整的配置对象

    Raises:
        ValueError: 当 push_url 未配置时
    """
    watch_dir = args.dir or os.environ.get("WXWATCHER_DIR")
    if not watch_dir:
        watch_dir = os.getcwd()

    # 推送 URL 为必填项
    push_url = args.push_url or os.environ.get("WXWATCHER_PUSH_URL")
    if not push_url:
        raise ValueError(
            "推送地址未配置。请通过以下任一方式提供：\n"
            "  - CLI 参数：--push-url <URL>\n"
            "  - 环境变量：export WXWATCHER_PUSH_URL=<URL>"
        )

    to_user = args.to_user or os.environ.get("WXWATCHER_TO_USER", DEFAULT_TO_USER)

    interval = args.interval
    if interval is None:
        interval = int(os.environ.get("WXWATCHER_INTERVAL", DEFAULT_POLL_INTERVAL))

    max_batch = args.max_batch
    if max_batch is None:
        max_batch = int(os.environ.get("WXWATCHER_MAX_BATCH", DEFAULT_MAX_BATCH))

    # 忽略规则：环境变量为逗号分隔列表
    ignore_str = os.environ.get("WXWATCHER_IGNORE", "")
    ignore_patterns = IGNORE_PATTERNS | {s.strip() for s in ignore_str.split(",") if s.strip()}

    # CLI --ext 参数 + 环境变量
    ext_source = args.ext if hasattr(args, "ext") and args.ext else os.environ.get("WXWATCHER_EXT", "")
    monitor_exts = MONITOR_EXTS | {
        s.strip() if s.strip().startswith(".") else f".{s.strip()}"
        for s in ext_source.split(",") if s.strip()
    }

    log_file = args.log_file or os.environ.get("WXWATCHER_LOG_FILE")
    if not log_file:
        log_dir = os.path.expanduser("~/.wxwatcher")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "file_watcher.log")

    return AppConfig(
        watch_dir=os.path.abspath(watch_dir),
        poll_interval=interval,
        push_url=push_url,
        to_user=to_user,
        max_batch=max_batch,
        ignore_patterns=ignore_patterns,
        ignore_exts=IGNORE_EXTS.copy(),
        monitor_exts=monitor_exts,
        log_file=log_file,
    )
