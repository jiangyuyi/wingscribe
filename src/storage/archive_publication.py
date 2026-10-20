"""Recoverable publication of metadata-complete JPEGs under one output root."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from src.core.io.path_utils import is_within_directory
from src.storage.catalogue import _json, _now


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class ArchivePublisher:
    def __init__(self, catalogue, photo_store, output_root):
        self.catalogue, self.photo_store = catalogue, photo_store
        self.output_root = Path(output_root).absolute()

    def _checked_path(self, value):
        path = Path(value)
        if not path.is_absolute() or not is_within_directory(path, self.output_root):
            raise ValueError('Archive path is outside the configured output root')
        return path

    def recover(self):
        """Caller holds the catalogue's JobSession lock. Conflicts stop the scan."""
        rows = self.catalogue._read("SELECT * FROM archive_publications WHERE status='pending' "
                                    'AND output_root=? ORDER BY created_at,id', (str(self.output_root),))
        for row in rows:
            self._complete(row)
        return len(rows)

    def publish(self, crop_path, final_path, record, tags, writer, *, version_id, reuse_key):
        for row in self.catalogue._read("SELECT * FROM archive_publications WHERE reuse_key=? "
                                       "AND status='completed' AND output_root=? ORDER BY created_at DESC",
                                       (reuse_key, str(self.output_root))):
            path = self._checked_path(row['final_path'])
            if path.is_file() and _hash(path) == row['sha256']:
                # Never replace or reinsert the associated row (manual labels may exist).
                with self.catalogue.transaction() as tx:
                    photo = tx.conn.execute('SELECT file_path FROM photos WHERE id=?', (row['photo_id'],)).fetchone()
                if photo and photo[0] == json.loads(row['record_json'])['file_path']:
                    return str(path)
        final = self._checked_path(final_path)
        if final.exists():
            raise FileExistsError(f'Archive destination already exists: {final}')
        final.parent.mkdir(parents=True, exist_ok=True)
        publication_id = uuid4().hex
        staged = final.parent / f'.wingscribe-{publication_id}.pending.jpg'
        with staged.open('xb') as destination, Path(crop_path).open('rb') as source:
            shutil.copyfileobj(source, destination)
        # Failed metadata never reaches the final output name or photos table.
        if writer.write_metadata(str(staged), tags) is not True:
            raise RuntimeError(f'Output metadata writing failed; staging retained at {staged}')
        digest = _hash(staged)
        with self.catalogue.transaction() as tx:
            prepared = self.photo_store.prepare_photo_record(tx.conn, record)
            now = _now()
            tx.conn.execute('INSERT INTO archive_publications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (publication_id, version_id, reuse_key, str(self.output_root), str(staged), str(final),
                 digest, _json(prepared), 'pending', None, None, now, now))
        row = self.catalogue._read('SELECT * FROM archive_publications WHERE id=?', (publication_id,))[0]
        return self._complete(row)

    def _complete(self, row):
        try:
            final, staged = self._checked_path(row['final_path']), self._checked_path(row['staged_path'])
            if not final.exists():
                if not staged.is_file() or _hash(staged) != row['sha256']:
                    raise RuntimeError('Prepared archive is missing or its hash changed')
                if os.name == 'nt':
                    os.rename(staged, final)  # Windows refuses to overwrite an existing destination.
                else:
                    os.link(staged, final)  # Atomic no-clobber publication on the same filesystem.
                    staged.unlink()
            if not final.is_file() or _hash(final) != row['sha256']:
                raise RuntimeError('Published archive hash conflict; existing file left untouched')
            with self.catalogue.transaction() as tx:
                current = tx.conn.execute('SELECT status FROM archive_publications WHERE id=?', (row['id'],)).fetchone()
                if current[0] == 'completed':
                    return str(final)
                record = json.loads(row['record_json'])
                if tx.conn.execute('SELECT 1 FROM photos WHERE file_path=?', (record['file_path'],)).fetchone():
                    raise RuntimeError('Archive photo row conflict; existing labels left untouched')
                photo_id = self.photo_store.insert_photo_record_conn(tx.conn, record)
                tx.conn.execute("UPDATE archive_publications SET status='completed',photo_id=?,error=NULL,updated_at=? WHERE id=?",
                                (photo_id, _now(), row['id']))
            return str(final)
        except Exception as exc:
            with self.catalogue.transaction() as tx:
                tx.conn.execute('UPDATE archive_publications SET error=?,updated_at=? WHERE id=?',
                                (str(exc), _now(), row['id']))
            raise
