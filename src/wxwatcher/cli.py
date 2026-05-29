"""CLI entry point for wxwatcher."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

from . import __version__
from .config import load_config, UPLOAD_EXTS
from .config_file import find_config_file, load_config_file
from .watcher import scan_directory, fast_scan, detect_changes, save_state, load_state
from .notifier import send_wechat, upload_to_knowly


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wxwatcher",
        description="文件变更监控工具，检测到变化时通过微信推送通知",
    )
    parser.add_argument("dir", nargs="?", default=None, help="监控目录（默认当前目录）")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-i", "--interval", type=int, default=None, help=f"轮询间隔（秒，默认 30）")
    parser.add_argument("--push-url", default=None, help="推送 API 地址")
    parser.add_argument("--push-token", default=None, help="推送 Bearer token（默认 0503）")
    parser.add_argument("--to-user", default=None, help="接收人（默认 @all）")
    parser.add_argument("--max-batch", type=int, default=None, help=f"单批最大变更数（默认 50）")
    parser.add_argument("--ext", default=None, help="仅监控指定扩展名（逗号分隔，如 py,md）")
    parser.add_argument("--ignore", default=None, help="忽略的目录/文件名（逗号分隔，如 dist,build）")
    parser.add_argument("--log-file", default=None, help="日志文件路径")
    parser.add_argument("--verbose", action="store_true", help="输出 DEBUG 级别日志")
    parser.add_argument("--quiet", action="store_true", help="仅输出 WARNING 及以上")
    parser.add_argument("--knowly-url", default=None, help="Knowly 上传 API 地址（需显式配置，默认不上传）")
    parser.add_argument("--no-knowly", action="store_true", help="禁用上传到 Knowly")
    parser.add_argument("--config", default=None, help="配置文件路径（默认自动搜索）")
    parser.add_argument("--no-config", action="store_true", help="跳过配置文件加载")
    return parser


def setup_logging(log_file: str, level: int = logging.INFO) -> logging.Logger:
    """
    配置日志处理器（避免重复添加）。

    Args:
        log_file: 日志文件路径
        level: 日志级别

    Returns:
        配置好的 Logger 实例
    """
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("wxwatcher")
    logger.setLevel(level)

    # 避免重复添加 handler
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.setLevel(level)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        stream_handler.setLevel(level)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)

    return logger


def mask_url(url: str) -> str:
    """脱敏 URL，隐藏 query 参数中的 token/secret。"""
    parsed = urlparse(url)
    if parsed.query:
        parsed = parsed._replace(query="<hidden>")
    return parsed.geturl()


def format_startup_msg(watch_dir: str, file_count: int) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    return (
        f"文件监控已启动\n"
        f"{'─' * 10}\n"
        f"监控目录: {os.path.basename(watch_dir)}\n"
        f"文件数量: {file_count}\n"
        f"启动时间: {now}\n"
        f"{'─' * 10}\n"
        f"By: 苑广山的文件监控助手"
    )


def format_change_msg(
    changes: list[str],
    now: str,
    batch_idx: int,
    total_batches: int,
    total_changes: int,
    knowly_paths: list[tuple[str, str]] | None = None
) -> str:
    header = f"文件变更  {now}"
    text = header + "\n" + f"{'─' * 10}\n" + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(changes))
    if total_batches > 1:
        text += f"\n{'─' * 10}\n共检测到 {total_changes} 项变更（第 {batch_idx + 1}/{total_batches} 批）"
    if knowly_paths:
        uploaded = "\n".join(f"  [{src} -> {dst}]" for src, dst in knowly_paths)
        text += f"\n{'─' * 10}\n已上传到 Knowly:\n{uploaded}"
    text += f"\n{'─' * 10}\nBy: 苑广山的文件监控助手"
    return text


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 加载配置文件（如存在）
    config_file_data = None
    if not args.no_config:
        config_path = find_config_file(args.config)
        if config_path:
            try:
                config_file_data = load_config_file(config_path)
            except ImportError as e:
                print(f"配置错误: {e}", file=sys.stderr)
                sys.exit(1)
            except ValueError as e:
                print(f"配置错误: {e}", file=sys.stderr)
                sys.exit(1)

    # 加载配置，合并 CLI 参数、环境变量、配置文件和默认值
    try:
        cfg = load_config(args, config_file_data)
    except ValueError as e:
        print(f"配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 参数校验
    if cfg.poll_interval < 1:
        print("配置错误: 轮询间隔不能小于 1 秒", file=sys.stderr)
        sys.exit(1)
    if cfg.max_batch < 1:
        print("配置错误: 单批最大变更数不能小于 1", file=sys.stderr)
        sys.exit(1)

    # 日志级别
    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO

    logger = setup_logging(cfg.log_file, log_level)
    watch_dir = cfg.watch_dir

    if not os.path.isdir(watch_dir):
        logger.error(f"错误: '{watch_dir}' 不是有效目录")
        sys.exit(1)

    logger.info(f"监控目录: {watch_dir}")
    logger.info(f"轮询间隔: {cfg.poll_interval}秒")
    logger.info(f"推送地址: {mask_url(cfg.push_url)}")
    if cfg.knowly_upload_url:
        logger.info(f"Knowly 上传: {cfg.knowly_upload_url}")

    # 尝试加载持久化状态（先按 watch_dir 查找，再回退到旧默认文件）
    saved_state, saved_dir = load_state(watch_dir)
    if not saved_state:
        saved_state, saved_dir = load_state()  # 兼容旧版 state.json
    if saved_dir == watch_dir and saved_state:
        state = saved_state
        logger.info(f"已加载持久化状态，共 {len(state)} 个文件")
    else:
        logger.info("开始扫描基线...")
        state = scan_directory(watch_dir, cfg.ignore_patterns, cfg.ignore_exts, cfg.monitor_exts)
        logger.info(f"基线已建立，共 {len(state)} 个文件")

    startup_msg = format_startup_msg(watch_dir, len(state))
    ok = send_wechat(startup_msg, cfg.push_url, cfg.to_user, logger, token=cfg.push_token)
    logger.info(f"{'[OK]' if ok else '[FAIL]'} 启动消息推送")

    last_heartbeat = time.time()

    try:
        while True:
            try:
                time.sleep(cfg.poll_interval)
                fast_state = fast_scan(watch_dir, cfg.ignore_patterns, cfg.ignore_exts, cfg.monitor_exts)
                changes, changed_files, state = detect_changes(state, fast_state, watch_dir)

                if changes:
                    # 上传可支持的文件到 Knowly
                    knowly_paths = []
                    if cfg.knowly_upload_url:
                        for fpath in changed_files:
                            ext = os.path.splitext(fpath)[1].lower()
                            if ext in UPLOAD_EXTS:
                                uploaded_path = upload_to_knowly(fpath, cfg.knowly_upload_url, logger)
                                if uploaded_path:
                                    knowly_paths.append((os.path.relpath(fpath, watch_dir), uploaded_path))
                                else:
                                    logger.warning(f"Knowly 上传失败: {fpath}")

                    now = datetime.now().strftime("%H:%M:%S")
                    batches = [changes[i:i + cfg.max_batch] for i in range(0, len(changes), cfg.max_batch)]
                    for idx, batch in enumerate(batches):
                        text = format_change_msg(batch, now, idx, len(batches), len(changes), knowly_paths)
                        ok = send_wechat(text, cfg.push_url, cfg.to_user, logger, token=cfg.push_token)
                        logger.info(f"{'[OK]' if ok else '[FAIL]'} 推送变更批次 {idx + 1}，共 {len(batch)} 项")

                    save_state(state, watch_dir)
                    last_heartbeat = time.time()
                else:
                    if time.time() - last_heartbeat >= 600:
                        logger.info("无变更")
                        last_heartbeat = time.time()

            except (OSError, IOError) as e:
                logger.error(f"可恢复异常: {e}")
                time.sleep(cfg.poll_interval)
    except KeyboardInterrupt:
        logger.info("收到退出信号，保存状态...")
        save_state(state, watch_dir)
        logger.info("程序结束")


if __name__ == "__main__":
    main()
