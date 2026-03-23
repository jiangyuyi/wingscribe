import logging
import sqlite3
import sys
import yaml
import shutil
import os
import gc
import asyncio
import threading
import json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List

# Add project root to path for imports
BASE_DIR = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(BASE_DIR))

from src.metadata.ioc_manager import IOCManager
from src.metadata.exif_writer import ExifWriter # Added import
from src.utils.config_loader import load_config, validate_paths_config
from src.pipeline_runner import WingScribePipeline # Import Pipeline
from src.core.io.path_generator import PathGenerator # Added import
from src.web.routes.recognition import router as recognition_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize ExifWriter
exif_writer = ExifWriter()

# --- Task Manager (Background Pipeline) ---
class TaskManager:
    _instance = None
    
    def __init__(self):
        self.is_running = False
        self.should_stop = False # New flag
        self.logs = []
        self.websocket_clients = []
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance
        
    def stop(self):
        self.should_stop = True

    def broadcast_log(self, message: str):
        self.logs.append(message)
        if len(self.logs) > 1000: self.logs.pop(0)
        
    def start_pipeline(self, start_date=None, end_date=None):
        logger.info(f"[TaskManager] start_pipeline called with start_date={start_date}, end_date={end_date}")
        if self.is_running:
            logger.warning("[TaskManager] Pipeline already running, rejecting request")
            return False

        self.is_running = True
        self.logs = ["Starting pipeline..."]
        logger.info("[TaskManager] Pipeline flag set, starting thread...")

        # Run in thread
        thread = threading.Thread(target=self._run_pipeline_thread, args=(start_date, end_date), daemon=True)
        thread.start()
        logger.info("[TaskManager] Thread started, returning success")
        return True

    def start_pipeline_by_folders(self, folder_paths: list, recursive: bool = True):
        """按文件夹执行 Pipeline"""
        logger.info(f"[TaskManager] start_pipeline_by_folders called with paths={folder_paths}, recursive={recursive}")
        if self.is_running:
            logger.warning("[TaskManager] Pipeline already running, rejecting request")
            return False

        self.is_running = True
        self.logs = ["Starting pipeline for selected folders..."]
        logger.info("[TaskManager] Pipeline flag set, starting thread...")

        # Run in thread
        thread = threading.Thread(target=self._run_pipeline_thread_by_folders, args=(folder_paths, recursive), daemon=True)
        thread.start()
        logger.info("[TaskManager] Thread started, returning success")
        return True

    def _run_pipeline_thread_by_folders(self, folder_paths: list, recursive: bool):
        try:
            # Ensure working directory is project root for relative path resolution
            os.chdir(str(BASE_DIR))

            # Setup custom logger to capture output
            log_capture = logging.getLogger()
            handler = ListLogHandler(self.logs)
            log_capture.addHandler(handler)

            self.logs.append("Initializing pipeline (this may take a while on first run)...")

            # Create pipeline with timeout protection (120 seconds default)
            runner = WingScribePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

            # 设置进度回调
            def progress_callback(processed, total):
                self.logs.append(f"[PROGRESS] {processed}/{total}")
            runner.set_progress_callback(progress_callback)

            self.logs.append("Pipeline initialized, processing selected folders...")

            runner.run_by_folders(folder_paths, recursive=recursive)

            logging.info("Pipeline (by folders) execution completed.")
        except Exception as e:
            logging.error(f"Pipeline failed: {e}")
            self.logs.append(f"Error: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)

    def _run_pipeline_thread(self, start_date, end_date):
        try:
            # Ensure working directory is project root for relative path resolution
            os.chdir(str(BASE_DIR))

            # Setup custom logger to capture output
            log_capture = logging.getLogger()
            handler = ListLogHandler(self.logs)
            log_capture.addHandler(handler)

            self.logs.append("Initializing pipeline (this may take a while on first run)...")

            # Create pipeline with timeout protection (120 seconds default)
            runner = WingScribePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

            # 设置进度回调
            def progress_callback(processed, total):
                self.logs.append(f"[PROGRESS] {processed}/{total}")
            runner.set_progress_callback(progress_callback)

            self.logs.append("Pipeline initialized, starting processing...")

            runner.run(start_date=start_date, end_date=end_date)

            logging.info("Pipeline execution completed.")
        except Exception as e:
            logging.error(f"Pipeline failed: {e}")
            self.logs.append(f"Error: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)

class ListLogHandler(logging.Handler):
    def __init__(self, log_list):
        super().__init__()
        self.log_list = log_list
    
    def emit(self, record):
        msg = self.format(record)
        self.log_list.append(msg)

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

# Get source directory (photo base directory) for path resolution
sources = config['paths'].get('sources', [])
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
    if not p:
        return False
    # Check for Unix absolute path
    if p.startswith('/'):
        return True
    # Check for Windows drive letter format (Y:/ or Y:\ or //server/path)
    if len(p) >= 2 and p[1] == ':':
        return True
    # Check for UNC path
    if p.startswith('//') or p.startswith('\\\\'):
        return True
    return False

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

# Mount source directory for "Original View" - use follow_symlink=True for Unicode path support
if source_dir and source_dir.exists():
    app.mount("/static", StaticFiles(directory=str(source_dir), follow_symlink=True), name="static")

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
    return IOCManager(
        str(db_path),
        source_base_dir=str(source_dir) if source_dir else "",
        processed_base_dir=str(processed_dir) if processed_dir else ""
    )

# --- Helper ---
def get_db_conn():
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def resolve_web_path(original_path_str: str) -> Optional[str]:
    """Resolves raw file path to /static/... URL"""
    if not original_path_str:
        logger.warning(f"resolve_web_path: empty path")
        return None
    try:
        # Normalize path separators to avoid escape sequence issues
        normalized = original_path_str.replace('\\', '/')

        # Handle relative paths - convert to absolute using source_dir
        # 不使用 resolve()，避免UNC路径问题（与pipeline_runner.py一致）
        if source_dir and not is_absolute_path(normalized):
            abs_path = source_dir / normalized
        else:
            abs_path = Path(normalized)

        # 使用规范化路径比较，不使用resolve()
        norm_abs = os.path.normpath(str(abs_path))
        norm_base = os.path.normpath(str(source_dir)) if source_dir else None

        logger.debug(f"resolve_web_path: input='{original_path_str}', normalized='{normalized}', abs_path='{abs_path}', norm_base={norm_base}")

        # 基于 source_dir 计算相对路径
        if norm_base and norm_abs.startswith(norm_base):
            # 提取相对路径部分
            rel_part = norm_abs[len(norm_base):].lstrip('/\\')
            result = f"/static/{rel_part.replace(os.sep, '/')}"
            logger.debug(f"resolve_web_path: rel_part={rel_part}, result={result}")
            return result

        logger.warning(f"resolve_web_path: path '{abs_path}' is not under source_dir {source_dir}")
    except Exception as e:
        logger.warning(f"resolve_web_path failed for '{original_path_str}': {e}")
    return None

@app.get("/processed/{path:path}")
def serve_processed_file(path: str):
    """Custom static file handler for processed images (Unicode-safe on Windows)"""
    # 直接用 source_dir 解析
    full_path = processed_dir / path.replace('/', os.sep) if processed_dir else None

    if full_path and full_path.exists() and full_path.is_file():
        return FileResponse(full_path)

    raise HTTPException(status_code=404, detail=f"File not found: {path}")

def resolve_processed_web_path(file_path_str: str) -> Optional[str]:
    """Resolves processed file path to /processed/... URL"""
    if not file_path_str: return None
    try:
        # Normalize path separators
        normalized = file_path_str.replace('\\', '/')

        # file_path is stored relative to source_dir, so use source_dir to resolve
        # 不使用 resolve()，避免UNC路径问题
        if processed_dir and not is_absolute_path(normalized):
            abs_path = processed_dir / normalized
        elif not is_absolute_path(normalized):
            abs_path = BASE_DIR / normalized
        else:
            abs_path = Path(normalized)

        # 使用规范化路径比较
        norm_abs = os.path.normpath(str(abs_path))
        norm_base = os.path.normpath(str(processed_dir)) if processed_dir else None

        # Check if it's under source_dir, then generate the URL
        if norm_base and norm_abs.startswith(norm_base):
            rel_part = norm_abs[len(norm_base):].lstrip('/\\')
            return f"/processed/{rel_part.replace(os.sep, '/')}"

        logger.warning(f"resolve_processed_web_path: path '{abs_path}' is not under processed_dir {processed_dir}")
        return None
    except Exception as e:
        logger.warning(f"Failed to resolve processed path '{file_path_str}': {e}")
        return None

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
        return templates.TemplateResponse("settings.html", {"request": request, "is_first_run": is_first_run()})

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
    
    return templates.TemplateResponse("index.html", {
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
        "prev_offset": prev_offset
    })

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    # Check if paths are configured - redirect to settings if not
    if not is_paths_configured():
        return templates.TemplateResponse("settings.html", {"request": request, "is_first_run": False})
    stats = get_stats()
    return templates.TemplateResponse("admin.html", {"request": request, "stats": stats})

def get_stats():
    """获取统计数据"""
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM photos")
        total_photos = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT scientific_name) FROM photos")
        total_species = cursor.fetchone()[0]
    except:
        total_photos = 0
        total_species = 0
    finally:
        conn.close()

    return {
        "total_photos": total_photos,
        "total_species": total_species
    }

@app.get("/api/stats")
def get_api_stats():
    """API: 获取统计数据"""
    return get_stats()

@app.get("/api/scan_history")
def get_scan_history():
    manager = create_db_manager()
    try:
        history = manager.get_recent_scans(limit=10)
        return history
    finally:
        manager.close()

@app.post("/api/pipeline/start")
def start_pipeline(req: StartPipelineRequest):
    if task_manager.is_running:
        return {"status": "error", "message": "Pipeline already running"}
    
    # Normalize empty strings to None
    s_date = req.start_date if req.start_date else None
    e_date = req.end_date if req.end_date else None
    
    task_manager.start_pipeline(s_date, e_date)
    return {"status": "success", "message": "Pipeline started"}

# 需要排除的系统文件夹列表
IGNORED_DIRS = {'@Recycle', '$RECYCLE.BIN', '.Trash-', '@eaDir', 'System Volume Information'}

@app.get("/api/pipeline/folders")
def get_folder_tree():
    """获取 sources 配置的文件夹树形结构（只返回第一层）"""
    try:
        sources = config.get('paths', {}).get('sources', [])
        if not sources:
            return {"tree": []}

        tree = []
        for source in sources:
            if not source.get('enabled', True):
                continue

            path_str = source.get('path', '')
            if not path_str:
                continue

            # sources.path now uses absolute path
            full_path = Path(path_str)

            if not full_path.exists():
                continue

            # Build tree from this path, only first level (lazy load children)
            folder_tree = _build_folder_tree(full_path, recursive=False, base_rel_path=path_str, max_depth=1)
            tree.extend(folder_tree)

        return {"tree": tree}
    except Exception as e:
        logger.error(f"Error building folder tree: {e}")
        return {"tree": [], "error": str(e)}


@app.get("/api/pipeline/folders/{full_path:path}")
def get_folder_children(full_path: str):
    """获取指定路径的子目录（懒加载）"""
    try:
        # full_path is now absolute, no need to resolve relative to base_dir
        current_path = Path(full_path)

        if not current_path.exists() or not current_path.is_dir():
            return {"children": []}

        # Build one level of children
        children = _build_folder_tree(current_path, recursive=False, base_rel_path=full_path, max_depth=1)

        return {"children": children}
    except Exception as e:
        logger.error(f"Error getting folder children: {e}")
        return {"children": [], "error": str(e)}

def _build_folder_tree(root_path: Path, recursive: bool, base_rel_path: str = "", max_depth: int = 5, current_depth: int = 0):
    """递归构建文件夹树

    Args:
        root_path: 绝对路径的根目录
        recursive: 是否递归扫描子目录
        base_rel_path: 相对于 source_dir 的基础路径
    """
    if current_depth >= max_depth:
        return []

    result = []
    try:
        for item in sorted(root_path.iterdir()):
            if not item.is_dir():
                continue

            # Skip system directories and recycle bins
            if item.name.startswith('.') or item.name.startswith('$'):
                continue
            if item.name in IGNORED_DIRS or any(item.name.startswith(p.replace('-', '')) for p in IGNORED_DIRS if '-'):
                continue

            # Calculate relative path from source_dir
            if base_rel_path:
                rel_path = f"{base_rel_path}/{item.name}"
            else:
                rel_path = item.name

            node = {
                "name": item.name,
                "path": rel_path,
                "type": "folder"
            }

            if recursive and current_depth < max_depth - 1:
                children = _build_folder_tree(item, recursive, rel_path, max_depth, current_depth + 1)
                if children:
                    node["children"] = children

            result.append(node)
    except PermissionError:
        pass
    except Exception as e:
        logger.warning(f"Error scanning {root_path}: {e}")

    return result

@app.post("/api/pipeline/start_by_folders")
def start_pipeline_by_folders(req: StartPipelineByFoldersRequest):
    """按文件夹执行 Pipeline"""
    if task_manager.is_running:
        return {"status": "error", "message": "Pipeline already running"}

    logger.info(f"Starting pipeline by folders: {req.paths}, recursive={req.recursive}")
    task_manager.start_pipeline_by_folders(req.paths, req.recursive)
    return {"status": "success", "message": f"Pipeline started for {len(req.paths)} folder(s)"}

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
    # path parameter is expected to be a web path suffix or relative path
    # But since we have multiple roots, this is tricky.
    # Better to rely on static serving for viewing.
    # If user wants to "download", they can right click -> save as on the served image.
    # Implementing a generic download endpoint for arbitrary files is complex with multiple roots.
    # We will skip this for now and rely on static mounts.
    return {"error": "Use context menu to save image"}

# Existing APIs (search, update, reset) ... 
# (Keep reset logic but simplify for brevity in this rewrite, ensure full logic is present in final file)

@app.post("/api/admin/reset")
def reset_system():
    try:
        # 安全检查：获取所有配置的源目录，禁止删除这些目录
        source_paths = []
        sources_config = config.get('paths', {}).get('sources', [])
        for src in sources_config:
            src_path = src.get('path', '')
            if src_path:
                # sources.path is now always absolute
                source_paths.append(Path(src_path).absolute())

        # 如果 output 目录也是源目录，禁止删除（防止配置错误导致的灾难）
        protected_paths = set(source_paths)
        protected_paths.add(BASE_DIR.absolute())  # 保护项目根目录

        logger.warning(f"Factory reset: Protected paths: {protected_paths}")

        # 1. Clear DB
        if db_path.exists():
            gc.collect()
            temp_path = db_path.with_suffix(".db.del")
            try:
                if temp_path.exists(): os.remove(temp_path)
                os.rename(db_path, temp_path)
                os.remove(temp_path)
            except: pass

        # 2. Clear Processed - 带安全检查
        # 只清空与源目录不同的输出目录
        processed_abs = processed_dir.absolute()
        if processed_dir.exists() and processed_abs not in protected_paths:
            for item in processed_dir.iterdir():
                try:
                    if item.is_file(): item.unlink()
                    elif item.is_dir(): shutil.rmtree(item)
                except: pass
        else:
            logger.warning(f"Skipped clearing processed_dir (protected or not exists): {processed_dir}")

        init_app_db()

        # Re-import taxonomy with references for Chinese name mappings
        mgr = create_db_manager()
        if mgr.conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0] == 0:
            refs_dir = str(BASE_DIR / config['paths']['references_path'])
            mgr.import_from_excel(
                str(BASE_DIR / config['paths']['ioc_list_path']),
                refs_dir=refs_dir
            )
        mgr.close()
        
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/api/admin/rebuild_stats")
def rebuild_species_stats():
    """重建物种统计表（首次使用或数据不一致时调用）"""
    try:
        manager = create_db_manager()
        manager.rebuild_species_stats()
        manager.close()
        return {"status": "success", "message": "Species stats table rebuilt"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/api/search_species")
def search_species(q: str):
    manager = create_db_manager()
    res = manager.search_species(q, limit=20)
    manager.close()
    return res

@app.get("/api/taxonomy/tree")
def get_taxonomy_tree(include_empty: bool = True, date: str = None):
    """获取分类树，支持显示/隐藏空层级和日期筛选"""
    manager = create_db_manager()
    try:
        # Use fast method when no date filter (uses precomputed stats table)
        if date:
            tree = manager.get_taxonomy_tree(include_empty=include_empty, date_filter=date)
        else:
            tree = manager.get_taxonomy_tree_fast(include_empty=include_empty)
        return tree
    finally:
        manager.close()

@app.get("/api/taxonomy/stats")
def get_taxonomy_stats(level: str, date: str = None):
    """按层级统计物种数量（order/family/genus/species）"""
    manager = create_db_manager()
    try:
        stats = manager.get_stats_by_level(level=level, date_filter=date)
        return stats
    finally:
        manager.close()

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
    manager = create_db_manager()
    conn = get_db_conn()
    cursor = conn.cursor()

    try:
        # Build WHERE clause - 优先使用中文参数，fallback到拉丁名参数
        query_parts = ["1=1"]
        params = []

        # 目 - 优先中文参数
        if order_cn:
            query_parts.append("t.order_cn = ?")
            params.append(order_cn)
        elif order_sci:
            query_parts.append("t.order_sci = ?")
            params.append(order_sci)

        # 科 - 优先中文参数
        if family_cn:
            query_parts.append("t.family_cn = ?")
            params.append(family_cn)
        elif family_sci:
            query_parts.append("t.family_sci = ?")
            params.append(family_sci)

        # 属 - 优先中文参数
        if genus_cn:
            query_parts.append("t.genus_cn = ?")
            params.append(genus_cn)
        elif genus_sci:
            query_parts.append("t.genus_sci = ?")
            params.append(genus_sci)

        if scientific_name:
            query_parts.append("t.scientific_name = ?")
            params.append(scientific_name)
        if date:
            query_parts.append("p.captured_date = ?")
            params.append(date)

        where_clause = "WHERE " + " AND ".join(query_parts)

        # Get total count
        count_sql = f'''
            SELECT COUNT(DISTINCT p.id)
            FROM taxonomy t
            JOIN photos p ON LOWER(t.scientific_name) = LOWER(p.scientific_name)
            {where_clause}
        '''
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()[0]

        # Get photos
        sql = f'''
            SELECT p.*
            FROM taxonomy t
            JOIN photos p ON LOWER(t.scientific_name) = LOWER(p.scientific_name)
            {where_clause}
            ORDER BY p.captured_date DESC, p.id DESC
            LIMIT ? OFFSET ?
        '''
        cursor.execute(sql, params + [limit, offset])
        photos = cursor.fetchall()

        # Convert to dicts and resolve web paths
        display_photos = []
        for p in photos:
            p_dict = dict(p)
            p_dict['web_raw_path'] = resolve_web_path(p_dict.get('original_path'))
            p_dict['web_processed_path'] = resolve_processed_web_path(p_dict.get('file_path'))
            display_photos.append(p_dict)

        return {
            "photos": display_photos,
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        }

    finally:
        manager.close()
        conn.close()

@app.get("/api/taxonomy/search")
def search_taxonomy(q: str, limit: int = 20):
    """搜索分类信息（支持目、科、属、物种）"""
    manager = create_db_manager()
    try:
        results = manager.search_taxonomy(query=q, limit=limit)
        return results
    finally:
        manager.close()

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

def get_config_definition():
    """Return the configuration schema for UI"""
    return {
        "basic": {
            "paths": [
                {
                    "key": "sources[0].path",
                    "label": "照片基准目录",
                    "description": "照片源目录（必填，使用绝对路径）",
                    "type": "path",
                    "required": True
                },
                {
                    "key": "output.root_dir",
                    "label": "输出目录",
                    "description": "裁切输出目录（必填，使用绝对路径）",
                    "type": "path",
                    "required": True
                }
            ],
            "web": [
                {
                    "key": "host",
                    "label": "监听地址",
                    "description": "0.0.0.0 = 允许局域网访问，127.0.0.1 = 仅本机",
                    "type": "string",
                    "default": "0.0.0.0"
                },
                {
                    "key": "port",
                    "label": "端口号",
                    "description": "Web 服务访问端口",
                    "type": "int",
                    "default": 8000
                }
            ]
        },
        "advanced": {
            "paths": [
                {
                    "key": "db_path",
                    "label": "数据库路径",
                    "description": "SQLite 数据库文件位置",
                    "type": "file"
                },
                {
                    "key": "references_path",
                    "label": "参考数据目录",
                    "description": "IOC 鸟类名录等参考文件",
                    "type": "directory"
                },
                {
                    "key": "ioc_list_path",
                    "label": "IOC 鸟类名录",
                    "description": "Excel 格式的鸟类分类数据",
                    "type": "file"
                },
                {
                    "key": "model_cache_dir",
                    "label": "模型缓存目录",
                    "description": "BioCLIP 模型缓存位置",
                    "type": "directory"
                },
                {
                    "key": "output.structure_template",
                    "label": "输出路径模板",
                    "description": "处理后的文件命名模板",
                    "type": "string",
                    "default": "{source_structure}/{filename}_{species_cn}_{confidence}"
                },
                {
                    "key": "output.write_back_to_source",
                    "label": "回写原图",
                    "description": "是否将元数据写回原始照片",
                    "type": "bool",
                    "default": False
                }
            ],
            "processing": [
                {
                    "key": "device",
                    "label": "处理设备",
                    "description": "auto/cuda/cpu",
                    "type": "select",
                    "options": ["auto", "cuda", "cpu"],
                    "default": "auto"
                },
                {
                    "key": "yolo_model",
                    "label": "YOLO 模型",
                    "description": "鸟类检测模型",
                    "type": "string",
                    "default": "yolo26n.pt"
                },
                {
                    "key": "confidence_threshold",
                    "label": "检测置信度",
                    "description": "YOLO 检测阈值 (0-1)",
                    "type": "float",
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0
                },
                {
                    "key": "blur_threshold",
                    "label": "模糊阈值",
                    "description": "模糊照片检测阈值",
                    "type": "float",
                    "default": 40.0
                },
                {
                    "key": "target_size",
                    "label": "目标尺寸",
                    "description": "图像处理目标尺寸",
                    "type": "int",
                    "default": 640
                },
                {
                    "key": "crop_padding",
                    "label": "裁剪边距",
                    "description": "鸟类裁剪区域的扩展边距",
                    "type": "int",
                    "default": 200
                }
            ],
            "recognition": [
                {
                    "key": "mode",
                    "label": "识别模式",
                    "description": "local/api/dongniao",
                    "type": "select",
                    "options": ["local", "api", "dongniao"],
                    "default": "local"
                },
                {
                    "key": "region_filter",
                    "label": "区域过滤",
                    "description": "china/auto/null",
                    "type": "select",
                    "options": ["china", "auto", "null"],
                    "default": "auto"
                },
                {
                    "key": "top_k",
                    "label": "Top-K 候选",
                    "description": "返回前 K 个候选物种",
                    "type": "int",
                    "default": 5
                },
                {
                    "key": "alternatives_threshold",
                    "label": "备选阈值",
                    "description": "显示备选结果的置信度阈值",
                    "type": "int",
                    "default": 70
                },
                {
                    "key": "low_confidence_threshold",
                    "label": "低置信度阈值",
                    "description": "标记为不确定的置信度阈值",
                    "type": "int",
                    "default": 60
                }
            ],
            "web": [
                {
                    "key": "log_level",
                    "label": "日志级别",
                    "description": "info/debug",
                    "type": "select",
                    "options": ["info", "debug"],
                    "default": "info"
                }
            ]
        }
    }

def get_nested_value(obj, key_path):
    """Get value from nested dict using dot notation"""
    keys = key_path.split('.')
    value = obj
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value

def set_nested_value(obj, key_path, value):
    """Set value in nested dict using dot notation, supports array indices like sources[0].path"""
    import re
    # Split by '.' but preserve array indices like [0]
    keys = re.split(r'\.(?!\d)', key_path)
    current = obj

    for key in keys[:-1]:
        # Handle array index like "sources[0]"
        array_match = re.match(r'^(\w+)\[(\d+)\]$', key)
        if array_match:
            array_key = array_match.group(1)
            index = int(array_match.group(2))

            if array_key not in current:
                current[array_key] = []
            # Ensure the array is long enough
            while len(current[array_key]) <= index:
                current[array_key].append({})
            current = current[array_key][index]
        else:
            if key not in current:
                current[key] = {}
            current = current[key]

    # Set the final value
    final_key = keys[-1]
    array_match = re.match(r'^(\w+)\[(\d+)\]$', final_key)
    if array_match:
        array_key = array_match.group(1)
        index = int(array_match.group(2))
        if array_key not in current:
            current[array_key] = []
        while len(current[array_key]) <= index:
            current[array_key].append({})
        current[array_key][index] = value
    else:
        current[final_key] = value

@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """Configuration page"""
    return templates.TemplateResponse("settings.html", {"request": {}})

@app.get("/api/config")
async def get_config():
    """Get current configuration"""
    config_path = BASE_DIR / "config" / "settings.yaml"

    if not config_path.exists():
        return {"error": "Configuration file not found", "is_first_run": True}

    with open(config_path, 'r', encoding='utf-8') as f:
        current_config = yaml.safe_load(f)

    return {
        "config": current_config,
        "definition": get_config_definition(),
        "is_first_run": False
    }

@app.post("/api/config/save")
async def save_config(req: SaveConfigRequest):
    """Save configuration to file"""
    config_path = BASE_DIR / "config" / "settings.yaml"
    config_dir = config_path.parent
    config_dir.mkdir(parents=True, exist_ok=True)

    # Load existing config or create new
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            current_config = yaml.safe_load(f) or {}
    else:
        current_config = {
            'paths': {},
            'processing': {},
            'recognition': {},
            'web': {}
        }

    # Check if db_path was changed
    db_path_changed = False
    old_db_path = current_config.get('paths', {}).get('db_path', '')

    # Apply changes
    for item in req.configs:
        value = item.value

        # Check if this is db_path
        if item.section == 'paths' and item.key == 'db_path':
            if value != old_db_path:
                db_path_changed = True

        # Type conversion
        if item.type == "int":
            value = int(value)
        elif item.type == "float":
            value = float(value)
        elif item.type == "bool":
            value = value.lower() in ("true", "yes", "1", "on")

        set_nested_value(current_config, f"{item.section}.{item.key}", value)

    # Validate db_path if changed
    if db_path_changed:
        new_db_path = current_config.get('paths', {}).get('db_path', '')
        if new_db_path:
            db_path_obj = Path(new_db_path)
            # Check if parent directory exists and is writable
            if not db_path_obj.parent.exists():
                try:
                    db_path_obj.parent.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    return {"status": "error", "error": f"无法创建数据库目录: {e}"}
            # Test write permission
            try:
                test_file = db_path_obj.parent / ".wingscribe_db_test"
                test_file.touch()
                test_file.unlink()
            except Exception as e:
                return {"status": "error", "error": f"数据库目录不可写: {e}"}

    # Save to file
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(current_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # Force restart if db_path changed, otherwise respect user's choice
    if db_path_changed:
        return {"status": "saved", "restart_required": True, "db_path_changed": True}

    if req.restart:
        return {"status": "saved", "restart_required": True}

    return {"status": "saved"}

@app.post("/api/config/restart")
async def restart_server():
    """Restart the server by spawning a new process and exiting current one"""
    import subprocess
    import time
    import threading

    global _startup_host, _startup_port, _startup_python

    # Get startup parameters
    host = _startup_host or config['web']['host']
    port = _startup_port or config['web']['port']

    # Build the command to restart
    app_path = str(BASE_DIR / "src" / "web" / "app.py")
    cmd = [_startup_python, app_path, "--host", str(host), "--port", str(port)]

    logger.info(f"Restarting server with command: {' '.join(cmd)}")

    def _delayed_exit():
        """Wait and then exit the current process"""
        time.sleep(3)
        logger.info("Exiting old server process")
        os._exit(0)

    try:
        # Start new process in background (detached on Windows)
        subprocess.Popen(cmd, cwd=str(BASE_DIR), creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0)

        # Start a background thread to exit the current process after a delay
        exit_thread = threading.Thread(target=_delayed_exit, daemon=True)
        exit_thread.start()

        # Return success - frontend will reload the page
        return {"status": "restarting", "message": "Server restarting..."}
    except Exception as e:
        logger.error(f"Failed to restart server: {e}")
        return {"error": str(e)}

@app.get("/api/config/validate")
async def validate_config_path(path: str, path_type: str = "directory"):
    """Validate if a path exists and is accessible

    Args:
        path: The path to validate
        path_type: Expected type - "directory" or "file"
    """
    try:
        p = Path(path)
        exists = p.exists()
        is_dir = p.is_dir() if exists else False
        is_file = p.is_file() if exists else False
        can_write = False
        can_read = False

        if exists:
            # Check read permission
            try:
                if is_file:
                    with open(p, 'rb') as f:
                        f.read(1)
                    can_read = True
                elif is_dir:
                    list(p)
                    can_read = True
            except:
                pass

            # Check write permission
            try:
                if is_dir:
                    test_file = p / ".wingscribe_write_test"
                    test_file.touch()
                    test_file.unlink()
                elif is_file:
                    # Test parent directory write permission
                    test_file = p.parent / ".wingscribe_write_test"
                    test_file.touch()
                    test_file.unlink()
                can_write = True
            except:
                pass

        return {
            "exists": exists,
            "is_directory": is_dir,
            "is_file": is_file,
            "can_write": can_write,
            "can_read": can_read
        }
    except Exception as e:
        return {"error": str(e)}

import threading

def open_folder_dialog(title: str, initial_dir: str = "") -> str:
    """Open a folder selection dialog using tkinter (runs in separate thread)"""
    result = {"path": None, "error": None}

    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            folder = filedialog.askdirectory(title=title, initialdir=initial_dir or None)
            root.destroy()
            result["path"] = folder
        except Exception as e:
            result["error"] = str(e)

    thread = threading.Thread(target=_run_dialog)
    thread.start()
    thread.join()

    if result["error"]:
        raise Exception(result["error"])
    return result["path"]

def open_file_dialog(title: str, initial_file: str = "", file_types: str = "") -> str:
    """Open a file selection dialog using tkinter (runs in separate thread)"""
    result = {"path": None, "error": None}

    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)

            # Parse file types
            filetypes = []
            if file_types:
                for ft in file_types.split('|'):
                    if ft:
                        filetypes.append((ft, f"*.{ft}"))

            file = filedialog.askopenfilename(
                title=title,
                initialfile=initial_file or None,
                filetypes=filetypes if filetypes else [("All Files", "*.*")]
            )
            root.destroy()
            result["path"] = file
        except Exception as e:
            result["error"] = str(e)

    thread = threading.Thread(target=_run_dialog)
    thread.start()
    thread.join()

    if result["error"]:
        raise Exception(result["error"])
    return result["path"]

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
