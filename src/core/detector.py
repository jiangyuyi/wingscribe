import yaml
from ultralytics import YOLO
import logging
from pathlib import Path
import torch
import os

def _check_cuda_stable(max_retries: int = 3) -> bool:
    """
    Check if CUDA is actually stable and usable.
    Returns True if CUDA works, False otherwise.
    Uses retries to handle transient CUDA initialization issues.
    """
    if not torch.cuda.is_available():
        logging.info("torch.cuda.is_available() returned False")
        return False

    for attempt in range(max_retries):
        try:
            # Try a simple CUDA operation to verify it works
            test_tensor = torch.zeros(1, device='cuda')
            _ = test_tensor + 1
            # Also try a synchronization to ensure CUDA is fully initialized
            torch.cuda.synchronize()
            del test_tensor
            torch.cuda.empty_cache()
            logging.info(f"CUDA stability check passed (attempt {attempt + 1})")
            return True
        except Exception as e:
            logging.warning(f"CUDA stability check failed (attempt {attempt + 1}/{max_retries}): {e}")
            # Small delay before retry
            import time
            time.sleep(0.1)

    return False

class BirdDetector:
    def __init__(self, model_path: str, confidence: float = 0.5, device: str = "auto"):
        """
        Initialize the YOLO26 bird detector.
        Supports YOLOv8, YOLOv11, YOLO26 models via Ultralytics API.
        """
        self.confidence = confidence
        self.bird_class_id = 14  # COCO class for 'bird'
        self.model_path = model_path  # Store for reloading
        self.reload_count = 0  # Track reloads to avoid infinite loop
        self._model = None  # Lazy load

        # Determine device with careful checking
        if device == "auto":
            # Multiple checks to ensure CUDA stability
            if torch.cuda.is_available():
                logging.info("CUDA available, performing stability check...")
                if _check_cuda_stable():
                    self.device = "cuda"
                    logging.info("CUDA confirmed stable, using CUDA")
                else:
                    logging.warning("CUDA stability check failed after retries, using CPU")
                    self.device = "cpu"
            else:
                logging.info("CUDA not available, using CPU")
                self.device = "cpu"
        else:
            self.device = device

        # Final verification before loading model
        if self.device == "cuda" and not torch.cuda.is_available():
            logging.warning("CUDA became unavailable between check and model load, falling back to CPU")
            self.device = "cpu"

        logging.info(f"Device selected: {self.device}")
        # Model will be loaded lazily when first used

    def _load_model(self):
        """Load or reload the YOLO model."""
    @property
    def model(self):
        """Lazy load the model on first access."""
        if self._model is None:
            self._load_model()
        return self._model

    def _load_model(self):
        """Load or reload the YOLO model."""
        if not os.path.exists(self.model_path):
            logging.warning(f"YOLO model not found at {self.model_path}, downloading yolo26n.pt...")
            self._model = YOLO("yolo26n.pt")
        else:
            self._model = YOLO(self.model_path)
        logging.info(f"YOLO detector initialized on {self.device}")

    def detect(self, image_path: str):
        """
        Detect birds in the image.
        """
        # Ensure model is loaded before detection
        _ = self.model

        try:
            results = self.model.predict(
                source=image_path,
                conf=self.confidence,
                verbose=False,
                device=self.device
            )
        except Exception as e:
            error_str = str(e)
            # Handle model compatibility errors - reload model once
            if "Conv" in error_str and "bn" in error_str:
                if self.reload_count < 2:  # Limit reload attempts
                    self.reload_count += 1
                    self._load_model()
                    results = self.model.predict(
                        source=image_path,
                        conf=self.confidence,
                        verbose=False,
                        device=self.device
                    )
                else:
                    return []
            elif "CUDA" in error_str and self.device != "cpu":
                self.device = "cpu"
                results = self.model.predict(
                    source=image_path,
                    conf=self.confidence,
                    verbose=False,
                    device="cpu"
                )
            else:
                return []

        bird_boxes = []
        for result in results:
            for box in result.boxes:
                if int(box.cls) == self.bird_class_id:
                    # Convert to list of floats [x1, y1, x2, y2]
                    coords = box.xyxy[0].tolist()
                    score = float(box.conf[0])
                    bird_boxes.append((coords, score))

        return bird_boxes

if __name__ == "__main__":
    # Quick test if run directly
    detector = BirdDetector("yolo26n.pt")
    print("Detector initialized.")
