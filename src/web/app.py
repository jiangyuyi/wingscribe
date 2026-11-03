import logging
import sys
import shutil
import os
import gc
import asyncio
import json
from copy import deepcopy
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List

# Add project root to path for imports
BASE_DIR = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(BASE_DIR))

from src.metadata.exif_writer import ExifWriter
from src.utils.config_loader import load_config, validate_paths_config
from src.utils.settings import first_run_defaults, with_defaults
import yaml
from src.core.io.path_generator import PathGenerator
from src.web.routes.recognition import router as recognition_router
from src.web.routes.culling import router as culling_router
from src.web.culling_service import CullingWeb
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
from src.web import location_service
from src.recognition.cloud.factory import RecognizerFactory
from src.recognition.batch import BatchRecognitionService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

class ConfigItem(BaseModel):
    key: str
    value: str
    section: str
    type: str = "string"

class SaveConfigRequest(BaseModel):
    configs: List[ConfigItem]
    restart: bool = False

class LocationPreviewRequest(BaseModel):
    locations: List[str]


class WebRuntime:
    """Configuration and services owned by one application instance."""

    def __init__(self, base_dir: Path, config_override=None):
        self.BASE_DIR = Path(base_dir).resolve()
        self.startup_errors = []
        try:
            settings = (load_config(str(self.BASE_DIR / "config/settings.yaml"),
                                    str(self.BASE_DIR / "config/secrets.yaml"))
                        if config_override is None else deepcopy(config_override))
            self.config = with_defaults(settings)
        except (OSError, ValueError, yaml.YAMLError):
            self.startup_errors.append("配置无法读取或格式错误，请检查 settings.yaml 和 secrets.yaml")
            self.config = first_run_defaults()
        _, errors = validate_paths_config(self.config)
        self.startup_errors.extend(errors)
        self.source_dirs = [Path(src["path"]) for src in self.config["paths"]["sources"]
                            if src.get("path") and src.get("enabled", True)]
        self.source_dir = self.source_dirs[0] if self.source_dirs else ""
        self.output_root = self.config["paths"]["output"].get("root_dir", "")
        self.processed_dir = Path(self.output_root) if self.output_root else None
        self.db_path = Path(self.config["paths"].get("db_path") or "data/db/wingscribe.db")
        if not self.db_path.is_absolute():
            self.db_path = self.BASE_DIR / self.db_path
        task_config = deepcopy(self.config)
        task_config["paths"]["db_path"] = str(self.db_path)
        self.task_manager = ExtractedTaskManager(config_path=self.BASE_DIR / "config/settings.yaml",
                                                 config_override=task_config)
        self.exif_writer = ExifWriter()
        self.templates = Jinja2Templates(directory=str(BASE_DIR / "src/web/templates"))
        self.get_config_definition = get_config_definition
        self.get_nested_value = get_nested_value
        self.set_nested_value = set_nested_value
        self._startup_host = None
        self._startup_port = None
        self._startup_python = sys.executable

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        # Startup
        if self.is_paths_configured():
            self.init_app_db()
        logger.info("Application started.")
        try:
            yield
        finally:
            await asyncio.to_thread(app.state.culling.close)
            if self.task_manager.is_running:
                self.task_manager.stop()
                await asyncio.to_thread(self.task_manager.wait)
            await app.state.batch_service.close()
            app.state.recognizer_factory.clear_local_cache()
            logger.info("Application shutting down...")


    async def require_configuration(self, request: Request, call_next):
        path = request.url.path
        setup_route = path in ("/", "/settings") or path.startswith(("/api/config", "/lib/"))
        if not self.is_paths_configured() and not setup_route:
            return JSONResponse(status_code=409, content={"error": "请先修复并保存配置，然后重启服务。"})
        return await call_next(request)


    def is_absolute_path(self, p: str) -> bool:
        """Check if path is absolute, including Windows drive letter format like 'Y:/path'"""
        return path_helpers.is_absolute_path(p)


    def init_app_db(self):
        try:
            mgr = self.create_db_manager()
            mgr.close()
            del mgr
            gc.collect()
        except Exception as e:
            self.startup_errors.append("数据库初始化失败，请检查数据库路径和权限后重启。")
            logger.error("Startup DB initialization failed (%s)", type(e).__name__)


    def create_db_manager(self):
        return path_helpers.create_db_manager(self.db_path, self.source_dir, self.processed_dir)


    def get_db_conn(self):
        return path_helpers.get_db_conn(self.db_path)


    def resolve_web_path(self, original_path_str: str) -> Optional[str]:
        """Resolves raw file path to /raw/... URL"""
        return path_helpers.resolve_web_path(original_path_str, self.source_dirs, logger)


    def serve_raw_file(self, path: str):
        """Custom file handler for original images across multiple source roots."""
        return path_helpers.get_raw_file_response(path, self.source_dirs)


    def serve_processed_file(self, path: str):
        """Custom static file handler for processed images (Unicode-safe on Windows)"""
        return path_helpers.get_processed_file_response(path, self.processed_dir)


    def resolve_processed_web_path(self, file_path_str: str) -> Optional[str]:
        """Resolves processed file path to /processed/... URL"""
        return path_helpers.resolve_processed_web_path(file_path_str, self.processed_dir, self.BASE_DIR, logger)


    def is_first_run(self):
        """Check if this is the first run (no config file)"""
        config_path = self.BASE_DIR / "config" / "settings.yaml"
        return not config_path.exists()


    def is_paths_configured(self):
        """Check if source and output paths are configured (not empty)"""
        return not self.startup_errors and bool(self.source_dir) and bool(self.output_root)


    def index(self, request: Request, q: str = "", filter: str = "", date: str = "", limit: int = 50, offset: int = 0, skip_first_check: bool = False):
        # Check for first run or empty paths - redirect to settings if not configured
        if not skip_first_check and (self.is_first_run() or not self.is_paths_configured()):
            return self.templates.TemplateResponse(
                request=request,
                name="settings.html",
                context={"request": request, "is_first_run": self.is_first_run()},
            )

        conn = self.get_db_conn()
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
            p_dict['web_raw_path'] = self.resolve_web_path(p_dict.get('original_path'))
            p_dict['web_processed_path'] = self.resolve_processed_web_path(p_dict.get('file_path'))
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
    
        return self.templates.TemplateResponse(
            request=request,
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


    def admin_dashboard(self, request: Request):
        return admin_service.admin_dashboard(request, self.templates, self.is_paths_configured, self.get_stats)


    def get_stats(self):
        return admin_service.get_stats(self.get_db_conn)


    def get_api_stats(self):
        return self.get_stats()


    def get_scan_history(self):
        return admin_service.get_scan_history(self.create_db_manager)


    def start_pipeline(self, req: StartPipelineRequest):
        return pipeline_service.start_pipeline(self.task_manager, req)


    def get_folder_tree(self):
        """获取 sources 配置的文件夹树形结构（只返回第一层）"""
        return pipeline_service.get_folder_tree(self.config, logger, self._build_folder_tree)


    def get_folder_children(self, full_path: str):
        """获取指定路径的子目录（懒加载）"""
        return pipeline_service.get_folder_children(full_path, logger, self._build_folder_tree)


    def _build_folder_tree(self, root_path: Path, recursive: bool, base_rel_path: str = "", max_depth: int = 5, current_depth: int = 0):
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


    def start_pipeline_by_folders(self, req: StartPipelineByFoldersRequest):
        """按文件夹执行 Pipeline"""
        return pipeline_service.start_pipeline_by_folders(self.task_manager, req, logger)


    def pipeline_status(self):
        return self.task_manager.snapshot()


    def stop_pipeline(self):
        return pipeline_service.stop_pipeline(self.task_manager)


    async def websocket_endpoint(self, websocket: WebSocket):
        await websocket.accept()
        try:
            cursor = None
            while True:
                cursor, new_logs = self.task_manager.logs_since(cursor)
                for log in new_logs:
                    await websocket.send_text(log)
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            # Handle server shutdown cancellation
            pass
        except Exception as e:
            # Expected disconnect or other error
            pass


    def download_raw(self, path: str):
        return admin_service.download_raw()


    def reset_system(self):
        return admin_service.reset_system(
            self.config,
            self.BASE_DIR,
            self.db_path,
            self.processed_dir,
            self.init_app_db,
            self.create_db_manager,
            logger,
        )


    def rebuild_species_stats(self):
        return admin_service.rebuild_species_stats(self.create_db_manager)


    def search_species(self, q: str):
        return taxonomy_service.search_species(self.create_db_manager, q)


    def get_taxonomy_tree(self, include_empty: bool = True, date: str = None):
        """获取分类树，支持显示/隐藏空层级和日期筛选"""
        return taxonomy_service.get_taxonomy_tree(self.create_db_manager, include_empty, date)


    def get_taxonomy_stats(self, level: str, date: str = None):
        """按层级统计物种数量（order/family/genus/species）"""
        return taxonomy_service.get_taxonomy_stats(self.create_db_manager, level, date)


    def get_photos_by_taxonomy(self,
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
            self.create_db_manager,
            self.get_db_conn,
            self.resolve_web_path,
            self.resolve_processed_web_path,
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


    def search_taxonomy(self, q: str, limit: int = 20):
        """搜索分类信息（支持目、科、属、物种）"""
        return taxonomy_service.search_taxonomy(self.create_db_manager, q, limit)


    def update_label(self, req: UpdateLabelRequest):
        manager = self.create_db_manager()
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
                    alt_threshold = self.config.get('recognition', {}).get('alternatives_threshold', 70)
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
                out_conf = self.config.get('paths', {}).get('output', {})
                template = out_conf.get('structure_template', "")

                if any(x in template for x in ["{species_cn}", "{species_sci}", "{confidence}"]):
                    source_structure = "."
                    if photo.get('original_path'):
                        orig_path_obj = Path(photo['original_path'])
                        sources = self.config.get('paths', {}).get('sources', [])
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

                    output_root_raw = out_conf.get('root_dir', '') or self.processed_dir
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
                if not self.exif_writer.write_metadata(final_processed_path, tags):
                    raise RuntimeError("Failed to update metadata for processed image")

            original_path = photo.get('original_path')
            if original_path and os.path.exists(original_path):
                source_tags = tags.copy()
                source_tags["IPTC:Keywords"] = source_tags["IPTC:Keywords"] + ["WingScribe"]
                if not self.exif_writer.write_metadata(original_path, source_tags):
                    raise RuntimeError("Failed to update metadata for original image")

            manager.conn.execute(
                '''
                UPDATE photos
                SET scientific_name = ?, primary_bird_cn = ?, confidence_score = ?,
                    file_path = ?, filename = ?, label_source = 'manual',
                    manual_verified_at = CURRENT_TIMESTAMP
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


    async def settings_page(self, request: Request):
        """Configuration page"""
        return self.templates.TemplateResponse(request=request, name="settings.html", context={"request": request})


    async def get_config(self):
        """Get current configuration"""
        result = config_service.get_config(self.BASE_DIR, self.get_config_definition)
        if self.startup_errors and not result.get("is_first_run"):
            result.setdefault("error", "启动配置无效；请检查设置和 secrets.yaml，保存后重启服务。")
        return result


    async def preview_locations(self, req: LocationPreviewRequest):
        """Preview normalized locations without changing photos or configuration."""
        if not 1 <= len(req.locations) <= 100:
            raise HTTPException(status_code=400, detail="locations must contain between 1 and 100 items")
        if any(not location.strip() or len(location) > 500 for location in req.locations):
            raise HTTPException(status_code=400, detail="each location must contain 1 to 500 characters")
        return location_service.preview_locations(self.BASE_DIR, req.locations)


    async def save_config(self, req: SaveConfigRequest):
        """Save configuration to file"""
        return config_service.save_config(req, self.BASE_DIR, self.set_nested_value)


    async def restart_server(self):
        """Restart the server by spawning a new process and exiting current one"""
        return config_service.restart_server(
            self.BASE_DIR,
            self.config,
            self._startup_host,
            self._startup_port,
            self._startup_python,
            logger,
        )


    async def validate_config_path(self, path: str, path_type: str = "directory"):
        """Validate if a path exists and is accessible

        Args:
            path: The path to validate
            path_type: Expected type - "directory" or "file"
        """
        return config_service.validate_config_path(path, path_type)


    def open_folder_dialog(self, title: str, initial_dir: str = "") -> str:
        return config_service.open_folder_dialog(title, initial_dir)


    def open_file_dialog(self, title: str, initial_file: str = "", file_types: str = "") -> str:
        return config_service.open_file_dialog(title, initial_file, file_types)


    async def browse_folder_api(self, title: str = "选择文件夹", initial_path: str = ""):
        """API endpoint to open folder selection dialog"""
        try:
            folder_path = await asyncio.to_thread(self.open_folder_dialog, title, initial_path)
            return {"path": folder_path}
        except Exception as e:
            return {"error": str(e), "path": None}


    async def browse_file_api(self, title: str = "选择文件", initial_path: str = "", file_types: str = "xlsx|xls", save: bool = False):
        """API endpoint to open file selection dialog"""
        try:
            if save:
                file_path = await asyncio.to_thread(config_service.open_file_dialog, title, initial_path, file_types, True)
            else:
                file_path = await asyncio.to_thread(self.open_file_dialog, title, initial_path, file_types)
            return {"path": file_path}
        except Exception as e:
            return {"error": str(e), "path": None}


def create_app(base_dir: Path = BASE_DIR, *, config_override=None) -> FastAPI:
    """Build an isolated app; creating it does not initialize the database or models."""
    runtime = WebRuntime(base_dir, config_override)
    app = FastAPI(lifespan=runtime.lifespan)
    runtime.app = app
    app.state.runtime = runtime
    app.state.culling = CullingWeb(runtime)
    app.state.recognizer_factory = RecognizerFactory.configured(runtime.config)
    app.state.batch_service = BatchRecognitionService(recognizer_factory=app.state.recognizer_factory)
    app.include_router(recognition_router)
    app.include_router(culling_router)
    static_dir = BASE_DIR / "src/web/static"
    if static_dir.exists():
        app.mount("/lib", StaticFiles(directory=str(static_dir), follow_symlink=True), name="lib")
    app.middleware("http")(runtime.require_configuration)
    app.get("/raw/{path:path}")(runtime.serve_raw_file)
    app.get("/processed/{path:path}")(runtime.serve_processed_file)
    app.get("/", response_class=HTMLResponse)(runtime.index)
    app.get("/admin", response_class=HTMLResponse)(runtime.admin_dashboard)
    app.get("/api/stats")(runtime.get_api_stats)
    app.get("/api/scan_history")(runtime.get_scan_history)
    app.post("/api/pipeline/start")(runtime.start_pipeline)
    app.get("/api/pipeline/folders")(runtime.get_folder_tree)
    app.get("/api/pipeline/folders/{full_path:path}")(runtime.get_folder_children)
    app.post("/api/pipeline/start_by_folders")(runtime.start_pipeline_by_folders)
    app.get("/api/pipeline/status")(runtime.pipeline_status)
    app.post("/api/pipeline/stop")(runtime.stop_pipeline)
    app.websocket("/ws/progress")(runtime.websocket_endpoint)
    app.get("/download_raw")(runtime.download_raw)
    app.post("/api/admin/reset")(runtime.reset_system)
    app.get("/api/admin/rebuild_stats")(runtime.rebuild_species_stats)
    app.get("/api/search_species")(runtime.search_species)
    app.get("/api/taxonomy/tree")(runtime.get_taxonomy_tree)
    app.get("/api/taxonomy/stats")(runtime.get_taxonomy_stats)
    app.get("/api/photos/by_taxonomy")(runtime.get_photos_by_taxonomy)
    app.get("/api/taxonomy/search")(runtime.search_taxonomy)
    app.post("/api/update_label")(runtime.update_label)
    app.get("/settings", response_class=HTMLResponse)(runtime.settings_page)
    app.get("/api/config")(runtime.get_config)
    app.post("/api/location/preview")(runtime.preview_locations)
    app.post("/api/config/save")(runtime.save_config)
    app.post("/api/config/restart")(runtime.restart_server)
    app.get("/api/config/validate")(runtime.validate_config_path)
    app.post("/api/config/browse_folder")(runtime.browse_folder_api)
    app.post("/api/config/browse_file")(runtime.browse_file_api)
    return app


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="WingScribe Web Server")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    application = create_app()
    runtime = application.state.runtime
    host = args.host or runtime.config["web"]["host"]
    port = args.port or runtime.config["web"]["port"]
    runtime._startup_host = host
    runtime._startup_port = port
    uvicorn.run(application, host=host, port=port)
