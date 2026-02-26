import os
import torch
from pathlib import Path
from PIL import Image
from .bioclip_base import BirdRecognizer
from typing import List, Dict, Any
import logging

# Lazy import open_clip - will be imported after environment variables are set
_open_clip = None

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
        # Set HuggingFace mirror if provided
        if hf_mirror:
            import os
            os.environ['HF_ENDPOINT'] = hf_mirror
            os.environ['HF_HUB_URL'] = hf_mirror
            # Also try the newer HFTransfer method
            try:
                os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '1'
            except:
                pass
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

        # Map friendly names to HF model IDs
        model_map = {
            "bioclip": "hf-hub:imageomics/bioclip",
            "bioclip-2": "hf-hub:imageomics/bioclip-2"
        }

        self.model_id = model_map.get(model_name.lower(), model_map["bioclip"])
        self.model_type_slug = model_name.lower()
        self.hf_mirror = hf_mirror  # Save for _load_model

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
        ckpt_path = local_model_path / "open_clip_pytorch_model.bin"
        use_local = ckpt_path.exists()

        try:
            if use_local:
                logging.info(f"Loading from local checkpoint: {ckpt_path} (Precision: {precision})")
                self.model, _, self.preprocess = oc.create_model_and_transforms(
                    'ViT-B-16',
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
                            'ViT-B-16',
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
                        self.model_id if not use_local else 'ViT-B-16',
                        pretrained=str(ckpt_path) if use_local else self.model_id
                    )
                    self.model.to(self.device)
            else:
                raise e
        
        # Ensure tokenizer is ready
        self.tokenizer = _get_open_clip().get_tokenizer('ViT-B-16')

        # Restore logging levels
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

    def _get_text_features(self, candidate_labels):
        # Check if cache is valid
        if self.cached_labels == candidate_labels and self.cached_text_features is not None:
            logging.debug("Text features cache hit.")
            return self.cached_text_features

        logging.info(f"Cache miss. Encoding {len(candidate_labels)} text labels (this may take a moment)...")
        
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
                original_device = self.device
                self.device = "cpu"
                self.model.to("cpu")
                self.cached_text_features = None
                res = self._do_predict_batch(image_paths, candidate_labels, top_k)
                return res
            else:
                logging.error(f"Batch recognition error: {e}")
                return [[] for _ in image_paths]

    def _do_predict_batch(self, image_paths, candidate_labels, top_k):
        # 1. Prepare Images
        images_tensors = []
        valid_indices = []
        
        for idx, path in enumerate(image_paths):
            try:
                img = Image.open(path)
                tensor = self.preprocess(img)
                images_tensors.append(tensor)
                valid_indices.append(idx)
            except Exception as e:
                logging.error(f"Failed to load image for batch {path}: {e}")
        
        if not images_tensors:
            return [[] for _ in image_paths]
            
        # Stack: [B, C, H, W]
        image_input = torch.stack(images_tensors).to(self.device)
        
        # 2. Get Text Features (Cached)
        text_features = self._get_text_features(candidate_labels)
        
        # 3. Inference
        device_type = 'cuda' if 'cuda' in self.device else 'cpu'
        with torch.no_grad(), torch.amp.autocast(device_type=device_type, enabled=(device_type == 'cuda')):
            image_features = self.model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            
            # MatMul: [B, Dim] @ [Dim, N_Labels] -> [B, N_Labels]
            text_probs = (100.0 * image_features @ text_features.T).softmax(dim=-1)
            
        # 4. Process Results
        batch_results = [[] for _ in image_paths] # Default empty
        
        # Get Top K for the whole batch
        # topk returns values, indices with shape [B, K]
        top_probs, top_indices = text_probs.topk(min(top_k, len(candidate_labels)), dim=1)
        
        for i, original_idx in enumerate(valid_indices):
            res_list = []
            for k in range(top_probs.shape[1]):
                idx = top_indices[i, k].item()
                prob = top_probs[i, k].item()
                res_list.append({
                    "scientific_name": candidate_labels[idx],
                    "confidence": prob
                })
            batch_results[original_idx] = res_list
            
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
                # Temp fallback for this object
                original_device = self.device
                self.device = "cpu"
                self.model.to("cpu")
                # Clear cache as device changed
                self.cached_text_features = None
                res = self._do_predict(image_path, candidate_labels, top_k)
                # Restore device (optional, but safer to stay on CPU if CUDA is unstable)
                # self.device = original_device
                # self.model.to(original_device)
                return res
            else:
                logging.error(f"Recognition error: {e}")
                return []

    def _do_predict(self, image_path, candidate_labels, top_k):
        image = Image.open(image_path)
        image_input = self.preprocess(image).unsqueeze(0).to(self.device)
        
        # Get cached or new text features
        text_features = self._get_text_features(candidate_labels)

        # Use autocast to handle fp16/fp32 mismatches automatically
        # This is safer than manual casting for complex models like CLIP
        device_type = 'cuda' if 'cuda' in self.device else 'cpu'
        with torch.no_grad(), torch.amp.autocast(device_type=device_type, enabled=(device_type == 'cuda')):
            image_features = self.model.encode_image(image_input)
            
            # Ensure features are normalized for cosine similarity
            image_features /= image_features.norm(dim=-1, keepdim=True)
            # Text features are already normalized in _get_text_features

            text_probs = (100.0 * image_features @ text_features.T).softmax(dim=-1)

        # Get top K
        top_probs, top_indices = text_probs[0].topk(min(top_k, len(candidate_labels)))
        
        results = []
        for prob, idx in zip(top_probs, top_indices):
            results.append({
                "scientific_name": candidate_labels[idx.item()],
                "confidence": prob.item()
            })
        
        return results

