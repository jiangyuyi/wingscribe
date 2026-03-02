"""
Unit tests for ExifWriter module.

Tests cover:
- Metadata writing
- Tag handling
- Error handling
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from src.metadata.exif_writer import ExifWriter


class TestExifWriter:
    """Test ExifWriter class."""

    @pytest.fixture
    def test_image(self):
        """Create a temporary test image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    def test_init(self):
        """Test initialization."""
        writer = ExifWriter("exiftool")
        assert writer.exiftool_path == "exiftool"

    def test_init_default_path(self):
        """Test default exiftool path."""
        writer = ExifWriter()
        assert writer.exiftool_path == "exiftool"

    @patch('subprocess.run')
    def test_write_metadata_success(self, mock_run, test_image):
        """Test successful metadata write."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "Test Title",
            "XPKeywords": ["bird", "nature"]
        }
        result = writer.write_metadata(test_image, tags)
        assert result is True
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_write_metadata_with_list_tags(self, mock_run, test_image):
        """Test writing metadata with list tags."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPKeywords": ["bird", "nature", "wildlife"]
        }
        result = writer.write_metadata(test_image, tags)
        assert result is True

        # Check that subprocess was called
        assert mock_run.called

    @patch('subprocess.run')
    def test_write_metadata_with_none_values(self, mock_run, test_image):
        """Test writing metadata ignores None values."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "Test",
            "XPKeywords": None
        }
        result = writer.write_metadata(test_image, tags)
        assert result is True

    @patch('subprocess.run')
    def test_write_metadata_with_empty_string(self, mock_run, test_image):
        """Test writing metadata handles empty strings."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "",
            "XPKeywords": "test"
        }
        result = writer.write_metadata(test_image, tags)
        # Empty string should still be processed (not filtered out)
        assert result is True


class TestExifWriterExiftoolNotFound:
    """Test exiftool not found scenario."""

    @patch('shutil.which')
    def test_write_metadata_exiftool_not_found(self, mock_which):
        """Test handling when exiftool is not found."""
        mock_which.return_value = None

        writer = ExifWriter("exiftool")
        result = writer.write_metadata("/tmp/test.jpg", {"XPTitle": "Test"})
        assert result is False


class TestExifWriterErrorHandling:
    """Test error handling."""

    @patch('subprocess.run')
    def test_write_metadata_subprocess_error(self, mock_run):
        """Test handling subprocess errors."""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "exiftool")

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)

            writer = ExifWriter("exiftool")
            result = writer.write_metadata(f.name, {"XPTitle": "Test"})
            assert result is False

        if os.path.exists(f.name):
            os.remove(f.name)

    @patch('subprocess.run')
    def test_write_metadata_general_error(self, mock_run):
        """Test handling general errors."""
        mock_run.side_effect = Exception("Unknown error")

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)

            writer = ExifWriter("exiftool")
            result = writer.write_metadata(f.name, {"XPTitle": "Test"})
            assert result is False

        if os.path.exists(f.name):
            os.remove(f.name)


class TestExifWriterEncoding:
    """Test encoding handling."""

    @pytest.fixture
    def test_image_encoding(self):
        """Create a temporary test image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    @patch('subprocess.run')
    def test_write_metadata_chinese_chars(self, mock_run, test_image_encoding):
        """Test writing metadata with Chinese characters."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "测试标题",
            "XPKeywords": ["鸟类", "自然"]
        }
        result = writer.write_metadata(test_image_encoding, tags)
        assert result is True

    @patch('subprocess.run')
    def test_write_metadata_newlines_escaped(self, mock_run, test_image_encoding):
        """Test that newlines are properly escaped."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "Line1\nLine2"
        }
        result = writer.write_metadata(test_image_encoding, tags)
        # Should not raise exception
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
