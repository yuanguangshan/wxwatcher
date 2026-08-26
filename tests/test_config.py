"""Unit tests for wxwatcher config module."""
import os
import argparse
from unittest import mock

from wxwatcher.config import load_config, AppConfig


def _make_args(**overrides):
    defaults = dict(dir=None, push_url="http://example.com/push", push_token="test-token",
                    to_user=None, interval=None, max_batch=None, log_file=None, ext=None, ignore=None)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestLoadConfig:
    def test_defaults(self):
        cfg = load_config(_make_args())
        assert isinstance(cfg, AppConfig)
        assert cfg.poll_interval == 30
        assert cfg.max_batch == 50
        assert cfg.to_user == "@all"

    def test_cli_args_override(self):
        cfg = load_config(_make_args(dir="/tmp", interval=10, max_batch=20))
        assert cfg.watch_dir == "/tmp"
        assert cfg.poll_interval == 10
        assert cfg.max_batch == 20

    def test_env_vars_override(self):
        with mock.patch.dict(os.environ, {"WXWATCHER_INTERVAL": "5", "WXWATCHER_MAX_BATCH": "99"}):
            cfg = load_config(_make_args())
            assert cfg.poll_interval == 5
            assert cfg.max_batch == 99

    def test_cli_overrides_env(self):
        with mock.patch.dict(os.environ, {"WXWATCHER_INTERVAL": "5"}):
            cfg = load_config(_make_args(interval=15))
            assert cfg.poll_interval == 15

    def test_ignore_env(self):
        with mock.patch.dict(os.environ, {"WXWATCHER_IGNORE": "dist,build"}):
            cfg = load_config(_make_args())
            assert "dist" in cfg.ignore_patterns
            assert "build" in cfg.ignore_patterns

    def test_ext_env(self):
        with mock.patch.dict(os.environ, {"WXWATCHER_EXT": "py,md"}):
            cfg = load_config(_make_args())
            assert ".py" in cfg.monitor_exts
            assert ".md" in cfg.monitor_exts

    def test_ext_cli_arg(self):
        cfg = load_config(_make_args(ext="go,rs"))
        assert ".go" in cfg.monitor_exts
        assert ".rs" in cfg.monitor_exts

    def test_watch_dir_defaults_to_cwd(self):
        cfg = load_config(_make_args())
        assert cfg.watch_dir == os.path.abspath(os.getcwd())

    def test_ignore_cli_arg(self):
        cfg = load_config(_make_args(ignore="dist,build"))
        assert "dist" in cfg.ignore_patterns
        assert "build" in cfg.ignore_patterns

    def test_ignore_cli_merges_with_env(self):
        with mock.patch.dict(os.environ, {"WXWATCHER_IGNORE": "vendor"}):
            cfg = load_config(_make_args(ignore="dist"))
            assert "vendor" in cfg.ignore_patterns
            assert "dist" in cfg.ignore_patterns

    def test_config_file_poll_interval(self):
        """Config file value used when CLI/env not set."""
        cfg = load_config(_make_args(), config_file_data={"poll_interval": 60})
        assert cfg.poll_interval == 60

    def test_cli_overrides_config_file(self):
        """CLI arg takes precedence over config file."""
        cfg = load_config(
            _make_args(interval=10),
            config_file_data={"poll_interval": 60}
        )
        assert cfg.poll_interval == 10

    def test_env_overrides_config_file(self):
        """Env var takes precedence over config file."""
        with mock.patch.dict(os.environ, {"WXWATCHER_INTERVAL": "5"}):
            cfg = load_config(_make_args(), config_file_data={"poll_interval": 60})
            assert cfg.poll_interval == 5

    def test_ignore_patterns_merged_across_layers(self):
        """Ignore patterns merged from defaults + config file + CLI."""
        cfg = load_config(
            _make_args(ignore="dist"),
            config_file_data={"ignore": ["*.log", "tmp"]}
        )
        assert "dist" in cfg.ignore_patterns
        assert "*.log" in cfg.ignore_patterns
        assert "tmp" in cfg.ignore_patterns
        # defaults still present
        assert ".git" in cfg.ignore_patterns

    def test_ext_merged_from_config_file(self):
        """Extensions merged from config file list."""
        cfg = load_config(
            _make_args(),
            config_file_data={"ext": ["py", ".md"]}
        )
        assert ".py" in cfg.monitor_exts
        assert ".md" in cfg.monitor_exts

    def test_push_url_from_config_file(self):
        """Push URL can come from config file."""
        cfg = load_config(
            _make_args(push_url=None),
            config_file_data={"push_url": "http://config.com/push"}
        )
        assert cfg.push_url == "http://config.com/push"

    def test_config_file_push_overridden_by_cli(self):
        """CLI push_url overrides config file."""
        cfg = load_config(
            _make_args(push_url="http://cli.com/push"),
            config_file_data={"push_url": "http://config.com/push"}
        )
        assert cfg.push_url == "http://cli.com/push"

    def test_dry_run_waives_push_credentials(self):
        """--dry-run 不推送，缺 push_url/push_token 也应可用（零配置试用）。"""
        cfg = load_config(_make_args(push_url=None, push_token=None, dry_run=True))
        assert cfg.dry_run is True
        assert cfg.push_url == ""
        assert cfg.push_token == ""

    def test_push_token_still_required_without_dry_run(self):
        import pytest
        with pytest.raises(ValueError):
            load_config(_make_args(push_token=None))

    def test_max_changes_default_and_overrides(self):
        cfg = load_config(_make_args())
        assert cfg.max_changes == 100
        cfg = load_config(_make_args(max_changes=20))
        assert cfg.max_changes == 20
        cfg = load_config(_make_args(), config_file_data={"max_changes": 7})
        assert cfg.max_changes == 7

    def test_ignore_ext_from_config_file(self):
        """ignore_ext 配置层与默认值合并，自动补点号并转小写。"""
        cfg = load_config(
            _make_args(),
            config_file_data={"ignore_ext": ["TMP", ".bak"]}
        )
        assert ".tmp" in cfg.ignore_exts
        assert ".bak" in cfg.ignore_exts
        assert ".pyc" in cfg.ignore_exts  # 默认值仍在

    def test_no_knowly_accepts_both_key_styles(self):
        """配置文件同时接受 no_knowly 与 no-knowly。"""
        cfg = load_config(_make_args(knowly_url="http://k/upload"),
                          config_file_data={"knowly_url": "http://k/upload", "no_knowly": True})
        assert cfg.knowly_upload_url == ""
        cfg = load_config(_make_args(),
                          config_file_data={"no-knowly": True})
        assert cfg.knowly_upload_url == ""

    def test_hostname_defaults_to_local_machine(self):
        """未指定时自动取本机主机名（非空）。"""
        from wxwatcher.config import detect_hostname
        cfg = load_config(_make_args())
        assert cfg.hostname == detect_hostname()
        assert cfg.hostname

    def test_hostname_cli_override(self):
        """--host-name 自定义别名优先于自动检测。"""
        cfg = load_config(_make_args(host_name="家里Mac"))
        assert cfg.hostname == "家里Mac"

    def test_hostname_env_and_config_layers(self):
        with mock.patch.dict(os.environ, {"WXWATCHER_HOST_NAME": "env-box"}):
            assert load_config(_make_args()).hostname == "env-box"
            # 配置文件被环境变量压住
            cfg = load_config(_make_args(), config_file_data={"host_name": "cfg-box"})
            assert cfg.hostname == "env-box"
        cfg = load_config(_make_args(), config_file_data={"host_name": "cfg-box"})
        assert cfg.hostname == "cfg-box"
