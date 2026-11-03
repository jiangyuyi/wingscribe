# WingScribe 3.0 user guide

[English README](../../README.en.md) · [中文文档总览](../README.md)

Follow [Install on Windows](#install-on-windows) for a new installation, or [Upgrade from 2.3.1](#upgrade-from-231) if you have an existing library. For a shoot already on disk, use [Scan and correct species](#scan-and-correct-species) to build a gallery, or [Cull a JPEG burst](#cull-a-jpeg-burst) to choose photographs.

## Install on Windows

Download the files from the [3.0.0 release](https://github.com/jiangyuyi/wingscribe/releases/tag/v3.0.0). The CPU edition is one EXE. The GPU edition contains the EXE and all `WingScribe-Setup-GPU-3.0.0-N.bin` parts. Keep the original names and put the parts in one directory. The accompanying `.sha256.json` for your edition lists each file's size and SHA-256. You can compare a downloaded file using `Get-FileHash -Algorithm SHA256 <filename>` in PowerShell.

Run the EXE. The installer includes Python and ExifTool. It checks for the Microsoft Visual C++ x64 v14 runtime, with 14.51.36247 as the tested minimum. If prompted, complete the Microsoft installer and close its completion window to let WingScribe setup continue. If Windows requests a restart, restart when convenient and run setup again. Unattended installation requires the runtime to be present first.

Start the desktop or Start menu shortcut. Leave the server window open and visit `http://127.0.0.1:8000/settings` in a browser on that computer. For local recognition, allow space for the selected model in addition to the application. YOLO weights are bundled. BioCLIP weights are a separate download. After preparing the model locally, the recognition workflow can run offline.

## Upgrade from 2.3.1

1. Stop active processing and wait for workers to finish. Close WingScribe and any other process using its database. Record the actual source, output, and database paths.
2. Copy the configuration directory, including private `settings.yaml` and `secrets.yaml`, the closed database directory, and backups to a location outside the installation. Back up your photo sources and archives separately. Older uninstallers can remove data kept inside the old installation directory.
3. Install 3.0.0 into a **new, empty directory**. If setup detects a legacy uninstall log, return to directory selection. Keep the old installation available until you have checked the new one.
4. For a fresh start, choose a new local database and output directory. Run a small batch of copies and review the results. To keep historical labels, preview the [catalogue migration](#species-catalogue-and-migration) on a copy of the database before applying it.
5. To roll back, stop 3.0.0 and use the older application with the configuration and database you backed up. Give each installation its own database and output directory while comparing them.

## Configure paths and recognition

In **设置** (Settings), **照片基准目录** is the photo source and **输出目录** is the archive destination. Use **选择文件夹** (Choose folder) or **选择文件** (Choose file), or type the path. Selecting a path fills the field. Save and restart the service to apply it. Missing or invalid configuration leaves the settings page accessible and blocks processing. If an existing YAML file is malformed, repair it before saving.

The following excerpt shows the main fields for a Windows installation. Adapt the paths to your machine. The [settings example](../../config/settings.example.yaml) contains the remaining sections.

```yaml
paths:
  sources:
    - path: "D:/BirdPhotos/Originals"
      recursive: true
      enabled: true
  output:
    root_dir: "D:/BirdPhotos/Archive"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false
  db_path: "data/db/wingscribe.db"
processing:
  device: "auto"
recognition:
  mode: "local"
  local:
    model_type: "bioclip-2"
web:
  host: "127.0.0.1"
  port: 8000
```

Use absolute paths for sources and outputs. A separate destination keeps a scan from consuming its own archive. Keep SQLite on local storage. The database picker accepts an existing file or a new filename. Cancel leaves the field unchanged. On a new installation, Basic settings prefills the full database path under `%LOCALAPPDATA%\WingScribe\data\wingscribe.db`. It remains in the user data directory after application uninstall. Existing configurations keep their original database location. An omitted or blank legacy path continues to refer to `data/db/wingscribe.db` under the application directory. For a NAS, connect the share using the same account that starts WingScribe. Use a path such as `Z:/Birds`, `\\server\photos`, or a mounted directory on Linux. A mapped drive in your desktop session may be invisible to a background service. After a share outage, restore access and start another scan. History is retained, and unchanged work can be reused.

`processing.device` selects `auto`, `cpu`, or `cuda`. `recognition.top_k` controls the number of species suggestions. Processing quality options affect the archiving pipeline; burst focus ranking is a separate tool. Keep API credentials in `config/secrets.yaml` following the [secrets example](../../config/secrets.example.yaml). Keep the Web UI and recognition endpoints on localhost or a trusted network.

### Archive naming and model files

`{source_structure}` preserves the folder hierarchy below the source. `{filename}` is the original stem. Use `{species_sci}` for the scientific name or `{species_cn}` for the Chinese display name. `{confidence}` produces a string such as `85pct`. The `{date}`, `{year}`, `{month}`, `{day}` and `{location}` fields come from parsed shoot metadata. Try a template on a test output folder before adopting it for a library.

The example configuration selects `bioclip-2`. For an offline setup, prepare that model's weights under `data/models/bioclip-2/` in the application directory. The legacy `scripts/download_model.py` helper fetches the original `imageomics/bioclip` model. Check which model you selected before using a cached download. A first recognition run may spend several minutes building text features even when the weights are already on disk.

## Scan and correct species

1. Put a few JPEG copies into a shoot folder, for example `20261001_Park`. In the administration page (`/admin`), select that folder or a date range and start processing. Watch the job log for the first failure if a scan is incomplete. Stopping a job waits for work already in progress. Start a new scan after correcting a problem.
2. Open the gallery (`/`) to inspect the detected subject, crop and candidate species. A high ranking is a suggestion. An image with no bird detected may produce no archive file.
3. Confirm or correct the species in the gallery. WingScribe updates the database, can rename the archived image using the output template, and writes metadata to the image. **Manual correction also attempts to update an accessible original.** `paths.output.write_back_to_source` controls automatic pipeline writes only.

From a source checkout with the environment active, run the following command to process the configured sources. For a date-limited run, set the date range on the administration page.

```powershell
python src/pipeline_runner.py
```

## Cull a JPEG burst

Open **选片** (Culling) from the gallery. Choose an enabled source and optionally a subfolder. A blank subfolder scans the entire source recursively. Start with a single shoot on a large NAS. Choose the maximum gap between adjacent frames and the maximum group duration. Five seconds and thirty seconds are useful initial values. Open the completed analysis under **已保存的分析** (Saved analyses).

| On-screen mode | What you get |
| --- | --- |
| 稳妥推荐 — Conservative | Up to three recommendations per group. Groups with a large difference in subject scale may be left for manual comparison. |
| 辅助比较 — Compare candidates | Ordered candidates and cautions for you to review. |
| 宽松推荐（实验） — Permissive (experimental) | Up to three suggestions even when subject scales differ. Check the crops before choosing. |

The largest detected bird is the default scoring subject. Under **查看／改选评分主体**, pick a different existing box and apply to rescore that photo. If no bird was detected, review the full image. Use the side-by-side crop view at 100% for native pixels. Small differences can be visually indistinguishable. RAW is outside the current culling workflow.

Save **保留** (Keep), **待定** (Undecided), or **拒绝** (Reject) and optional notes per photo. Group mode overrides do not alter these decisions. You can split a selection into a new group or merge two or more groups. Edits create a revision and preserve the parent for inspection. Saved decisions follow the same file version across reruns. A new analysis does not automatically inherit a manually chosen subject or revised grouping.

Closing the page leaves a running analysis active. Stopping waits for the current image. A compatible cached score is reused when the full file hash, version, and analysis settings match. WingScribe still reads and decodes the JPEG, so a NAS rerun can take time.

### Quarantine and restore on Windows

A saved Reject decision leaves the file in place. To move it, open **预览拒绝原片清单** (Preview rejected originals), review the paths and count, then confirm. Only explicitly rejected JPEGs in the selected result qualify. The destination is `.wingscribe-quarantine/<operation-id>/` on the same source, preserving relative paths. Keep the database and quarantine directory together for recovery.

Check each item's result. A file lock or disconnected share can leave a partially completed operation. Restore access and use the reconcile/retry action for unfinished items. In **隔离历史** (Quarantine history), preview the restore list before confirming. An occupied destination must be resolved first. Previously archived crops are retained. There is no permanent-delete or empty-quarantine action.

## Species catalogue and migration

New libraries use AviList v2025b with 11,131 species. The catalogue includes scientific and English names. Chinese display names come from IOC 15.1 where scientific names match; unmatched entries fall back to the scientific name. Use the [catalogue manifest](../../data/references/avilist-v2025b.json) for attribution, source hashes and the CC BY 4.0 license. Matching a name alone does not resolve the historical scope of a split or merged species.

For an existing IOC library, stop all writers and run the preview on a database copy. From the repository root with the source environment active:

```powershell
python scripts/migrate_avilist.py --database data/db/wingscribe.db --report data/backups/avilist-preview.json
python scripts/migrate_avilist.py --database data/db/wingscribe.db --apply --backup-dir data/backups --report data/backups/avilist-migration.json
```

Review the first report before running the second command. Migration keeps historical photo labels and records legacy names for review. For rollback, stop the application, keep a copy of the current database, and restore the report's `pre_schema_backup` to the original database path. A region list with no matching taxonomy version falls back to the full candidate set.

## Source installation and recognition API

Install uv and ExifTool, then follow the [source commands in the README](../../README.en.md#run-from-source). On Linux, activate with `source .venv/bin/activate`. The lock covers Windows and Linux. For Windows source runs, you can set `$env:EXIFTOOL_PATH = (Resolve-Path installer/tools/exiftool.exe).Path`. Run `python -m pytest` in the activated development environment. The main code areas are `src/core`, `src/recognition`, `src/metadata`, `src/storage`, `src/application`, and `src/web`.

| Service | Command | Local single-image route |
| --- | --- | --- |
| Full Web UI | `python src/web/app.py --host 127.0.0.1 --port 8000` | `POST /api/recognition/recognize` |
| Standalone recognition | `python src/recognition_service.py` | `POST /api/recognize` |

Start one service per port. Open `/docs` on the running service for its request schema. For example, send the following JSON body using a path readable by the **server**:

```json
{"platform":"local","image_path":"D:/BirdPhotos/Originals/example.jpg","top_k":5,"timeout":60}
```

Supply exactly one image source. The local adapter accepts a server path or raw Base64. `top_k` ranges from 1 to 20 and `timeout` from 1 to 300 seconds. The full Web service also accepts `POST /api/recognition/batch` with an `images` array of up to 1,000 requests. Poll `/api/recognition/batch/{batch_id}` and `/api/recognition/batch/{batch_id}/result`. These API batch jobs are held in memory. Persisted photo scan jobs are separate. Cloud adapters have separate credential schemas and have not undergone live service acceptance for this release.

### Command-line culling and maintenance

From the source environment, this example runs culling on a single local shoot using a dedicated test database. The gap and span values are in seconds. Run from the repository root and substitute your own paths.

```powershell
python scripts/run_culling.py --source "D:/BirdPhotos/TestShoot" --db "D:/BirdPhotos/TestDB/culling.db" --backup-dir "D:/BirdPhotos/TestDB/backups" --model "installer/models/yolo26n.pt" --device cpu --gap 5 --span 30
```

For development, the dependency versions are locked in `uv.lock`. Install one hardware variant per environment. Run `python -m pytest` for the full suite or `python -m pytest tests/test_path_parser.py -v` for path parsing. Windows package sources are in `installer/`. The installer build instructions and version-specific engineering verification logs are in the [Chinese documentation index](../README.md).

### Location dictionaries and optional backends

The read-only `POST /api/location/preview` endpoint accepts a JSON object with a `locations` array of 1–100 strings. It can use `config/dictionaries/location_aliases.yaml` and `config/dictionaries/china_admin_divisions.csv`. Use the supplied `.example` files as format examples. Specific aliases take priority; ambiguous entries can use parent folder text to disambiguate. Previewing a location leaves the stored location and recognition results unchanged.

The batch photo pipeline reads `recognition.mode` (`local`, `api` or `dongniao`). For the latter two, the corresponding `recognition.api` or `recognition.dongniao` section carries `url` and `key`. The separate REST adapters use `cloud.*` entries in the secrets file. Local recognition is the tested path. Treat remote services as optional integrations requiring their own validation.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| First run shows settings or processing returns HTTP 409 | Fill in valid source and output paths, save, restart. Inspect existing YAML for syntax errors. |
| First identification takes much longer than the next | Check model availability and the text-encoding log. The first run may encode all 11,131 candidate names. |
| CUDA is unavailable or memory is exhausted | From source, run `python scripts/check_gpu.py` in the active environment. Check the driver and selected build. Select `processing.device: cpu` to run on CPU. |
| Metadata cannot be read or written | From source, check `exiftool -ver` in the launch environment. In an installation, check `tools/` and file permissions. |
| Images disappear after moving to a share | Confirm the configured absolute path and access from the WingScribe process's account. Reconnect the share and scan again. |
| A reject did not move, or a restore is blocked | Review the per-item result, file hash and destination conflict in quarantine history. |
| You need a backup | Stop writers and back up the local database directory, configuration, source photos, outputs, and any quarantine directories. A database backup contains the index, not the JPEGs. |
