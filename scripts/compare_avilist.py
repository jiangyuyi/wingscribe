"""Compare two pinned catalogues without inferring historical photo labels."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.metadata.avilist import DEFAULT_CATALOGUE, load_catalogue


def compare(old_path, new_path):
    old, old_manifest = load_catalogue(old_path)
    new, new_manifest = load_catalogue(new_path)
    old_ids = {r['taxon_id']: r for r in old}
    new_ids = {r['taxon_id']: r for r in new}
    old_names = {r['scientific_name']: r for r in old}
    new_names = {r['scientific_name']: r for r in new}
    common = old_ids.keys() & new_ids.keys()
    renamed = [dict(taxon_id=i, old_name=old_ids[i]['scientific_name'],
                    new_name=new_ids[i]['scientific_name'])
               for i in sorted(common)
               if old_ids[i]['scientific_name'] != new_ids[i]['scientific_name']]
    concept_changes = [dict(scientific_name=n, old_id=old_names[n]['taxon_id'],
                            new_id=new_names[n]['taxon_id'])
                       for n in sorted(old_names.keys() & new_names.keys())
                       if old_names[n]['taxon_id'] != new_names[n]['taxon_id']]
    display_changes = [dict(taxon_id=i, old_name=old_ids[i]['scientific_name'],
                            new_name=new_ids[i]['scientific_name'],
                            old_chinese=old_ids[i]['chinese_name'], new_chinese=new_ids[i]['chinese_name'])
                       for i in sorted(common)
                       if old_ids[i]['chinese_name'] != new_ids[i]['chinese_name']]
    return dict(old_version=old_manifest['version'], new_version=new_manifest['version'],
                old_count=len(old), new_count=len(new), shared_concept_ids=len(common),
                renamed_same_id=renamed, same_name_changed_id=concept_changes,
                removed_concepts=[old_ids[i] for i in sorted(old_ids.keys() - new_ids.keys())],
                added_concepts=[new_ids[i] for i in sorted(new_ids.keys() - old_ids.keys())],
                chinese_display_changes=display_changes,
                new_name_status_counts=new_manifest['name_status_counts'],
                photo_labels_rewritten=0,
                note='ID and name comparisons are review evidence; no split/merge photo assignment is inferred')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--old', type=Path, default=DEFAULT_CATALOGUE.with_name('avilist-v2025b.csv'))
    p.add_argument('--new', type=Path, default=DEFAULT_CATALOGUE)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    report = compare(args.old, args.new)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: len(v) if isinstance(v, list) else v for k, v in report.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
