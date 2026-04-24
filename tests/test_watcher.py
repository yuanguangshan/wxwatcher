"""Unit tests for wxwatcher watcher module."""
import os
import tempfile
import time

from wxwatcher.watcher import (
    should_ignore,
    fmt_size,
    fmt_size_diff,
    scan_directory,
    fast_scan,
    detect_changes,
    sha256_file,
    save_state,
    load_state,
    _walk_files,
)


class TestShouldIgnore:
    def test_git_ignored(self):
        assert should_ignore(".git", "/proj/.git", {".git"}, set(), set()) is True

    def test_normal_file_not_ignored(self):
        assert should_ignore("hello.py", "/proj/hello.py", {".git"}, set(), set()) is False

    def test_pyc_ignored(self):
        assert should_ignore("mod.pyc", "/proj/mod.pyc", {".git"}, {".pyc"}, set()) is True

    def test_monitor_exts_filters(self):
        assert should_ignore("test.md", "/proj/test.md", set(), set(), {".py"}) is True
        assert should_ignore("test.py", "/proj/test.py", set(), set(), {".py"}) is False


class TestFmtSize:
    def test_bytes(self):
        assert fmt_size(512) == "512B"

    def test_kilobytes(self):
        assert fmt_size(1536) == "1.5KB"

    def test_megabytes(self):
        assert fmt_size(2 * 1024 * 1024) == "2.0MB"

    def test_diff_positive(self):
        assert fmt_size_diff(1024) == "+1.0KB"

    def test_diff_negative(self):
        assert fmt_size_diff(-512) == "-512B"

    def test_diff_zero(self):
        assert fmt_size_diff(0) == "0B"


class TestSha256File:
    def test_normal_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello")
            f.flush()
            result = sha256_file(f.name)
        os.unlink(f.name)
        assert len(result) == 64

    def test_large_file_marker(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 11 * 1024 * 1024)  # 11 MB
            f.flush()
            result = sha256_file(f.name, max_size=10 * 1024 * 1024)
        os.unlink(f.name)
        assert result.startswith("LARGE:")

    def test_nonexistent_file(self):
        assert sha256_file("/nonexistent/path") == ""


class TestDetectChanges:
    def _make_state(self, **kwargs):
        return {
            k: (v.get("mtime", 1000.0), v.get("size", 100), v.get("hash", "abc"))
            for k, v in kwargs.items()
        }

    def _make_fast_state(self, **kwargs):
        return {k: (v.get("mtime", 1000.0), v.get("size", 100)) for k, v in kwargs.items()}

    def test_new_file(self):
        old = {}
        fast = {"/tmp/new.txt": (2000.0, 50)}
        changes = detect_changes(old, fast, "/tmp")
        assert len(changes) == 1
        assert "[新增]" in changes[0]

    def test_deleted_file(self):
        old = {"/tmp/old.txt": (1000.0, 50, "abc")}
        fast = {}
        changes = detect_changes(old, fast, "/tmp")
        assert len(changes) == 1
        assert "[删除]" in changes[0]

    def test_modified_file(self):
        old = {"/tmp/f.txt": (1000.0, 100, "old_hash")}
        fast = {"/tmp/f.txt": (2000.0, 200)}
        # sha256_file will return "" for non-existent file, so it'll be detected as changed
        changes = detect_changes(old, fast, "/tmp")
        assert len(changes) == 1
        assert "[修改]" in changes[0]

    def test_no_change_same_mtime_size(self):
        old = {"/tmp/f.txt": (1000.0, 100, "abc")}
        fast = {"/tmp/f.txt": (1000.0, 100)}
        changes = detect_changes(old, fast, "/tmp")
        assert len(changes) == 0

    def test_does_not_mutate_old_state(self):
        old = {"/tmp/f.txt": (1000.0, 100, "abc")}
        fast = {"/tmp/f.txt": (2000.0, 100)}
        old_copy = dict(old)
        detect_changes(old, fast, "/tmp")
        assert old == old_copy  # old_state should NOT be mutated

    def test_full_detection_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # baseline scan
            state = scan_directory(tmpdir, {".git"}, {".pyc"}, set())
            assert len(state) == 0

            # create a file
            f1 = os.path.join(tmpdir, "a.txt")
            with open(f1, "w") as f:
                f.write("hello")
            time.sleep(0.1)

            fs = fast_scan(tmpdir, {".git"}, {".pyc"}, set())
            changes = detect_changes(state, fs, tmpdir)
            assert len(changes) == 1
            assert "[新增]" in changes[0]

            # sync state manually
            mtime, size = fs[f1]
            state[f1] = (mtime, size, sha256_file(f1))

            # modify the file
            time.sleep(0.1)
            with open(f1, "w") as f:
                f.write("hello world")
            time.sleep(0.1)

            fs2 = fast_scan(tmpdir, {".git"}, {".pyc"}, set())
            changes2 = detect_changes(state, fs2, tmpdir)
            assert len(changes2) == 1
            assert "[修改]" in changes2[0]

            # delete the file
            os.unlink(f1)
            fs3 = fast_scan(tmpdir, {".git"}, {".pyc"}, set())
            changes3 = detect_changes(state, fs3, tmpdir)
            assert len(changes3) == 1
            assert "[删除]" in changes3[0]


class TestWalkFiles:
    def test_walk_skips_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".git", "objects"))
            with open(os.path.join(tmpdir, ".git", "objects", "a"), "w") as f:
                f.write("x")
            with open(os.path.join(tmpdir, "hello.py"), "w") as f:
                f.write("print('hi')")
            results = list(_walk_files(tmpdir, {".git"}, {".pyc"}, set()))
            assert len(results) == 1
            assert results[0][0].endswith("hello.py")

    def test_walk_skips_pyc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "a.pyc"), "w") as f:
                f.write("x")
            with open(os.path.join(tmpdir, "a.py"), "w") as f:
                f.write("x")
            results = list(_walk_files(tmpdir, {".git"}, {".pyc"}, set()))
            assert len(results) == 1
            assert results[0][0].endswith("a.py")


class TestScanDirectory:
    def test_scan_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scan_directory(tmpdir, {".git"}, {".pyc"}, set())
            assert len(result) == 0

    def test_scan_with_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "test.txt")
            with open(fpath, "w") as f:
                f.write("hello")
            result = scan_directory(tmpdir, {".git"}, {".pyc"}, set())
            assert len(result) == 1
            assert fpath in result
            _, size, file_hash = result[fpath]
            assert size == 5
            assert len(file_hash) == 64

    def test_fast_scan_metadata_matches_scan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "test.txt")
            with open(fpath, "w") as f:
                f.write("hello world")
            full = scan_directory(tmpdir, {".git"}, {".pyc"}, set())
            fast = fast_scan(tmpdir, {".git"}, {".pyc"}, set())
            assert fpath in full and fpath in fast
            assert full[fpath][0] == fast[fpath][0]  # mtime matches
            assert full[fpath][1] == fast[fpath][1]  # size matches


class TestStatePersistence:
    def _patch_state_file(self, tmpdir):
        """Redirect STATE_FILE to a temp directory for test isolation."""
        import wxwatcher.watcher as wmod
        state_path = os.path.join(tmpdir, "state.json")
        original = wmod.STATE_FILE
        wmod.STATE_FILE = state_path
        return original, state_path

    def _restore_state_file(self, original):
        import wxwatcher.watcher as wmod
        wmod.STATE_FILE = original

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original, _ = self._patch_state_file(tmpdir)
            try:
                state = {
                    os.path.join(tmpdir, "a.txt"): (1000.0, 100, "abc123"),
                    os.path.join(tmpdir, "b.py"): (2000.0, 200, "def456"),
                }
                save_state(state, tmpdir)
                loaded, loaded_dir = load_state()
                assert loaded_dir == tmpdir
                assert loaded == {k: tuple(v) for k, v in state.items()}
            finally:
                self._restore_state_file(original)

    def test_load_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original, _ = self._patch_state_file(tmpdir)
            try:
                state, watch_dir = load_state()
                assert state == {}
                assert watch_dir is None
            finally:
                self._restore_state_file(original)

    def test_load_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original, state_path = self._patch_state_file(tmpdir)
            try:
                with open(state_path, "w") as f:
                    f.write("not json")
                state, watch_dir = load_state()
                assert state == {}
                assert watch_dir is None
            finally:
                self._restore_state_file(original)

    def test_persisted_state_matches_watch_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original, _ = self._patch_state_file(tmpdir)
            try:
                state = {"/some/file": (1.0, 2, "hash")}
                save_state(state, "/original/dir")
                loaded, loaded_dir = load_state()
                assert loaded_dir == "/original/dir"
                assert loaded != {}
            finally:
                self._restore_state_file(original)
