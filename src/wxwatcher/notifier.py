"""WeChat push notification."""
import httpx


def send_wechat(text: str, push_url: str, to_user: str, logger) -> bool:
    """通过推送接口发送文本消息"""
    try:
        resp = httpx.post(
            push_url,
            json={"msgtype": "text", "content": text, "to_user": to_user},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("status") == "success"
    except Exception as e:
        logger.warning(f"微信推送失败: {e}")
        return False
