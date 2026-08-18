from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PRIOR_SCHEMA_VERSION = 1
REGION_FALLBACK = ("site", "city", "province", "national")


class PriorFormatError(ValueError):
    """Raised when a species-prior file cannot be applied safely."""


@dataclass(frozen=True)
class PriorRecord:
    scientific_name: str
    region_level: str
    region_code: str
    month: int | None
    probability: float


@dataclass(frozen=True)
class PriorMatch:
    probability: float
    region_level: str
    region_code: str
    month: int | None


@dataclass(frozen=True)
class PriorApplication:
    adjustments: tuple[float, ...]
    matches: tuple[PriorMatch | None, ...]
    applied: bool


class SpeciesPriorProvider:
    def __init__(
        self,
        records: Sequence[PriorRecord],
        *,
        source: Mapping[str, Any] | None = None,
        minimum_probability: float = 1e-8,
    ):
        if not 0 < minimum_probability <= 1:
            raise ValueError("minimum_probability must be in (0, 1]")
        self.source = dict(source or {})
        self.minimum_probability = minimum_probability
        self._records: dict[tuple[str, str, str, int | None], PriorRecord] = {}
        for record in records:
            self._validate_record(record)
            key = (
                record.scientific_name,
                record.region_level,
                record.region_code,
                record.month,
            )
            if key in self._records:
                raise PriorFormatError(f"Duplicate species-prior record: {key}")
            self._records[key] = record

    @staticmethod
    def _validate_record(record: PriorRecord) -> None:
        if not record.scientific_name or not record.region_code:
            raise PriorFormatError("Prior species and region code must be non-empty")
        if record.region_level not in REGION_FALLBACK:
            raise PriorFormatError(f"Unsupported prior region level: {record.region_level}")
        if record.month is not None and not 1 <= record.month <= 12:
            raise PriorFormatError("Prior month must be between 1 and 12")
        if not 0 < record.probability <= 1 or not math.isfinite(record.probability):
            raise PriorFormatError("Prior probability must be finite and in (0, 1]")

    def _match(
        self,
        scientific_name: str,
        region_context: Mapping[str, str],
        month: int | None,
    ) -> PriorMatch | None:
        for region_level in REGION_FALLBACK:
            region_code = str(region_context.get(region_level) or "").strip()
            if not region_code:
                continue
            months = (month, None) if month is not None else (None,)
            for candidate_month in months:
                record = self._records.get(
                    (scientific_name, region_level, region_code, candidate_month)
                )
                if record is not None:
                    return PriorMatch(
                        probability=record.probability,
                        region_level=record.region_level,
                        region_code=record.region_code,
                        month=record.month,
                    )
        return None

    def build_application(
        self,
        candidate_labels: Sequence[str],
        *,
        region_context: Mapping[str, str] | None,
        month: int | None,
        weight: float,
        location_confidence: float,
        max_adjustment: float,
    ) -> PriorApplication:
        if month is not None and not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        if weight < 0 or not 0 <= location_confidence <= 1 or max_adjustment < 0:
            raise ValueError("Prior weight, confidence, and adjustment bounds are invalid")

        labels = tuple(str(label) for label in candidate_labels)
        matches = tuple(
            self._match(label, region_context or {}, month)
            for label in labels
        )
        if (
            not labels
            or not any(matches)
            or weight == 0
            or location_confidence == 0
            or max_adjustment == 0
        ):
            return PriorApplication((0.0,) * len(labels), matches, False)

        log_probabilities = [
            math.log(match.probability if match else self.minimum_probability)
            for match in matches
        ]
        strongest = max(log_probabilities)
        scale = weight * location_confidence
        adjustments = tuple(
            max(-max_adjustment, (value - strongest) * scale)
            for value in log_probabilities
        )
        return PriorApplication(adjustments, matches, True)


def load_prior_provider(path: str | Path) -> SpeciesPriorProvider:
    prior_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(prior_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PriorFormatError(f"Unable to read species-prior file: {prior_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PRIOR_SCHEMA_VERSION:
        raise PriorFormatError("Unsupported species-prior schema version")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise PriorFormatError("Species-prior file contains no records")

    try:
        records = [
            PriorRecord(
                scientific_name=str(item["scientific_name"]).strip(),
                region_level=str(item["region_level"]).strip(),
                region_code=str(item["region_code"]).strip(),
                month=int(item["month"]) if item.get("month") is not None else None,
                probability=float(item["probability"]),
            )
            for item in raw_records
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise PriorFormatError("Species-prior file contains an invalid record") from exc
    return SpeciesPriorProvider(records, source=payload.get("source") or {})


def rerank_visual_logits(
    visual_logits: Sequence[float],
    candidate_labels: Sequence[str],
    application: PriorApplication,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if len(visual_logits) != len(candidate_labels) or len(visual_logits) != len(application.adjustments):
        raise ValueError("Visual logits, labels, and prior adjustments must have equal lengths")
    if not visual_logits:
        return []
    if any(not math.isfinite(float(value)) for value in visual_logits):
        raise ValueError("Visual logits must be finite")

    final_logits = [
        float(visual_logit) + prior_adjustment
        for visual_logit, prior_adjustment in zip(visual_logits, application.adjustments)
    ]
    maximum = max(final_logits)
    exponentials = [math.exp(value - maximum) for value in final_logits]
    denominator = sum(exponentials)
    ranked_indices = sorted(
        range(len(candidate_labels)),
        key=lambda index: (-final_logits[index], index),
    )[:top_k]

    results: list[dict[str, Any]] = []
    for index in ranked_indices:
        match = application.matches[index]
        results.append(
            {
                "scientific_name": str(candidate_labels[index]),
                "confidence": exponentials[index] / denominator,
                "visual_logit": float(visual_logits[index]),
                "prior_adjustment": application.adjustments[index],
                "final_logit": final_logits[index],
                "prior_source": (
                    {
                        "region_level": match.region_level,
                        "region_code": match.region_code,
                        "month": match.month,
                        "probability": match.probability,
                    }
                    if match
                    else None
                ),
            }
        )
    return results
