"""Reproducible AviList species catalogue with explicitly sourced display names."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

VERSION = "AviList-v2026"
SOURCE_URL = "https://www.avilist.org/wp-content/uploads/2026/10/AviList-v2026-20Oct2026-extended-version.xlsx"
# Locally pinned digest of the workbook downloaded from the official release link;
# this is not an upstream signature or independently published checksum.
SOURCE_SHA256 = "df031d392b766673ce8a9eb37b8e57a91baabf9576b6b2bcfd6cf9aa4902797d"
SPECIES_COUNT = 11172
LEGACY_VERSION = "AviList-v2025b"
LEGACY_CATALOGUE_SHA256 = "291535dc1a196ba281340c917c64f4470c8a5c92dcbb7d87b5fe3bc9753d0984"
CATALOGUE_SHA256 = "ea52f38f02ab30f26db7c810d1a834f2c1fa2985b53ca11b372d95dcb7f88ab9"
FIELDS = (
    "scientific_name", "chinese_name", "family_cn", "order_cn", "genus_cn",
    "genus_sci", "family_sci", "order_sci", "english_name", "taxon_id",
    "chinese_name_source",
)
DEFAULT_CATALOGUE = Path(__file__).resolve().parents[2] / "data/references/avilist-v2026.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_species(workbook: Path) -> list[dict]:
    """Read species only; reject malformed or duplicate identifiers before import."""
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        rows = book.worksheets[0].iter_rows(values_only=True)
        aliases = {'RANK': 'Taxon_rank', 'SCIENTIFIC NAME': 'Scientific_name',
                   'ORDER': 'Order', 'FAMILY': 'Family',
                   'ENGLISH NAME: AVILIST': 'English_name_AviList', 'AVIBASE ID': 'AvibaseID'}
        headers = tuple(aliases.get(value, value) for value in next(rows))
        required = {"Taxon_rank", "Scientific_name", "Order", "Family", "English_name_AviList", "AvibaseID"}
        if not required.issubset(headers):
            raise ValueError("Not an AviList workbook: required columns missing")
        result = []
        for cells in rows:
            row = dict(zip(headers, cells))
            if row["Taxon_rank"] != "species":
                continue
            name = str(row["Scientific_name"] or "").strip()
            result.append({
                "scientific_name": name,
                "chinese_name": name,
                "family_cn": row["Family"], "family_sci": row["Family"],
                "order_cn": row["Order"], "order_sci": row["Order"],
                "genus_cn": name.split()[0] if name else "",
                "genus_sci": name.split()[0] if name else "",
                "english_name": row["English_name_AviList"],
                "taxon_id": row["AvibaseID"],
                "chinese_name_source": "scientific-name fallback",
            })
        validate_species(result)
        return result
    finally:
        book.close()


def validate_species(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Empty species catalogue")
    for field in ("scientific_name", "taxon_id"):
        values = [row.get(field) for row in rows]
        if any(not value for value in values) or len(set(values)) != len(values):
            raise ValueError(f"Missing or duplicate {field}")
    for row in rows:
        if len(row["scientific_name"].split()) != 2 or not row.get("family_sci") or not row.get("order_sci"):
            raise ValueError(f"Invalid species row: {row['scientific_name']}")


def build_catalogue(workbook: Path, ioc_names: Path, references: Path, output: Path) -> dict:
    if sha256(workbook) != SOURCE_SHA256:
        raise ValueError("Official AviList workbook checksum does not match the pinned release")
    rows = read_species(workbook)
    if len(rows) != SPECIES_COUNT:
        raise ValueError("Unexpected species count")
    names = {}
    book = load_workbook(ioc_names, read_only=True, data_only=True)
    try:
        values = book.worksheets[0].iter_rows(values_only=True)
        headers = next(values)
        if not {"IOC_15.1", "Chinese"}.issubset(headers):
            raise ValueError("Expected IOC 15.1 multilingual name source")
        for cells in values:
            row = dict(zip(headers, cells))
            if row.get("IOC_15.1") and row.get("Chinese"):
                names[row["IOC_15.1"]] = row["Chinese"]
    finally:
        book.close()
    sources = {ioc_names.name: sha256(ioc_names)}
    maps = {}
    for rank in ("order", "family", "genus"):
        source = references / f"bird_{rank}_mapping_complete.csv"
        with source.open(encoding="utf-8-sig", newline="") as stream:
            maps[rank] = {row[f"{rank.title()}_SCI"].casefold(): row[f"{rank.title()}_CN"] for row in csv.DictReader(stream)}
        sources[source.name] = sha256(source)
    for row in rows:
        name = row["scientific_name"]
        if name in names:
            row["chinese_name"] = names[name]
            # This is a display alias, NOT evidence of taxonomic equivalence.
            row["chinese_name_source"] = "IOC-15.1 Chinese; exact-name alias; concept unverified"
        for rank in maps:
            row[f"{rank}_cn"] = maps[rank].get(row[f"{rank}_sci"].casefold()) or row[f"{rank}_sci"]
    # Renamed genera can retain an explicitly sourced display alias when the
    # stable taxonomic concept matches. Never use this to relabel old photos.
    old_path = references / 'avilist-v2025b.csv'
    old_rows, _ = load_catalogue(old_path)
    sources[old_path.name] = sha256(old_path)
    old_by_id = {row['taxon_id']: row for row in old_rows}
    for row in rows:
        old = old_by_id.get(row['taxon_id'])
        if (row['chinese_name_source'] == 'scientific-name fallback' and old
                and old['chinese_name'] != old['scientific_name']):
            row['chinese_name'] = old['chinese_name']
            row['chinese_name_source'] = 'AviList-v2025b display alias; matching AvibaseID; not official Chinese name'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "version": VERSION, "species_count": len(rows), "source_url": SOURCE_URL,
        "source_sha256": SOURCE_SHA256, "catalogue_sha256": sha256(output),
        "citation": "AviList Core Team. 2026. AviList: The Global Avian Checklist, v2026. https://doi.org/10.2173/avilist.v2026",
        "source_checksum_origin": "locally pinned official HTTPS download; no independently published upstream checksum",
        "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "name_sources_sha256": sources,
        "name_status_counts": dict(Counter(row["chinese_name_source"] for row in rows)),
        "transform": "species rows only; official order; IOC same-name aliases and v2025b matching-AvibaseID display aliases; existing Chinese rank CSVs; no photo-label equivalence inferred",
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_catalogue(path: Path = DEFAULT_CATALOGUE) -> tuple[list[dict], dict]:
    manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    counts = {VERSION: SPECIES_COUNT, LEGACY_VERSION: 11131}
    if manifest["version"] not in counts or manifest["catalogue_sha256"] != sha256(path):
        raise ValueError("Catalogue version or checksum mismatch")
    if (manifest['version'] == LEGACY_VERSION
            and manifest['catalogue_sha256'] != LEGACY_CATALOGUE_SHA256):
        raise ValueError('Legacy catalogue does not match the pinned release')
    if manifest['version'] == VERSION and manifest['catalogue_sha256'] != CATALOGUE_SHA256:
        raise ValueError('Catalogue does not match the pinned release checksum')
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("Catalogue columns mismatch")
        rows = list(reader)
    validate_species(rows)
    if len(rows) != manifest["species_count"] or len(rows) != counts[manifest['version']]:
        raise ValueError("Catalogue species count mismatch")
    return rows, manifest
