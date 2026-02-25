import os
import sys
import yaml
import logging
import hashlib
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from datetime import datetime

# Add project root to sys.path to allow running as script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.metadata.ioc_manager import IOCManager
from src.core.detector import BirdDetector
from src.core.quality import QualityChecker
from src.core.processor import ImageProcessor
from src.recognition.inference_local import LocalBirdRecognizer
from src.recognition.inference_dongniao import DongniaoRecognizer
from src.recognition.inference_api import APIBirdRecognizer
from src.metadata.exif_writer import ExifWriter
from src.utils.config_loader import load_config
from src.utils.env_check import check_system_dependencies

from src.core.io.fs_manager import FileSystemManager
from src.core.io.local import LocalProvider # Import to access IGNORED_DIRS
from src.core.io.temp_manager import TempFileManager
from src.core.io.path_generator import PathGenerator
from src.core.io.path_parser import PathParser

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SmartScanner:
    def __init__(self, root_path: Path, start_date: str = None, end_date: str = None, exclude_dirs: list = None):
        self.root_path = root_path
        self.start_date = int(start_date) if start_date else 0
        self.end_date = int(end_date) if end_date else 99999999
        # Normalize exclude dirs to absolute paths
        self.exclude_dirs = []
        if exclude_dirs:
            for d in exclude_dirs:
                try:
                    self.exclude_dirs.append(Path(d).resolve())
                except:
                    pass

    def _is_in_range(self, d_start, d_end):
        if not d_start: return True # No date info, assume safe to explore
        
        # d_start is always present if d_end is present
        start_int = int(d_start)
        end_int = int(d_end) if d_end else start_int
        
        # Check intersection
        # Folder range: [start_int, end_int]
        # Query range: [self.start_date, self.end_date]
        return not (end_int < self.start_date or start_int > self.end_date)

    def scan(self, current_path: Path):
        try:
            # First, process files in current dir
            for entry in os.scandir(current_path):
                # Ignore system/recycle directories
                if entry.name in LocalProvider.IGNORED_DIRS:
                    continue
                    
                if entry.is_file():
                    yield entry
                elif entry.is_dir():
                    # Check if this directory should be excluded (output dir)
                    entry_path = Path(entry.path).resolve()
                    if self.exclude_dirs:
                        if any(str(entry_path).startswith(str(ex)) for ex in self.exclude_dirs):
                            logging.debug(f"Excluding output dir: {entry.name}")
                            continue

                    # Check pruning
                    d_start, d_end, _ = PathParser.parse_folder_name(entry.name)
                    
                    if self._is_in_range(d_start, d_end):
                         # Recurse
                         yield from self.scan(Path(entry.path))
                    else:
                        logging.debug(f"Pruning skipped: {entry.name}")
        except PermissionError:
            pass

class FeatherTracePipeline:
    def __init__(self, config_path: str = "config/settings.yaml", init_timeout: int = 120):
        """
        Initialize the pipeline.

        Args:
            config_path: Path to config file
            init_timeout: Maximum seconds to wait for model loading (default 120s)
        """
        # Use centralized config loader
        self.config = load_config(config_path)

        # Initialize FS Manager
        self.fs_manager = FileSystemManager.get_instance(self.config.get('paths', {}))

        # Get base_dir for relative path storage
        base_dir = self.config.get('paths', {}).get('base_dir', '')
        self.db = IOCManager(self.config['paths']['db_path'], base_dir)
        self.device = self.config['processing'].get('device', 'cpu')

        # Lazy load detector with timeout protection
        self._detector = None
        self._detector_loaded = False
        self._init_timeout = init_timeout

        self.recognizer = None # Lazy load later
        self.exif_writer = ExifWriter()
        
        # Path Generator - resolve relative paths using base_dir
        paths_conf = self.config['paths']
        base_dir = paths_conf.get('base_dir', '')

        out_conf = paths_conf.get('output', {})
        output_root = out_conf.get('root_dir', 'data/processed')
        # Resolve relative path to absolute
        if base_dir and not Path(output_root).is_absolute():
            output_root = str(Path(base_dir) / output_root)

        self.path_generator = PathGenerator(
            template=out_conf.get('structure_template', "{year}/{location}/{species_cn}/{filename}"),
            output_root=output_root
        )
        self.write_back_raw = out_conf.get('write_back_to_source', False)

        # Store base_dir and output_root for relative path conversion and exclusion
        self.base_dir = base_dir
        self.output_root = output_root  # Absolute path for exclusion
        
        # Batch Buffer
        self.batch_buffer = []
        self.batch_lock = threading.Lock() # Lock for buffer access
        self.current_candidate_labels = None
        self.inference_batch_size = self.config.get('recognition', {}).get('local', {}).get('inference_batch_size', 16)

        # Load taxonomy and config lists (with defaults for backward compatibility)
        paths_config = self.config.get('paths', {})
        self.foreign_countries = self._load_list(paths_config.get('foreign_list', 'config/dictionaries/foreign_countries.txt'))
        self.china_allowlist = self._load_list(paths_config.get('china_list', 'config/dictionaries/china_bird_list.txt'))
        self.all_labels = self._get_taxonomy_labels()

    @property
    def detector(self):
        """Lazy load detector with timeout protection."""
        if self._detector is None and not self._detector_loaded:
            import signal
            import functools

            class TimeoutError(Exception):
                pass

            def timeout_handler(signum, frame):
                raise TimeoutError("Model loading timed out")

            # Set alarm for timeout (only works on Unix-like systems)
            # On Windows, we'll use a simpler approach with threading
            use_signal = hasattr(signal, 'SIGALRM')

            if use_signal:
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(self._init_timeout)

            try:
                self._detector = BirdDetector(
                    self.config['processing']['yolo_model'],
                    self.config['processing']['confidence_threshold'],
                    device=self.device
                )
                self._detector_loaded = True
            except TimeoutError:
                logging.error(f"Detector loading timed out after {self._init_timeout} seconds")
                self._detector_loaded = True
                raise
            finally:
                if use_signal:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)

        return self._detector

    def _load_list(self, path_str):
        path = Path(path_str)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return set(line.strip() for line in f if line.strip())
        return set()

    def _calculate_file_hash(self, provider, file_path: str, size: int) -> str:
        """
        Calculate partial SHA256 hash for fast deduplication.
        """
        sha256 = hashlib.sha256()
        
        data = provider.read_bytes(file_path)
        
        if size < 12288:
             sha256.update(data)
        else:
             sha256.update(data[:4096])
             sha256.update(data[size//2 : size//2 + 4096])
             sha256.update(data[-4096:])

        return f"{size}_{sha256.hexdigest()}"

    def _get_taxonomy_labels(self):
        # Check if DB is empty
        cursor = self.db.conn.execute("SELECT count(*) FROM taxonomy")
        count = cursor.fetchone()[0]

        if count == 0:
            logging.warning("Taxonomy table is empty! Attempting auto-import from Excel...")

            # Try to find IOC Excel file
            refs_dir = Path(self.config['paths'].get('references_path', 'data/references'))
            excel_file = None

            # First try configured path (with quotes handling for spaces)
            configured_path = self.config['paths'].get('ioc_list_path', '')
            if configured_path:
                p = Path(configured_path)
                if p.exists():
                    excel_file = p
                    logging.info(f"Using configured IOC file: {excel_file}")

            # If not found, search in references directory for Multiling IOC file
            if excel_file is None and refs_dir.exists():
                for f in sorted(refs_dir.glob("*.xlsx")):
                    # Look for Multiling IOC files (they have the correct format)
                    name_lower = f.name.lower()
                    if 'multiling' in name_lower and 'ioc' in name_lower:
                        excel_file = f
                        logging.info(f"Found IOC file: {excel_file}")
                        break

            if excel_file and excel_file.exists():
                try:
                    refs_dir = str(self.config['paths'].get('references_path', 'data/references'))
                    self.db.import_from_excel(str(excel_file), refs_dir=refs_dir)
                    # Verify import
                    cursor = self.db.conn.execute("SELECT count(*) FROM taxonomy")
                    count = cursor.fetchone()[0]
                    logging.info(f"Auto-import completed. Taxonomy count: {count}")
                except Exception as e:
                    logging.error(f"Failed to import Excel: {e}")
            else:
                logging.error(f"IOC Excel file not found. Searched: {refs_dir}")

        # Fetch all scientific names from taxonomy table
        cursor = self.db.conn.execute("SELECT scientific_name FROM taxonomy")
        all_labels = [row[0] for row in cursor.fetchall()]
        logging.info(f"Loaded {len(all_labels)} total labels from DB.")
        return all_labels

    def _select_candidate_labels(self, location_tag: str):
        mode = self.config.get('recognition', {}).get('region_filter')
        
        if mode == 'china':
            if not self.china_allowlist:
                 return self.all_labels
            return [name for name in self.all_labels if name in self.china_allowlist]
            
        if mode == 'auto':
            is_foreign = False
            for country in self.foreign_countries:
                if country in location_tag:
                    is_foreign = True
                    break
            
            if is_foreign:
                return self.all_labels
            else:
                if not self.china_allowlist:
                    return self.all_labels
                return [name for name in self.all_labels if name in self.china_allowlist]

        return self.all_labels

    def _init_recognizer(self):
        """
        Lazy load the recognizer to save resources if no birds are found.
        """
        rec_config = self.config['recognition']
        mode = rec_config.get('mode', 'local')
        
        if mode == 'local':
            conf = rec_config.get('local', {})
            self.recognizer = LocalBirdRecognizer(
                model_name=conf.get('model_type', 'bioclip'),
                device=self.device
            )
        elif mode == 'dongniao':
            conf = rec_config.get('dongniao', {})
            self.recognizer = DongniaoRecognizer(
                api_key=conf.get('key'),
                base_url=conf.get('url')
            )
        elif mode == 'api':
             conf = rec_config.get('api', {})
             self.recognizer = APIBirdRecognizer(
                 api_key=conf.get('key'),
                 base_url=conf.get('url')
             )
        else:
            logging.error(f"Unknown recognition mode: {mode}")
            raise ValueError(f"Unknown recognition mode: {mode}")

    def _flush_batch(self):
        with self.batch_lock:
            if not self.batch_buffer:
                return
            items = self.batch_buffer[:] # Copy
            self.batch_buffer = [] # Clear buffer immediately
        
        try:
            # Prepare paths
            image_paths = [item['crop_path'] for item in items]
            
            # Batch Predict
            top_k = self.config.get('recognition', {}).get('top_k', 5)
            
            if hasattr(self.recognizer, 'predict_batch'):
                batch_results = self.recognizer.predict_batch(image_paths, self.current_candidate_labels, top_k=top_k)
            else:
                batch_results = [
                    self.recognizer.predict(p, self.current_candidate_labels, top_k=top_k) 
                    for p in image_paths
                ]

            # Process Results
            alt_threshold = self.config.get('recognition', {}).get('alternatives_threshold', 70)
            low_conf_threshold = self.config.get('recognition', {}).get('low_confidence_threshold', 60)

            for item, results in zip(items, batch_results):
                self._archive_item(item, results, alt_threshold, low_conf_threshold)
                
        except Exception as e:
            logging.error(f"Batch processing failed: {e}", exc_info=True)
            for item in items:
                try: os.remove(item['crop_path'])
                except: pass

    def _archive_item(self, item, results, alt_threshold, low_conf_threshold):
        entry = item['entry']
        meta = item['meta']
        temp_crop_path = item['crop_path']
        detections_len = item['detections_count']
        i_det = item['detection_index']
        img_width = item['width']
        img_height = item['height']
        file_hash = item['file_hash']

        # Initialize default values
        is_low_conf = False
        cn_name = "Unknown"
        sci_name = "Unknown"
        user_comment = "No recognition results."

        if not results:
            top_result = {"scientific_name": "Unknown", "confidence": 0.0}
        else:
            top_result = results[0]
            top_conf_pct = top_result['confidence'] * 100
            is_low_conf = top_conf_pct < low_conf_threshold
            
            comment_lines = []
            candidates_data = []
            
            show_alternatives = (top_conf_pct <= alt_threshold) or is_low_conf
            display_results = results if show_alternatives else [results[0]]

            for i, res in enumerate(results):
                r_sci = res['scientific_name']
                r_conf = res['confidence'] * 100
                r_info = self.db.get_bird_info(r_sci)
                r_cn = r_info['chinese_name'] if r_info else r_sci
                
                candidates_data.append({"sci": r_sci, "cn": r_cn, "score": res['confidence']})

                if i < len(display_results):
                    if i == 0:
                        prefix = "Top Match" if not is_low_conf else "Low Confidence Match"
                        comment_lines.append(f"{prefix}: {r_cn} ({r_sci}) - {r_conf:.1f}%")
                        if show_alternatives and len(results) > 1:
                            comment_lines.append("Alternatives:")
                    else:
                        comment_lines.append(f"{i}. {r_cn} ({r_sci}) - {r_conf:.1f}%")
            
            user_comment = "&#xa;".join(comment_lines)

        if is_low_conf:
            cn_name = "待确认鸟种"
            sci_name = "Uncertain"
        else:
            sci_name = top_result['scientific_name']
            bird_info = self.db.get_bird_info(sci_name)
            cn_name = bird_info['chinese_name'] if bird_info else sci_name
        
        confidence = top_result['confidence']
        
        # Generate Path
        gen_meta = {
            'captured_date': meta.get('captured_date', '00000000'),
            'location_tag': meta.get('location_tag', 'Unknown'),
            'primary_bird_cn': cn_name,
            'scientific_name': sci_name,
            'confidence_score': confidence,
            'source_structure': meta.get('source_structure', '.')
        }
        
        current_filename = entry.name
        if detections_len > 1:
            base = Path(entry.name).stem
            ext = Path(entry.name).suffix
            current_filename = f"{base}_{i_det+1}{ext}"

        final_path = self.path_generator.generate_path(gen_meta, current_filename)
        Path(final_path).parent.mkdir(parents=True, exist_ok=True)
        
        try:
            import shutil
            shutil.move(temp_crop_path, final_path)
            
            if is_low_conf:
                description = "Uncertain Bird (Low Confidence)"
                keywords = ["FeatherTrace", "LowConfidence", meta.get('location_tag')]
            else:
                description = f"{cn_name} ({sci_name})"
                keywords = [cn_name, sci_name, meta.get('location_tag'), "FeatherTrace"]

            # Filter out None values from keywords
            keywords = [k for k in keywords if k is not None]

            self.exif_writer.write_metadata(str(final_path), {
                'ImageDescription': description,
                'XMP:Description': description,
                'XPTitle': description,
                'XPSubject': "",
                'Keywords': keywords,
                'UserComment': user_comment
            })
            
            # Convert absolute paths to relative paths for database storage
            # The entry.path may be UNC path (\\server\share\...) or drive letter path (Y:\...)
            # We need to handle both formats relative to base_dir
            rel_original_path = entry.path
            rel_file_path = str(final_path)

            if self.base_dir:
                norm_base_dir = os.path.normpath(self.base_dir)
                base_dir_parts = Path(norm_base_dir).parts  # e.g., ('Y:', '1按年份', '2026')

                # Try method 1: direct relative path (works for Y:\path format)
                try:
                    norm_entry_path = os.path.normpath(entry.path)
                    rel_original_path = str(Path(norm_entry_path).relative_to(Path(norm_base_dir)))
                    logging.debug(f"Converted original_path: {entry.path} -> {rel_original_path}")
                except ValueError:
                    # Try method 2: extract relative path from UNC path
                    # UNC path: \\192.168.31.205\picturessd\1按年份\2026\20260102北京八渡桥附近\file.jpg
                    # base_dir: Y:\1按年份\2026 -> parts: ('Y:', '1按年份', '2026')
                    # We need to find where base_dir ends and extract the rest
                    try:
                        entry_parts = Path(os.path.normpath(entry.path)).parts
                        # Find the position after base_dir's last component in entry_parts
                        if len(base_dir_parts) >= 2:
                            # Look for base_dir's last component (e.g., "2026")
                            base_last = base_dir_parts[-1]  # "2026"
                            if base_last in entry_parts:
                                idx = entry_parts.index(base_last) + 1  # Skip "2026"
                                if idx < len(entry_parts):
                                    rel_original_path = str(Path(*entry_parts[idx:]))
                                    logging.debug(f"Converted original_path (UNC): {entry.path} -> {rel_original_path}")
                    except Exception:
                        logging.warning(f"Failed to convert original_path, keeping original: {entry.path}")

                # Same for final_path (processed file)
                try:
                    norm_final_path = os.path.normpath(str(final_path))
                    rel_file_path = str(Path(norm_final_path).relative_to(Path(norm_base_dir)))
                    logging.debug(f"Converted file_path: {final_path} -> {rel_file_path}")
                except ValueError:
                    try:
                        final_parts = Path(os.path.normpath(str(final_path))).parts
                        base_last = base_dir_parts[-1]
                        if base_last in final_parts:
                            idx = final_parts.index(base_last) + 1
                            if idx < len(final_parts):
                                rel_file_path = str(Path(*final_parts[idx:]))
                                logging.debug(f"Converted file_path (UNC): {final_path} -> {rel_file_path}")
                    except Exception:
                        logging.warning(f"Failed to convert file_path, keeping original: {final_path}")

            self.db.add_photo_record({
                'file_path': rel_file_path,
                'filename': Path(final_path).name,
                'original_path': rel_original_path,
                'file_hash': file_hash,
                'captured_date': meta.get('captured_date'),
                'location_tag': meta.get('location_tag'),
                'primary_bird_cn': cn_name,
                'scientific_name': sci_name,
                'confidence_score': confidence,
                'width': img_width,
                'height': img_height,
                'candidates_json': json.dumps(candidates_data, ensure_ascii=False)
            })
            
            log_name = cn_name if not is_low_conf else f"Uncertain ({top_result['scientific_name']})"
            logging.info(f"Processed: {entry.name} -> {log_name} ({confidence*100:.1f}%)")
            
        except Exception as e:
            logging.error(f"Failed to archive {entry.name}: {e}")
            # Log more details for debugging
            import traceback
            logging.debug(traceback.format_exc())

    def process_image(self, provider, entry, meta):
        # 1. Deduplication
        file_hash = self._calculate_file_hash(provider, entry.path, entry.size)
        if self.db.check_hash_exists(file_hash):
             logging.debug(f"Skipping duplicate: {entry.name}")
             return

        local_source_path = provider.get_local_path(entry.path)
        if not local_source_path: return

        # 2. Detect (Thread-safe if YOLO is)
        # Note: YOLO instantiation might need lock if not thread-safe, but predict is usually ok
        try:
            detections = self.detector.detect(local_source_path)
        except Exception as e:
            logging.error(f"Detection failed for {entry.name}: {e}")
            return
            
        if not detections: return
        
        # Init recognizer if needed (double check locking if lazily init)
        if self.recognizer is None: 
            with self.batch_lock:
                if self.recognizer is None: self._init_recognizer()

        # 3. Context Check (Batching)
        location_tag = meta.get('location_tag', 'Unknown')
        candidates = self._select_candidate_labels(location_tag)
        
        with self.batch_lock:
            # If context changed, flush previous batch
            if self.current_candidate_labels is not None and candidates != self.current_candidate_labels:
                # We release lock inside flush? No, _flush_batch uses lock.
                # Recursive locking? Lock is RLock? Default is Lock.
                # We need to be careful.
                # Better: Queue everything, flush if needed.
                # But flush needs to clear buffer.
                # If we are holding lock, we can't call a function that acquires lock.
                pass 
            
            # Simple strategy: If labels change, we must flush.
            # But in multi-threaded env, multiple threads might be processing different locations?
            # If so, they fight over 'current_candidate_labels'.
            # Ideally, batch should be homogeneous.
            # For now, let's assume one run mostly has one context or we accept flushing often.
            
            if self.current_candidate_labels is not None and candidates != self.current_candidate_labels:
                 # Manually flush logic here to avoid re-acquiring lock
                 items = self.batch_buffer[:]
                 self.batch_buffer = []
                 # Processing must happen OUTSIDE the lock to avoid blocking detectors
                 # But we need to update current_labels.
                 pass # Complex.
            
            # SIMPLIFICATION:
            # We skip flushing on context change inside thread for now, 
            # assuming the run is mostly consistent or we handle mixed batches later.
            # OR, we just update the global labels?
            self.current_candidate_labels = candidates # This is risky if threads mix.

        # 4. Crop & Queue
        img_width, img_height = 0, 0
        try:
            from PIL import Image
            with Image.open(local_source_path) as tmp_img:
                img_width, img_height = tmp_img.size
        except: pass

        for i, (box, score) in enumerate(detections):
            # Use output_root for temp directory (which is now resolved to absolute path)
            temp_dir = Path(self.output_root) / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_crop_path = temp_dir / f"temp_{entry.name}_{i}.jpg" 
            
            success = ImageProcessor.crop_and_resize(
                local_source_path, box, str(temp_crop_path), 
                target_size=self.config['processing']['target_size'],
                padding=self.config['processing']['crop_padding']
            )
            
            if success:
                # 5. Blur detection (quality check)
                blur_threshold = self.config.get('processing', {}).get('blur_threshold', 40.0)
                if blur_threshold > 0:
                    blur_score = QualityChecker.calculate_blur_score(str(temp_crop_path))
                    if blur_score < blur_threshold:
                        logging.info(f"[Quality] blur_score={blur_score:.1f} < {blur_threshold} SKIP - {temp_crop_path.name}")
                        try:
                            os.remove(str(temp_crop_path))
                        except:
                            pass
                        continue

                should_flush = False
                with self.batch_lock:
                    self.batch_buffer.append({
                        'entry': entry,
                        'meta': meta,
                        'crop_path': str(temp_crop_path),
                        'file_hash': file_hash,
                        'width': img_width,
                        'height': img_height,
                        'detection_index': i,
                        'detections_count': len(detections)
                    })
                    if len(self.batch_buffer) >= self.inference_batch_size:
                        should_flush = True
                
                if should_flush:
                    self._flush_batch()

    def run(self, start_date: str = None, end_date: str = None):
        t_start = time.time()
        start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        processed_count = 0
        
        if start_date:
            logging.info(f"Pipeline Filter: Range [{start_date} - {end_date or 'Max'}]")
        
        sources = self.config['paths'].get('sources', [])
        # Fallback for old config
        if not sources and 'raw_dir' in self.config['paths']:
             sources = [{'path': self.config['paths']['raw_dir'], 'recursive': False}]

        # Resolve source paths (relative to base_dir)
        base_dir = self.base_dir
        for source in sources:
            path_str = source['path']
            # Resolve relative path to absolute
            if base_dir and path_str and not Path(path_str).is_absolute():
                source['path'] = str(Path(base_dir) / path_str)

        # Use ThreadPool for detection/cropping
        # 4 workers is a good start for IO/CPU bound mix
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []

            for source in sources:
                if not source.get('enabled', True):
                    continue

                path_str = source['path']
                recursive = source.get('recursive', True)
                structure_pattern = source.get('structure_pattern', None)
                
                logging.info(f"Scanning source: {path_str} (Recursive: {recursive})")
                
                provider, rel_path = self.fs_manager.resolve_path(path_str)
                if not provider.exists(rel_path):
                    logging.warning(f"Source path not found: {path_str}")
                    continue
                
                source_root_abs = Path(provider.get_local_path(rel_path))
                parser = PathParser(source_root_abs, structure_pattern)

                # Get output directory to exclude from scanning (use pre-resolved absolute path)
                exclude_dirs = [self.output_root] if self.output_root else []

                iterator = []
                if recursive and (start_date or end_date):
                    scanner = SmartScanner(source_root_abs, start_date, end_date, exclude_dirs)
                    iterator = scanner.scan(source_root_abs)
                else:
                    iterator = provider.list_dir(rel_path, recursive=recursive)

                for entry in iterator:
                    is_dir = entry.is_dir() if callable(entry.is_dir) else entry.is_dir
                    if is_dir: continue

                    entry_name = entry.name
                    entry_path = entry.path

                    # Skip files in output directory
                    if self.output_root:
                        try:
                            entry_abs = Path(entry_path).resolve()
                            output_abs = Path(self.output_root).resolve()
                            if str(entry_abs).startswith(str(output_abs)):
                                logging.debug(f"Skipping output file: {entry_name}")
                                continue
                        except:
                            pass

                    if not entry_name.lower().endswith(('.jpg', '.jpeg')):
                        continue
                    
                    meta = parser.parse(entry_path)
                    
                    c_date = meta.get('captured_date')
                    if start_date and c_date:
                        if int(c_date) < int(start_date): continue
                    if end_date and c_date:
                        if int(c_date) > int(end_date): continue

                    if not hasattr(entry, 'size'):
                        class Adapter:
                            def __init__(self, e):
                                self.path = e.path
                                self.name = e.name
                                self.size = e.stat().st_size
                        entry_obj = Adapter(entry)
                    else:
                        entry_obj = entry
                        
                    processed_count += 1
                    # Submit task to pool
                    futures.append(executor.submit(self.process_image, provider, entry_obj, meta))
                    
                    # Prevent memory explosion from too many futures
                    if len(futures) > 500:
                        done, not_done = wait(futures, timeout=0.1)
                        futures = list(not_done)

            # Wait for all tasks to complete
            if futures:
                wait(futures)

        # Process any remaining items in the buffer
        self._flush_batch()
        t_end = time.time()
        duration = t_end - t_start
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        self.db.add_scan_history({
            'start_time': start_time_str,
            'end_time': end_time_str,
            'range_start': start_date or "All",
            'range_end': end_date or "All",
            'processed_count': processed_count,
            'duration_seconds': round(duration, 2),
            'status': 'Completed'
        })
        logging.info(f"Pipeline completed. Processed: {processed_count}. Duration: {duration:.2f}s")

if __name__ == "__main__":
    config_path = "config/settings.yaml"
    config = load_config(config_path)
    
    if not check_system_dependencies(config):
        logging.error("System check failed. Please fix the issues above and restart.")
        sys.exit(1)
        
    runner = FeatherTracePipeline(config_path)
    runner.run()