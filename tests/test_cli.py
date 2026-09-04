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

    def test_hostname_line(self):
        msg = format_startup_msg("/tmp/myproject", 42, hostname="ygs-mac")
        assert "运行主机: ygs-mac" in msg

    def test_hostname_omitted_when_empty(self):
        msg = format_startup_msg("/tmp/myproject", 42, hostname="")
        assert "运行主机" not in msg


class TestFormatChangeMsg:
    def test_single_change(self):
        msg = format_change_msg(["[修改] a.txt (+10B)"], "12:00:00", 0, 1, 1)
        assert "a.txt" in msg
        assert "12:00:00" in msg

    def test_multi_batch(self):
        msg = format_change_msg(["[修改] a.txt"], "12:00:00", 0, 3, 100)
        assert "第 1/3 批" in msg
        assert "100 项" in msg

    def test_hostname_in_header(self):
        """多机场景：变更通知头部直接带来源主机，不展开即可区分。"""
        msg = format_change_msg(["[修改] a.txt"], "12:00:00", 0, 1, 1, hostname="nas")
        assert "文件变更  12:00:00 @nas" in msg

    def test_no_hostname_no_at(self):
        msg = format_change_msg(["[修改] a.txt"], "12:00:00", 0, 1, 1)
        assert "@" not in msg


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


class TestMainLoopMissingDir:
    """回归测试：监控目录消失时不得误报全部文件删除（P0 修复）。"""

    def _make_state(self, tmp_path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        (watch_dir / "a.txt").write_text("hello")
        from wxwatcher.watcher import scan_directory

        state = scan_directory(str(watch_dir), set(), set(), set())
        assert len(state) == 1
        return str(watch_dir), state

    def _make_cfg(self, tmp_path):
        from wxwatcher.config import AppConfig

        return AppConfig(
            watch_dir=str(tmp_path / "watch"),
            poll_interval=0,
            dry_run=True,
        )

    def test_once_mode_skips_when_dir_missing(self, tmp_path, caplog):
        """目录消失时 once 模式应直接跳过退出，状态保持不变。"""
        import logging

        from wxwatcher.cli import _main_loop

        watch_dir, state = self._make_state(tmp_path)
        cfg = self._make_cfg(tmp_path)
        import shutil

        shutil.rmtree(watch_dir)
        with caplog.at_level(logging.WARNING):
            _main_loop(state, cfg, logging.getLogger("test"), watch_dir, once=True)
        assert any("跳过本轮" in r.message for r in caplog.records)
        # 状态未被清空（基线还在）
        assert len(state) == 1

    def test_dir_restored_no_false_delete(self, tmp_path, caplog):
        """目录短暂消失后恢复，不应产生任何删除告警。"""
        import logging
        import shutil

        from wxwatcher.cli import _main_loop

        watch_dir, state = self._make_state(tmp_path)
        cfg = self._make_cfg(tmp_path)
        shutil.rmtree(watch_dir)
        _main_loop(state, cfg, logging.getLogger("test"), watch_dir, once=True)
        # 恢复目录（文件内容不变）
        watch_dir_new = tmp_path / "watch"
        watch_dir_new.mkdir()
        (watch_dir_new / "a.txt").write_text("hello")
        changes, changed_files, new_state = _main_loop.__globals__["detect_changes"](
            state,
            _main_loop.__globals__["fast_scan"](str(watch_dir_new), set(), set(), set()),
            str(watch_dir_new),
        )
        assert changes == []
        assert len(new_state) == 1
