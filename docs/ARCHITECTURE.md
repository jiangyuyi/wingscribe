# Architecture Documentation

## System Overview

WingScribe is an automated pipeline for bird photography management. It bridges the gap between raw data ingestion and organized, searchable archives.

### Core Components

1.  **Pipeline Runner (`src/pipeline_runner.py`)**:
    *   **Orchestrator**: Manages the ETL process.
    *   **Smart Scanning**: Uses `SmartScanner` to walk directories, applying date-based pruning to skip irrelevant folders.
    *   **Processing**:
        *   **Detection**: Uses `src/core/detector.py` (YOLO, with `yolo26n.pt` as the current default) to find birds.
        *   **Quality**: Uses `src/core/quality.py` to calculate sharpness, exposure, contrast, and noise metrics. `legacy_reject` preserves the historical blur rejection behavior, while `score_only` records scores without rejecting photos.
        *   **Cropping**: Uses `src/core/processor.py` to create standardized crops.
    *   **Recognition**: Delegates to `LocalBirdRecognizer` (BioCLIP), `DongniaoRecognizer`, or `APIBirdRecognizer`.
    *   **Metadata**: Uses `ExifWriter` to inject standard tags (EXIF/IPTC/XMP) into images.

2.  **Data Management (`src/metadata/`)**:
    *   **IOCManager**: SQLite wrapper. Manages:
        *   `taxonomy`: IOC World Bird List data.
        *   `photos`: Index of processed images, including `candidates_json` (Top-K results), explicit automatic/manual label provenance, and optional quality audit data.
        *   `scan_history`: Execution logs.
    *   **ExifWriter**: Wrapper around `exiftool`. Handles encoding (UTF-8/GBK) and safe writing of complex metadata.

3.  **Web Interface (`src/web/`)**:
    *   **FastAPI App**: Serves the UI and API.
    *   **Interactive Editing**:
        *   Updates DB records.
        *   **Auto-Renaming**: If species name changes, triggers file move/rename based on `structure_template`.
        *   **Write-back**: Updates EXIF on both processed and original raw files.
    *   **WebSocket**: Streams pipeline logs to the frontend.

4.  **Evaluation (`src/evaluation/`, `scripts/evaluate_*.py`)**:
    *   Provides repeatable public-dataset and local-directory shadow evaluation.
    *   Records dataset/candidate fingerprints, hardware metadata, latency, memory, and Top-K metrics where ground truth exists.
    *   Supports controlled multi-crop, image degradation, and species-prior experiments without changing production defaults.

5.  **Recognition Support (`src/recognition/`)**:
    *   `model_registry.py` defines supported local BioCLIP models and marks experimental choices.
    *   `prior.py` implements bounded, auditable reranking primitives; evaluated priors are not enabled in the production pipeline by default.
    *   `src/metadata/location_resolver.py` and the Web preview endpoint provide conservative location normalization without changing production recognition.

## Key Data Flows

### 1. Ingestion Flow
`Raw Files` -> `SmartScanner` -> `Detector` -> `Cropper` -> `Recognizer (Top-K)` -> `DB & File System`

*   **Scanning**: `PathParser` extracts metadata (Date/Location) from folder structures. Supports hybrid logic (Strict Parent / Regex Child).
*   **Archiving**: Files are saved to `data/processed` using a template (e.g., `{year}/{location}/{species}/{filename}`).

### 2. Correction Flow
`User UI` -> `API (/update_label)` -> `DB Update` -> `File Rename` -> `EXIF Write`

*   **Candidates**: User sees Top-5 suggestions from AI.
*   **Provenance**: A successful correction sets `label_source=manual` and `manual_verified_at`; historical automatic rows are not inferred to be human labels.
*   **Renaming**: If the new name affects the file path (e.g., moving from `/Sparrow/` to `/Eagle/`), the system handles the move automatically.

### 3. Taxonomy Filter Flow
`User clicks tree node` -> `API (/api/photos/by_taxonomy)` -> `Update Grid & Status Bar`

*   **Dynamic Pagination**: Both top status bar and bottom pagination buttons use the same JavaScript function `renderPaginationBottom` for consistent behavior.
*   **CSS Grid**: Photo gallery uses CSS Grid for consistent 4-column layout regardless of photo count.

## Infrastructure

*   **Database**: SQLite (`wingscribe.db`).
*   **AI Models**:
    *   **Detection**: YOLO (current packaged default: YOLO26n).
    *   **Classification**: BioCLIP ViT-B/16, BioCLIP2 ViT-L/14 (production default), experimental BioCLIP 2.5 ViT-H/14, or external APIs.
    *   **GPU Packaging**: CUDA 12.8 PyTorch supports RTX 50-series Blackwell devices; the CPU package keeps an independent CPU runtime.
*   **Storage**:
    *   **Local**: Direct file access.
    *   **NAS**: Supported via OS-level mounting (WebDAV/SMB).
