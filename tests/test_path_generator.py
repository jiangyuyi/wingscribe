"""
Unit tests for PathGenerator module.

Tests cover:
- Template path generation
- Source structure normalization
- Variable sanitization
- Date parsing
"""

import pytest
from pathlib import Path
from src.core.io.path_generator import PathGenerator


class TestPathGeneratorSanitize:
    """Test path sanitization."""

    def setup_method(self):
        self.generator = PathGenerator("{date}_{species_cn}", "/output")

    def test_sanitize_removes_illegal_chars(self):
        """Test that illegal characters are removed."""
        result = self.generator._sanitize("test<>file:name?test")
        assert '<' not in result
        assert '>' not in result
        assert ':' not in result
        assert '?' not in result

    def test_sanitize_preserves_valid_chars(self):
        """Test that valid characters are preserved."""
        result = self.generator._sanitize("北京_柳荫公园")
        assert "北京" in result
        assert "柳荫公园" in result

    def test_sanitize_replaces_with_underscore(self):
        """Test that illegal chars are replaced with underscore."""
        result = self.generator._sanitize("test|file*test")
        assert "|" not in result
        assert "*" not in result


class TestPathGeneratorNormalizeSourceStructure:
    """Test source structure normalization."""

    def test_no_normalization_needed(self):
        """Test when source structure is different from output root."""
        generator = PathGenerator("{date}_{species_cn}", "/output/clip")
        result = generator._normalize_source_structure("20260110北京")
        assert result == "20260110北京"

    def test_exact_match(self):
        """Test when source_structure exactly matches output folder name."""
        generator = PathGenerator("{date}_{species_cn}", "/output/clip")
        result = generator._normalize_source_structure("clip")
        assert result == "."

    def test_prefix_match(self):
        """Test when source_structure starts with output folder name."""
        generator = PathGenerator("{date}_{species_cn}", "/output/clip")
        result = generator._normalize_source_structure("clip/20260110北京")
        assert result == "20260110北京"

    def test_empty_source_structure(self):
        """Test with empty source structure."""
        generator = PathGenerator("{date}_{species_cn}", "/output/clip")
        result = generator._normalize_source_structure("")
        assert result == "."

    def test_dot_source_structure(self):
        """Test with dot source structure."""
        generator = PathGenerator("{date}_{species_cn}", "/output/clip")
        result = generator._normalize_source_structure(".")
        assert result == "."

    def test_root_output(self):
        """Test when output_root has no subfolder."""
        generator = PathGenerator("{date}_{species_cn}", "clip")
        result = generator._normalize_source_structure("clip/20260110北京")
        assert result == "clip/20260110北京"


class TestPathGeneratorGenerate:
    """Test path generation."""

    def test_basic_generation(self):
        """Test basic path generation."""
        generator = PathGenerator("{date}_{species_cn}", "/output")
        metadata = {
            "captured_date": "20260110",
            "location_tag": "北京",
            "primary_bird_cn": "白头鹎",
            "scientific_name": "Pycnonotus sinensis",
            "confidence_score": 0.95,
            "source_structure": "."
        }
        path = generator.generate_path(metadata, "test.jpg")
        assert "20260110_白头鹎" in str(path)

    def test_date_with_dashes(self):
        """Test date parsing with dashes."""
        generator = PathGenerator("{date}_{species_cn}", "/output")
        metadata = {
            "captured_date": "2026-01-10",
            "primary_bird_cn": "麻雀",
            "source_structure": "."
        }
        path = generator.generate_path(metadata, "test.jpg")
        assert "2026-01-10" in str(path)

    def test_source_structure_in_template(self):
        """Test using source_structure in template."""
        generator = PathGenerator("{source_structure}/{species_cn}", "/output")
        metadata = {
            "captured_date": "20260110",
            "location_tag": "北京",
            "primary_bird_cn": "白头鹎",
            "source_structure": "20260110_北京"
        }
        path = generator.generate_path(metadata, "test.jpg")
        path_str = str(path).replace('\\', '/')
        assert "20260110_北京/白头鹎" in path_str

    def test_confidence_format(self):
        """Test confidence score formatting."""
        generator = PathGenerator("{confidence}_{species_cn}", "/output")
        metadata = {
            "captured_date": "20260110",
            "primary_bird_cn": "麻雀",
            "confidence_score": 0.876,
            "source_structure": "."
        }
        path = generator.generate_path(metadata, "test.jpg")
        assert "87pct" in str(path)

    def test_year_month_day_variables(self):
        """Test year/month/day template variables."""
        generator = PathGenerator("{year}/{month}/{day}/{species_cn}", "/output")
        metadata = {
            "captured_date": "20260110",
            "primary_bird_cn": "麻雀",
            "source_structure": "."
        }
        path = generator.generate_path(metadata, "test.jpg")
        path_str = str(path).replace('\\', '/')
        assert "2026/01/10" in path_str

    def test_missing_metadata_defaults(self):
        """Test with missing metadata fields."""
        generator = PathGenerator("{date}_{species_cn}", "/output")
        metadata = {
            "captured_date": "20260110",
            "source_structure": "."
        }
        path = generator.generate_path(metadata, "test.jpg")
        assert "Unknown" in str(path)

    def test_invalid_date_fallback(self):
        """Test invalid date falls back to current date."""
        generator = PathGenerator("{date}_{species_cn}", "/output")
        metadata = {
            "captured_date": "invalid-date",
            "primary_bird_cn": "麻雀",
            "source_structure": "."
        }
        path = generator.generate_path(metadata, "test.jpg")
        # Should not raise exception, uses current date
        assert path is not None


class TestPathGeneratorIntegration:
    """Integration tests for path generator."""

    def test_real_world_scenario(self):
        """Test a realistic use case."""
        template = "{source_structure}/{species_cn}_{confidence}"
        generator = PathGenerator(template, "Y:/输出/2026")

        metadata = {
            "captured_date": "20260110",
            "location_tag": "北京柳荫公园",
            "primary_bird_cn": "白头鹎",
            "scientific_name": "Pycnonotus sinensis",
            "confidence_score": 0.95,
            "source_structure": "20260110_北京柳荫公园"
        }

        path = generator.generate_path(metadata, "IMG_1234.jpg")
        assert "白头鹎_95pct" in str(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
