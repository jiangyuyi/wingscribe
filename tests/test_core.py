import sys
import os
import numpy as np
from PIL import Image
import cv2

# Add src to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.detector import BirdDetector
from src.core.quality import QualityChecker
from src.core.processor import ImageProcessor

def test_core_processing():
    print("--- Testing Core Processing ---")
    
    # Create a dummy image
    test_img_path = "tests/test_bird.jpg"
    img = Image.new('RGB', (1000, 1000), color=(73, 109, 137))
    img.save(test_img_path)
    
    print("Testing QualityChecker...")
    score = QualityChecker.calculate_blur_score(test_img_path)
    print(f"Blur Score: {score}")
    assert isinstance(score, float)
    
    print("Testing BirdDetector (Initialization only)...")
    # We won't run full detection because it downloads weights
    detector = BirdDetector("yolo26n.pt")
    assert detector is not None
    
    print("Testing ImageProcessor...")
    output_path = "tests/test_cropped.jpg"
    box = [100, 100, 500, 500]
    success = ImageProcessor.crop_and_resize(test_img_path, box, output_path, target_size=640)
    assert success is True
    assert os.path.exists(output_path)
    
    # Cleanup
    if os.path.exists(test_img_path): os.remove(test_img_path)
    if os.path.exists(output_path): os.remove(output_path)
    
    print("--- Core Processing Test Passed (Logic Check) ---")

if __name__ == "__main__":
    test_core_processing()
