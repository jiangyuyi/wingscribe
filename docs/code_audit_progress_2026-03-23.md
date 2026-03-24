# Code Audit Progress 2026-03-23

## This round

- Reviewed `src/recognition/cloud/` and confirmed a real input-loading defect across all four cloud recognizers:
  - `src/recognition/cloud/huggingface.py`
  - `src/recognition/cloud/modelscope.py`
  - `src/recognition/cloud/aliyun.py`
  - `src/recognition/cloud/baidu.py`
- Fixed two concrete problems in `_load_image()`:
  - Removed the broken dependency on a non-existent `...core.io.get_fs_manager`
  - Replaced invalid `with httpx.get(...) as response:` usage with a normal synchronous request flow
- Local file inputs now read directly from `image_path`, and URL inputs now call `raise_for_status()` correctly.

## Tests added

- Added `tests/test_cloud_recognizers.py`
- Covered `image_base64`, `image_path`, and `image_url` input loading for all four cloud recognizers

## Validation

- `python -m pytest tests/test_cloud_recognizers.py -v`
- `python -m pytest`
- Result: `145 passed, 1 skipped`
- Total coverage: `51%`

## Later rounds

- Added low-risk shared platform metadata:
  - `src/recognition/platform_catalog.py`
  - `src/recognition_service.py`
  - `src/web/routes/recognition.py`
- Consolidated duplicate `/platforms` metadata into one shared source and added tests:
  - `tests/test_platform_catalog.py`
  - `tests/test_recognition_service.py`
  - `tests/test_recognition_routes.py`
- Added direct factory and legacy API recognizer coverage:
  - `tests/test_cloud_factory.py`
  - `tests/test_inference_api.py`
- Fixed a real defect in `src/recognition/inference_api.py`:
  - `APIBirdRecognizer` was missing `predict_batch()` and could not be instantiated
- Added Dongniao coverage:
  - `tests/test_inference_dongniao.py`
- Fixed two real defects in the legacy Dongniao path:
  - `src/recognition/inference_dongniao.py` was missing `predict_batch()`
  - `src/pipeline_runner.py` passed `base_url` to `DongniaoRecognizer`, but the constructor expects `api_url`

## Current validated state

- Latest full test run:
  - `python -m pytest`
  - Result: `168 passed, 1 skipped`
  - Total coverage: `55%`
- Recent commits on this branch:
  - `e7f7fd6` `优化: 收口审查修复与测试补强`
  - `1c63cd5` `测试: 补云工厂与API识别覆盖`
  - `5c4a935` `测试: 补懂鸟识别链路覆盖`

## Compressed context

- Already fixed correctness issues:
  - deep-merge `cloud` secrets into runtime config
  - recognition service now resolves repo-root `config/`
  - original/processed path storage and resolution are separated
  - `/api/update_label` updates file/metadata before DB commit
  - pipeline no longer mixes candidate labels across images in threaded runs
  - cloud recognizers now load local files and remote URLs correctly
  - legacy API and Dongniao recognizers can now be instantiated because `predict_batch()` exists
- Current high-value remaining work:
  - `src/recognition/inference_local.py` still has very low coverage
  - `src/web/app.py` still has broad uncovered route surface
  - `TaskManager.should_stop` is still a pseudo-stop flag
  - `IOCManager` still uses a long-lived SQLite connection model worth refactoring later
- Important local-only note:
  - `config/settings.yaml` contains local machine path changes and is intentionally left uncommitted

## Remaining high-value areas

- Current known remaining work:
  - `src/metadata/ioc_manager.py` still uses a long-lived SQLite connection model that is shared inside pipeline worker execution
  - `src/recognition/inference_local.py` still needs deeper coverage on model-loading and fallback branches
  - `src/recognition/inference_dongniao.py` still has large uncovered business branches
  - `src/web/app.py` may still be worth expanding for any remaining photo list/detail/admin routes
- `src/web/app.py`
  - Added route coverage for stats, taxonomy-photo filtering, and pagination parameter forwarding
  - Still worth expanding later for any remaining photo list/detail endpoints if the route surface grows
- `src/recognition/cloud/factory.py`
  - Still needs direct tests for platform creation and default config extraction
- `src/recognition/inference_api.py`
  - Low coverage and overlaps conceptually with cloud recognition paths
- `src/recognition/inference_dongniao.py`
  - Still a large low-coverage business module
- `src/recognition/inference_local.py`
  - Still a large low-coverage business module
- `TaskManager.should_stop`
  - Fixed into a cooperative stop path
  - Current behavior:
    - `start_pipeline*()` resets stale stop state before a new run
    - `src/web/app.py` now exposes `/api/pipeline/stop`
    - `WingScribePipeline` now receives a stop checker and stops submitting new work when a stop is requested
    - already-submitted tasks are allowed to finish naturally, and scan history is recorded as `Stopped`
- `IOCManager` connection model
  - Low-risk concurrency hardening completed for pipeline hot-path methods
  - Current behavior:
    - file-backed databases now use short-lived operation connections for hot-path reads/writes
    - write operations are serialized with a manager-level lock to reduce SQLite contention
    - `add_photo_record()` and species-stats updates now stay in the same short transaction
    - in-memory databases keep using the shared connection for test compatibility
    - legacy direct `manager.conn` access still exists for compatibility, so a full session/transaction refactor can still be considered later
