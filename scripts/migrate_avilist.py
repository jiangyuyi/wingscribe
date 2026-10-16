"""Preview or apply the pinned AviList catalogue to an explicitly named database."""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.metadata.avilist import DEFAULT_CATALOGUE, build_catalogue, load_catalogue
from src.metadata.ioc_manager import IOCManager
from src.metadata.taxonomy_catalogue import replace_catalogue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, default=DEFAULT_CATALOGUE)
    parser.add_argument("--apply", action="store_true", help="Without this flag, only inspect the database read-only")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--build-from", type=Path, help="Optional pinned official XLSX to rebuild the catalogue")
    parser.add_argument("--ioc-names", type=Path)
    args = parser.parse_args()
    if args.build_from:
        if not args.ioc_names:
            parser.error("--build-from requires --ioc-names")
        build_catalogue(args.build_from, args.ioc_names, args.ioc_names.parent, args.catalogue)
    rows, manifest = load_catalogue(args.catalogue)
    if args.apply:
        before = None
        # Back up before IOCManager's legacy schema initialization as well.
        if args.database.exists() and args.backup_dir is None:
            parser.error("--apply to an existing database requires --backup-dir")
        if args.database.exists():
            args.backup_dir.mkdir(parents=True, exist_ok=True)
            from uuid import uuid4
            before = args.backup_dir / f"before-schema-{uuid4().hex}.db"
            with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(before)) as target:
                    source.backup(target)
        manager = IOCManager(str(args.database))
        try:
            report = replace_catalogue(manager, rows, manifest, args.backup_dir)
            if before is not None:
                report["pre_schema_backup"] = str(before)
            manager.rebuild_species_stats()
        finally:
            manager.close()
    else:
        with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            old_names = {row[0] for row in conn.execute("SELECT scientific_name FROM taxonomy")}
            active = {row["scientific_name"] for row in rows}
            report = {"status": "preview", "version": manifest["version"], "species_count": len(rows),
                      "legacy_species_count": len(old_names), "same_name_unverified": len(old_names & active),
                      "unmatched_names": sorted(old_names - active),
                      "preserved_photos": conn.execute("SELECT count(*) FROM photos").fetchone()[0],
                      "photo_labels_rewritten": 0}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"review", "unmatched_names"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
