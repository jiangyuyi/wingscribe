from pathlib import Path


IGNORED_DIRS = {"@Recycle", "$RECYCLE.BIN", ".Trash-", "@eaDir", "System Volume Information"}


def start_pipeline(task_manager, req):
    if task_manager.is_running:
        return {"status": "error", "message": "Pipeline already running"}

    s_date = req.start_date if req.start_date else None
    e_date = req.end_date if req.end_date else None
    task_manager.start_pipeline(s_date, e_date)
    return {"status": "success", "message": "Pipeline started"}


def get_folder_tree(config, logger, build_folder_tree):
    try:
        sources = config.get("paths", {}).get("sources", [])
        if not sources:
            return {"tree": []}

        tree = []
        for source in sources:
            if not source.get("enabled", True):
                continue

            path_str = source.get("path", "")
            if not path_str:
                continue

            full_path = Path(path_str)
            if not full_path.exists():
                continue

            folder_tree = build_folder_tree(
                full_path,
                recursive=False,
                base_rel_path=path_str,
                max_depth=1,
            )
            tree.extend(folder_tree)

        return {"tree": tree}
    except Exception as exc:
        logger.error("Error building folder tree: %s", exc)
        return {"tree": [], "error": str(exc)}


def get_folder_children(full_path: str, logger, build_folder_tree):
    try:
        current_path = Path(full_path)
        if not current_path.exists() or not current_path.is_dir():
            return {"children": []}

        children = build_folder_tree(
            current_path,
            recursive=False,
            base_rel_path=full_path,
            max_depth=1,
        )
        return {"children": children}
    except Exception as exc:
        logger.error("Error getting folder children: %s", exc)
        return {"children": [], "error": str(exc)}


def build_folder_tree(root_path: Path, recursive: bool, base_rel_path: str = "", max_depth: int = 5, current_depth: int = 0, logger=None):
    if current_depth >= max_depth:
        return []

    result = []
    try:
        for item in sorted(root_path.iterdir()):
            if not item.is_dir():
                continue

            if item.name.startswith(".") or item.name.startswith("$"):
                continue
            if item.name in IGNORED_DIRS or any(item.name.startswith(p.replace("-", "")) for p in IGNORED_DIRS if "-"):
                continue

            rel_path = f"{base_rel_path}/{item.name}" if base_rel_path else item.name
            node = {"name": item.name, "path": rel_path, "type": "folder"}

            if recursive and current_depth < max_depth - 1:
                children = build_folder_tree(item, recursive, rel_path, max_depth, current_depth + 1, logger)
                if children:
                    node["children"] = children

            result.append(node)
    except PermissionError:
        pass
    except Exception as exc:
        if logger is not None:
            logger.warning("Error scanning %s: %s", root_path, exc)

    return result


def start_pipeline_by_folders(task_manager, req, logger):
    if task_manager.is_running:
        return {"status": "error", "message": "Pipeline already running"}

    logger.info("Starting pipeline by folders: %s, recursive=%s", req.paths, req.recursive)
    task_manager.start_pipeline_by_folders(req.paths, req.recursive)
    return {"status": "success", "message": f"Pipeline started for {len(req.paths)} folder(s)"}


def stop_pipeline(task_manager):
    if not task_manager.is_running:
        return {"status": "error", "message": "Pipeline is not running"}

    task_manager.stop()
    return {"status": "success", "message": "Pipeline stop requested"}
