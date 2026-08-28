import os
import torch
import threading
from pathlib import Path
from PIL import Image
from .bioclip_base import BirdRecognizer
from .model_registry import get_model_spec
from typing import List, Dict, Any
import logging

# Lazy import open_clip - will be imported after environment variables are set
_open_clip = None


def _get_process_rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        pass

    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        return -1.0

def _get_open_clip():
    """Lazy load open_clip to ensure HF mirror env vars are set first."""
    global _open_clip
    if _open_clip is None:
        import open_clip as _oc
        _open_clip = _oc
    return _open_clip

def _check_cuda_stable(max_retries: int = 3) -> bool:
    """
    Check if CUDA is actually stable and usable.
    Returns True if CUDA works, False otherwise.
    Uses retries to handle transient CUDA initialization issues.
    """
    if not torch.cuda.is_available():
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
            return True
        except Exception as e:
            logging.warning(f"CUDA stability check failed (attempt {attempt + 1}/{max_retries}): {e}")
            # Small delay before retry
            import time
            time.sleep(0.1)

    return False

class LocalBirdRecognizer(BirdRecognizer):
    def __init__(self, model_name: str = "bioclip", device: str = None, hf_mirror: str = None):
        self._memory_profile_enabled = os.getenv("WINGSCRIBE_PROFILE_MEMORY") == "1"
        self._text_features_lock = threading.Lock()
        # Set HuggingFace mirror if provided
        if hf_mirror:
            os.environ['HF_ENDPOINT'] = hf_mirror
            os.environ['HF_HUB_URL'] = hf_mirror
            # Use the current Xet transfer switch when supported by huggingface_hub.
            os.environ['HF_XET_HIGH_PERFORMANCE'] = '1'
            logging.info(f"Using HuggingFace mirror: {hf_mirror}")

        if device is None or device == "auto":
            # First check basic availability
            if torch.cuda.is_available():
                # Then verify CUDA is actually stable
                if _check_cuda_stable():
                    self.device = "cuda"
                else:
                    logging.warning("CUDA available but not stable, falling back to CPU")
                    self.device = "cpu"
            else:
                self.device = "cpu"
        else:
            self.device = device

        self.model_spec = get_model_spec(model_name)
        self.model_id = self.model_spec.hub_model_id
        self.model_type_slug = self.model_spec.slug
        self.hf_mirror = hf_mirror  # Save for _load_model

        if self.model_spec.experimental:
            logging.warning(
                "%s is experimental and has substantially higher memory requirements; "
                "keep bioclip-2 as the production fallback",
                self.model_type_slug,
            )

        logging.info(f"Loading {model_name} ({self.model_id}) on {self.device}...")

        self.cached_labels = None
        self.cached_text_features = None

        try:
            self._load_model()
        except RuntimeError as e:
            if "CUDA" in str(e) and self.device != "cpu":
                logging.warning(f"CUDA initialization failed: {e}. Falling back to CPU.")
                self.device = "cpu"
                self._load_model()
            else:
                raise e

    def _log_memory(self, stage: str):
        if not getattr(self, "_memory_profile_enabled", False):
            return

        rss_mb = _get_process_rss_mb()
        logging.info(
            "[MemoryProfile][LocalBirdRecognizer][%s][thread=%s] rss=%.1fMB device=%s",
            stage,
            threading.current_thread().name,
            rss_mb,
            self.device,
        )

    def _resolve_hf_checkpoint(self, local_dir: Path) -> Path | None:
        """Materialize a Hub checkpoint locally, avoiding Windows cache symlinks."""
        if not self.model_id.startswith("hf-hub:"):
            return None

        from huggingface_hub import hf_hub_download

        repo_id = self.model_id[len("hf-hub:"):]
        errors = []
        for filename in ("open_clip_model.safetensors", "open_clip_pytorch_model.bin"):
            kwargs = {
                "repo_id": repo_id,
                "filename": filename,
                "local_dir": str(local_dir),
            }
            if getattr(self, "hf_mirror", None):
                kwargs["endpoint"] = self.hf_mirror

            try:
                checkpoint = Path(hf_hub_download(**kwargs))
                if not checkpoint.is_file() or checkpoint.stat().st_size <= 0:
                    raise OSError(f"Downloaded checkpoint is not a usable file: {checkpoint}")
                return checkpoint
            except Exception as exc:
                errors.append(f"{filename}: {exc}")

        raise OSError("; ".join(errors))

    def _load_model(self):
        import gc
        # Pre-emptive cleanup to avoid VRAM fragmentation causing spikes
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # Suppress verbose logging during model download
        import logging
        _verbose_loggers = []

        # Store and suppress root logger level
        root_logger = logging.getLogger()
        _verbose_loggers.append((None, root_logger.level))  # None marks root logger
        root_logger.setLevel(logging.WARNING)

        # Suppress open_clip factory logger
        logger = logging.getLogger('open_clip.factory')
        _verbose_loggers.append((logger, logger.level))
        logger.setLevel(logging.WARNING)

        # Also suppress httpx
        logger = logging.getLogger('httpx')
        _verbose_loggers.append((logger, logger.level))
        logger.setLevel(logging.WARNING)

        # Check for local model in specific subfolder
        local_model_root = Path("data/models")
        local_model_path = local_model_root / self.model_type_slug
        model_spec = getattr(self, "model_spec", None) or get_model_spec(self.model_type_slug)

        # RTX 4060/Laptop Fix: Use fp16 for CUDA to reduce bandwidth spike/power surge
        precision = 'fp16' if self.device == 'cuda' else 'fp32'

        # Try multiple parameter combinations for open_clip compatibility
        oc = _get_open_clip()

        # Strategy 1: Full parameters (newer open_clip versions)
        model_kwargs = {
            "precision": precision,
            "device": self.device
        }

        # Try local path first
        local_checkpoints = (
            local_model_path / "open_clip_model.safetensors",
            local_model_path / "open_clip_pytorch_model.bin",
        )
        ckpt_path = next((path for path in local_checkpoints if path.exists()), local_checkpoints[-1])
        use_local = ckpt_path.exists()

        if not use_local:
            try:
                cached_checkpoint = self._resolve_hf_checkpoint(local_model_path)
                if cached_checkpoint is not None:
                    ckpt_path = cached_checkpoint
                    use_local = True
                    logging.info(
                        f"Loading cached Hub checkpoint locally: {ckpt_path} "
                        f"(Precision: {precision})"
                    )
            except Exception as e:
                logging.warning(
                    "Could not resolve a local Hub checkpoint; falling back to open_clip HF loading: %s",
                    e,
                )

        try:
            try:
                if use_local:
                    logging.info(f"Loading from local checkpoint: {ckpt_path} (Precision: {precision})")
                    self.model, _, self.preprocess = oc.create_model_and_transforms(
                        model_spec.architecture,
                        pretrained=str(ckpt_path),
                        **model_kwargs
                    )
                else:
                    logging.info(f"Local checkpoint not found at {ckpt_path}, loading from Hub: {self.model_id}")
                    self.model, _, self.preprocess = oc.create_model_and_transforms(
                        self.model_id,
                        **model_kwargs
                    )
            except TypeError as e:
                error_msg = str(e)
                # Strategy 2: Remove device parameter (older versions)
                if 'device' in error_msg or 'unexpected keyword argument' in error_msg:
                    logging.warning(f"open_clip doesn't support 'device' param: {e}. Trying without device...")
                    model_kwargs.pop("device", None)
                    try:
                        if use_local:
                            self.model, _, self.preprocess = oc.create_model_and_transforms(
                                model_spec.architecture,
                                pretrained=str(ckpt_path),
                                **model_kwargs
                            )
                        else:
                            self.model, _, self.preprocess = oc.create_model_and_transforms(
                                self.model_id,
                                **model_kwargs
                            )
                        self.model.to(self.device)
                    except TypeError as e2:
                        # Strategy 3: Remove precision parameter as well
                        logging.warning(f"open_clip doesn't support 'precision' param: {e2}. Using fp32 default...")
                        model_kwargs.pop("precision", None)
                        self.model, _, self.preprocess = oc.create_model_and_transforms(
                            self.model_id if not use_local else model_spec.architecture,
                            pretrained=str(ckpt_path) if use_local else self.model_id
                        )
                        self.model.to(self.device)
                else:
                    raise e

            # Ensure tokenizer is ready
            tokenizer_id = model_spec.architecture if use_local else self.model_id
            self.tokenizer = _get_open_clip().get_tokenizer(tokenizer_id)
        finally:
            # Restore logging levels even if model loading fails midway
            for logger, level in _verbose_loggers:
                if logger is None:
                    # Restore root logger level
                    logging.getLogger().setLevel(level)
                else:
                    logger.setLevel(level)

        # Verify model device
        try:
            param_device = next(self.model.parameters()).device
            logging.info(f"Model loaded successfully. Model parameters are on: {param_device}")
            if self.device == 'cuda' and param_device.type == 'cpu':
                logging.warning("CRITICAL: Model requested on CUDA but parameters are on CPU!")
        except Exception as e:
            logging.warning(f"Could not verify model device: {e}")

        logging.info("Model loaded successfully.")
        self._log_memory("after_model_load")

    def _get_text_features(self, candidate_labels):
        # Check if cache is valid
        if self.cached_labels == candidate_labels and self.cached_text_features is not None:
            logging.debug("Text features cache hit.")
            return self.cached_text_features

        if not hasattr(self, "_text_features_lock"):
            self._text_features_lock = threading.Lock()

        with self._text_features_lock:
            if self.cached_labels == candidate_labels and self.cached_text_features is not None:
                logging.debug("Text features cache hit after lock acquisition.")
                return self.cached_text_features

            logging.info(f"Cache miss. Encoding {len(candidate_labels)} text labels (this may take a moment)...")
            self._log_memory(f"before_text_encode labels={len(candidate_labels)}")

            prompted_labels = [f"a photo of {label}, a type of bird." for label in candidate_labels]
            tokens = self.tokenizer(prompted_labels) # CPU tensor first

            # Batch processing to avoid OOM
            batch_size = 512 # Conservative batch size
            text_features_list = []

            device_type = 'cuda' if 'cuda' in self.device else 'cpu'

            with torch.no_grad(), torch.amp.autocast(device_type=device_type, enabled=(device_type == 'cuda')):
                for i in range(0, len(tokens), batch_size):
                    batch_tokens = tokens[i : i + batch_size].to(self.device)
                    batch_features = self.model.encode_text(batch_tokens)
                    # Normalize immediately to save memory and prep for cosine sim
                    batch_features /= batch_features.norm(dim=-1, keepdim=True)
                    text_features_list.append(batch_features)

            # Concatenate all features
            all_text_features = torch.cat(text_features_list, dim=0)

            # Update Cache
            self.cached_labels = candidate_labels
            self.cached_text_features = all_text_features
            logging.info("Text features encoded and cached.")
            self._log_memory(f"after_text_encode labels={len(candidate_labels)}")

            return all_text_features

    def predict_batch(self, image_paths: List[str], candidate_labels: List[str], top_k: int = 5) -> List[List[Dict[str, Any]]]:
        """
        Predict a batch of images.
        Returns a list of result lists (one result list per image).
        """
        if not candidate_labels:
            return [[] for _ in image_paths]
            
        try:
            return self._do_predict_batch(image_paths, candidate_labels, top_k)
        except RuntimeError as e:
            if "CUDA" in str(e) and self.device != "cpu":
                logging.warning(f"CUDA batch prediction failed: {e}. Falling back to CPU.")
                self._move_to_cpu()
                res = self._do_predict_batch(image_paths, candidate_labels, top_k)
                return res
            else:
                logging.error(f"Batch recognition error: {e}")
                return [[] for _ in image_paths]

    def _move_to_cpu(self):
        self.device = "cpu"
        self.model.to("cpu")
        self.cached_text_features = None

    def encode_images(self, image_paths: List[str]) -> torch.Tensor:
        """Encode a complete image batch into normalized embeddings."""
        try:
            features, _ = self._encode_image_paths(image_paths, skip_invalid=False)
            return features
        except RuntimeError as e:
            if "CUDA" in str(e) and self.device != "cpu":
                logging.warning(f"CUDA image encoding failed: {e}. Falling back to CPU.")
                self._move_to_cpu()
                features, _ = self._encode_image_paths(image_paths, skip_invalid=False)
                return features
            raise

    def _encode_image_paths(self, image_paths, *, skip_invalid):
        images_tensors = []
        valid_indices = []

        for idx, path in enumerate(image_paths):
            try:
                with Image.open(path) as img:
                    tensor = self.preprocess(img)
                images_tensors.append(tensor)
                valid_indices.append(idx)
            except Exception as e:
                if not skip_invalid:
                    raise ValueError(f"Failed to load image {path}: {e}") from e
                logging.error(f"Failed to load image for batch {path}: {e}")

        if not images_tensors:
            return torch.empty((0, 0), device=self.device), valid_indices

        self._log_memory(f"before_image_stack batch={len(images_tensors)}")
        image_input = torch.stack(images_tensors).to(self.device)
        self._log_memory(f"after_image_stack batch={len(images_tensors)}")

        device_type = 'cuda' if 'cuda' in self.device else 'cpu'
        with torch.no_grad(), torch.amp.autocast(device_type=device_type, enabled=(device_type == 'cuda')):
            image_features = self.model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)
        self._log_memory(f"after_batch_inference batch={len(images_tensors)}")
        return image_features, valid_indices

    def classify_embeddings(
        self,
        image_features: torch.Tensor,
        candidate_labels: List[str],
        top_k: int = 5,
    ) -> List[List[Dict[str, Any]]]:
        """Classify embeddings while preserving the existing softmax result format."""
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        logits = self.score_embeddings(image_features, candidate_labels)
        if logits.shape[1] == 0:
            return [[] for _ in range(logits.shape[0])]

        text_probs = logits.softmax(dim=-1)
        top_probs, top_indices = text_probs.topk(min(top_k, len(candidate_labels)), dim=1)
        batch_results = []
        for row_probs, row_indices in zip(top_probs, top_indices):
            batch_results.append([
                {
                    "scientific_name": candidate_labels[index.item()],
                    "confidence": probability.item(),
                }
                for probability, index in zip(row_probs, row_indices)
            ])
        return batch_results

    def score_embeddings(
        self,
        image_features: torch.Tensor,
        candidate_labels: List[str],
    ) -> torch.Tensor:
        """Return pre-softmax visual logits for every image and candidate label."""
        if image_features.ndim == 1:
            image_features = image_features.unsqueeze(0)
        if image_features.ndim != 2:
            raise ValueError("image_features must be a 1D or 2D tensor")
        if not candidate_labels:
            return torch.empty(
                (image_features.shape[0], 0),
                device=self.device,
                dtype=image_features.dtype,
            )
        if image_features.shape[0] == 0:
            return torch.empty(
                (0, len(candidate_labels)),
                device=self.device,
                dtype=image_features.dtype,
            )

        image_features = image_features.to(self.device)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        text_features = self._get_text_features(candidate_labels)

        device_type = 'cuda' if 'cuda' in self.device else 'cpu'
        with torch.no_grad(), torch.amp.autocast(device_type=device_type, enabled=(device_type == 'cuda')):
            return 100.0 * image_features @ text_features.T

    def _do_predict_batch(self, image_paths, candidate_labels, top_k):
        image_features, valid_indices = self._encode_image_paths(image_paths, skip_invalid=True)
        if not valid_indices:
            return [[] for _ in image_paths]

        valid_results = self.classify_embeddings(image_features, candidate_labels, top_k)
        batch_results = [[] for _ in image_paths]
        for original_idx, result in zip(valid_indices, valid_results):
            batch_results[original_idx] = result
        return batch_results

    def predict(self, image_path: str, candidate_labels: List[str], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Predict using zero-shot classification via OpenCLIP.
        """
        if not candidate_labels:
            logging.warning("No candidate labels provided.")
            return []

        try:
            return self._do_predict(image_path, candidate_labels, top_k)
        except RuntimeError as e:
            if "CUDA" in str(e) and self.device != "cpu":
                logging.warning(f"CUDA prediction failed: {e}. Falling back to CPU for this request.")
                self._move_to_cpu()
                res = self._do_predict(image_path, candidate_labels, top_k)
                return res
            else:
                logging.error(f"Recognition error: {e}")
                return []

    def _do_predict(self, image_path, candidate_labels, top_k):
        return self._do_predict_batch([image_path], candidate_labels, top_k)[0]

