"""WeChat push notification with retry."""
import logging
import time

import httpx


def send_wechat(
    text: str,
    push_url: str,
    to_user: str,
    logger: logging.Logger,
    max_retries: int = 3
) -> bool:
    """
    通过推送接口发送文本消息，带指数退避重试。

    Args:
        text: 消息文本内容
        push_url: 推送 API 地址
        to_user: 接收人标识
        logger: 日志记录器
        max_retries: 最大重试次数，默认 3

    Returns:
        True 表示推送成功，False 表示失败
    """
    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                push_url,
                json={"msgtype": "text", "content": text, "to_user": to_user},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return True
            else:
                logger.warning(f"推送返回失败: {data}")
        except httpx.TimeoutException as e:
            logger.warning(f"推送超时 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        except httpx.HTTPStatusError as e:
            logger.warning(f"推送HTTP错误 {e.response.status_code} (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            logger.warning(f"推送异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    logger.error(f"推送最终失败，丢弃消息: {text[:50]}...")
    return False
