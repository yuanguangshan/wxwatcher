"""Unit tests for wxwatcher config module."""
import os
import argparse
from unittest import mock

from wxwatcher.config import load_config, AppConfig


def _make_args(**overrides):
    defaults = dict(dir=None, push_url=None, to_user=None, interval=None,
                    max_batch=None, log_file=None, ext=None)
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
