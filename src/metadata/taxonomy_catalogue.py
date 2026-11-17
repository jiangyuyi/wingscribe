"""Transactional active-catalogue replacement; legacy labels remain unchanged."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .avilist import (DEFAULT_CATALOGUE, FIELDS, load_catalogue, validate_species,
                      VERSION, LEGACY_VERSION, LEGACY_CATALOGUE_SHA256, CATALOGUE_SHA256)


@contextmanager
def migration_guard(database: Path):
    """Share the processing/culling OS lock; never recover jobs during migration."""
    from types import SimpleNamespace
    from src.storage.job_session import JobSession
    from contextlib import closing
    database = Path(database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    with JobSession(SimpleNamespace(db_path=database)):
        if database.is_file():
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='processing_jobs'").fetchone():
                    if conn.execute("SELECT 1 FROM processing_jobs WHERE status='running'").fetchone():
                        raise RuntimeError('Finish or explicitly recover the running job before taxonomy migration')
        yield


def current_release(conn: sqlite3.Connection) -> dict | None:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='taxonomy_release'").fetchone()
    if not exists:
        return None
    row = conn.execute("SELECT manifest_json FROM taxonomy_release WHERE id=1").fetchone()
    return json.loads(row[0]) if row else None


def replace_catalogue(manager, rows: list[dict], manifest: dict, backup_dir: Path | None = None,
                      *, upgrade_from: str | None = None, _migration_guard_held=False) -> dict:
    """Replace active species atomically, keeping legacy taxonomy and photo labels.

    Existing file databases require a consistent SQLite backup. A reserved write
    lock prevents another writer changing the database between backup and import.
    No legacy species is asserted to be equivalent on the basis of spelling.
    """
    if upgrade_from and manager.db_path != ':memory:' and not _migration_guard_held:
        with migration_guard(Path(manager.db_path)):
            return replace_catalogue(manager, rows, manifest, backup_dir,
                                     upgrade_from=upgrade_from, _migration_guard_held=True)
    validate_species(rows)
    if len(rows) != manifest["species_count"]:
        raise ValueError("Species count mismatch")
    conn = manager.conn
    if conn.in_transaction:
        raise RuntimeError("Finish the current database transaction before importing")
    with manager._write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            previous = current_release(conn)
            if upgrade_from and not previous:
                raise ValueError('Version upgrade requires an existing versioned catalogue')
            if previous and previous["catalogue_sha256"] == manifest["catalogue_sha256"]:
                count = conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0]
                if count != len(rows):
                    raise ValueError("Active catalogue is incomplete; restore backup before retrying")
                conn.rollback()
                return {"status": "already_current", "version": manifest["version"], "species_count": count}
            if previous:
                if not (upgrade_from == LEGACY_VERSION == previous['version']
                        and manifest['version'] == VERSION
                        and previous['catalogue_sha256'] == LEGACY_CATALOGUE_SHA256
                        and manifest['catalogue_sha256'] == CATALOGUE_SHA256):
                    raise ValueError("A different versioned catalogue is installed; a release-specific migration is required")
                pinned_target, _ = load_catalogue()
                if rows != pinned_target:
                    raise ValueError('Target catalogue differs from the pinned release')
                # Validate the actual active rows, not just the stored version label.
                expected, _ = load_catalogue(DEFAULT_CATALOGUE.with_name('avilist-v2025b.csv'))
                actual = {r['scientific_name']: dict(r) for r in conn.execute('SELECT * FROM taxonomy')}
                if len(actual) != len(expected) or any(
                        name not in actual or any(actual[name].get(k) != row[k] for k in FIELDS[:9])
                        for row in expected for name in [row['scientific_name']]):
                    raise ValueError('Active legacy catalogue differs from the pinned release')
                expected_ids = {r['scientific_name']: r['taxon_id'] for r in expected}
                if dict(conn.execute('SELECT scientific_name,taxon_id FROM taxonomy_provenance')) != expected_ids:
                    raise ValueError('Active legacy provenance differs from the pinned release')
            legacy = [dict(row) for row in conn.execute("SELECT * FROM taxonomy")]
            photo_count = conn.execute("SELECT count(*) FROM photos").fetchone()[0]
            backup_path = None
            if legacy or photo_count:
                if manager.db_path != ":memory:":
                    if backup_dir is None:
                        raise ValueError("A backup directory is required for an existing database")
                    backup_dir = Path(backup_dir)
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    backup_path = backup_dir / f"before-avilist-{stamp}-{uuid4().hex[:8]}.db"
                    source = sqlite3.connect(Path(manager.db_path).resolve().as_uri() + "?mode=ro", uri=True)
                    target = sqlite3.connect(backup_path)
                    try:
                        source.backup(target)
                        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise RuntimeError("Backup integrity check failed")
                    finally:
                        target.close()
                        source.close()
            active_names = {row["scientific_name"] for row in rows}
            review = [
                {"legacy_name": row["scientific_name"],
                 "candidate_name": row["scientific_name"] if row["scientific_name"] in active_names else None,
                 "status": "same_name_unverified" if row["scientific_name"] in active_names else "unmatched"}
                for row in legacy
            ]
            if previous:
                conn.execute('''CREATE TABLE IF NOT EXISTS taxonomy_release_history (
                    version TEXT PRIMARY KEY, manifest_json TEXT NOT NULL,
                    taxonomy_json TEXT NOT NULL, provenance_json TEXT NOT NULL, archived_at TEXT NOT NULL)''')
                provenance = [dict(r) for r in conn.execute('SELECT * FROM taxonomy_provenance')]
                conn.execute('INSERT INTO taxonomy_release_history VALUES (?,?,?,?,?)',
                             (previous['version'], json.dumps(previous, ensure_ascii=False),
                              json.dumps(legacy, ensure_ascii=False), json.dumps(provenance, ensure_ascii=False),
                              datetime.now(timezone.utc).isoformat()))
                conn.execute('DELETE FROM taxonomy_provenance')
            else:
                conn.execute("CREATE TABLE taxonomy_legacy AS SELECT * FROM taxonomy")
            conn.execute("CREATE TABLE IF NOT EXISTS taxonomy_release (id INTEGER PRIMARY KEY CHECK(id=1), manifest_json TEXT NOT NULL)")
            conn.execute("""CREATE TABLE IF NOT EXISTS taxonomy_provenance (
                scientific_name TEXT PRIMARY KEY, taxon_id TEXT UNIQUE NOT NULL,
                version TEXT NOT NULL, chinese_name_source TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS taxonomy_legacy_review (
                legacy_name TEXT PRIMARY KEY, candidate_name TEXT, status TEXT NOT NULL)""")
            conn.execute("DELETE FROM taxonomy")
            columns = FIELDS[:9]
            sql = f"INSERT INTO taxonomy ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
            conn.executemany(sql, [tuple(row[column] for column in columns) for row in rows])
            conn.executemany(
                "INSERT INTO taxonomy_provenance VALUES (?, ?, ?, ?)",
                [(row["scientific_name"], row["taxon_id"], manifest["version"], row["chinese_name_source"]) for row in rows],
            )
            if not previous:
                conn.executemany("INSERT INTO taxonomy_legacy_review VALUES (:legacy_name, :candidate_name, :status)", review)
            conn.execute("INSERT OR REPLACE INTO taxonomy_release VALUES (1, ?)", (json.dumps(manifest, ensure_ascii=False),))
            # Derived legacy statistics must not continue describing the old tree.
            conn.execute("DELETE FROM species_stats")
            if conn.execute("SELECT count(*) FROM photos").fetchone()[0] != photo_count:
                raise RuntimeError("Photo count changed during catalogue replacement")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return {
        "status": "imported", "version": manifest["version"], "species_count": len(rows),
        "legacy_species_count": len(legacy), "preserved_photos": photo_count,
        "photo_labels_rewritten": 0, "backup_path": str(backup_path) if backup_path else None,
        "previous_version": previous['version'] if previous else None,
        "review": review,
    }


def ensure_taxonomy(manager, config: dict, base_dir: Path | None = None) -> None:
    """Bootstrap empty catalogues only; existing libraries require explicit migration."""
    if manager.conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0]:
        return
    root = base_dir or Path(__file__).resolve().parents[2]
    configured = config.get("paths", {}).get("taxonomy_catalogue_path")
    path = Path(configured) if configured else DEFAULT_CATALOGUE
    if not path.is_absolute():
        path = root / path
    rows, manifest = load_catalogue(path)
    replace_catalogue(manager, rows, manifest, backup_dir=root / "data/backups")
