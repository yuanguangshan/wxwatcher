"""Configuration management for wxwatcher."""
import os
from dataclasses import dataclass, field

# --- 默认配置 ---
DEFAULT_POLL_INTERVAL = 30
DEFAULT_MAX_BATCH = 50
DEFAULT_PUSH_URL = "https://api.yuangs.cc/weixinpush"
DEFAULT_TO_USER = "@all"

IGNORE_PATTERNS = {
    ".git", "__pycache__", ".venv", "node_modules", ".cache",
    ".DS_Store",
}
IGNORE_EXTS = {".pyc", ".pyo"}
MONITOR_EXTS: set[str] = set()


@dataclass
class AppConfig:
    watch_dir: str = ""
    poll_interval: int = DEFAULT_POLL_INTERVAL
    push_url: str = DEFAULT_PUSH_URL
    to_user: str = DEFAULT_TO_USER
    max_batch: int = DEFAULT_MAX_BATCH
    ignore_patterns: set = field(default_factory=lambda: IGNORE_PATTERNS.copy())
    ignore_exts: set = field(default_factory=lambda: IGNORE_EXTS.copy())
    monitor_exts: set = field(default_factory=set)
    log_file: str = ""


def load_config(args) -> AppConfig:
    """合并 CLI 参数、环境变量和默认值，优先级：CLI > 环境变量 > 默认值。"""
    watch_dir = args.dir or os.environ.get("WXWATCHER_DIR")
    if not watch_dir:
        watch_dir = os.getcwd()

    push_url = args.push_url or os.environ.get("WXWATCHER_PUSH_URL", DEFAULT_PUSH_URL)
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
