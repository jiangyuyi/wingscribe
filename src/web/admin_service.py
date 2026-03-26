import gc
import os
import shutil
from pathlib import Path


def admin_dashboard(request, templates, is_paths_configured, get_stats):
    if not is_paths_configured():
        return templates.TemplateResponse(
            name="settings.html",
            context={"request": request, "is_first_run": False},
        )
    stats = get_stats()
    return templates.TemplateResponse(
        name="admin.html",
        context={"request": request, "stats": stats},
    )


def get_stats(get_db_conn):
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM photos")
        total_photos = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT scientific_name) FROM photos")
        total_species = cursor.fetchone()[0]
    except Exception:
        total_photos = 0
        total_species = 0
    finally:
        conn.close()

    return {
        "total_photos": total_photos,
        "total_species": total_species,
    }


def get_scan_history(create_db_manager):
    manager = create_db_manager()
    try:
        return manager.get_recent_scans(limit=10)
    finally:
        manager.close()


def download_raw():
    return {"error": "Use context menu to save image"}


def reset_system(config, base_dir, db_path, processed_dir, init_app_db, create_db_manager, logger):
    try:
        source_paths = []
        sources_config = config.get("paths", {}).get("sources", [])
        for src in sources_config:
            src_path = src.get("path", "")
            if src_path:
                source_paths.append(Path(src_path).absolute())

        protected_paths = set(source_paths)
        protected_paths.add(base_dir.absolute())

        logger.warning(f"Factory reset: Protected paths: {protected_paths}")

        if db_path.exists():
            gc.collect()
            temp_path = db_path.with_suffix(".db.del")
            try:
                if temp_path.exists():
                    os.remove(temp_path)
                os.rename(db_path, temp_path)
                os.remove(temp_path)
            except Exception:
                pass

        processed_abs = processed_dir.absolute()
        if processed_dir.exists() and processed_abs not in protected_paths:
            for item in processed_dir.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception:
                    pass
        else:
            logger.warning(
                f"Skipped clearing processed_dir (protected or not exists): {processed_dir}"
            )

        init_app_db()

        mgr = create_db_manager()
        try:
            if mgr.conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0] == 0:
                refs_dir = str(base_dir / config["paths"]["references_path"])
                mgr.import_from_excel(
                    str(base_dir / config["paths"]["ioc_list_path"]),
                    refs_dir=refs_dir,
                )
        finally:
            mgr.close()

        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def rebuild_species_stats(create_db_manager):
    manager = None
    try:
        manager = create_db_manager()
        manager.rebuild_species_stats()
        return {"status": "success", "message": "Species stats table rebuilt"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    finally:
        if manager is not None:
            manager.close()
