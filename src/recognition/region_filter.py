"""Offline, versioned candidate selection shared by pipeline and local API."""
from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path

from ..metadata.avilist import DEFAULT_CATALOGUE, VERSION, load_catalogue

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHINA = ROOT / 'data/references/china-avilist-v2026.csv'
DEFAULT_FOREIGN = ROOT / 'config/dictionaries/foreign_countries.txt'
SELECTOR_VERSION = 'china-region-v1'
CHINA_VERSION = 'Avibase-China-AviList2026-20261104'
CHINA_SHA256 = '2b7f6a1c1a9c539b35acb48af162d5c0c74e3b3441358ac0b62326d2f93a52ab'
CHINA_SPECIES_COUNT = 1539


class RegionFilterError(ValueError):
    """A restricted candidate request cannot safely be fulfilled."""


def validate_region_support(platform, mode):
    if platform != 'local' and mode in ('china', 'auto'):
        raise RegionFilterError('该云端接口尚未验证推理前候选限定；中国/auto 范围请使用 local，或明确选择 global')


@dataclass(frozen=True)
class CandidateSelection:
    labels: tuple[str, ...]
    metadata: dict


class RegionSelector:
    def __init__(self, labels, taxonomy_version, *, catalogue_path=DEFAULT_CATALOGUE,
                 china_path=DEFAULT_CHINA, foreign_path=DEFAULT_FOREIGN):
        self.labels = tuple(labels)
        self.taxonomy_version = taxonomy_version
        self.catalogue_path = Path(catalogue_path)
        self.china_path = Path(china_path)
        self.foreign_path = Path(foreign_path)
        self._china = None
        self._foreign = None
        self._cache = {}

    def _china_labels(self):
        if self._china is not None:
            return self._china
        try:
            rows, global_manifest = load_catalogue(self.catalogue_path)
            manifest = json.loads(self.china_path.with_suffix('.json').read_text(encoding='utf-8'))
            data = self.china_path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if (self.taxonomy_version != VERSION or manifest['taxonomy_version'] != self.taxonomy_version
                    or manifest['taxonomy_sha256'] != global_manifest['catalogue_sha256']
                    or manifest['subset_sha256'] != digest
                    or digest != CHINA_SHA256 or manifest['version'] != CHINA_VERSION
                    or manifest['species_count'] != CHINA_SPECIES_COUNT
                    or set(self.labels) != {row['scientific_name'] for row in rows}
                    or len(self.labels) != len(rows)):
                raise ValueError('taxonomy or checksum mismatch')
            subset = list(csv.DictReader(data.decode('utf-8').splitlines()))
            by_id = {row['taxon_id']: row['scientific_name'] for row in rows}
            ids = [row['taxon_id'] for row in subset]
            if (not ids or len(ids) != len(set(ids)) or len(ids) != manifest['species_count']
                    or any(by_id.get(row['taxon_id']) != row['scientific_name'] for row in subset)):
                raise ValueError('empty, duplicate or unknown species')
            names = {by_id[taxon_id] for taxon_id in ids}
            labels = tuple(name for name in self.labels if name in names)
            self._china = (labels, manifest['version'], digest)
            return self._china
        except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
            raise RegionFilterError('中国候选名单缺失、损坏或与当前 AviList 不匹配；请修复名单，或明确选择 global 全球模式') from exc

    def _foreign_words(self):
        if self._foreign is None:
            try:
                data = self.foreign_path.read_bytes()
                words = tuple(dict.fromkeys(line.strip() for line in data.decode('utf-8-sig').splitlines()
                                             if line.strip() and not line.lstrip().startswith('#')))
                if not words:
                    raise ValueError('empty dictionary')
                self._foreign = (words, hashlib.sha256(data).hexdigest())
            except (OSError, ValueError) as exc:
                raise RegionFilterError('auto 模式需要有效的国外名称词典；请修复词典或明确选择 china/global') from exc
        return self._foreign

    def select(self, mode=None, location_tag='') -> CandidateSelection:
        mode = 'global' if mode in (None, 'null') else mode
        if mode not in ('china', 'global', 'auto'):
            raise RegionFilterError('区域模式必须为 auto、china 或 global')
        location_tag = location_tag or ''
        matched, dictionary_digest = None, None
        effective = mode
        if mode == 'auto':
            words, dictionary_digest = self._foreign_words()
            matched = next((word for word in words if word in location_tag), None)
            effective = 'global' if matched else 'china'
        key = (mode, effective, matched)
        if key not in self._cache:
            labels, version, digest = (self.labels, None, None)
            if effective == 'china':
                labels, version, digest = self._china_labels()
            self._cache[key] = CandidateSelection(labels, {
                'selector_version': SELECTOR_VERSION, 'requested_region': mode,
                'effective_region': effective, 'matched_foreign_word': matched,
                'reason': ('foreign_keyword' if matched else 'default_china') if mode == 'auto' else 'explicit',
                'candidate_count': len(labels), 'taxonomy_version': self.taxonomy_version,
                'regional_list_version': version, 'regional_list_sha256': digest,
                'foreign_dictionary_sha256': dictionary_digest,
                'candidates_sha256': hashlib.sha256('\n'.join(labels).encode('utf-8')).hexdigest(),
            })
        return self._cache[key]


def selector_from_config(labels, taxonomy_version, config):
    paths = config.get('paths', {})
    def resolve(key, default):
        path = Path(paths.get(key) or default)
        return path if path.is_absolute() else ROOT / path
    return RegionSelector(labels, taxonomy_version,
                          catalogue_path=resolve('taxonomy_catalogue_path', DEFAULT_CATALOGUE),
                          china_path=resolve('china_catalogue_path', DEFAULT_CHINA),
                          foreign_path=resolve('foreign_list', DEFAULT_FOREIGN))
