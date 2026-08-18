import cv2
import logging
from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class QualityResult:
    valid: bool
    quality_score: float
    laplacian_variance: float
    tenengrad: float
    contrast: float
    brightness: float
    underexposed_ratio: float
    overexposed_ratio: float
    detector_confidence: float | None = None
    bird_pixel_ratio: float | None = None
    error: str | None = None

    def to_dict(self):
        return asdict(self)


class QualityEvaluator:
    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @classmethod
    def evaluate(
        cls,
        image_path: str,
        *,
        detector_confidence: float | None = None,
        bird_pixel_ratio: float | None = None,
    ) -> QualityResult:
        try:
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Could not read image: {image_path}")

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            gradient_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            gradient_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            tenengrad = float(np.mean(gradient_x * gradient_x + gradient_y * gradient_y))
            contrast = float(gray.std() / 255.0)
            brightness = float(gray.mean() / 255.0)
            underexposed_ratio = float(np.mean(gray <= 5))
            overexposed_ratio = float(np.mean(gray >= 250))

            components = [
                (0.30, laplacian_variance / (laplacian_variance + 100.0)),
                (0.20, tenengrad / (tenengrad + 1000.0)),
                (0.15, cls._clamp(contrast / 0.25)),
                (0.15, 1.0 - cls._clamp(underexposed_ratio + overexposed_ratio)),
            ]
            if detector_confidence is not None:
                components.append((0.10, cls._clamp(detector_confidence)))
            if bird_pixel_ratio is not None:
                ratio = max(0.0, float(bird_pixel_ratio))
                components.append((0.10, cls._clamp(np.sqrt(ratio / 0.10))))

            weight_sum = sum(weight for weight, _ in components)
            quality_score = sum(weight * score for weight, score in components) / weight_sum
            return QualityResult(
                valid=True,
                quality_score=cls._clamp(quality_score),
                laplacian_variance=laplacian_variance,
                tenengrad=tenengrad,
                contrast=contrast,
                brightness=brightness,
                underexposed_ratio=underexposed_ratio,
                overexposed_ratio=overexposed_ratio,
                detector_confidence=(
                    cls._clamp(detector_confidence) if detector_confidence is not None else None
                ),
                bird_pixel_ratio=(max(0.0, float(bird_pixel_ratio)) if bird_pixel_ratio is not None else None),
            )
        except Exception as exc:
            logging.error(f"Error evaluating image quality: {exc}")
            return QualityResult(
                valid=False,
                quality_score=0.0,
                laplacian_variance=0.0,
                tenengrad=0.0,
                contrast=0.0,
                brightness=0.0,
                underexposed_ratio=0.0,
                overexposed_ratio=0.0,
                detector_confidence=detector_confidence,
                bird_pixel_ratio=bird_pixel_ratio,
                error=str(exc),
            )

class QualityChecker:
    @staticmethod
    def calculate_blur_score(image_path: str) -> float:
        """
        Calculate the sharpness score using the Variance of Laplacian method.
        Higher score means sharper image.
        """
        try:
            return QualityEvaluator.evaluate(image_path).laplacian_variance
        except Exception as e:
            logging.error(f"Error calculating blur score: {e}")
            return 0.0

    @staticmethod
    def is_sharp(image_path: str, threshold: float = 80.0) -> bool:
        """Check if the image is sharp enough based on a threshold."""
        score = QualityChecker.calculate_blur_score(image_path)
        return score >= threshold
