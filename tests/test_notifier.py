"""Unit tests for wxwatcher notifier module."""
import logging
import tempfile
from unittest import mock

from wxwatcher.notifier import send_wechat, upload_to_knowly


class TestSendWechat:
    def test_success(self):
        logger = logging.getLogger("test")
        with mock.patch("wxwatcher.notifier.httpx.post") as mock_post:
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"status": "success"}
            mock_resp.raise_for_status = mock.MagicMock()
            mock_post.return_value = mock_resp
            assert send_wechat("hello", "http://url", "@all", logger, token="0503") is True
            mock_post.assert_called_once()

    def test_non_success_response(self):
        logger = logging.getLogger("test")
        with mock.patch("wxwatcher.notifier.httpx.post") as mock_post:
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"status": "error"}
            mock_resp.raise_for_status = mock.MagicMock()
            mock_post.return_value = mock_resp
            assert send_wechat("hello", "http://url", "@all", logger, token="0503") is False

    def test_retry_on_exception(self):
        logger = logging.getLogger("test")
        with mock.patch("wxwatcher.notifier.httpx.post") as mock_post:
            mock_post.side_effect = Exception("connection error")
            with mock.patch("wxwatcher.notifier.time.sleep"):
                assert send_wechat("hello", "http://url", "@all", logger, token="0503", max_retries=3) is False
                assert mock_post.call_count == 3

    def test_retry_succeeds_on_second_attempt(self):
        logger = logging.getLogger("test")
        with mock.patch("wxwatcher.notifier.httpx.post") as mock_post:
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"status": "success"}
            mock_resp.raise_for_status = mock.MagicMock()
            mock_post.side_effect = [Exception("timeout"), mock_resp]
            with mock.patch("wxwatcher.notifier.time.sleep"):
                assert send_wechat("hello", "http://url", "@all", logger, token="0503", max_retries=3) is True
                assert mock_post.call_count == 2


class TestUploadToKnowly:
    def test_success(self):
        logger = logging.getLogger("test")
        with (
            tempfile.NamedTemporaryFile(suffix=".pdf") as tmp,
            mock.patch("wxwatcher.notifier.httpx.post") as mock_post,
        ):
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"path": "/remote/uploads/test.pdf"}
            mock_resp.raise_for_status = mock.MagicMock()
            mock_post.return_value = mock_resp

            result = upload_to_knowly(tmp.name, "http://upload.url", logger)
            assert result == "/remote/uploads/test.pdf"
            mock_post.assert_called_once()

    def test_non_standard_response(self):
        logger = logging.getLogger("test")
        with (
            tempfile.NamedTemporaryFile(suffix=".pdf") as tmp,
            mock.patch("wxwatcher.notifier.httpx.post") as mock_post,
            mock.patch("wxwatcher.notifier.time.sleep"),
        ):
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"status": "ok"}
            mock_resp.raise_for_status = mock.MagicMock()
            mock_post.return_value = mock_resp

            result = upload_to_knowly(tmp.name, "http://upload.url", logger, max_retries=3)
            assert result is None
            assert mock_post.call_count == 3

    def test_retry_on_exception(self):
        logger = logging.getLogger("test")
        with (
            tempfile.NamedTemporaryFile(suffix=".pdf") as tmp,
            mock.patch("wxwatcher.notifier.httpx.post") as mock_post,
            mock.patch("wxwatcher.notifier.time.sleep"),
        ):
            mock_post.side_effect = Exception("upload failed")

            result = upload_to_knowly(tmp.name, "http://upload.url", logger, max_retries=3)
            assert result is None
            assert mock_post.call_count == 3

    def test_retry_succeeds_on_second_attempt(self):
        logger = logging.getLogger("test")
        with (
            tempfile.NamedTemporaryFile(suffix=".pdf") as tmp,
            mock.patch("wxwatcher.notifier.httpx.post") as mock_post,
            mock.patch("wxwatcher.notifier.time.sleep"),
        ):
            success_resp = mock.MagicMock()
            success_resp.json.return_value = {"path": "/remote/uploads/test.pdf"}
            success_resp.raise_for_status = mock.MagicMock()
            mock_post.side_effect = [Exception("timeout"), success_resp]

            result = upload_to_knowly(tmp.name, "http://upload.url", logger, max_retries=3)
            assert result == "/remote/uploads/test.pdf"
            assert mock_post.call_count == 2
