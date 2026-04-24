"""WeChat push notification with retry."""
import logging
import time

import httpx


def send_wechat(text: str, push_url: str, to_user: str, logger: logging.Logger, max_retries: int = 3) -> bool:
    """通过推送接口发送文本消息，带指数退避重试"""
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
        except Exception as e:
            logger.warning(f"推送异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    logger.error(f"推送最终失败，丢弃消息: {text[:50]}...")
    return False
