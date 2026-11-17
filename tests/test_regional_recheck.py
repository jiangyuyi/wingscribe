import hashlib
import json
import sqlite3

import pytest

from scripts.preview_regional_recheck import preview


def test_preview_is_read_only_and_does_not_treat_unknown_scope_as_global(tmp_path):
    path = tmp_path / 'history.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE photos (label_source TEXT)')
        conn.execute("INSERT INTO photos VALUES ('manual')")
        conn.execute('CREATE TABLE analysis_runs (id TEXT, parameters_json TEXT)')
        conn.execute('CREATE TABLE detections (analysis_id TEXT,result_json TEXT)')
        for key, location, scope in [('domestic', '北京', 'global'), ('foreign', '日本', 'global'),
                                     ('restricted', '北京', 'china'), ('unknown', '', None)]:
            parameters = {'metadata': {'location_tag': location}}
            if scope:
                parameters['region_selection'] = {'effective_region': scope}
            conn.execute('INSERT INTO analysis_runs VALUES (?,?)', (key, json.dumps(parameters)))
            conn.execute('INSERT INTO detections VALUES (?,?)', (key, json.dumps({
                'candidates': [{'scientific_name': 'Cyanocitta cristata'}, {'scientific_name': 'Passer montanus'}]})))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    report = preview(path)
    assert report['domestic_global_analysis_count'] == 1
    assert report['domestic_unknown_scope_count'] == 1
    assert report['outside_current_regional_names'] == 1
    assert report['manual_photo_count'] == 1
    assert report['review_analysis_ids'] == ['domestic']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_preview_does_not_create_missing_database(tmp_path):
    path = tmp_path / 'missing.db'
    with pytest.raises(FileNotFoundError):
        preview(path)
    assert not path.exists()


@pytest.mark.parametrize('release', ['avilist-v2025b.csv', 'avilist-v2026.csv'])
def test_preview_recognizes_old_sqlite_sorted_candidate_hash(tmp_path, release):
    from src.metadata.avilist import DEFAULT_CATALOGUE, load_catalogue
    rows, _ = load_catalogue(DEFAULT_CATALOGUE.with_name(release))
    labels = sorted(row['scientific_name'] for row in rows)
    signature = hashlib.sha256(json.dumps(labels, ensure_ascii=False).encode()).hexdigest()
    path = tmp_path / 'history.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE analysis_runs (id TEXT,parameters_json TEXT)')
        conn.execute('CREATE TABLE detections (analysis_id TEXT,result_json TEXT)')
        conn.execute('INSERT INTO analysis_runs VALUES (?,?)', ('old', json.dumps({
            'metadata': {'location_tag': '北京'}, 'candidates_sha256': signature})))
    report = preview(path)
    assert report['domestic_global_analysis_count'] == 1
    assert report['domestic_unknown_scope_count'] == 0
