"""Unit tests for wxwatcher notifier module."""
import logging
from unittest import mock

from wxwatcher.notifier import send_wechat


class TestSendWechat:
    def test_success(self):
        logger = logging.getLogger("test")
        with mock.patch("wxwatcher.notifier.httpx.post") as mock_post:
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"status": "success"}
            mock_resp.raise_for_status = mock.MagicMock()
            mock_post.return_value = mock_resp
            assert send_wechat("hello", "http://url", "@all", logger) is True
            mock_post.assert_called_once()

    def test_non_success_response(self):
        logger = logging.getLogger("test")
        with mock.patch("wxwatcher.notifier.httpx.post") as mock_post:
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"status": "error"}
            mock_resp.raise_for_status = mock.MagicMock()
            mock_post.return_value = mock_resp
            assert send_wechat("hello", "http://url", "@all", logger) is False

    def test_retry_on_exception(self):
        logger = logging.getLogger("test")
        with mock.patch("wxwatcher.notifier.httpx.post") as mock_post:
            mock_post.side_effect = Exception("connection error")
            with mock.patch("wxwatcher.notifier.time.sleep"):
                assert send_wechat("hello", "http://url", "@all", logger, max_retries=3) is False
                assert mock_post.call_count == 3

    def test_retry_succeeds_on_second_attempt(self):
        logger = logging.getLogger("test")
        with mock.patch("wxwatcher.notifier.httpx.post") as mock_post:
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"status": "success"}
            mock_resp.raise_for_status = mock.MagicMock()
            mock_post.side_effect = [Exception("timeout"), mock_resp]
            with mock.patch("wxwatcher.notifier.time.sleep"):
                assert send_wechat("hello", "http://url", "@all", logger, max_retries=3) is True
                assert mock_post.call_count == 2
