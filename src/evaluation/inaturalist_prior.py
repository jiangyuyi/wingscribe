from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import httpx

from src.recognition.prior import PRIOR_SCHEMA_VERSION, PriorFormatError

from .datasets import DatasetFormatError


API_URL = "https://api.inaturalist.org/v1/observations/species_counts"
PLACE_AUTOCOMPLETE_URL = "https://api.inaturalist.org/v1/places/autocomplete"
OBSERVATIONS_URL = "https://api.inaturalist.org/v1/observations"
PROVINCE_CATALOG_SCHEMA_VERSION = 1
PROVINCE_ASSIGNMENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProvinceRegion:
    region_code: str
    province: str
    query: str
    expected_name: str
    place_id: int | None = None


def load_province_catalog(path: str | Path) -> tuple[dict[str, Any], tuple[ProvinceRegion, ...]]:
    catalog_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetFormatError(f"Unable to read province catalog: {catalog_path}") from exc
    if payload.get("schema_version") != PROVINCE_CATALOG_SCHEMA_VERSION:
        raise DatasetFormatError("Unsupported province catalog schema version")
    source = payload.get("source") or {}
    if int(source.get("country_place_id") or 0) < 1:
        raise DatasetFormatError("Province catalog country_place_id is invalid")
    try:
        regions = tuple(
            ProvinceRegion(
                region_code=str(item["region_code"]).strip(),
                province=str(item["province"]).strip(),
                query=str(item["query"]).strip(),
                expected_name=str(item["expected_name"]).strip(),
            )
            for item in payload.get("regions") or []
        )
    except (KeyError, TypeError) as exc:
        raise DatasetFormatError("Province catalog contains an invalid region") from exc
    codes = [region.region_code for region in regions]
    if (
        not regions
        or any(not all((region.region_code, region.province, region.query, region.expected_name)) for region in regions)
        or any(not code.startswith("CN-") for code in codes)
        or len(codes) != len(set(codes))
    ):
        raise DatasetFormatError("Province catalog regions must have unique non-empty CN codes")
    return dict(source), regions


def resolve_province_places(
    client: httpx.Client,
    source: Mapping[str, Any],
    regions: Sequence[ProvinceRegion],
    *,
    request_delay_seconds: float = 0.1,
) -> tuple[ProvinceRegion, ...]:
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must not be negative")
    country_place_id = int(source.get("country_place_id") or 0)
    if country_place_id < 1:
        raise ValueError("country_place_id must be positive")
    resolved = []
    for region in regions:
        response = client.get(
            PLACE_AUTOCOMPLETE_URL,
            params={"q": region.query, "per_page": 20},
        )
        response.raise_for_status()
        matches = [
            item
            for item in response.json().get("results") or []
            if str(item.get("name") or "").casefold() == region.expected_name.casefold()
            and int(item.get("admin_level") or -1) == 10
            and country_place_id in (item.get("ancestor_place_ids") or [])
        ]
        if len(matches) != 1:
            raise DatasetFormatError(
                f"Expected one official iNaturalist province for {region.region_code}, found {len(matches)}"
            )
        resolved.append(
            ProvinceRegion(
                region_code=region.region_code,
                province=region.province,
                query=region.query,
                expected_name=region.expected_name,
                place_id=int(matches[0]["id"]),
            )
        )
        if request_delay_seconds:
            time.sleep(request_delay_seconds)
    place_ids = [region.place_id for region in resolved]
    if len(place_ids) != len(set(place_ids)):
        raise DatasetFormatError("Resolved province place IDs must be unique")
    return tuple(resolved)


def load_manifest_candidate_labels(path: str | Path) -> tuple[str, ...]:
    manifest_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetFormatError(f"Unable to read candidate manifest: {manifest_path}") from exc
    labels = tuple(str(item).strip() for item in payload.get("candidate_labels") or [])
    if not labels or any(not item for item in labels) or len(labels) != len(set(labels)):
        raise DatasetFormatError("Candidate manifest labels must be non-empty and unique")
    return labels


def fetch_species_month_counts(
    client: httpx.Client,
    *,
    place_id: int = 6903,
    taxon_id: int = 3,
    cutoff_date: str = "2021-12-31",
    max_api_records: int = 20_000,
    request_delay_seconds: float = 0.1,
    per_page: int = 200,
    months: Iterable[int] = range(1, 13),
) -> tuple[Counter[tuple[str, int]], dict[str, Any]]:
    if max_api_records < 1 or not 1 <= per_page <= 200:
        raise ValueError("API record and page limits are invalid")
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must not be negative")

    queried_months = tuple(months)
    if (
        not queried_months
        or len(queried_months) != len(set(queried_months))
        or any(not 1 <= month <= 12 for month in queried_months)
    ):
        raise ValueError("months must contain unique values between 1 and 12")

    counts: Counter[tuple[str, int]] = Counter()
    scanned = 0
    counted = 0
    reported_rows_by_month: dict[str, int] = {}
    truncated = False

    for month in queried_months:
        page = 1
        month_scanned = 0
        month_total: int | None = None
        while scanned < max_api_records:
            params: dict[str, Any] = {
                "place_id": place_id,
                "taxon_id": taxon_id,
                "quality_grade": "research",
                "rank": "species",
                "d2": cutoff_date,
                "month": month,
                "locale": "en",
                "page": page,
                "per_page": min(per_page, max_api_records - scanned),
            }
            response = client.get(API_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            if month_total is None:
                month_total = int(payload.get("total_results") or 0)
                reported_rows_by_month[str(month)] = month_total
            results = payload.get("results") or []
            if not results:
                break

            for item in results:
                scanned += 1
                month_scanned += 1
                taxon = item.get("taxon") or {}
                count = int(item.get("count") or 0)
                if taxon.get("rank") == "species" and taxon.get("name") and count > 0:
                    counts[(str(taxon["name"]), month)] += count
                    counted += count
                if scanned >= max_api_records:
                    break

            if month_total is not None and month_scanned >= month_total:
                break
            if len(results) < int(params["per_page"]):
                break
            page += 1
            if request_delay_seconds:
                time.sleep(request_delay_seconds)

        if month_total is None or month_scanned < month_total:
            truncated = True
            break

    return counts, {
        "name": "iNaturalist observations",
        "api_url": API_URL,
        "place_id": place_id,
        "taxon_id": taxon_id,
        "quality_grade": "research",
        "rank": "species",
        "cutoff_date": cutoff_date,
        "locale": "en",
        "queried_months": list(queried_months),
        "reported_species_rows_by_month": reported_rows_by_month,
        "species_count_rows_scanned": scanned,
        "observations_counted": counted,
        "truncated": truncated,
    }


def fetch_species_province_counts(
    client: httpx.Client,
    regions: Sequence[ProvinceRegion],
    *,
    taxon_id: int = 3,
    cutoff_date: str = "2021-12-31",
    max_api_records: int = 20_000,
    request_delay_seconds: float = 0.1,
    per_page: int = 200,
) -> tuple[Counter[tuple[str, str]], dict[str, Any]]:
    if max_api_records < 1 or not 1 <= per_page <= 200:
        raise ValueError("API record and page limits are invalid")
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must not be negative")
    if not regions or any(region.place_id is None for region in regions):
        raise ValueError("All province regions must have resolved place IDs")

    counts: Counter[tuple[str, str]] = Counter()
    scanned = 0
    counted = 0
    reported_rows_by_region: dict[str, int] = {}
    truncated_regions: list[str] = []
    for region in regions:
        page = 1
        region_scanned = 0
        region_total: int | None = None
        while scanned < max_api_records:
            params: dict[str, Any] = {
                "place_id": region.place_id,
                "taxon_id": taxon_id,
                "quality_grade": "research",
                "rank": "species",
                "d2": cutoff_date,
                "locale": "en",
                "page": page,
                "per_page": min(per_page, max_api_records - scanned),
            }
            response = client.get(API_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            if region_total is None:
                region_total = int(payload.get("total_results") or 0)
                reported_rows_by_region[region.region_code] = region_total
            results = payload.get("results") or []
            if not results:
                break
            for item in results:
                scanned += 1
                region_scanned += 1
                taxon = item.get("taxon") or {}
                count = int(item.get("count") or 0)
                if taxon.get("rank") == "species" and taxon.get("name") and count > 0:
                    counts[(str(taxon["name"]), region.region_code)] += count
                    counted += count
                if scanned >= max_api_records:
                    break
            if region_total is not None and region_scanned >= region_total:
                break
            if len(results) < int(params["per_page"]):
                break
            page += 1
            if request_delay_seconds:
                time.sleep(request_delay_seconds)
        if region_total is None or region_scanned < region_total:
            truncated_regions.append(region.region_code)
            break

    return counts, {
        "name": "iNaturalist observations",
        "api_url": API_URL,
        "taxon_id": taxon_id,
        "quality_grade": "research",
        "rank": "species",
        "cutoff_date": cutoff_date,
        "locale": "en",
        "regions": [
            {
                "region_code": region.region_code,
                "province": region.province,
                "place_id": region.place_id,
                "name": region.expected_name,
            }
            for region in regions
        ],
        "reported_species_rows_by_region": reported_rows_by_region,
        "species_count_rows_scanned": scanned,
        "observations_counted": counted,
        "truncated_regions": truncated_regions,
        "truncated": bool(truncated_regions),
    }


def fetch_observation_province_assignments(
    client: httpx.Client,
    samples: Sequence[Mapping[str, Any]],
    regions: Sequence[ProvinceRegion],
    *,
    batch_size: int = 100,
    request_delay_seconds: float = 0.1,
) -> tuple[dict[str, str], dict[str, Any]]:
    if not 1 <= batch_size <= 200 or request_delay_seconds < 0:
        raise ValueError("Observation batch size or request delay is invalid")
    place_to_code = {
        int(region.place_id): region.region_code
        for region in regions
        if region.place_id is not None
    }
    if len(place_to_code) != len(regions):
        raise ValueError("All province regions must have unique resolved place IDs")
    observation_to_sample: dict[int, str] = {}
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "").strip()
        try:
            observation_id = int(sample["observation_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DatasetFormatError("Manifest sample observation_id is invalid") from exc
        if not sample_id or observation_id in observation_to_sample:
            raise DatasetFormatError("Manifest samples must have unique observation IDs and sample IDs")
        observation_to_sample[observation_id] = sample_id

    assignments: dict[str, str] = {}
    found_observations: set[int] = set()
    observation_ids = list(observation_to_sample)
    for offset in range(0, len(observation_ids), batch_size):
        batch = observation_ids[offset : offset + batch_size]
        response = client.get(
            OBSERVATIONS_URL,
            params={"id": ",".join(map(str, batch)), "per_page": len(batch)},
        )
        response.raise_for_status()
        for observation in response.json().get("results") or []:
            observation_id = int(observation["id"])
            if observation_id not in observation_to_sample:
                continue
            found_observations.add(observation_id)
            matches = {
                place_to_code[place_id]
                for place_id in observation.get("place_ids") or []
                if place_id in place_to_code
            }
            if len(matches) > 1:
                raise DatasetFormatError(
                    f"Observation {observation_id} belongs to multiple configured provinces"
                )
            if matches:
                assignments[observation_to_sample[observation_id]] = matches.pop()
        if request_delay_seconds and offset + batch_size < len(observation_ids):
            time.sleep(request_delay_seconds)

    return assignments, {
        "requested_observations": len(observation_ids),
        "found_observations": len(found_observations),
        "assigned_observations": len(assignments),
        "unassigned_observations": len(observation_ids) - len(assignments),
    }


def build_national_month_prior(
    counts: Counter[tuple[str, int]],
    candidate_labels: Iterable[str],
    source: dict[str, Any],
    *,
    smoothing_alpha: float = 1.0,
    region_code: str = "CN",
) -> dict[str, Any]:
    labels = tuple(str(label).strip() for label in candidate_labels)
    if not labels or any(not label for label in labels) or len(labels) != len(set(labels)):
        raise PriorFormatError("Prior candidate labels must be non-empty and unique")
    if smoothing_alpha <= 0 or not region_code:
        raise ValueError("Prior smoothing and region code are invalid")

    label_set = set(labels)
    monthly_totals = {
        month: sum(count for (label, item_month), count in counts.items() if item_month == month and label in label_set)
        for month in range(1, 13)
    }
    annual_counts = {
        label: sum(counts.get((label, month), 0) for month in range(1, 13))
        for label in labels
    }
    annual_total = sum(annual_counts.values())
    candidate_count = len(labels)
    records: list[dict[str, Any]] = []

    for label in labels:
        records.append(
            {
                "scientific_name": label,
                "region_level": "national",
                "region_code": region_code,
                "month": None,
                "probability": (annual_counts[label] + smoothing_alpha)
                / (annual_total + smoothing_alpha * candidate_count),
            }
        )
        for month in range(1, 13):
            records.append(
                {
                    "scientific_name": label,
                    "region_level": "national",
                    "region_code": region_code,
                    "month": month,
                    "probability": (counts.get((label, month), 0) + smoothing_alpha)
                    / (monthly_totals[month] + smoothing_alpha * candidate_count),
                }
            )

    matched_observations = sum(annual_counts.values())
    return {
        "schema_version": PRIOR_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            **source,
            "aggregation": "national_month_species_frequency",
            "region_code": region_code,
            "smoothing_alpha": smoothing_alpha,
            "candidate_species": candidate_count,
            "matched_candidate_observations": matched_observations,
            "excluded_taxonomy_observations": max(
                0, int(source.get("observations_counted") or 0) - matched_observations
            ),
        },
        "records": records,
    }


def build_province_annual_prior(
    counts: Counter[tuple[str, str]],
    candidate_labels: Iterable[str],
    regions: Sequence[ProvinceRegion],
    source: dict[str, Any],
    *,
    smoothing_alpha: float = 1.0,
    national_region_code: str = "CN",
) -> dict[str, Any]:
    labels = tuple(str(label).strip() for label in candidate_labels)
    region_codes = tuple(region.region_code for region in regions)
    if not labels or any(not label for label in labels) or len(labels) != len(set(labels)):
        raise PriorFormatError("Prior candidate labels must be non-empty and unique")
    if not region_codes or len(region_codes) != len(set(region_codes)):
        raise PriorFormatError("Prior province regions must be non-empty and unique")
    if smoothing_alpha <= 0 or not national_region_code:
        raise ValueError("Prior smoothing and national region code are invalid")

    label_set = set(labels)
    region_totals = {
        code: sum(
            count
            for (label, item_code), count in counts.items()
            if item_code == code and label in label_set
        )
        for code in region_codes
    }
    national_counts = {
        label: sum(counts.get((label, code), 0) for code in region_codes)
        for label in labels
    }
    national_total = sum(national_counts.values())
    candidate_count = len(labels)
    records: list[dict[str, Any]] = []
    for label in labels:
        records.append(
            {
                "scientific_name": label,
                "region_level": "national",
                "region_code": national_region_code,
                "month": None,
                "probability": (national_counts[label] + smoothing_alpha)
                / (national_total + smoothing_alpha * candidate_count),
            }
        )
        for code in region_codes:
            records.append(
                {
                    "scientific_name": label,
                    "region_level": "province",
                    "region_code": code,
                    "month": None,
                    "probability": (counts.get((label, code), 0) + smoothing_alpha)
                    / (region_totals[code] + smoothing_alpha * candidate_count),
                }
            )

    matched_observations = sum(national_counts.values())
    return {
        "schema_version": PRIOR_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            **source,
            "aggregation": "province_annual_species_frequency",
            "national_region_code": national_region_code,
            "smoothing_alpha": smoothing_alpha,
            "candidate_species": candidate_count,
            "matched_candidate_observations": matched_observations,
            "excluded_taxonomy_observations": max(
                0, int(source.get("observations_counted") or 0) - matched_observations
            ),
        },
        "records": records,
    }


def write_province_assignments(
    assignments: Mapping[str, str],
    source: Mapping[str, Any],
    manifest_sha256: str,
    path: str | Path,
) -> None:
    if len(manifest_sha256) != 64:
        raise ValueError("manifest_sha256 must contain 64 hexadecimal characters")
    payload = {
        "schema_version": PROVINCE_ASSIGNMENT_SCHEMA_VERSION,
        "manifest_sha256": manifest_sha256,
        "source": dict(source),
        "assignments": dict(sorted(assignments.items())),
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)


def write_prior_file(payload: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
