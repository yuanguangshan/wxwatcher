"""CLI entry point for wxwatcher."""
import argparse
import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler

import httpx

from . import __version__
from .config import load_config
from .watcher import scan_directory, fast_scan, detect_changes, sha256_file, save_state, load_state
from .notifier import send_wechat


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wxwatcher",
        description="文件变更监控工具，检测到变化时通过微信推送通知",
    )
    parser.add_argument("dir", nargs="?", default=None, help="监控目录（默认当前目录）")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-i", "--interval", type=int, default=None, help=f"轮询间隔（秒，默认 30）")
    parser.add_argument("--push-url", default=None, help="推送 API 地址")
    parser.add_argument("--to-user", default=None, help="接收人（默认 @all）")
    parser.add_argument("--max-batch", type=int, default=None, help=f"单批最大变更数（默认 50）")
    parser.add_argument("--ext", default=None, help="仅监控指定扩展名（逗号分隔，如 py,md）")
    parser.add_argument("--log-file", default=None, help="日志文件路径")
    return parser


def setup_logging(log_file: str) -> logging.Logger:
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("wxwatcher")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def format_startup_msg(watch_dir: str, file_count: int) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    return (
        f"📂 文件监控已启动\n"
        f"{'─' * 10}\n"
        f"监控目录: {os.path.basename(watch_dir)}\n"
        f"文件数量: {file_count}\n"
        f"启动时间: {now}\n"
        f"{'─' * 10}\n"
        f"By: 苑广山的文件监控助手"
    )


def format_change_msg(changes: list[str], now: str, batch_idx: int, total_batches: int, total_changes: int) -> str:
    header = f"📝 文件变更  {now}"
    text = header + "\n" + f"{'─' * 10}\n" + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(changes))
    if total_batches > 1:
        text += f"\n{'─' * 10}\n共检测到 {total_changes} 项变更（第 {batch_idx + 1}/{total_batches} 批）"
    text += f"\n{'─' * 10}\nBy: 苑广山的文件监控助手"
    return text


def main():
    parser = build_parser()
    args = parser.parse_args()
    cfg = load_config(args)

    logger = setup_logging(cfg.log_file)
    watch_dir = cfg.watch_dir

    if not os.path.isdir(watch_dir):
        logger.error(f"错误: '{watch_dir}' 不是有效目录")
        sys.exit(1)

    logger.info(f"监控目录: {watch_dir}")
    logger.info(f"轮询间隔: {cfg.poll_interval}秒")
    logger.info(f"推送地址: {cfg.push_url}")

    # 尝试加载持久化状态
    saved_state, saved_dir = load_state()
    if saved_dir == watch_dir and saved_state:
        state = saved_state
        logger.info(f"已加载持久化状态，共 {len(state)} 个文件")
    else:
        logger.info("开始扫描基线...")
        state = scan_directory(watch_dir, cfg.ignore_patterns, cfg.ignore_exts, cfg.monitor_exts)
        logger.info(f"基线已建立，共 {len(state)} 个文件")

    startup_msg = format_startup_msg(watch_dir, len(state))
    ok = send_wechat(startup_msg, cfg.push_url, cfg.to_user, logger)
    logger.info(f"{'[OK]' if ok else '[FAIL]'} 启动消息推送")

    last_heartbeat = time.time()

    try:
        while True:
            try:
                time.sleep(cfg.poll_interval)
                fast_state = fast_scan(watch_dir, cfg.ignore_patterns, cfg.ignore_exts, cfg.monitor_exts)
                changes = detect_changes(state, fast_state, watch_dir)

                if changes:
                    now = datetime.now().strftime("%H:%M:%S")
                    # 同步状态（调用方负责）
                    fast_keys = set(fast_state.keys())
                    old_keys = set(state.keys())
                    for fpath in fast_keys - old_keys:
                        mtime, size = fast_state[fpath]
                        state[fpath] = (mtime, size, sha256_file(fpath))
                    for fpath in old_keys - fast_keys:
                        del state[fpath]
                    # 修改文件：更新哈希
                    for fpath in fast_keys & old_keys:
                        old_mtime, old_size, _ = state[fpath]
                        new_mtime, new_size = fast_state[fpath]
                        if old_mtime != new_mtime or old_size != new_size:
                            state[fpath] = (new_mtime, new_size, sha256_file(fpath))

                    batches = [changes[i:i + cfg.max_batch] for i in range(0, len(changes), cfg.max_batch)]
                    for idx, batch in enumerate(batches):
                        text = format_change_msg(batch, now, idx, len(batches), len(changes))
                        ok = send_wechat(text, cfg.push_url, cfg.to_user, logger)
                        logger.info(f"{'[OK]' if ok else '[FAIL]'} 推送变更批次 {idx + 1}，共 {len(batch)} 项")

                    save_state(state, watch_dir)
                    last_heartbeat = time.time()
                else:
                    if time.time() - last_heartbeat >= 600:
                        logger.info("无变更")
                        last_heartbeat = time.time()

            except (OSError, httpx.HTTPError) as e:
                logger.error(f"可恢复异常: {e}")
                time.sleep(cfg.poll_interval)
    except KeyboardInterrupt:
        logger.info("收到退出信号，保存状态...")
        save_state(state, watch_dir)
        logger.info("程序结束")


if __name__ == "__main__":
    main()
