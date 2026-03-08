# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/`, split by responsibility:
- `src/core/`: detection, quality checks, processing, and IO/path utilities.
- `src/recognition/`: local/cloud inference backends and protocol logic.
- `src/metadata/`: IOC taxonomy handling and EXIF/IPTC writing.
- `src/web/`: FastAPI app, routes, and Jinja templates.

Tests are in `tests/` (`test_*.py`), runtime/config files are under `config/`, and reference/sample data is in `data/`. Deployment and maintenance scripts are in `scripts/`. Windows installer sources are in `installer/`; treat `installer/build-*` artifacts as generated output.

## Build, Test, and Development Commands
- `python -m venv venv` then `.\venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Unix): create/activate env.
- `pip install -r requirements.txt`: install runtime and test dependencies.
- `python src/web/app.py`: start the local Web UI (`http://localhost:8000`).
- `python src/recognition_service.py`: run recognition API service only.
- `python src/pipeline_runner.py --start 20240101 --end 20240131`: run batch pipeline for a date range.
- `python -m pytest`: run full test suite with coverage (configured in `pytest.ini`).
- `python -m pytest tests/test_path_parser.py -v`: run a focused test file.
- `cd installer; .\build.ps1; iscc installer.iss`: build Windows installer.

## Coding Style & Naming Conventions
Use Python 3.11+ with 4-space indentation and PEP 8 naming:
- `snake_case` for functions/variables/files, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Keep modules focused by domain (`core`, `recognition`, `web`, etc.).
- Prefer type hints for public interfaces and keep logging explicit for pipeline/debug flows.

## Testing Guidelines
Pytest is the standard (`pytest.ini` enforces `--strict-markers`, branch coverage, and `--cov=src`).
- Name tests as `test_*.py`, classes `Test*`, functions `test_*`.
- Use markers when relevant: `unit`, `integration`, `slow`.
- Add/adjust tests with every behavior change, especially in path parsing/generation, detector, DB, and metadata flows.

## Commit & Pull Request Guidelines
Follow the existing commit style seen in history: scoped, short prefixes such as `修复:`, `功能:`, `优化:`, `配置:`, `工具:` plus a concise summary.

For PRs, include:
- What changed and why.
- Linked issue/task (if any).
- Test evidence (`python -m pytest` output or equivalent).
- Screenshots for `src/web/templates/*` or UI behavior changes.
