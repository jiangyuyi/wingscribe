"""
Unit tests for LocalProvider module.

Tests cover:
- Path validation
- Directory listing
- File operations
"""

import pytest
import tempfile
import os
from pathlib import Path
from src.core.io.local import LocalProvider


class TestLocalProvider:
    """Test LocalProvider class."""

    @pytest.fixture
    def temp_root(self):
        """Create a temporary root directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test structure
            root = Path(tmpdir)
            (root / "folder1").mkdir()
            (root / "folder1" / "file1.jpg").touch()
            (root / "folder2").mkdir()
            (root / "folder2" / "file2.jpg").touch()
            (root / "root_file.txt").touch()
            yield str(root)

    def test_init(self, temp_root):
        """Test provider initialization."""
        provider = LocalProvider(temp_root)
        assert provider.base_dir == Path(temp_root)

    def test_list_dir_non_recursive(self, temp_root):
        """Test non-recursive directory listing."""
        provider = LocalProvider(temp_root)
        # Use absolute path for listing
        entries = list(provider.list_dir(temp_root, recursive=False))
        names = [e.name for e in entries]
        assert "folder1" in names
        assert "folder2" in names
        assert "root_file.txt" in names

    def test_list_dir_recursive(self, temp_root):
        """Test recursive directory listing."""
        provider = LocalProvider(temp_root)
        entries = list(provider.list_dir(temp_root, recursive=True))
        names = [e.name for e in entries]
        assert "file1.jpg" in names
        assert "file2.jpg" in names
        assert "root_file.txt" in names

    def test_exists_true(self, temp_root):
        """Test exists returns True for existing path."""
        provider = LocalProvider(temp_root)
        folder_path = os.path.join(temp_root, "folder1")
        assert provider.exists(folder_path) is True
        file_path = os.path.join(temp_root, "folder1", "file1.jpg")
        assert provider.exists(file_path) is True

    def test_exists_false(self, temp_root):
        """Test exists returns False for non-existing path."""
        provider = LocalProvider(temp_root)
        assert provider.exists(os.path.join(temp_root, "nonexistent")) is False


class TestLocalProviderSecurity:
    """Test path security validation."""

    def test_path_traversal_blocked(self):
        """Test that path traversal is blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalProvider(tmpdir)
            # Try to escape the base directory using parent reference
            parent = os.path.dirname(tmpdir)
            with pytest.raises(Exception):  # Could be ValueError or SecurityViolationError
                list(provider.list_dir(parent, recursive=False))

    def test_absolute_path_blocked(self):
        """Test that absolute paths outside base_dir are blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalProvider(tmpdir)
            # This should fail because it's outside base_dir
            assert provider.exists("/etc/passwd") is False


class TestLocalProviderEdgeCases:
    """Test edge cases."""

    def test_list_empty_directory(self):
        """Test listing empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalProvider(tmpdir)
            entries = list(provider.list_dir(tmpdir, recursive=False))
            assert len(entries) == 0

    def test_get_local_path(self):
        """Test get_local_path returns path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalProvider(tmpdir)
            folder_path = os.path.join(tmpdir, "folder1")
            os.makedirs(folder_path)
            result = provider.get_local_path(folder_path)
            assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
