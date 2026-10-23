import hashlib
from pathlib import Path

import pytest
from PIL import Image

from src.application.culling import CullingService, jpeg_paths
from src.application.quarantine import QuarantinePreview
from src.core.io.local import LocalProvider, SecurityViolationError
from src.core.quarantine_paths import QUARANTINE_DIR, checked_path
from src.storage.catalogue import AssetCatalogue
from src.storage.culling import CullingStore


@pytest.fixture
def setup(tmp_path):
    root = tmp_path/'photos'
    album = root/'album'
    album.mkdir(parents=True)
    for name in ['reject.jpg', 'keep.jpg', 'undecided.jpg']:
        Image.new('RGB', (80, 80), 'gray').save(album/name)
    catalogue = AssetCatalogue(tmp_path/'db.sqlite')
    catalogue.initialize()
    store = CullingStore(catalogue.db_path)
    store.initialize(backup_dir=tmp_path/'backups')
    result = CullingService(catalogue, store, lambda frame: [], detector_identity={'test':'quarantine'}).run(
        album, request_key='test', gap=5, span=30)
    sid = result['snapshot_id']
    versions = {Path(row['relative_path']).name: row['id'] for row in catalogue._read(
        'SELECT v.id,a.relative_path FROM asset_versions v JOIN assets a ON a.id=v.asset_id', ())}
    store.set_decision(versions['reject.jpg'], 'reject', note='人工选择')
    store.set_decision(versions['keep.jpg'], 'keep')
    return root, catalogue, store, sid, versions


def preview(setup, **kwargs):
    root, catalogue, store, sid, _ = setup
    return QuarantinePreview(catalogue, store, kwargs.pop('sources', [root])).build(
        sid, operation_id='a'*32, **kwargs)


def test_preview_only_explicit_reject_and_no_files_or_db_written(setup):
    root, catalogue, store, sid, versions = setup
    files = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    db_hash = hashlib.sha256(catalogue.db_path.read_bytes()).hexdigest()
    plan = preview(setup)
    assert plan['ready'] and plan['count'] == 1
    item = plan['items'][0]
    assert item['version_id'] == versions['reject.jpg']
    assert item['relative_path'] == 'album/reject.jpg'
    assert item['destination_path'] == str(root/QUARANTINE_DIR/('a'*32)/'album/reject.jpg')
    assert preview(setup) == plan
    assert not (root/QUARANTINE_DIR).exists()
    assert files == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert hashlib.sha256(catalogue.db_path.read_bytes()).hexdigest() == db_hash


@pytest.mark.parametrize('change', ['changed', 'missing', 'disabled', 'collision'])
def test_unavailable_preview_blocks_execution(setup, change):
    root, _, _, _, _ = setup
    kwargs = {}
    if change == 'changed':
        (root/'album/reject.jpg').write_bytes(b'changed')
    elif change == 'missing':
        (root/'album/reject.jpg').unlink()
    elif change == 'disabled':
        kwargs['sources'] = [root/'other']
    else:
        target = root/QUARANTINE_DIR/('a'*32)/'album/reject.jpg'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'never overwrite')
    plan = preview(setup, **kwargs)
    assert not plan['ready'] and not plan['items'][0]['eligible']
    assert plan['items'][0]['error']


def test_overlapping_sources_use_most_specific_independent_of_order(setup):
    root = setup[0]
    a = preview(setup, sources=[root, root/'album'])
    b = preview(setup, sources=[root/'album', root])
    assert a == b
    assert a['items'][0]['source_root'] == str(root/'album')
    assert a['items'][0]['relative_path'] == 'reject.jpg'


def test_decision_edit_changes_preview_and_keep_removes_candidate(setup):
    _, _, store, _, versions = setup
    before = preview(setup)
    store.set_decision(versions['reject.jpg'], 'reject', note='changed')
    assert preview(setup)['preview_hash'] != before['preview_hash']
    store.set_decision(versions['reject.jpg'], 'keep')
    after = preview(setup)
    assert not after['ready'] and after['count'] == 0


@pytest.mark.parametrize('strict', [True, False])
def test_scanners_skip_quarantine_including_explicit_root(setup, strict):
    root = setup[0]
    quarantine = root/'.WINGSCRIBE-QUARANTINE'
    quarantine.mkdir()
    Image.new('RGB', (10, 10)).save(quarantine/'ignored.jpg')
    assert len(list(jpeg_paths(root))) == 3
    with pytest.raises(ValueError):
        list(jpeg_paths(quarantine))
    provider = LocalProvider(str(root))
    provider.strict = strict
    entries = list(provider.list_dir(str(root), recursive=True))
    assert all('ignored.jpg' not in entry.path for entry in entries)
    with pytest.raises(SecurityViolationError):
        list(provider.list_dir(str(quarantine), recursive=True))


def test_invalid_operation_unknown_snapshot_and_path_traversal(setup):
    root, catalogue, store, sid, _ = setup
    service = QuarantinePreview(catalogue, store, [root])
    with pytest.raises(ValueError):
        service.build(sid, operation_id='../outside')
    with pytest.raises(LookupError):
        service.build('missing')
    with pytest.raises(ValueError):
        checked_path(root, Path('../outside'))


def test_reparse_point_rejected_without_requiring_windows_link_privilege(setup, monkeypatch):
    import stat
    from types import SimpleNamespace
    root = setup[0]
    original = Path.lstat
    def lstat(path):
        if path == root/'album':
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path)
    monkeypatch.setattr(Path, 'lstat', lstat)
    plan = preview(setup)
    assert not plan['ready'] and '联接' in plan['items'][0]['error']
