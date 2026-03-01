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
from src.pipeline_runner import FeatherTracePipeline # Import Pipeline
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
            runner = FeatherTracePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

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
            runner = FeatherTracePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

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

# Get base_dir for relative path resolution
base_dir = config['paths'].get('base_dir', '')
if base_dir:
    base_dir = Path(base_dir)

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

# Resolve db_path - based on base_dir
db_path_config = config['paths'].get('db_path', 'data/db/wingscribe.db')
if is_absolute_path(db_path_config):
    db_path = Path(db_path_config)
else:
    db_path = base_dir / db_path_config if base_dir else BASE_DIR / db_path_config

# Handle output.root_dir - based on base_dir
output_root = config['paths']['output']['root_dir']
if is_absolute_path(output_root):
    processed_dir = Path(output_root)
elif base_dir:
    processed_dir = base_dir / output_root
else:
    processed_dir = BASE_DIR / output_root

logger.info(f"Project Base Directory: {BASE_DIR}")
logger.info(f"Data Base Directory (base_dir): {base_dir}")
logger.info(f"Database Path: {db_path}")
logger.info(f"Processed Images Directory: {processed_dir}")

if not processed_dir.exists():
    logger.error(f"Processed directory does not exist: {processed_dir}")
    processed_dir.mkdir(parents=True, exist_ok=True)

# Note: Using custom route for /processed (see serve_processed_file above)
app.include_router(recognition_router)

# Mount base_dir for "Original View" - use follow_symlink=True for Unicode path support
if base_dir and base_dir.exists():
    app.mount("/static", StaticFiles(directory=str(base_dir), follow_symlink=True), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "src" / "web" / "templates"))

# --- Initialization ---
# Call explicitly
def init_app_db():
    try:
        mgr = IOCManager(str(db_path))
        mgr.close()
        del mgr
        gc.collect()
    except Exception as e:
        logger.error(f"Startup DB Initialization failed: {e}")

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

        # Handle relative paths - convert to absolute using base_dir
        # 不使用 resolve()，避免UNC路径问题（与pipeline_runner.py一致）
        if base_dir and not is_absolute_path(normalized):
            abs_path = base_dir / normalized
        else:
            abs_path = Path(normalized)

        # 使用规范化路径比较，不使用resolve()
        norm_abs = os.path.normpath(str(abs_path))
        norm_base = os.path.normpath(str(base_dir)) if base_dir else None

        logger.debug(f"resolve_web_path: input='{original_path_str}', normalized='{normalized}', abs_path='{abs_path}', norm_base={norm_base}")

        # 基于 base_dir 计算相对路径
        if norm_base and norm_abs.startswith(norm_base):
            # 提取相对路径部分
            rel_part = norm_abs[len(norm_base):].lstrip('/')
            result = f"/static/{rel_part.replace(os.sep, '/')}"
            logger.debug(f"resolve_web_path: rel_part={rel_part}, result={result}")
            return result

        logger.warning(f"resolve_web_path: path '{abs_path}' is not under base_dir {base_dir}")
    except Exception as e:
        logger.warning(f"resolve_web_path failed for '{original_path_str}': {e}")
    return None

@app.get("/processed/{path:path}")
def serve_processed_file(path: str):
    """Custom static file handler for processed images (Unicode-safe on Windows)"""
    # 直接用 base_dir 解析，因为 file_path 是相对于 base_dir 存储的
    full_path = base_dir / path.replace('/', os.sep) if base_dir else None

    if full_path and full_path.exists() and full_path.is_file():
        return FileResponse(full_path)

    raise HTTPException(status_code=404, detail=f"File not found: {path}")

def resolve_processed_web_path(file_path_str: str) -> Optional[str]:
    """Resolves processed file path to /processed/... URL"""
    if not file_path_str: return None
    try:
        # Normalize path separators
        normalized = file_path_str.replace('\\', '/')

        # file_path is stored relative to base_dir, so use base_dir to resolve
        # 不使用 resolve()，避免UNC路径问题
        if base_dir and not is_absolute_path(normalized):
            abs_path = base_dir / normalized
        elif not is_absolute_path(normalized):
            abs_path = BASE_DIR / normalized
        else:
            abs_path = Path(normalized)

        # 使用规范化路径比较
        norm_abs = os.path.normpath(str(abs_path))
        norm_base = os.path.normpath(str(base_dir)) if base_dir else None

        # Check if it's under base_dir, then generate the URL
        if norm_base and norm_abs.startswith(norm_base):
            rel_part = norm_abs[len(norm_base):].lstrip('/')
            return f"/processed/{rel_part.replace(os.sep, '/')}"

        logger.warning(f"resolve_processed_web_path: path '{abs_path}' is not under base_dir {base_dir}")
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

@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", filter: str = "", date: str = "", limit: int = 50, offset: int = 0):
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
    manager = IOCManager(str(db_path))
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
    """获取 sources 配置的文件夹树形结构"""
    try:
        sources = config.get('paths', {}).get('sources', [])
        if not sources:
            return {"tree": []}

        base_dir = config.get('paths', {}).get('base_dir', '')

        tree = []
        for source in sources:
            if not source.get('enabled', True):
                continue

            path_str = source.get('path', '.')
            # Resolve relative path
            if base_dir and not Path(path_str).is_absolute():
                full_path = Path(base_dir) / path_str
            else:
                full_path = Path(path_str)

            if not full_path.exists():
                continue

            # Build tree from this path, pass path_str for relative path calculation
            folder_tree = _build_folder_tree(full_path, source.get('recursive', True), path_str)
            tree.extend(folder_tree)

        return {"tree": tree}
    except Exception as e:
        logger.error(f"Error building folder tree: {e}")
        return {"tree": [], "error": str(e)}

def _build_folder_tree(root_path: Path, recursive: bool, base_rel_path: str = "", max_depth: int = 5, current_depth: int = 0):
    """递归构建文件夹树

    Args:
        root_path: 绝对路径的根目录
        recursive: 是否递归扫描子目录
        base_rel_path: 相对于 base_dir 的基础路径（如 "1按年份/2026"）
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

            # Calculate relative path from base_dir
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
                if Path(src_path).is_absolute():
                    source_paths.append(Path(src_path).absolute())
                elif base_dir:
                    source_paths.append((base_dir / src_path).absolute())
                else:
                    source_paths.append((BASE_DIR / src_path).absolute())

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
        mgr = IOCManager(str(db_path))
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
        manager = IOCManager(str(db_path))
        manager.rebuild_species_stats()
        manager.close()
        return {"status": "success", "message": "Species stats table rebuilt"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/api/search_species")
def search_species(q: str):
    manager = IOCManager(str(db_path))
    res = manager.search_species(q, limit=20)
    manager.close()
    return res

@app.get("/api/taxonomy/tree")
def get_taxonomy_tree(include_empty: bool = True, date: str = None):
    """获取分类树，支持显示/隐藏空层级和日期筛选"""
    manager = IOCManager(str(db_path))
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
    manager = IOCManager(str(db_path))
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
    manager = IOCManager(str(db_path))
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
    manager = IOCManager(str(db_path))
    try:
        results = manager.search_taxonomy(query=q, limit=limit)
        return results
    finally:
        manager.close()

@app.post("/api/update_label")
def update_label(req: UpdateLabelRequest):
    manager = IOCManager(str(db_path))

    # 1. Fetch photo details BEFORE update to get file paths
    # Use conn.execute directly as manager.cursor is removed
    cursor = manager.conn.execute("SELECT * FROM photos WHERE id = ?", (req.photo_id,))
    photo = cursor.fetchone()

    if not photo:
        manager.close()
        raise HTTPException(status_code=404, detail="Photo not found")

    photo = dict(photo)

    # Convert relative paths to absolute using base_dir
    if base_dir:
        if photo.get('file_path'):
            photo['file_path'] = str(base_dir / photo['file_path'])
        if photo.get('original_path'):
            photo['original_path'] = str(base_dir / photo['original_path'])
    
    # 2. Get extra bird info (Family) for tags
    bird_info = manager.get_bird_info(req.scientific_name)
    family_cn = bird_info['family_cn'] if bird_info else ""
    
    # 3. Update DB
    manager.update_photo_species(req.photo_id, req.scientific_name, req.chinese_name)
    manager.close()
    
    # 4. Prepare Tags
    # Reconstruct UserComment from candidates_json if available
    user_comment = req.chinese_name
    
    # Try to load candidates to preserve history in EXIF
    try:
        candidates = []
        if 'candidates_json' in photo and photo['candidates_json']:
            candidates = json.loads(photo['candidates_json'])
        
        if candidates:
            # We must adhere to the same logic as pipeline: check threshold from config
            # But wait, config is loaded at module level.
            alt_threshold = config.get('recognition', {}).get('alternatives_threshold', 70)
            
            # Since this is a manual update, the "Top Match" is now the user selection.
            # But the candidates list reflects the *AI's* original opinion.
            # We should probably keep the list as "AI Alternatives" vs "Manual Selection".
            # Or just rewrite the list with the user selection as "Current"?
            # User requirement: "all alternatives still preserved".
            
            # Let's reconstruct the original AI string, but maybe add a note?
            # Or simpler: Just regenerate the string exactly as the pipeline did, 
            # based on the stored AI data. The UserComment is "AI's opinion".
            # The ImageDescription/Keywords reflect the "Current Truth".
            
            # Re-generate comment based on AI data
            # Note: The 'top' in candidates is the original AI top, not necessarily the current label.
            # This preserves the history of what AI thought.
            
            comment_lines = []
            
            # Check if we should show alternatives based on original AI top score
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
            
            # Add a manual override note if it differs
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
        "XPTitle": description,   # Windows Explorer Title
        "XPSubject": "",          # Explicitly clear Subject per request
        "ImageDescription": description, # Ensure standard compatibility
        "UserComment": user_comment
    }
    
    # 5. Handle File Renaming (If template uses species name or confidence)
    processed_path = photo.get('file_path')
    
    if processed_path and os.path.exists(processed_path):
        out_conf = config.get('paths', {}).get('output', {})
        template = out_conf.get('structure_template', "")
        
        # Check if template depends on species or confidence
        if any(x in template for x in ["{species_cn}", "{species_sci}", "{confidence}"]):
            try:
                # Resolve Source Structure
                source_structure = "."
                if photo.get('original_path'):
                    orig_path_obj = Path(photo['original_path'])
                    # Check sources to find relative root
                    sources = config.get('paths', {}).get('sources', [])
                    for src in sources:
                        try:
                            src_path = Path(src['path']).resolve()
                            if src_path in orig_path_obj.parents:
                                rel = orig_path_obj.parent.relative_to(src_path)
                                source_structure = str(rel).replace('\\', '/')
                                break
                        except Exception: continue

                gen_meta = {
                    'captured_date': photo['captured_date'],
                    'location_tag': photo['location_tag'],
                    'primary_bird_cn': req.chinese_name,
                    'scientific_name': req.scientific_name,
                    'confidence_score': 1.0, # Manual confirmation = 100% confidence
                    'source_structure': source_structure 
                }
                
                # Re-instantiate generator
                generator = PathGenerator(
                    template=template,
                    output_root=out_conf.get('root_dir', 'data/processed')
                )
                
                # FIX: Use ORIGINAL filename stem to avoid appending suffixes to already processed names
                # e.g. "Bird.jpg" -> "Bird_NewName.jpg", NOT "Bird_OldName_NewName.jpg"
                orig_filename = photo.get('filename') # Default fallback
                if photo.get('original_path'):
                    orig_filename = Path(photo['original_path']).name
                
                new_path = generator.generate_path(gen_meta, orig_filename)
                
                # If path changed, move file and update DB
                if Path(new_path).resolve() != Path(processed_path).resolve():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Rename/Move
                    # Since we are essentially "re-processing" the name, 
                    # we must ensure we don't overwrite an existing file (unless it's self?)
                    # PathGenerator does NOT handle collision check inside generate_path, 
                    # pipeline_runner handled it. We should handle it here too.
                    
                    final_path = new_path
                    if final_path.exists() and final_path.resolve() != Path(processed_path).resolve():
                         stem = final_path.stem
                         counter = 1
                         while final_path.exists():
                             final_path = final_path.with_name(f"{stem}_{counter}.jpg")
                             counter += 1
                    
                    shutil.move(processed_path, final_path)
                    
                    # Update DB (convert absolute path to relative)
                    conn = get_db_conn()
                    rel_path = str(final_path)
                    if base_dir:
                        try:
                            rel_path = str(Path(final_path).relative_to(base_dir))
                        except ValueError:
                            pass  # Keep absolute path if not under base_dir
                    conn.execute("UPDATE photos SET file_path = ?, filename = ? WHERE id = ?",
                                 (rel_path, final_path.name, req.photo_id))
                    conn.commit()
                    conn.close()
                    
                    processed_path = str(final_path) # Update local var for EXIF writing
                    logger.info(f"Renamed file to: {final_path}")
            except Exception as e:
                logger.error(f"Failed to rename file: {e}")

    # 6. Update Metadata for Processed Image
    if processed_path and os.path.exists(processed_path):
        exif_writer.write_metadata(processed_path, tags)
    
    # 7. Update Metadata for Original Image (if exists)
    original_path = photo.get('original_path')
    if original_path and os.path.exists(original_path):
        # We might want to append "FeatherTrace" to keywords if not present, 
        # but purely replacing with the new set is safer to keep consistency with the new ID.
        # Ideally, we should read existing keywords and merge, but for now, 
        # strictly following the requirement "Update tags" with the corrected info.
        # Adding "FeatherTrace" tag to mark it as touched by our system is good practice though.
        
        # Re-creating the logic from pipeline_runner:
        source_tags = tags.copy()
        source_tags["IPTC:Keywords"] = source_tags["IPTC:Keywords"] + ["FeatherTrace"]
        
        exif_writer.write_metadata(original_path, source_tags)

    return {"status": "success"}

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description='WingScribe Web Server')
    parser.add_argument('--host', type=str, default=None, help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to bind to')
    args = parser.parse_args()

    # Use command line args if provided, otherwise fall back to config
    host = args.host if args.host else config['web']['host']
    port = args.port if args.port else config['web']['port']

    uvicorn.run(app, host=host, port=port)