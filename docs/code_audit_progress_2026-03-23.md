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

## Remaining high-value areas

- `src/recognition/cloud/factory.py`
  - Still needs direct tests for platform creation and default config extraction
- `src/recognition/inference_api.py`
  - Low coverage and overlaps conceptually with cloud recognition paths
- `src/recognition/inference_dongniao.py`
  - Still a large low-coverage business module
- `src/recognition/inference_local.py`
  - Still a large low-coverage business module
- `TaskManager.should_stop`
  - Still behaves like a pseudo-stop flag rather than an effective cancellation path
- `IOCManager` connection model
  - Still worth a dedicated concurrency refactor later
