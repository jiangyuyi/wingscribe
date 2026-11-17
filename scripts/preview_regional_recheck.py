"""Read-only counts of domestic analyses previously classified with global candidates.

This does not enqueue work, relabel photos, or delete old archives. Outside-list
names are review leads, not proof that an identification or historical name is wrong.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

# The installed embedded runtime isolates sys.path; support direct script use.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.metadata.avilist import DEFAULT_CATALOGUE, load_catalogue
from src.recognition.region_filter import RegionSelector


def preview(database: Path):
    database = Path(database).resolve(strict=True)
    rows, manifest = load_catalogue()
    selector = RegionSelector([row['scientific_name'] for row in rows], manifest['version'])
    china = set(selector.select('china').labels)
    fingerprints = set()
    for path in (DEFAULT_CATALOGUE, DEFAULT_CATALOGUE.with_name('avilist-v2025b.csv')):
        release, _ = load_catalogue(path)
        labels = [row['scientific_name'] for row in release]
        # Old SQLite scans commonly traversed the scientific-name index. New
        # code uses canonical CSV order; both exact historical signatures count.
        for ordered in (labels, sorted(labels)):
            fingerprints.add(hashlib.sha256(json.dumps(ordered, ensure_ascii=False).encode()).hexdigest())
    report = {'read_only': True, 'domestic_global_analysis_count': 0,
              'domestic_unknown_scope_count': 0, 'outside_current_regional_names': 0,
              'manual_photo_count': 0, 'review_analysis_ids': [],
              'note': 'Counts include analysis history, not unique photos. Outside-list names may be historical names or valid captive/foreign birds. No reprocessing or relabeling is performed.'}
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'photos' in tables:
            columns = {row[1] for row in connection.execute('PRAGMA table_info(photos)')}
            if 'label_source' in columns:
                report['manual_photo_count'] = connection.execute("SELECT count(*) FROM photos WHERE label_source='manual'").fetchone()[0]
        if not {'analysis_runs', 'detections'}.issubset(tables):
            report['status'] = 'no_analysis_history'
            return report
        for analysis_id, parameters_json in connection.execute('SELECT id,parameters_json FROM analysis_runs ORDER BY id'):
            parameters = json.loads(parameters_json)
            location = parameters.get('metadata', {}).get('location_tag', '')
            if selector.select('auto', location).metadata['effective_region'] != 'china':
                continue
            scope = parameters.get('region_selection', {}).get('effective_region')
            if scope is None and parameters.get('candidates_sha256') in fingerprints:
                scope = 'global'
            if scope is None:
                report['domestic_unknown_scope_count'] += 1
                continue
            if scope != 'global':
                continue
            report['domestic_global_analysis_count'] += 1
            report['review_analysis_ids'].append(analysis_id)
            for (result_json,) in connection.execute('SELECT result_json FROM detections WHERE analysis_id=?', (analysis_id,)):
                candidates = json.loads(result_json).get('candidates', [])
                report['outside_current_regional_names'] += sum(
                    bool(item.get('scientific_name')) and item['scientific_name'] not in china for item in candidates)
        report['status'] = 'preview_only'
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = preview(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'review_analysis_ids'}, ensure_ascii=False))
