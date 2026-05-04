"""Unit tests for wxwatcher CLI module."""
from wxwatcher.cli import build_parser, mask_url, format_startup_msg, format_change_msg


class TestBuildParser:
    def test_basic(self):
        parser = build_parser()
        args = parser.parse_args(["/tmp"])
        assert args.dir == "/tmp"

    def test_verbose_quiet(self):
        parser = build_parser()
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True
        args2 = parser.parse_args(["--quiet"])
        assert args2.quiet is True

    def test_ignore(self):
        parser = build_parser()
        args = parser.parse_args(["--ignore", "dist,build"])
        assert args.ignore == "dist,build"


class TestMaskUrl:
    def test_url_with_query(self):
        result = mask_url("https://example.com/api?token=secret123")
        assert "secret123" not in result
        assert "<hidden>" in result

    def test_url_without_query(self):
        result = mask_url("https://example.com/api/push")
        assert result == "https://example.com/api/push"


class TestFormatStartupMsg:
    def test_contains_key_fields(self):
        msg = format_startup_msg("/tmp/myproject", 42)
        assert "myproject" in msg
        assert "42" in msg
        assert "文件监控已启动" in msg


class TestFormatChangeMsg:
    def test_single_change(self):
        msg = format_change_msg(["[修改] a.txt (+10B)"], "12:00:00", 0, 1, 1)
        assert "a.txt" in msg
        assert "12:00:00" in msg

    def test_multi_batch(self):
        msg = format_change_msg(["[修改] a.txt"], "12:00:00", 0, 3, 100)
        assert "第 1/3 批" in msg
        assert "100 项" in msg
