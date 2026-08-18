"""
Unit tests for QualityChecker module.

Tests cover:
- Blur score calculation
- Sharpness threshold detection
- Error handling
"""

import pytest
import tempfile
import os
from pathlib import Path
from PIL import Image
import numpy as np
import cv2

from src.core.quality import QualityChecker, QualityEvaluator


class TestQualityCheckerBlurScore:
    """Test blur score calculation."""

    @pytest.fixture
    def sharp_image(self):
        """Create a sharp test image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            # Create an image with clear edges (high contrast)
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            img[:50, :] = 0  # Black top half
            img[50:, :] = 255  # White bottom half - sharp edge
            cv2.imwrite(f.name, img)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    @pytest.fixture
    def blurry_image(self):
        """Create a blurry test image using Gaussian blur."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            # Create an image and apply Gaussian blur
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            img[:50, :] = 0
            img[50:, :] = 255
            # Apply heavy blur
            blurred = cv2.GaussianBlur(img, (21, 21), 0)
            cv2.imwrite(f.name, blurred)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    def test_calculate_blur_score_returns_float(self, sharp_image):
        """Test that blur score returns a float."""
        score = QualityChecker.calculate_blur_score(sharp_image)
        assert isinstance(score, float)

    def test_calculate_blur_score_sharp_image(self, sharp_image):
        """Test that sharp images have high blur scores."""
        score = QualityChecker.calculate_blur_score(sharp_image)
        assert score > 100  # Sharp images should have high variance

    def test_calculate_blur_score_blurry_image(self, blurry_image):
        """Test that blurry images have low blur scores."""
        score = QualityChecker.calculate_blur_score(blurry_image)
        assert score < 50  # Blurry images should have low variance

    def test_calculate_blur_score_nonexistent_file(self):
        """Test handling of non-existent file."""
        score = QualityChecker.calculate_blur_score("/nonexistent/image.jpg")
        assert score == 0.0

    def test_is_sharp_true(self, sharp_image):
        """Test is_sharp returns True for sharp image."""
        result = QualityChecker.is_sharp(sharp_image, threshold=80.0)
        assert result == True

    def test_is_sharp_false(self, blurry_image):
        """Test is_sharp returns False for blurry image."""
        result = QualityChecker.is_sharp(blurry_image, threshold=80.0)
        assert result == False

    def test_is_sharp_custom_threshold(self, sharp_image):
        """Test is_sharp with custom threshold."""
        # Very high threshold should fail even for sharp image
        result = QualityChecker.is_sharp(sharp_image, threshold=10000.0)
        assert result == False


class TestQualityCheckerEdgeCases:
    """Test edge cases."""

    def test_calculate_blur_score_grayscale_image(self):
        """Test with grayscale image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = np.zeros((100, 100), dtype=np.uint8)
            img[:50, :] = 0
            img[50:, :] = 255
            cv2.imwrite(f.name, img)
            score = QualityChecker.calculate_blur_score(f.name)
            assert isinstance(score, float)
            assert score > 0
        if os.path.exists(f.name):
            os.remove(f.name)

    def test_calculate_blur_score_small_image(self):
        """Test with very small image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            cv2.imwrite(f.name, img)
            score = QualityChecker.calculate_blur_score(f.name)
            assert isinstance(score, float)
        if os.path.exists(f.name):
            os.remove(f.name)


class TestQualityEvaluator:
    @pytest.fixture
    def evaluator_sharp_image(self, tmp_path: Path):
        path = tmp_path / "sharp.jpg"
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[:50, :] = 0
        image[50:, :] = 255
        cv2.imwrite(str(path), image)
        return str(path)

    @pytest.fixture
    def evaluator_blurry_image(self, tmp_path: Path):
        path = tmp_path / "blurry.jpg"
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[50:, :] = 255
        cv2.imwrite(str(path), cv2.GaussianBlur(image, (21, 21), 0))
        return str(path)

    def test_evaluate_combines_image_metrics(self, evaluator_sharp_image):
        result = QualityEvaluator.evaluate(
            evaluator_sharp_image,
            detector_confidence=0.8,
            bird_pixel_ratio=0.1,
        )

        assert result.valid is True
        assert 0.0 <= result.quality_score <= 1.0
        assert result.laplacian_variance > 0
        assert result.tenengrad > 0
        assert result.detector_confidence == pytest.approx(0.8)
        assert result.bird_pixel_ratio == pytest.approx(0.1)

    def test_sharp_image_scores_higher_than_blurry_image(
        self,
        evaluator_sharp_image,
        evaluator_blurry_image,
    ):
        sharp = QualityEvaluator.evaluate(evaluator_sharp_image)
        blurry = QualityEvaluator.evaluate(evaluator_blurry_image)

        assert sharp.quality_score > blurry.quality_score
        assert sharp.tenengrad > blurry.tenengrad

    def test_extreme_exposure_reduces_score(self, evaluator_sharp_image, tmp_path: Path):
        white_path = tmp_path / "white.jpg"
        cv2.imwrite(str(white_path), np.full((100, 100, 3), 255, dtype=np.uint8))

        balanced = QualityEvaluator.evaluate(evaluator_sharp_image)
        overexposed = QualityEvaluator.evaluate(str(white_path))

        assert overexposed.overexposed_ratio > 0.99
        assert balanced.quality_score > overexposed.quality_score

    def test_detection_and_bird_size_contribute_to_score(self, evaluator_sharp_image):
        low = QualityEvaluator.evaluate(
            evaluator_sharp_image,
            detector_confidence=0.1,
            bird_pixel_ratio=0.001,
        )
        high = QualityEvaluator.evaluate(
            evaluator_sharp_image,
            detector_confidence=0.9,
            bird_pixel_ratio=0.1,
        )

        assert high.quality_score > low.quality_score

    def test_invalid_image_returns_structured_error(self, tmp_path: Path):
        result = QualityEvaluator.evaluate(str(tmp_path / "missing.jpg"))

        assert result.valid is False
        assert result.quality_score == 0.0
        assert result.error

    def test_result_is_serializable(self, evaluator_sharp_image):
        result = QualityEvaluator.evaluate(evaluator_sharp_image)

        assert result.to_dict()["quality_score"] == result.quality_score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
