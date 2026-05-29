"""WeChat push notification with retry."""
import logging
import time

import httpx


def send_wechat(
    text: str,
    push_url: str,
    to_user: str,
    logger: logging.Logger,
    token: str,
    max_retries: int = 3,
) -> bool:
    """
    通过推送接口发送文本消息，带指数退避重试。

    Args:
        text: 消息文本内容
        push_url: 推送 API 地址
        to_user: 接收人标识
        logger: 日志记录器
        token: Bearer token
        max_retries: 最大重试次数，默认 3

    Returns:
        True 表示推送成功，False 表示失败
    """
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                push_url,
                json={"msgtype": "text", "content": text, "to_user": to_user},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return True
            logger.warning(f"推送返回失败: {data}")
        except Exception as e:
            logger.warning(f"推送异常 (尝试 {attempt + 1}/{max_retries}): {e}")

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    logger.error(f"推送最终失败，丢弃消息: {text[:50]}...")
    return False


def upload_to_knowly(
    file_path: str,
    upload_url: str,
    logger: logging.Logger,
    max_retries: int = 3
) -> str | None:
    """
    上传文件到 Knowly 服务器，带指数退避重试。

    Args:
        file_path: 本地文件路径
        upload_url: Knowly 上传 API 地址
        logger: 日志记录器
        max_retries: 最大重试次数，默认 3

    Returns:
        上传成功返回远程路径，失败返回 None
    """
    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as f:
                resp = httpx.post(
                    upload_url,
                    files={"file": f},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                if "path" in data:
                    return data["path"]
                logger.warning(f"Knowly 上传返回格式异常: {data}")
        except Exception as e:
            logger.warning(f"Knowly 上传异常 (尝试 {attempt + 1}/{max_retries}): {e}")

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    return None
