"""
Unit tests for BirdDetector (YOLO26) module.

Tests cover:
- Model loading and initialization
- Device selection (CUDA/CPU)
- Detection functionality
- Error handling
"""

import sys
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from unittest.mock import patch, MagicMock

# Add src to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.detector import BirdDetector, _check_cuda_stable


class TestCudaStabilityCheck:
    """Test CUDA stability checking logic."""

    def test_cuda_not_available(self):
        """Test when CUDA is not available."""
        with patch('torch.cuda.is_available', return_value=False):
            result = _check_cuda_stable()
            assert result is False

    @patch('torch.cuda.is_available')
    def test_cuda_available_success(self, mock_is_available):
        """Test successful CUDA stability check."""
        mock_is_available.return_value = True
        with patch('torch.zeros') as mock_zeros:
            mock_tensor = MagicMock()
            mock_zeros.return_value = mock_tensor
            with patch('torch.cuda.synchronize'):
                result = _check_cuda_stable(max_retries=1)
                assert result is True

    @patch('torch.cuda.is_available')
    def test_cuda_available_failure(self, mock_is_available):
        """Test CUDA stability check failure after retries."""
        mock_is_available.return_value = True
        with patch('torch.zeros', side_effect=RuntimeError("CUDA error")):
            result = _check_cuda_stable(max_retries=2)
            assert result is False


class TestBirdDetector:
    """Test BirdDetector class."""

    def test_init_auto_device_cuda(self):
        """Test initialization with CUDA available."""
        with patch('torch.cuda.is_available', return_value=True):
            with patch('src.core.detector._check_cuda_stable', return_value=True):
                detector = BirdDetector("yolo26n.pt", device="auto")
                assert detector.device == "cuda"

    def test_init_auto_device_cpu(self):
        """Test initialization with CUDA not available."""
        with patch('torch.cuda.is_available', return_value=False):
            detector = BirdDetector("yolo26n.pt", device="auto")
            assert detector.device == "cpu"

    def test_init_explicit_cpu(self):
        """Test explicit CPU device setting."""
        detector = BirdDetector("yolo26n.pt", device="cpu")
        assert detector.device == "cpu"

    def test_init_explicit_cuda(self):
        """Test explicit CUDA device setting."""
        with patch('torch.cuda.is_available', return_value=True):
            detector = BirdDetector("yolo26n.pt", device="cuda")
            # May fallback to CPU if CUDA unstable, but constructor should accept the parameter
            assert detector.device in ["cuda", "cpu"]

    def test_init_default_values(self):
        """Test default parameter values."""
        with patch('torch.cuda.is_available', return_value=False):
            detector = BirdDetector("yolo26n.pt")
            assert detector.confidence == 0.5
            assert detector.bird_class_id == 14  # COCO bird class
            assert detector.model_path == "yolo26n.pt"

    def test_lazy_load_model(self):
        """Test that model is loaded lazily."""
        with patch('torch.cuda.is_available', return_value=False):
            detector = BirdDetector("yolo26n.pt")
            # Model should not be loaded yet
            assert detector._model is None
            # Accessing .model property should trigger load
            # Note: This will attempt to load YOLO model, which may download weights

    def test_lazy_load_model_is_thread_safe(self):
        """Concurrent first access should initialize the detector only once."""
        with patch('torch.cuda.is_available', return_value=False):
            detector = BirdDetector("yolo26n.pt")

        load_calls = []

        def fake_load_model():
            time.sleep(0.02)
            load_calls.append(True)
            detector._model = object()

        with patch.object(detector, '_load_model', side_effect=fake_load_model):
            with ThreadPoolExecutor(max_workers=4) as executor:
                models = list(executor.map(lambda _: detector.model, range(4)))

        assert len(load_calls) == 1
        assert len({id(model) for model in models}) == 1

    @patch('torch.cuda.is_available')
    def test_confidence_threshold(self, mock_is_available):
        """Test confidence threshold is stored correctly."""
        mock_is_available.return_value = False
        detector = BirdDetector("yolo26n.pt", confidence=0.7)
        assert detector.confidence == 0.7


class TestBirdDetectorIntegration:
    """Integration tests that require actual model loading."""

    @pytest.fixture
    def test_image(self):
        """Create a temporary test image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (640, 480), color=(100, 150, 200))
            img.save(f.name)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    @pytest.fixture
    def model_path(self):
        from pathlib import Path

        model = Path(__file__).resolve().parents[1] / "installer" / "models" / "yolo26n.pt"
        if not model.is_file():
            pytest.skip("Bundled YOLO weights unavailable; tests never download weights")
        return str(model)

    @pytest.mark.integration
    def test_detect_returns_list(self, test_image, model_path):
        """Test that detect returns a list (may be empty)."""
        # Use CPU to avoid CUDA issues in test environment
        detector = BirdDetector(model_path, device="cpu")
        result = detector.detect(test_image)
        assert isinstance(result, list)

    @pytest.mark.integration
    def test_detect_with_nonexistent_image(self, model_path):
        """An unreadable input must not be reported as a successful no-bird result."""
        detector = BirdDetector(model_path, device="cpu")
        with pytest.raises(FileNotFoundError):
            detector.detect("nonexistent_image.jpg")

    def test_bird_class_id(self):
        """Test that bird class ID is correct (COCO class 14)."""
        detector = BirdDetector("yolo26n.pt", device="cpu")
        assert detector.bird_class_id == 14


class TestDetectionFailureAndConcurrency:
    def test_unexpected_error_propagates(self):
        detector = BirdDetector('unused.pt', device='cpu')
        detector._model = MagicMock()
        detector._model.predict.side_effect = RuntimeError('decoder failed')
        with pytest.raises(RuntimeError, match='decoder failed'):
            detector.detect('input.jpg')

    def test_exhausted_reload_propagates(self):
        detector = BirdDetector('unused.pt', device='cpu')
        detector._model = MagicMock()
        detector.reload_count = 2
        detector._model.predict.side_effect = AttributeError("Conv has no attribute bn")
        with pytest.raises(AttributeError, match='bn'):
            detector.detect('input.jpg')

    def test_cuda_retry_failure_propagates(self):
        detector = BirdDetector('unused.pt', device='cpu')
        detector.device = 'cuda'
        detector._model = MagicMock()
        detector._model.predict.side_effect = [RuntimeError('CUDA failure'), RuntimeError('CPU failure')]
        with pytest.raises(RuntimeError, match='CPU failure'):
            detector.detect('input.jpg')
        assert detector._model.predict.call_args.kwargs['device'] == 'cpu'

    def test_parallel_calls_load_once_and_serialize_predictor(self):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor

        detector = BirdDetector('unused.pt', device='cpu')
        start = threading.Barrier(4)
        state_lock = threading.Lock()
        state = {'active': 0, 'peak': 0}

        def predict(**kwargs):
            with state_lock:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            try:
                time.sleep(0.02)  # Give competing callers time to enter an unsafe predictor.
                return []
            finally:
                with state_lock:
                    state['active'] -= 1

        model = MagicMock()
        model.predict.side_effect = predict

        def load():
            time.sleep(0.02)
            detector._model = model

        def run(index):
            start.wait(timeout=5)
            return detector.detect(f'{index}.jpg')

        with patch.object(detector, '_load_model', side_effect=load) as loader:
            with ThreadPoolExecutor(max_workers=4) as pool:
                assert list(pool.map(run, range(4))) == [[], [], [], []]
        assert loader.call_count == 1
        assert model.predict.call_count == 4
        assert state['peak'] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
