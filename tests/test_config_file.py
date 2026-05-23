"""Unit tests for wxwatcher config_file module."""
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from wxwatcher.config_file import find_config_file, load_config_file


class TestFindConfigFile:
    def test_explicit_path(self):
        """--config flag takes precedence."""
        result = find_config_file("/explicit/config.yml")
        assert result == Path("/explicit/config.yml")

    def test_not_found(self):
        """Returns None when no config file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(Path, "cwd", return_value=Path(tmpdir)):
                with mock.patch.dict(os.environ, {"HOME": tmpdir}):
                    result = find_config_file()
                    # Should return None since no config files exist
                    assert result is None

    def test_dot_wxwatcher_yml_in_cwd(self):
        """Finds .wxwatcher.yml in current directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".wxwatcher.yml"
            config_path.write_text("push_url: http://test.com\n")
            with mock.patch.object(Path, "cwd", return_value=Path(tmpdir)):
                result = find_config_file()
                assert result == config_path

    def test_wxwatcher_yml_in_cwd(self):
        """Finds wxwatcher.yml in current directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "wxwatcher.yml"
            config_path.write_text("push_url: http://test.com\n")
            with mock.patch.object(Path, "cwd", return_value=Path(tmpdir)):
                result = find_config_file()
                assert result == config_path


class TestLoadConfigFile:
    def test_valid_yaml(self):
        """Parses valid YAML correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("push_url: http://test.com\npoll_interval: 15\n")
            f.flush()
            try:
                data = load_config_file(Path(f.name))
                assert data["push_url"] == "http://test.com"
                assert data["poll_interval"] == 15
            finally:
                os.unlink(f.name)

    def test_empty_yaml(self):
        """Empty YAML returns empty dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("# empty\n")
            f.flush()
            try:
                data = load_config_file(Path(f.name))
                assert data == {}
            finally:
                os.unlink(f.name)

    def test_yaml_with_list(self):
        """YAML with list values."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("ignore:\n  - dist\n  - build\n  - '*.log'\n")
            f.flush()
            try:
                data = load_config_file(Path(f.name))
                assert data["ignore"] == ["dist", "build", "*.log"]
            finally:
                os.unlink(f.name)

    def test_invalid_type_raises(self):
        """Non-mapping YAML raises ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("- item1\n- item2\n")
            f.flush()
            try:
                with pytest.raises(ValueError, match="must be a YAML mapping"):
                    load_config_file(Path(f.name))
            finally:
                os.unlink(f.name)
