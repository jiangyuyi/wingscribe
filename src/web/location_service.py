from pathlib import Path

from src.metadata.location_resolver import LocationResolver


def preview_locations(base_dir: Path, locations: list[str]) -> dict:
    dictionary_dir = base_dir / "config" / "dictionaries"
    admin_path = dictionary_dir / "china_admin_divisions.csv"
    aliases_path = dictionary_dir / "location_aliases.yaml"
    resolver = LocationResolver(admin_path=admin_path, aliases_path=aliases_path)

    return {
        "dictionary": {
            "version": resolver.dictionary_version,
            "admin_available": admin_path.is_file(),
            "aliases_available": aliases_path.is_file(),
            "admin_record_count": resolver.admin_record_count,
            "alias_rule_count": resolver.alias_rule_count,
        },
        "results": [resolver.resolve(location).to_dict() for location in locations],
    }
