# Architecture Documentation

## System Overview

WingScribe is an automated pipeline for bird photography management. It bridges the gap between raw data ingestion and organized, searchable archives.

### Core Components

1.  **Pipeline Runner (`src/pipeline_runner.py`)**:
    *   **Orchestrator**: Manages the ETL process.
    *   **Smart Scanning**: Uses `SmartScanner` to walk directories, applying date-based pruning to skip irrelevant folders.
    *   **Processing**:
        *   **Detection**: Uses `src/core/detector.py` (YOLOv11) to find birds.
        *   **Quality**: Uses `src/core/quality.py` (Laplacian Variance) to filter blur.
        *   **Cropping**: Uses `src/core/processor.py` to create standardized crops.
    *   **Recognition**: Delegates to `LocalBirdRecognizer` (BioCLIP), `DongniaoRecognizer`, or `APIBirdRecognizer`.
    *   **Metadata**: Uses `ExifWriter` to inject standard tags (EXIF/IPTC/XMP) into images.

2.  **Data Management (`src/metadata/`)**:
    *   **IOCManager**: SQLite wrapper. Manages:
        *   `taxonomy`: IOC World Bird List data.
        *   `photos`: Index of processed images, including `candidates_json` (Top-K results).
        *   `scan_history`: Execution logs.
    *   **ExifWriter**: Wrapper around `exiftool`. Handles encoding (UTF-8/GBK) and safe writing of complex metadata.

3.  **Web Interface (`src/web/`)**:
    *   **FastAPI App**: Serves the UI and API.
    *   **Interactive Editing**:
        *   Updates DB records.
        *   **Auto-Renaming**: If species name changes, triggers file move/rename based on `structure_template`.
        *   **Write-back**: Updates EXIF on both processed and original raw files.
    *   **WebSocket**: Streams pipeline logs to the frontend.

## Key Data Flows

### 1. Ingestion Flow
`Raw Files` -> `SmartScanner` -> `Detector` -> `Cropper` -> `Recognizer (Top-K)` -> `DB & File System`

*   **Scanning**: `PathParser` extracts metadata (Date/Location) from folder structures. Supports hybrid logic (Strict Parent / Regex Child).
*   **Archiving**: Files are saved to `data/processed` using a template (e.g., `{year}/{location}/{species}/{filename}`).

### 2. Correction Flow
`User UI` -> `API (/update_label)` -> `DB Update` -> `File Rename` -> `EXIF Write`

*   **Candidates**: User sees Top-5 suggestions from AI.
*   **Renaming**: If the new name affects the file path (e.g., moving from `/Sparrow/` to `/Eagle/`), the system handles the move automatically.

### 3. Taxonomy Filter Flow
`User clicks tree node` -> `API (/api/photos/by_taxonomy)` -> `Update Grid & Status Bar`

*   **Dynamic Pagination**: Both top status bar and bottom pagination buttons use the same JavaScript function `renderPaginationBottom` for consistent behavior.
*   **CSS Grid**: Photo gallery uses CSS Grid for consistent 4-column layout regardless of photo count.

## Infrastructure

*   **Database**: SQLite (`wingscribe.db`).
*   **AI Models**:
    *   **Detection**: YOLOv11n (Local).
    *   **Classification**: BioCLIP (OpenCLIP ViT-B/16) or External APIs.
*   **Storage**:
    *   **Local**: Direct file access.
    *   **NAS**: Supported via OS-level mounting (WebDAV/SMB).
