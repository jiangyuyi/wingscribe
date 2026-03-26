import logging
import sys
import shutil
import os
import gc
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List

# Add project root to path for imports
BASE_DIR = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(BASE_DIR))

from src.metadata.exif_writer import ExifWriter
from src.utils.config_loader import load_config, validate_paths_config
from src.core.io.path_generator import PathGenerator
from src.web.routes.recognition import router as recognition_router
from src.web import task_manager as task_manager_module
from src.web.task_manager import TaskManager as ExtractedTaskManager
from src.web import taxonomy_service
from src.web import pipeline_service
from src.web import admin_service
from src.web.config_helpers import (
    get_config_definition,
    get_nested_value,
    set_nested_value,
)
from src.web import path_helpers
from src.web import config_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize ExifWriter
exif_writer = ExifWriter()

TaskManager = ExtractedTaskManager
threading = task_manager_module.threading
task_manager = TaskManager.get_instance()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_app_db()
    logger.info("Application started.")
    yield
    # Shutdown
    logger.info("Application shutting down...")
    if task_manager.is_running:
        logger.info("Stopping pipeline...")
        task_manager.stop()

app = FastAPI(lifespan=lifespan)

# Load config
config = load_config(str(BASE_DIR / "config" / "settings.yaml"), str(BASE_DIR / "config" / "secrets.yaml"))

# Validate paths configuration
is_valid, errors = validate_paths_config(config)
if not is_valid:
    logger.error(f"Configuration validation failed: {errors}")
    for err in errors:
        logger.error(f"  - {err}")
    raise ValueError(f"Invalid paths configuration: {errors}")

# Get source directories for raw photo path resolution
sources = config['paths'].get('sources', [])
source_dirs = [
    Path(src.get('path'))
    for src in sources
    if src.get('path')
]
source_dir = ''
if sources and len(sources) > 0:
    source_dir = sources[0].get('path', '')
if source_dir:
    source_dir = Path(source_dir)

# Server startup parameters (used for restart)
_startup_host = None
_startup_port = None
_startup_python = sys.executable

# Helper function to check if path is absolute (handles both Windows and Unix formats)
def is_absolute_path(p: str) -> bool:
    """Check if path is absolute, including Windows drive letter format like 'Y:/path'"""
    return path_helpers.is_absolute_path(p)

# Resolve db_path - relative to current working directory if not set or empty
db_path_config = config['paths'].get('db_path')
if not db_path_config:
    # Default: relative to current working directory
    db_path = Path('data/db/wingscribe.db')
elif is_absolute_path(db_path_config):
    db_path = Path(db_path_config)
else:
    db_path = Path(db_path_config)

# Ensure database directory exists
db_path.parent.mkdir(parents=True, exist_ok=True)

# Handle output.root_dir - allow empty for first-run setup
output_root = config['paths']['output'].get('root_dir', '')
processed_dir = Path(output_root) if output_root else None

logger.info(f"Project Base Directory: {BASE_DIR}")
logger.info(f"Photo Source Directory: {source_dir}")
logger.info(f"Database Path: {db_path}")
logger.info(f"Processed Images Directory: {processed_dir}")

if processed_dir and not processed_dir.exists():
    logger.error(f"Processed directory does not exist: {processed_dir}")
    processed_dir.mkdir(parents=True, exist_ok=True)

# Note: Using custom route for /processed (see serve_processed_file above)
app.include_router(recognition_router)

# Mount library static files (Bootstrap, icons, etc.) - does not depend on source_dir
lib_static_dir = BASE_DIR / "src" / "web" / "static"
if lib_static_dir.exists():
    app.mount("/lib", StaticFiles(directory=str(lib_static_dir), follow_symlink=True), name="lib")

templates = Jinja2Templates(directory=str(BASE_DIR / "src" / "web" / "templates"))

# --- Initialization ---
# Call explicitly
def init_app_db():
    try:
        mgr = create_db_manager()
        mgr.close()
        del mgr
        gc.collect()
    except Exception as e:
        logger.error(f"Startup DB Initialization failed: {e}")

def create_db_manager():
    return path_helpers.create_db_manager(db_path, source_dir, processed_dir)

# --- Helper ---
def get_db_conn():
    return path_helpers.get_db_conn(db_path)

def resolve_web_path(original_path_str: str) -> Optional[str]:
    """Resolves raw file path to /raw/... URL"""
    return path_helpers.resolve_web_path(original_path_str, source_dirs, logger)

@app.get("/raw/{path:path}")
def serve_raw_file(path: str):
    """Custom file handler for original images across multiple source roots."""
    return path_helpers.get_raw_file_response(path, source_dirs)

@app.get("/processed/{path:path}")
def serve_processed_file(path: str):
    """Custom static file handler for processed images (Unicode-safe on Windows)"""
    return path_helpers.get_processed_file_response(path, processed_dir)

def resolve_processed_web_path(file_path_str: str) -> Optional[str]:
    """Resolves processed file path to /processed/... URL"""
    return path_helpers.resolve_processed_web_path(file_path_str, processed_dir, BASE_DIR, logger)

# --- API Models ---
class UpdateLabelRequest(BaseModel):
    photo_id: int
    scientific_name: str
    chinese_name: str

class StartPipelineRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class StartPipelineByFoldersRequest(BaseModel):
    paths: List[str]
    recursive: bool = True

# --- Routes ---

# First-run detection helper
def is_first_run():
    """Check if this is the first run (no config file)"""
    config_path = BASE_DIR / "config" / "settings.yaml"
    return not config_path.exists()

def is_paths_configured():
    """Check if source and output paths are configured (not empty)"""
    global source_dir
    global output_root
    return bool(source_dir) and bool(output_root)

@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", filter: str = "", date: str = "", limit: int = 50, offset: int = 0, skip_first_check: bool = False):
    # Check for first run or empty paths - redirect to settings if not configured
    if not skip_first_check and (is_first_run() or not is_paths_configured()):
        return templates.TemplateResponse(
            name="settings.html",
            context={"request": request, "is_first_run": is_first_run()},
        )

    conn = get_db_conn()
    cursor = conn.cursor()
    
    query_parts = []
    params = []
    
    if q:
        query_parts.append('(primary_bird_cn LIKE ? OR scientific_name LIKE ? OR location_tag LIKE ? OR captured_date LIKE ?)')
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
    
    if filter == 'uncertain':
        query_parts.append('(primary_bird_cn = ? OR scientific_name = ?)')
        params.extend(['待确认鸟种', 'Uncertain'])
    
    if date:
        query_parts.append('captured_date = ?')
        params.append(date)
    
    where_clause = "WHERE " + " AND ".join(query_parts) if query_parts else ""
    
    # Get total count for pagination
    count_sql = f'SELECT COUNT(*) FROM photos {where_clause}'
    cursor.execute(count_sql, params)
    total_count = cursor.fetchone()[0]
    
    # Get photos
    sql = f'SELECT * FROM photos {where_clause} ORDER BY captured_date DESC, id DESC LIMIT ? OFFSET ?'
    cursor.execute(sql, params + [limit, offset])
    photos = cursor.fetchall()
    
    display_photos = []
    for p in photos:
        p_dict = dict(p)
        p_dict['web_raw_path'] = resolve_web_path(p_dict.get('original_path'))
        p_dict['web_processed_path'] = resolve_processed_web_path(p_dict.get('file_path'))
        display_photos.append(p_dict)

    # Get available dates for filter dropdown
    cursor.execute("SELECT DISTINCT captured_date FROM photos ORDER BY captured_date DESC")
    available_dates = [row[0] for row in cursor.fetchall() if row[0]]

    conn.close()
    
    # Pagination helpers
    has_next = (offset + limit) < total_count
    has_prev = offset > 0
    next_offset = offset + limit
    prev_offset = max(0, offset - limit)
    
    return templates.TemplateResponse(
        name="index.html",
        context={
            "request": request,
            "photos": display_photos,
            "query": q,
            "current_filter": filter,
            "current_date": date,
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "available_dates": available_dates,
            "has_next": has_next,
            "has_prev": has_prev,
            "next_offset": next_offset,
            "prev_offset": prev_offset,
        },
    )

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return admin_service.admin_dashboard(request, templates, is_paths_configured, get_stats)

def get_stats():
    return admin_service.get_stats(get_db_conn)

@app.get("/api/stats")
def get_api_stats():
    return get_stats()

@app.get("/api/scan_history")
def get_scan_history():
    return admin_service.get_scan_history(create_db_manager)

@app.post("/api/pipeline/start")
def start_pipeline(req: StartPipelineRequest):
    return pipeline_service.start_pipeline(task_manager, req)

@app.get("/api/pipeline/folders")
def get_folder_tree():
    """获取 sources 配置的文件夹树形结构（只返回第一层）"""
    return pipeline_service.get_folder_tree(config, logger, _build_folder_tree)


@app.get("/api/pipeline/folders/{full_path:path}")
def get_folder_children(full_path: str):
    """获取指定路径的子目录（懒加载）"""
    return pipeline_service.get_folder_children(full_path, logger, _build_folder_tree)

def _build_folder_tree(root_path: Path, recursive: bool, base_rel_path: str = "", max_depth: int = 5, current_depth: int = 0):
    """递归构建文件夹树

    Args:
        root_path: 绝对路径的根目录
        recursive: 是否递归扫描子目录
        base_rel_path: 相对于 source_dir 的基础路径
    """
    return pipeline_service.build_folder_tree(
        root_path,
        recursive,
        base_rel_path=base_rel_path,
        max_depth=max_depth,
        current_depth=current_depth,
        logger=logger,
    )

@app.post("/api/pipeline/start_by_folders")
def start_pipeline_by_folders(req: StartPipelineByFoldersRequest):
    """按文件夹执行 Pipeline"""
    return pipeline_service.start_pipeline_by_folders(task_manager, req, logger)


@app.post("/api/pipeline/stop")
def stop_pipeline():
    return pipeline_service.stop_pipeline(task_manager)

@app.websocket("/ws/progress")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        last_index = 0
        while True:
            current_len = len(task_manager.logs)
            if current_len > last_index:
                new_logs = task_manager.logs[last_index:current_len]
                for log in new_logs:
                    await websocket.send_text(log)
                last_index = current_len
            
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        # Handle server shutdown cancellation
        pass
    except Exception as e:
        # Expected disconnect or other error
        pass

@app.get("/download_raw")
def download_raw(path: str):
    return admin_service.download_raw()

@app.post("/api/admin/reset")
def reset_system():
    return admin_service.reset_system(
        config,
        BASE_DIR,
        db_path,
        processed_dir,
        init_app_db,
        create_db_manager,
        logger,
    )

@app.get("/api/admin/rebuild_stats")
def rebuild_species_stats():
    return admin_service.rebuild_species_stats(create_db_manager)

@app.get("/api/search_species")
def search_species(q: str):
    return taxonomy_service.search_species(create_db_manager, q)

@app.get("/api/taxonomy/tree")
def get_taxonomy_tree(include_empty: bool = True, date: str = None):
    """获取分类树，支持显示/隐藏空层级和日期筛选"""
    return taxonomy_service.get_taxonomy_tree(create_db_manager, include_empty, date)

@app.get("/api/taxonomy/stats")
def get_taxonomy_stats(level: str, date: str = None):
    """按层级统计物种数量（order/family/genus/species）"""
    return taxonomy_service.get_taxonomy_stats(create_db_manager, level, date)

@app.get("/api/photos/by_taxonomy")
def get_photos_by_taxonomy(
    order_cn: Optional[str] = None,
    order_sci: Optional[str] = None,
    family_cn: Optional[str] = None,
    family_sci: Optional[str] = None,
    genus_cn: Optional[str] = None,
    genus_sci: Optional[str] = None,
    scientific_name: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """按分类层级筛选照片，支持中文和拉丁名参数"""
    return taxonomy_service.get_photos_by_taxonomy(
        create_db_manager,
        get_db_conn,
        resolve_web_path,
        resolve_processed_web_path,
        order_cn=order_cn,
        order_sci=order_sci,
        family_cn=family_cn,
        family_sci=family_sci,
        genus_cn=genus_cn,
        genus_sci=genus_sci,
        scientific_name=scientific_name,
        date=date,
        limit=limit,
        offset=offset,
    )

@app.get("/api/taxonomy/search")
def search_taxonomy(q: str, limit: int = 20):
    """搜索分类信息（支持目、科、属、物种）"""
    return taxonomy_service.search_taxonomy(create_db_manager, q, limit)

@app.post("/api/update_label")
def update_label(req: UpdateLabelRequest):
    manager = create_db_manager()
    moved_from = None
    photo = {}
    final_processed_path = None
    try:
        cursor = manager.conn.execute("SELECT * FROM photos WHERE id = ?", (req.photo_id,))
        photo = cursor.fetchone()

        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        photo = dict(photo)
        old_scientific_name = photo.get("scientific_name")
        stored_processed_path = photo.get("file_path")
        stored_filename = photo.get("filename")

        if photo.get('file_path'):
            photo['file_path'] = manager.resolve_processed_path(photo['file_path'])
        if photo.get('original_path'):
            photo['original_path'] = manager.resolve_original_path(photo['original_path'])

        bird_info = manager.get_bird_info(req.scientific_name)
        family_cn = bird_info['family_cn'] if bird_info else ""

        user_comment = req.chinese_name
        try:
            candidates = []
            if 'candidates_json' in photo and photo['candidates_json']:
                candidates = json.loads(photo['candidates_json'])

            if candidates:
                alt_threshold = config.get('recognition', {}).get('alternatives_threshold', 70)
                comment_lines = []
                top_score = candidates[0].get('score', 0) * 100 if candidates else 0
                show_alternatives = (top_score <= alt_threshold)
                display_list = candidates if show_alternatives else [candidates[0]]

                for i, cand in enumerate(display_list):
                    c_sci = cand.get('sci')
                    c_cn = cand.get('cn')
                    c_conf = cand.get('score', 0) * 100

                    if i == 0:
                        comment_lines.append(f"AI Top: {c_cn} ({c_sci}) - {c_conf:.1f}%")
                        if show_alternatives and len(display_list) > 1:
                            comment_lines.append("Alternatives:")
                    else:
                        comment_lines.append(f"{i}. {c_cn} ({c_sci}) - {c_conf:.1f}%")

                if candidates[0].get('sci') != req.scientific_name:
                    comment_lines.insert(0, f"[Manual Correction] Current: {req.chinese_name}")

                user_comment = "&#xa;".join(comment_lines)
        except Exception as e:
            logger.error(f"Failed to reconstruct UserComment: {e}")
            user_comment = req.chinese_name

        description = f"{req.chinese_name} ({req.scientific_name})"
        tags = {
            "IPTC:Keywords": [req.chinese_name, photo['location_tag'], family_cn, req.scientific_name],
            "XMP:Description": description,
            "XPTitle": description,
            "XPSubject": "",
            "ImageDescription": description,
            "UserComment": user_comment
        }

        processed_path = photo.get('file_path')
        final_processed_path = processed_path

        if processed_path and os.path.exists(processed_path):
            out_conf = config.get('paths', {}).get('output', {})
            template = out_conf.get('structure_template', "")

            if any(x in template for x in ["{species_cn}", "{species_sci}", "{confidence}"]):
                source_structure = "."
                if photo.get('original_path'):
                    orig_path_obj = Path(photo['original_path'])
                    sources = config.get('paths', {}).get('sources', [])
                    for src in sources:
                        try:
                            src_path = Path(src['path']).resolve()
                            if src_path in orig_path_obj.parents:
                                rel = orig_path_obj.parent.relative_to(src_path)
                                source_structure = str(rel).replace('\\', '/')
                                break
                        except Exception:
                            continue

                gen_meta = {
                    'captured_date': photo['captured_date'],
                    'location_tag': photo['location_tag'],
                    'primary_bird_cn': req.chinese_name,
                    'scientific_name': req.scientific_name,
                    'confidence_score': 1.0,
                    'source_structure': source_structure
                }

                output_root_raw = out_conf.get('root_dir', '') or processed_dir
                generator = PathGenerator(
                    template=template,
                    output_root=str(Path(output_root_raw))
                )

                orig_filename = photo.get('filename')
                if photo.get('original_path'):
                    orig_filename = Path(photo['original_path']).name

                new_path = generator.generate_path(gen_meta, orig_filename)
                if Path(new_path).resolve() != Path(processed_path).resolve():
                    new_path.parent.mkdir(parents=True, exist_ok=True)

                    final_path = new_path
                    if final_path.exists() and final_path.resolve() != Path(processed_path).resolve():
                        stem = final_path.stem
                        counter = 1
                        while final_path.exists():
                            final_path = final_path.with_name(f"{stem}_{counter}.jpg")
                            counter += 1

                    shutil.move(processed_path, final_path)
                    moved_from = processed_path
                    final_processed_path = str(final_path)
                    stored_processed_path = manager.to_storage_processed_path(str(final_path))
                    stored_filename = final_path.name
                    logger.info(f"Renamed file to: {final_path}")

        if final_processed_path and os.path.exists(final_processed_path):
            if not exif_writer.write_metadata(final_processed_path, tags):
                raise RuntimeError("Failed to update metadata for processed image")

        original_path = photo.get('original_path')
        if original_path and os.path.exists(original_path):
            source_tags = tags.copy()
            source_tags["IPTC:Keywords"] = source_tags["IPTC:Keywords"] + ["WingScribe"]
            if not exif_writer.write_metadata(original_path, source_tags):
                raise RuntimeError("Failed to update metadata for original image")

        manager.conn.execute(
            '''
            UPDATE photos
            SET scientific_name = ?, primary_bird_cn = ?, confidence_score = ?, file_path = ?, filename = ?
            WHERE id = ?
            ''',
            (
                req.scientific_name,
                req.chinese_name,
                1.0,
                stored_processed_path,
                stored_filename,
                req.photo_id
            )
        )
        manager.conn.commit()

        if old_scientific_name:
            manager.update_species_stats_for_photo(old_scientific_name)
        if req.scientific_name:
            manager.update_species_stats_for_photo(req.scientific_name)

        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        if moved_from and final_processed_path and os.path.exists(final_processed_path) and not os.path.exists(moved_from):
            try:
                shutil.move(final_processed_path, moved_from)
            except Exception as rollback_error:
                logger.error(f"Failed to roll back renamed file: {rollback_error}")
        logger.error(f"Failed to update label for photo {req.photo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        manager.close()

# --- Configuration Management ---
class ConfigItem(BaseModel):
    key: str
    value: str
    section: str
    type: str = "string"  # string, int, float, bool

class SaveConfigRequest(BaseModel):
    configs: List[ConfigItem]
    restart: bool = False

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Configuration page"""
    return templates.TemplateResponse(name="settings.html", context={"request": request})

@app.get("/api/config")
async def get_config():
    """Get current configuration"""
    return config_service.get_config(BASE_DIR, get_config_definition)

@app.post("/api/config/save")
async def save_config(req: SaveConfigRequest):
    """Save configuration to file"""
    return config_service.save_config(req, BASE_DIR, set_nested_value)

@app.post("/api/config/restart")
async def restart_server():
    """Restart the server by spawning a new process and exiting current one"""
    return config_service.restart_server(
        BASE_DIR,
        config,
        _startup_host,
        _startup_port,
        _startup_python,
        logger,
    )

@app.get("/api/config/validate")
async def validate_config_path(path: str, path_type: str = "directory"):
    """Validate if a path exists and is accessible

    Args:
        path: The path to validate
        path_type: Expected type - "directory" or "file"
    """
    return config_service.validate_config_path(path, path_type)


def open_folder_dialog(title: str, initial_dir: str = "") -> str:
    return config_service.open_folder_dialog(title, initial_dir)


def open_file_dialog(title: str, initial_file: str = "", file_types: str = "") -> str:
    return config_service.open_file_dialog(title, initial_file, file_types)

@app.post("/api/config/browse_folder")
async def browse_folder_api(title: str = "选择文件夹", initial_path: str = ""):
    """API endpoint to open folder selection dialog"""
    try:
        folder_path = await asyncio.to_thread(open_folder_dialog, title, initial_path)
        return {"path": folder_path}
    except Exception as e:
        return {"error": str(e), "path": None}

@app.post("/api/config/browse_file")
async def browse_file_api(title: str = "选择文件", initial_path: str = "", file_types: str = "xlsx|xls"):
    """API endpoint to open file selection dialog"""
    try:
        file_path = await asyncio.to_thread(open_file_dialog, title, initial_path, file_types)
        return {"path": file_path}
    except Exception as e:
        return {"error": str(e), "path": None}

if __name__ == "__main__":
    import argparse
    import uvicorn
    import subprocess
    import time

    parser = argparse.ArgumentParser(description='WingScribe Web Server')
    parser.add_argument('--host', type=str, default=None, help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to bind to')
    args = parser.parse_args()

    # Use command line args if provided, otherwise fall back to config
    host = args.host if args.host else config['web']['host']
    port = args.port if args.port else config['web']['port']

    # Save startup parameters for restart (globals already declared at module level)
    _startup_host = host
    _startup_port = port

    uvicorn.run(app, host=host, port=port)
