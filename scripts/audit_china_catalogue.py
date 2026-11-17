"""Explain regional membership and legacy-name differences without guessing taxonomy."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from src.metadata.avilist import DEFAULT_CATALOGUE, load_catalogue
from src.recognition.region_filter import RegionSelector, ROOT


def audit():
    rows, manifest = load_catalogue()
    selection = RegionSelector([row['scientific_name'] for row in rows], manifest['version']).select('china')
    included = set(selection.labels)
    current_names = {row['scientific_name']: row for row in rows}
    current_ids = {row['taxon_id']: row for row in rows}
    old_rows, _ = load_catalogue(DEFAULT_CATALOGUE.with_name('avilist-v2025b.csv'))
    old_names = {row['scientific_name']: row for row in old_rows}
    legacy = sorted(set((ROOT / 'config/dictionaries/china_bird_list.txt').read_text(encoding='utf-8').splitlines()))
    review = []
    for name in legacy:
        current = current_names.get(name)
        if current:
            status = 'same_current_name_in_region' if name in included else 'current_global_species_absent_from_regional_source'
            evidence = 'exact current name; not proof of legacy concept equivalence'
        else:
            previous = old_names.get(name)
            current = current_ids.get(previous['taxon_id']) if previous else None
            status = ('prior_id_current_name_in_region' if current['scientific_name'] in included
                      else 'prior_id_current_name_absent_from_regional_source') if current else 'legacy_name_unresolved_in_pinned_global'
            evidence = 'matching prior AviList AvibaseID; not a legacy IOC concept migration' if current else 'no exact name/prior ID link; no fuzzy or Chinese-name guess'
        review.append({'legacy_name': name, 'status': status,
                       'current_name': current['scientific_name'] if current else None,
                       'current_id': current['taxon_id'] if current else None, 'evidence': evidence})
    snapshot = json.loads((ROOT / 'data/references/china-avibase-2026-snapshot.json').read_text(encoding='utf-8'))
    evidence = {}
    for code, region in snapshot['regions'].items():
        for value in region['ids']:
            evidence.setdefault('avibase-' + value, []).append(code)
    return {
        'region': selection.metadata,
        'legacy_count': len(legacy), 'legacy_status_counts': dict(Counter(row['status'] for row in review)),
        'new_names_absent_from_legacy_count': len(included - set(legacy)),
        'policy': 'Membership follows the reviewed Avibase regional union. Legacy differences are reported, not silently added. An unresolved legacy name does not mean a Chinese species was lost. Same-name/ID links do not relabel historical photos.',
        'regional_mapping': [{'taxon_id': row['taxon_id'], 'scientific_name': row['scientific_name'],
                              'capture_evidence': evidence[row['taxon_id']], 'status': 'exact_current_concept_id'}
                             for row in rows if row['scientific_name'] in included],
        'legacy_review': review,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('regional_mapping', 'legacy_review')}, ensure_ascii=False))
