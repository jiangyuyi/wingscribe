import csv
import hashlib
import logging
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class LocationResult:
    location_raw: str
    province: str | None = None
    city: str | None = None
    district: str | None = None
    site: str | None = None
    source: str = "unknown"
    confidence: float = 0.0

    @property
    def resolved(self) -> bool:
        return self.source != "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class _AdminRecord:
    province: str
    city: str
    district: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class _AliasRule:
    match: str
    province: str | None
    city: str | None
    district: str | None
    site: str | None
    parent_matches: tuple[str, ...]


class LocationResolver:
    """Resolve raw path location text without changing the original location tag."""

    def __init__(self, admin_path: str | Path | None = None, aliases_path: str | Path | None = None):
        self.admin_path = Path(admin_path) if admin_path else None
        self.aliases_path = Path(aliases_path) if aliases_path else None
        self._admin_records = self._load_admin_records()
        self._alias_rules = self._load_alias_rules()
        self.dictionary_version = self._calculate_dictionary_version()
        self._cache: dict[tuple[str, str], LocationResult] = {}
        self._cache_lock = threading.Lock()

    @staticmethod
    def normalize(value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"[\W_]+", "", str(value), flags=re.UNICODE).casefold()

    def resolve(self, location_raw: str, *, gps: tuple[float, float] | None = None) -> LocationResult:
        del gps  # Reserved for a future reverse-geocoding provider.
        normalized = self.normalize(location_raw)
        cache_key = (normalized, self.dictionary_version)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = self._resolve_alias(location_raw, normalized)
        if result is None:
            result = self._resolve_admin(location_raw, normalized)
        if result is None:
            result = LocationResult(location_raw=location_raw)

        with self._cache_lock:
            self._cache[cache_key] = result
        return result

    def _resolve_alias(self, location_raw: str, normalized: str) -> LocationResult | None:
        matches = []
        for rule in self._alias_rules:
            match = self.normalize(rule.match)
            if not match or match not in normalized:
                continue
            if any(self.normalize(parent) not in normalized for parent in rule.parent_matches):
                continue
            matches.append((len(match), rule))

        if not matches:
            return None
        longest = max(length for length, _ in matches)
        winners = [rule for length, rule in matches if length == longest]
        locations = {
            (rule.province, rule.city, rule.district, rule.site)
            for rule in winners
        }
        if len(locations) != 1:
            return None

        rule = winners[0]
        return LocationResult(
            location_raw=location_raw,
            province=rule.province,
            city=rule.city,
            district=rule.district,
            site=rule.site or rule.match,
            source="exact_site_alias",
            confidence=1.0,
        )

    def _resolve_admin(self, location_raw: str, normalized: str) -> LocationResult | None:
        candidates = []
        for record in self._admin_records:
            terms = self._record_terms(record)
            matched = [(term, level) for term, level in terms if term and term in normalized]
            if not matched:
                continue
            primary_length = max(len(term) for term, _ in matched)
            primary_level = max(level for term, level in matched if len(term) == primary_length)
            if primary_level == 1:
                parent_values = ()
            elif primary_level == 2:
                parent_values = (record.province,)
            else:
                parent_values = (record.province, record.city)
            parent_support = len(
                {
                    self.normalize(value)
                    for value in parent_values
                    if self.normalize(value) and self.normalize(value) in normalized
                }
            )
            candidates.append((primary_length, parent_support, primary_level, record))

        if not candidates:
            return None

        best_length = max(candidate[0] for candidate in candidates)
        longest = [candidate for candidate in candidates if candidate[0] == best_length]
        best_parent_support = max(candidate[1] for candidate in longest)
        contextual = [candidate for candidate in longest if candidate[1] == best_parent_support]
        contextual_locations = {(row.province, row.city, row.district) for *_, row in contextual}
        if best_parent_support == 0 and len(contextual_locations) != 1:
            return None

        best_level = max(candidate[2] for candidate in contextual)
        winners = [candidate[3] for candidate in contextual if candidate[2] == best_level]
        locations = {(row.province, row.city, row.district) for row in winners}
        if len(locations) != 1:
            return None

        record = winners[0]
        return LocationResult(
            location_raw=location_raw,
            province=record.province or None,
            city=record.city or None,
            district=record.district or None,
            source="exact_admin",
            confidence=1.0,
        )

    def _record_terms(self, record: _AdminRecord) -> list[tuple[str, int]]:
        terms = []
        for value, level in ((record.province, 1), (record.city, 2), (record.district, 3)):
            normalized = self.normalize(value)
            if normalized:
                terms.append((normalized, level))
        alias_level = 3 if record.district else 2 if record.city else 1
        terms.extend((self.normalize(alias), alias_level) for alias in record.aliases if self.normalize(alias))
        return terms

    def _load_admin_records(self) -> tuple[_AdminRecord, ...]:
        if not self.admin_path or not self.admin_path.is_file():
            return ()
        records = []
        try:
            with self.admin_path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    province = (row.get("province") or "").strip()
                    city = (row.get("city") or "").strip()
                    district = (row.get("district") or "").strip()
                    if not any((province, city, district)):
                        continue
                    aliases = tuple(
                        value.strip()
                        for value in re.split(r"[|;]", row.get("aliases") or "")
                        if value.strip()
                    )
                    records.append(_AdminRecord(province, city, district, aliases))
        except (OSError, csv.Error) as exc:
            logging.warning("Could not load administrative division dictionary %s: %s", self.admin_path, exc)
            return ()
        return tuple(records)

    def _load_alias_rules(self) -> tuple[_AliasRule, ...]:
        if not self.aliases_path or not self.aliases_path.is_file():
            return ()
        try:
            payload = yaml.safe_load(self.aliases_path.read_text(encoding="utf-8-sig")) or {}
            items = payload.get("aliases", []) if isinstance(payload, dict) else []
            rules = []
            for item in items:
                if not isinstance(item, dict) or not str(item.get("match", "")).strip():
                    continue
                parent_matches = item.get("parent_matches", [])
                if isinstance(parent_matches, str):
                    parent_matches = [parent_matches]
                rules.append(
                    _AliasRule(
                        match=str(item["match"]).strip(),
                        province=self._optional_text(item.get("province")),
                        city=self._optional_text(item.get("city")),
                        district=self._optional_text(item.get("district")),
                        site=self._optional_text(item.get("site")),
                        parent_matches=tuple(str(value).strip() for value in parent_matches if str(value).strip()),
                    )
                )
            return tuple(rules)
        except (OSError, yaml.YAMLError) as exc:
            logging.warning("Could not load location aliases %s: %s", self.aliases_path, exc)
            return ()

    @staticmethod
    def _optional_text(value) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    def _calculate_dictionary_version(self) -> str:
        digest = hashlib.sha256()
        for path in (self.admin_path, self.aliases_path):
            if path and path.is_file():
                try:
                    digest.update(path.read_bytes())
                except OSError:
                    digest.update(str(path).encode("utf-8"))
        return digest.hexdigest()[:16]
