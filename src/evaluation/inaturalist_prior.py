from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from src.recognition.prior import PRIOR_SCHEMA_VERSION, PriorFormatError

from .datasets import DatasetFormatError


API_URL = "https://api.inaturalist.org/v1/observations"


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
) -> tuple[Counter[tuple[str, int]], dict[str, Any]]:
    if max_api_records < 1 or not 1 <= per_page <= 200:
        raise ValueError("API record and page limits are invalid")
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must not be negative")

    counts: Counter[tuple[str, int]] = Counter()
    seen_observations: set[int] = set()
    cursor: int | None = None
    scanned = 0
    counted = 0
    total_results: int | None = None

    while scanned < max_api_records:
        params: dict[str, Any] = {
            "place_id": place_id,
            "taxon_id": taxon_id,
            "quality_grade": "research",
            "rank": "species",
            "d2": cutoff_date,
            "order_by": "id",
            "order": "asc",
            "locale": "en",
            "per_page": min(per_page, max_api_records - scanned),
        }
        if cursor is not None:
            params["id_above"] = cursor

        response = client.get(API_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        if total_results is None:
            total_results = int(payload.get("total_results") or 0)
        observations = payload.get("results") or []
        if not observations:
            break

        page_max_id = cursor or 0
        for observation in observations:
            observation_id = int(observation["id"])
            page_max_id = max(page_max_id, observation_id)
            if observation_id in seen_observations:
                continue
            seen_observations.add(observation_id)
            scanned += 1

            taxon = observation.get("taxon") or {}
            observed_on = str(observation.get("observed_on") or "")
            try:
                month = int(observed_on[5:7])
            except (TypeError, ValueError):
                month = 0
            if taxon.get("rank") == "species" and taxon.get("name") and 1 <= month <= 12:
                counts[(str(taxon["name"]), month)] += 1
                counted += 1
            if scanned >= max_api_records:
                break

        if cursor is not None and page_max_id <= cursor:
            raise RuntimeError("iNaturalist prior pagination cursor did not advance")
        cursor = page_max_id
        if len(observations) < int(params["per_page"]):
            break
        if request_delay_seconds:
            time.sleep(request_delay_seconds)

    return counts, {
        "name": "iNaturalist observations",
        "api_url": API_URL,
        "place_id": place_id,
        "taxon_id": taxon_id,
        "quality_grade": "research",
        "rank": "species",
        "cutoff_date": cutoff_date,
        "locale": "en",
        "reported_total_results": total_results,
        "api_records_scanned": scanned,
        "observations_counted": counted,
        "truncated": bool(total_results is not None and scanned < total_results),
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


def write_prior_file(payload: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
