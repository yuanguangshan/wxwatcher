"""CLI entry point for wxwatcher."""
from __future__ import annotations

import argparse
import errno
import logging
import os
import signal
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

import httpx

from . import __version__
from .config import load_config, UPLOAD_EXTS
from .config_file import find_config_file, load_config_file
from .watcher import scan_directory, fast_scan, detect_changes, save_state, load_state
from .notifier import send_wechat, upload_to_knowly


def cap_changes(changes: list[str], max_total: int = 100):
    """把变更列表截断到最多 max_total 条，避免单轮刷屏。

    返回 (截断后的清单, 被截掉的条数)。小于等于上限时不截断。
    """
    truncated = 0
    if len(changes) > max_total:
        truncated = len(changes) - max_total
        changes = changes[:max_total]
    return changes, truncated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wxwatcher",
        description="文件变更监控工具，检测到变化时通过微信推送通知",
    )
    parser.add_argument("dir", nargs="?", default=None, help="监控目录（默认当前目录）")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-i", "--interval", type=int, default=None, help=f"轮询间隔（秒，默认 30）")
    parser.add_argument("--push-url", default=None, help="推送 API 地址")
    parser.add_argument("--push-token", default=None, help="推送 Bearer token（必填）")
    parser.add_argument("--to-user", default=None, help="接收人（默认 @all）")
    parser.add_argument("--max-batch", type=int, default=None, help="单批最大变更数（默认 50）")
    parser.add_argument("--max-changes", type=int, default=None, help="单轮推送的最大变更条数，超出截断（默认 100）")
    parser.add_argument("--ext", default=None, help="仅监控指定扩展名（逗号分隔，如 py,md）")
    parser.add_argument("--ignore", default=None, help="忽略的目录/文件名（逗号分隔，如 dist,build）")
    parser.add_argument("--log-file", default=None, help="日志文件路径")
    parser.add_argument("--verbose", action="store_true", help="输出 DEBUG 级别日志")
    parser.add_argument("--quiet", action="store_true", help="仅输出 WARNING 及以上")
    parser.add_argument("--knowly-url", default=None, help="Knowly 上传 API 地址（需显式配置，默认不上传）")
    parser.add_argument("--no-knowly", action="store_true", help="禁用上传到 Knowly")
    parser.add_argument("--config", default=None, help="配置文件路径（默认自动搜索）")
    parser.add_argument("--no-config", action="store_true", help="跳过配置文件加载")
    parser.add_argument("--dry-run", action="store_true", help="只检测并打印变更，不推送、不写状态")
    parser.add_argument("--once", action="store_true", help="只跑一轮检测后退出（适合 cron / systemd timer）")
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
    """脱敏 URL，隐藏 query 参数和 userinfo 中的 token/secret。"""
    parsed = urlparse(url)
    if parsed.username:
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        parsed = parsed._replace(netloc=f"<hidden>@{netloc}")
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


def _init_watcher(args, config_file_data):
    """初始化并返回 (cfg, logger, state, watch_dir)。出错时直接 sys.exit。"""
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
        logger.info(f"Knowly 上传: {mask_url(cfg.knowly_upload_url)}")

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
    if cfg.dry_run:
        logger.info("[dry-run] 跳过启动消息推送")
    else:
        ok = send_wechat(startup_msg, cfg.push_url, cfg.to_user, logger, token=cfg.push_token)
        logger.info(f"{'[OK]' if ok else '[FAIL]'} 启动消息推送")

    return cfg, logger, state, watch_dir


def _main_loop(state, cfg, logger, watch_dir, once: bool = False):
    """主循环：轮询检测变更并推送通知。once=True 时只跑一轮后退出。"""
    last_heartbeat = time.time()
    consecutive_errors = 0
    max_consecutive_errors = 10

    try:
        while True:
            try:
                fast_state = fast_scan(watch_dir, cfg.ignore_patterns, cfg.ignore_exts, cfg.monitor_exts)
                changes, changed_files, state = detect_changes(state, fast_state, watch_dir)

                if changes and cfg.dry_run:
                    # dry-run：只打印变更，不推送、不写状态文件
                    for c in changes:
                        logger.info(f"[dry-run] {c}")
                    last_heartbeat = time.time()
                    consecutive_errors = 0  # 正常运行后重置错误计数
                elif changes:
                    # 上传可支持的文件到 Knowly
                    knowly_paths = []
                    if cfg.knowly_upload_url:
                        auth = (cfg.knowly_user, cfg.knowly_pass) if cfg.knowly_user and cfg.knowly_pass else None
                        for fpath in changed_files:
                            ext = os.path.splitext(fpath)[1].lower()
                            if ext in UPLOAD_EXTS:
                                uploaded_path = upload_to_knowly(fpath, cfg.knowly_upload_url, logger, auth=auth)
                                if uploaded_path:
                                    knowly_paths.append((os.path.relpath(fpath, watch_dir), uploaded_path))
                                else:
                                    logger.warning(f"Knowly 上传失败: {fpath}")

                    now = datetime.now().strftime("%H:%M:%S")
                    # ---- 封顶：单轮变更过多时只推前 N 条，避免微信刷屏 ----
                    changes, truncated = cap_changes(changes, max_total=cfg.max_changes)
                    if truncated:
                        logger.warning(f"变更过多，截断为前 {cfg.max_changes} 条（另有 {truncated} 条未显示）")
                    batches = [changes[i:i + cfg.max_batch] for i in range(0, len(changes), cfg.max_batch)]
                    for idx, batch in enumerate(batches):
                        text = format_change_msg(batch, now, idx, len(batches), len(changes), knowly_paths)
                        if truncated and idx == len(batches) - 1:
                            text = text.replace("By: 苑广山的文件监控助手",
                                                f"⚠️ 另有 {truncated} 条变更未显示\nBy: 苑广山的文件监控助手")
                        ok = send_wechat(text, cfg.push_url, cfg.to_user, logger, token=cfg.push_token)
                        logger.info(f"{'[OK]' if ok else '[FAIL]'} 推送变更批次 {idx + 1}，共 {len(batch)} 项")

                    save_state(state, watch_dir)
                    last_heartbeat = time.time()
                    consecutive_errors = 0  # 正常运行后重置错误计数
                else:
                    if time.time() - last_heartbeat >= 600:
                        logger.info("无变更")
                        last_heartbeat = time.time()

                if once:
                    # 单轮模式也要落盘状态，cron/timer 下次运行才能增量对比
                    if not cfg.dry_run:
                        save_state(state, watch_dir)
                    logger.info("单轮检测完成（--once），退出")
                    return
                # 轮询间隔放在迭代末尾，启动后立即做首轮检测
                time.sleep(cfg.poll_interval)

            except (OSError, PermissionError) as e:
                # 监控目录消失 → 致命错误，干净退出（不抛 traceback）
                if isinstance(e, OSError) and getattr(e, "errno", None) == errno.ENOENT:
                    save_state(state, watch_dir)
                    logger.critical(f"监控目录已不存在，退出: {e}")
                    sys.exit(1)
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"连续 {consecutive_errors} 次文件系统错误，退出监控")
                    raise
                time.sleep(cfg.poll_interval)
            except httpx.HTTPError as e:
                logger.warning(f"网络请求异常: {e}")
                # 网络错误不递增错误计数，可能只是瞬时中断
                time.sleep(cfg.poll_interval)
            except Exception as e:
                logger.error(f"未预期的异常: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"连续 {consecutive_errors} 次未知错误，退出监控")
                    raise
                time.sleep(cfg.poll_interval)
    except KeyboardInterrupt:
        logger.info("收到退出信号，保存状态...")
        save_state(state, watch_dir)
        logger.info("程序结束")


def _install_signal_handlers() -> None:
    """把 SIGTERM 转为 KeyboardInterrupt，让 systemd stop / kill 也走
    优雅退出路径（保存状态后再退出，避免重启后重建基线）。"""

    def _handle(signum, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, _handle)
    except (ValueError, OSError):
        pass  # 非主线程或平台不支持时保持默认行为


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

    _install_signal_handlers()
    cfg, logger, state, watch_dir = _init_watcher(args, config_file_data)
    _main_loop(state, cfg, logger, watch_dir, once=args.once)


if __name__ == "__main__":
    main()
