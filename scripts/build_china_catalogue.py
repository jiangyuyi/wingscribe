"""Build an offline China union from reviewed Avibase AviList-2026 ID snapshots.

Run from the repository root with ``python -m scripts.build_china_catalogue``.
No network requests, fuzzy names, or legacy Chinese-name inference are used.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from src.metadata.avilist import DEFAULT_CATALOGUE, load_catalogue

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'data/references/china-avibase-2026-snapshot.json'
OUTPUT = ROOT / 'data/references/china-avilist-v2026.csv'


def build(snapshot_path=SNAPSHOT, output=OUTPUT):
    capture = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    if set(capture['regions']) != {'CN', 'TW', 'HK', 'MO'}:
        raise ValueError('All four regional pages must be reviewed before building')
    if not capture.get('status', '').startswith('complete;'):
        raise ValueError('Capture is not reviewed')
    rows, taxonomy = load_catalogue(DEFAULT_CATALOGUE)
    by_id = {row['taxon_id']: row for row in rows}
    ids = set()
    for code, region in capture['regions'].items():
        values = region['ids']
        if len(values) != len(set(values)) or any(len(value) != 8 for value in values):
            raise ValueError(f'Invalid captured IDs: {code}')
        if code == 'CN' and len(values) != region['page_species_count']:
            raise ValueError('CN capture is incomplete')
        checksum = 2166136261
        for byte in (','.join(values) + '\n').encode('utf-8'):
            checksum = ((checksum ^ byte) * 16777619) & 0xffffffff
        if f'{checksum:08x}' != region.get('fnv32', region.get('delta_fnv32')):
            raise ValueError(f'Capture transport checksum mismatch: {code}')
        ids.update('avibase-' + value for value in values)
    unknown = ids - by_id.keys()
    if unknown:
        raise ValueError(f'Unknown AviList concepts: {sorted(unknown)}')
    subset = [row for row in rows if row['taxon_id'] in ids]
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['taxon_id', 'scientific_name'], lineterminator='\n', extrasaction='ignore')
    writer.writeheader()
    writer.writerows(subset)
    data = stream.getvalue().encode('utf-8')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    manifest = {
        'version': 'Avibase-China-AviList2026-20261104',
        'taxonomy_version': taxonomy['version'], 'taxonomy_sha256': taxonomy['catalogue_sha256'],
        'species_count': len(subset), 'subset_sha256': hashlib.sha256(data).hexdigest(),
        'snapshot_sha256': hashlib.sha256(Path(snapshot_path).read_bytes()).hexdigest(),
        'scope': 'Union of CN, TW, HK, MO; all listed species including rare/accidental records',
        'mapping': 'Exact first 8 hexadecimal digits of Avibase concept IDs to AviList AvibaseID; names from pinned AviList',
        'source': 'Avibase regional checklists, AviList 2026, Denis Lepage / Birds Canada',
        'source_urls': {code: row['url'] for code, row in capture['regions'].items()},
        'license_note': 'Regional membership facts derived from attributed Avibase pages; no page text or display names copied. AviList taxonomy CC BY 4.0 does not license Avibase pages. Public redistribution review remains separate.',
        'build': 'python -m scripts.build_china_catalogue; offline, stable AviList order',
    }
    output.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=SNAPSHOT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.snapshot, args.output), ensure_ascii=False, indent=2))
