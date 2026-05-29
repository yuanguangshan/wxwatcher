"""Configuration management for wxwatcher."""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

# --- 默认配置 ---
DEFAULT_POLL_INTERVAL = 30
DEFAULT_MAX_BATCH = 50
DEFAULT_TO_USER = "@all"

# 支持上传到 Knowly 的文件扩展名
UPLOAD_EXTS: Set[str] = {
    ".pdf", ".txt", ".md",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg",
}

IGNORE_PATTERNS: Set[str] = {
    ".git", "__pycache__", ".venv", "node_modules", ".cache",
    ".DS_Store", ".log",
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

    push_token: str = "0503"
    """推送 Bearer token，默认 0503"""

    knowly_upload_url: str = ""
    """Knowly 上传 API 地址（空表示不上传）"""


def _resolve(value, env_key: str, config_data: Optional[Dict[str, Any]], config_key: str, default):
    """Resolve a single config value with priority: CLI > env > config_file > default."""
    if value is not None:
        return value
    env_val = os.environ.get(env_key)
    if env_val is not None:
        return env_val
    if config_data and config_key in config_data:
        return config_data[config_key]
    return default


def load_config(args, config_file_data: Optional[Dict[str, Any]] = None) -> AppConfig:
    """
    加载配置，合并 CLI 参数、环境变量、配置文件和默认值。

    优先级：CLI 参数 > 环境变量 > 配置文件 > 默认值

    Args:
        args: 命令行参数对象（来自 argparse）
        config_file_data: 从 YAML 配置文件解析的字典（可选）

    Returns:
        完整的配置对象

    Raises:
        ValueError: 当 push_url 未配置时
    """
    # --- 基础路径 ---
    watch_dir = _resolve(args.dir, "WXWATCHER_DIR", config_file_data, "watch_dir", None)
    if not watch_dir:
        watch_dir = os.getcwd()

    # 推送 URL 为必填项
    push_url = _resolve(args.push_url, "WXWATCHER_PUSH_URL", config_file_data, "push_url", None)
    if not push_url:
        raise ValueError(
            "推送地址未配置。请通过以下任一方式提供：\n"
            "  - CLI 参数：--push-url <URL>\n"
            "  - 环境变量：export WXWATCHER_PUSH_URL=<URL>"
        )

    push_token = _resolve(
        args.push_token if hasattr(args, "push_token") else None,
        "WXWATCHER_PUSH_TOKEN",
        config_file_data,
        "push_token",
        "0503",
    )

    to_user = _resolve(args.to_user, "WXWATCHER_TO_USER", config_file_data, "to_user", DEFAULT_TO_USER)

    # --- 数值型 ---
    interval = _resolve(args.interval, "WXWATCHER_INTERVAL", config_file_data, "poll_interval", DEFAULT_POLL_INTERVAL)
    interval = int(interval)

    max_batch = _resolve(args.max_batch, "WXWATCHER_MAX_BATCH", config_file_data, "max_batch", DEFAULT_MAX_BATCH)
    max_batch = int(max_batch)

    # --- 忽略规则：合并所有层 ---
    ignore_parts = list(IGNORE_PATTERNS)  # 从默认值开始
    # 配置文件层
    if config_file_data and "ignore" in config_file_data:
        cfg_ignore = config_file_data["ignore"]
        if isinstance(cfg_ignore, list):
            ignore_parts.extend(str(s).strip() for s in cfg_ignore if str(s).strip())
        elif isinstance(cfg_ignore, str):
            ignore_parts.extend(s.strip() for s in cfg_ignore.split(",") if s.strip())
    # 环境变量层
    ignore_env = os.environ.get("WXWATCHER_IGNORE", "")
    if ignore_env:
        ignore_parts.extend(s.strip() for s in ignore_env.split(",") if s.strip())
    # CLI 层
    if hasattr(args, "ignore") and args.ignore:
        ignore_parts.extend(s.strip() for s in args.ignore.split(",") if s.strip())
    ignore_patterns = set(ignore_parts)

    # --- 监控扩展名：合并所有层 ---
    ext_parts = set(MONITOR_EXTS)  # 从默认值开始
    # 配置文件层
    if config_file_data and "ext" in config_file_data:
        cfg_ext = config_file_data["ext"]
        if isinstance(cfg_ext, list):
            cfg_ext_items = [str(s).strip() for s in cfg_ext if str(s).strip()]
        else:
            cfg_ext_items = [s.strip() for s in str(cfg_ext).split(",") if s.strip()]
        ext_parts.update(s if s.startswith(".") else f".{s}" for s in cfg_ext_items)
    # 环境变量层
    ext_env = os.environ.get("WXWATCHER_EXT", "")
    if ext_env:
        ext_parts.update(s.strip() if s.strip().startswith(".") else f".{s.strip()}" for s in ext_env.split(",") if s.strip())
    # CLI 层
    ext_cli = args.ext if hasattr(args, "ext") and args.ext else ""
    if ext_cli:
        ext_parts.update(s.strip() if s.strip().startswith(".") else f".{s.strip()}" for s in ext_cli.split(",") if s.strip())
    monitor_exts = ext_parts

    # --- 日志文件 ---
    log_file = _resolve(args.log_file, "WXWATCHER_LOG_FILE", config_file_data, "log_file", None)
    if not log_file:
        log_dir = os.path.expanduser("~/.wxwatcher")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "file_watcher.log")

    # --- Knowly 上传地址 ---
    no_knowly = False
    if hasattr(args, "no-knowly") and args.no-knowly:
        no_knowly = True
    elif config_file_data and config_file_data.get("no-knowly"):
        no_knowly = True

    knowly_url = ""
    if no_knowly:
        knowly_url = ""
    else:
        knowly_url = _resolve(
            args.knowly_url if hasattr(args, "knowly_url") else None,
            "WXWATCHER_KNOWLY_URL",
            config_file_data,
            "knowly_url",
            ""
        )

    return AppConfig(
        watch_dir=os.path.abspath(watch_dir),
        poll_interval=interval,
        push_url=push_url,
        push_token=push_token,
        to_user=to_user,
        max_batch=max_batch,
        ignore_patterns=ignore_patterns,
        ignore_exts=IGNORE_EXTS.copy(),
        monitor_exts=monitor_exts,
        log_file=log_file,
        knowly_upload_url=knowly_url,
    )
