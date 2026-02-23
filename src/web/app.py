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
from src.utils.config_loader import load_config
from src.core.io.fs_manager import FileSystemManager
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
        if self.is_running:
            return False
        
        self.is_running = True
        self.logs = ["Starting pipeline..."]
        
        # Run in thread
        thread = threading.Thread(target=self._run_pipeline_thread, args=(start_date, end_date), daemon=True)
        thread.start()
        return True

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

db_path = BASE_DIR / config['paths']['db_path']
processed_dir = BASE_DIR / config['paths']['output']['root_dir'] 

# Initialize FileSystemManager for security checks
fs_manager = FileSystemManager.get_instance(config['paths'])
allowed_roots = fs_manager.local_provider.allowed_roots if fs_manager.local_provider.allowed_roots else []

logger.info(f"Project Base Directory: {BASE_DIR}")
logger.info(f"Processed Images Directory: {processed_dir}")
logger.info(f"Allowed Roots: {allowed_roots}")

if not processed_dir.exists():
    logger.error(f"Processed directory does not exist: {processed_dir}")
    processed_dir.mkdir(parents=True, exist_ok=True)

# Note: Using custom route for /static/processed (see serve_processed_file above)
# because StaticFiles has issues with Unicode paths on Windows

# Include recognition API routes
app.include_router(recognition_router)

# Mount allowed roots for "Original View" - use follow_symlink=True for Unicode path support
for idx, root in enumerate(allowed_roots):
    if root.exists():
        app.mount(f"/static/roots/{idx}", StaticFiles(directory=str(root), follow_symlink=True), name=f"root_{idx}")

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
    """Resolves raw file path to /static/roots/... URL"""
    if not original_path_str: return None
    try:
        # Normalize path separators to avoid escape sequence issues
        normalized = original_path_str.replace('\\', '/')
        abs_path = Path(normalized).resolve()
        for idx, root in enumerate(allowed_roots):
            try:
                rel_path = abs_path.relative_to(root)
                return f"/static/roots/{idx}/{str(rel_path).replace(os.sep, '/')}"
            except ValueError: continue
    except Exception: pass
    return None

@app.get("/static/processed/{path:path}")
def serve_processed_file(path: str):
    """Custom static file handler for processed images (Unicode-safe on Windows)"""
    # Reconstruct the full path - use os.sep for cross-platform path construction
    full_path = processed_dir / path.replace('/', os.sep)
    if full_path.exists() and full_path.is_file():
        return FileResponse(full_path)
    raise HTTPException(status_code=404, detail="File not found")

def resolve_processed_web_path(file_path_str: str) -> Optional[str]:
    """Resolves processed file path to /static/processed/... URL"""
    if not file_path_str: return None
    try:
        # Normalize path separators
        normalized = file_path_str.replace('\\', '/')

        # Handle relative paths - prepend BASE_DIR if not absolute
        if not Path(normalized).is_absolute():
            abs_path = (BASE_DIR / normalized).absolute()
        else:
            abs_path = Path(normalized).absolute()

        # Normalize processed_dir for comparison
        processed_abs = processed_dir.absolute()

        # Check if it's inside processed_dir
        try:
            rel = abs_path.relative_to(processed_abs)
            return f"/static/processed/{str(rel).replace(os.sep, '/')}"
        except ValueError:
            # Try matching via parents
            for parent in abs_path.parents:
                if parent == processed_abs:
                    rel = abs_path.relative_to(processed_abs)
                    return f"/static/processed/{str(rel).replace(os.sep, '/')}"
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
    
    stats = {
        "total_photos": total_photos,
        "total_species": total_species,
        "storage_usage": 0 # TODO: Calculate properly for nested structure
    }
    return templates.TemplateResponse("admin.html", {"request": request, "stats": stats})

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
        # 1. Clear DB
        if db_path.exists():
            gc.collect()
            temp_path = db_path.with_suffix(".db.del")
            try:
                if temp_path.exists(): os.remove(temp_path)
                os.rename(db_path, temp_path)
                os.remove(temp_path)
            except: pass
            
        # 2. Clear Processed
        # WARNING: This deletes the entire root output dir!
        if processed_dir.exists():
            for item in processed_dir.iterdir():
                try:
                    if item.is_file(): item.unlink()
                    elif item.is_dir(): shutil.rmtree(item)
                except: pass

        init_app_db()
        
        # Re-import taxonomy
        mgr = IOCManager(str(db_path))
        if mgr.conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0] == 0:
             mgr.import_from_excel(str(BASE_DIR / config['paths']['ioc_list_path']))
        mgr.close()
        
        return {"status": "success"}
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
        tree = manager.get_taxonomy_tree(include_empty=include_empty, date_filter=date)
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
                    
                    # Update DB
                    conn = get_db_conn()
                    conn.execute("UPDATE photos SET file_path = ?, filename = ? WHERE id = ?", 
                                 (str(final_path), final_path.name, req.photo_id))
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
    import uvicorn
    uvicorn.run(app, host=config['web']['host'], port=config['web']['port'])