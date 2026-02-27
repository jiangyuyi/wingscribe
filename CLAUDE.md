# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WingScribe (飞羽志) is an automated bird photography management system that uses computer vision (YOLOv11) and multimodal AI models (BioCLIP) to automatically detect, filter, identify species, inject metadata, and organize bird photos into a hierarchical archive with a local web interface for manual verification.

**Technology Stack:** Python 3.10+, PyTorch, YOLOv11, BioCLIP (OpenCLIP), FastAPI, MySQL/PostgreSQL, ExifTool

## Common Commands

### Installation
```bash
# Create virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running the System
```bash
# Start Web UI (recommended)
python src/web/app.py
# Access at http://localhost:8000

# Run pipeline directly via CLI
python src/pipeline_runner.py --start 20240101 --end 20240131
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_path_parser.py

# Run specific test
pytest tests/test_path_parser.py::TestPathParserRecursive::test_basic_existing_behavior
```

### Database Operations
```bash
# Import IOC bird taxonomy from Excel
python scripts/import_ioc_data.py

# Populate database with test data
python scripts/populate_db.py
```

### Model Management
```bash
# Download BioCLIP model
python scripts/download_model.py

# Check GPU availability
python scripts/check_gpu.py
```

## Architecture

### Core Pipeline (`src/pipeline_runner.py`)

The `WingScribePipeline` class orchestrates the entire ETL process:

1. **Smart Scanning**: Uses `SmartScanner` to walk directories with date-based pruning to skip irrelevant folders
2. **Detection**: `BirdDetector` (YOLOv11) finds birds in images
3. **Cropping**: `ImageProcessor` creates standardized crops with padding
4. **Recognition**: One of `LocalBirdRecognizer`, `DongniaoRecognizer`, or `APIBirdRecognizer`
5. **Archiving**: Files saved to `data/processed` using configurable template, metadata injected via `ExifWriter`

**Key Pattern - Batch Processing**: The pipeline uses a batch buffer (`self.batch_buffer`) with threading locks to accumulate detections before running recognition inference. This is critical for performance when using local BioCLIP models.

**Region Filtering**: The `_select_candidate_labels()` method filters bird species based on `region_filter` config:
- `china`: Only birds from China allowlist
- `auto`: Detects foreign countries in folder names, switches to full list
- `null`: Global bird list

### Data Layer (`src/metadata/`)

**IOCManager**: SQLite wrapper managing three tables:
- `taxonomy`: IOC World Bird List data (scientific_name, chinese_name, family_cn, order_cn)
- `photos`: Index of processed images including `candidates_json` (Top-K AI results)
- `scan_history`: Execution logs

**ExifWriter**: Wrapper around `exiftool` CLI. Handles encoding issues (UTF-8/GBK) and safe writing of complex metadata including IPTC keywords, XMP fields, and UserComment.

### Recognition Engines (`src/recognition/`)

**LocalBirdRecognizer**: BioCLIP (OpenCLIP ViT-B/16) implementation with:
- Text feature caching to avoid re-encoding labels
- CUDA fallback to CPU on errors
- Batch inference support (`predict_batch()`) for efficiency
- Automatic precision selection (fp16 for CUDA, fp32 for CPU)

**Base class**: `BirdRecognizer` defines the interface for all recognition engines.

### File System Abstraction (`src/core/io/`)

**FileSystemManager**: Singleton managing file access with security via `base_dir`. Returns `LocalProvider` instances for path operations.

**PathParser**: Extracts metadata (date, location) from folder structures:
- Supports range patterns: `yyyyMMdd-yyyyMMdd_Location` or `yyyyMMdd-dd_Location`
- Supports single date: `yyyyMMdd_Location`
- Regex pattern support via `structure_pattern` config
- Recursive parsing joins location tags with `_`

**PathGenerator**: Generates output paths from metadata using template variables:
- `{year}`, `{month}`, `{day}`, `{date}`, `{location}`, `{species_cn}`, `{species_sci}`, `{confidence}`, `{filename}`, `{source_structure}`

### Web Interface (`src/web/app.py`)

FastAPI application with:
- Photo browsing with search, date filtering, and pagination
- `/api/update_label`: Updates species, auto-renames files, writes EXIF to both processed and original files
- `/api/pipeline/start`: Triggers background pipeline execution
- WebSocket `/ws/progress`: Streams pipeline logs in real-time
- `/api/admin/reset`: Clears database and processed directory

**Key Pattern - Label Updates**: When user corrects a species label:
1. Fetches original photo details from DB
2. Updates database record
3. If template uses species variables, regenerates path and moves file
4. Updates EXIF on both processed and original files
5. Preserves AI candidates in UserComment for audit trail

### Configuration

**`config/settings.yaml`**: Main configuration
- `paths`: Sources, output, base_dir, reference data paths
- `processing`: Device, YOLO model, thresholds, crop settings
- `recognition`: Mode (local/api/dongniao), region_filter, thresholds

**`config/secrets.yaml`**: API keys (not in git)

## Important Patterns

### Threading and Locks
The pipeline uses `ThreadPoolExecutor` for parallel detection/cropping. The `batch_lock` protects `batch_buffer` and `current_candidate_labels`. When modifying batch processing logic, ensure proper lock handling to avoid race conditions.

### CUDA Fallback
Both `BirdDetector` and `LocalBirdRecognizer` implement automatic fallback from CUDA to CPU on errors. This is essential for laptops with unstable GPU drivers or insufficient VRAM.

### Path Security
Web UI only serves files from `base_dir` defined in config. All paths are validated to be under `base_dir`.

### Database Migration
`IOCManager._init_db()` handles schema migrations by checking for new columns and adding them with ALTER TABLE statements wrapped in try/except.

### Date-Based Pruning
`SmartScanner` uses `_is_in_range()` to skip entire directory branches when their date ranges don't overlap with the query range. This is critical for performance on large photo archives.

## File Organization

```
src/
├── core/
│   ├── detector.py          # YOLOv11 bird detection
│   ├── processor.py         # Image cropping/resizing
│   ├── quality.py           # Blur detection (Laplacian variance)
│   └── io/
│       ├── provider.py      # File system provider interface
│       ├── local.py         # Local file system implementation
│       ├── fs_manager.py    # File system manager singleton
│       ├── path_parser.py   # Extract metadata from paths
│       ├── path_generator.py # Generate output paths from templates
│       └── temp_manager.py  # Temporary file management
├── recognition/
│   ├── bioclip_base.py      # Base recognizer class
│   ├── inference_local.py   # BioCLIP implementation
│   ├── inference_dongniao.py # Dongniao API client
│   └── inference_api.py     # HuggingFace API client
├── metadata/
│   ├── ioc_manager.py       # SQLite database wrapper
│   └── exif_writer.py       # EXIF/IPTC/XMP metadata writer
├── web/
│   └── app.py               # FastAPI web application
├── utils/
│   ├── config_loader.py     # YAML config loading
│   └── env_check.py         # System dependency checks
└── pipeline_runner.py       # Main pipeline orchestrator
```

## Dependencies

Key external libraries:
- `ultralytics`: YOLOv11 for bird detection
- `open_clip`: BioCLIP model for species recognition
- `fastapi` + `uvicorn`: Web server
- `PyExifTool`: EXIF metadata writing
- `pandas` + `openpyxl`: Excel import for taxonomy data
- `sqlalchemy`: Database ORM (though IOCManager uses raw SQL)

**Critical**: ExifTool must be installed and in system PATH for metadata writing.

## Database

The system uses MySQL/PostgreSQL instead of SQLite for remote access support.

### Configuration

Database connection is configured in `config/settings.yaml`:

```yaml
database:
  type: "mysql"  # or "postgresql"
  host: "localhost"
  port: 3306
  username: "wingscribe"
  password: "your_password"
  database: "wingscribe"
```