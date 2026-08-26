"""Unit tests for wxwatcher CLI module."""
from wxwatcher.cli import build_parser, mask_url, format_startup_msg, format_change_msg, cap_changes


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

    def test_once_and_dry_run_flags(self):
        parser = build_parser()
        args = parser.parse_args(["--once", "--dry-run"])
        assert args.once is True
        assert args.dry_run is True

    def test_max_changes(self):
        parser = build_parser()
        args = parser.parse_args(["--max-changes", "20"])
        assert args.max_changes == 20


class TestMaskUrl:
    def test_url_with_query(self):
        result = mask_url("https://example.com/api?token=secret123")
        assert "secret123" not in result
        assert "<hidden>" in result

    def test_url_without_query(self):
        result = mask_url("https://example.com/api/push")
        assert result == "https://example.com/api/push"

    def test_url_with_userinfo(self):
        result = mask_url("https://token123@example.com/api")
        assert "token123" not in result
        assert "<hidden>@" in result

    def test_url_with_userinfo_and_port(self):
        result = mask_url("https://user:pass@example.com:8080/api")
        assert "user" not in result
        assert "pass" not in result
        assert "<hidden>@example.com:8080" in result

    def test_url_with_userinfo_and_query(self):
        result = mask_url("https://token@example.com/api?key=abc")
        assert "token" not in result
        assert "abc" not in result
        assert "<hidden>" in result


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


class TestCapChanges:
    def test_below_limit_unchanged(self):
        changes = [f"[修改] f{i}.txt" for i in range(80)]
        out, truncated = cap_changes(changes, max_total=100)
        assert len(out) == 80
        assert truncated == 0

    def test_exact_limit_unchanged(self):
        changes = [f"[修改] f{i}.txt" for i in range(100)]
        out, truncated = cap_changes(changes, max_total=100)
        assert len(out) == 100
        assert truncated == 0

    def test_over_limit_truncated(self):
        changes = [f"[删除] f{i}.txt" for i in range(250)]
        out, truncated = cap_changes(changes, max_total=100)
        assert len(out) == 100
        assert truncated == 150

    def test_keeps_first_items(self):
        changes = [f"[增加] f{i}.txt" for i in range(120)]
        out, truncated = cap_changes(changes, max_total=100)
        assert out[0] == "[增加] f0.txt"
        assert truncated == 20
