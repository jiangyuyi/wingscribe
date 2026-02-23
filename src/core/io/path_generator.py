import re
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

class PathGenerator:
    def __init__(self, template: str, output_root: str):
        self.template = template
        self.output_root = Path(output_root)

    def _sanitize(self, value: str) -> str:
        """Remove illegal characters for filesystem paths."""
        # Windows/Linux forbidden chars
        return re.sub(r'[<>:"/\\|?*]', '_', str(value)).strip()

    def _normalize_source_structure(self, source_structure: str) -> str:
        """
        Normalize source_structure to avoid path duplication with output_root.
        Example: if output_root = "Y:/1按年份/2026/clip" and source_structure = "clip/20260110北京",
        the "clip" prefix should be removed to avoid "clip/clip/..." duplication.
        """
        if not source_structure or source_structure == '.':
            return '.'

        # Get the last folder name of output_root
        output_parts = self.output_root.parts
        if len(output_parts) > 1:
            output_last_folder = output_parts[-1]  # e.g., "clip"
        else:
            return source_structure

        # Normalize source_structure path separators
        ss_normalized = source_structure.replace('\\', '/')

        # Check if source_structure starts with the same folder name as output_root's last part
        # This handles cases like: output_root="clip", source_structure="clip/20260110" -> "20260110"
        if ss_normalized.startswith(output_last_folder + '/'):
            # Remove the duplicate prefix
            normalized = ss_normalized[len(output_last_folder) + 1:]
            # Handle case where source_structure exactly matches output_last_folder
            if not normalized:
                normalized = '.'
            return normalized
        elif ss_normalized == output_last_folder:
            return '.'

        return source_structure

    def generate_path(self, metadata: Dict[str, Any], original_filename: str) -> Path:
        """
        Generate the absolute output path based on metadata and template.
        metadata keys expected:
        - captured_date (YYYYMMDD or YYYY-MM-DD)
        - location_tag
        - primary_bird_cn
        - scientific_name
        - confidence_score (float)
        """
        # 1. Parse Date
        date_str = metadata.get('captured_date', '00000000')
        try:
            # Try parsing typical formats
            if '-' in date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            else:
                dt = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            dt = datetime.now()

        # 2. Prepare Variables
        # Normalize source_structure to avoid duplication with output_root
        raw_source_structure = metadata.get('source_structure', '.')
        normalized_source_structure = self._normalize_source_structure(raw_source_structure)

        vars = {
            'date': self._sanitize(date_str),
            'year': f"{dt.year:04d}",
            'month': f"{dt.month:02d}",
            'day': f"{dt.day:02d}",
            'location': self._sanitize(metadata.get('location_tag', 'Unknown')),
            'species_cn': self._sanitize(metadata.get('primary_bird_cn', 'Unknown')),
            'species_sci': self._sanitize(metadata.get('scientific_name', 'Unknown')),
            'confidence': f"{int(metadata.get('confidence_score', 0) * 100)}pct",
            'source_structure': normalized_source_structure,
            'filename': Path(original_filename).stem,
            'ext': Path(original_filename).suffix.lstrip('.')
        }

        # 3. Apply Template
        # We handle '/' separately to allow subdirectories
        # Python's format string might complain about missing keys if user makes a typo, so strictly check
        try:
            # If template contains {source_structure}, we should process it carefully to ensure separators work
            # But standard format should handle it if 'source_structure' is "folder/subfolder"

            # Custom split logic might break if a variable contains '/', but standard python format won't.
            # So we format the WHOLE string first, then resolve path.
            # BUT, we need to sanitize parts individually usually.
            # Exception: source_structure MUST contain slashes.

            # Revised Strategy: Use string.format on the whole template first, then sanitize?
            # No, that's dangerous. Sanitize variables first (done above), except source_structure.

            formatted_str = self.template.format(**vars)

            # Now split and sanitize only if needed?
            # Actually, we sanitized individual vars (except source_structure).
            # So formatted_str might look like "2023/Beijing/Sparrow.jpg" or "MySource/Folder/Image.jpg"

            # We trust that the template structure + sanitized vars = valid path.
            final_path = self.output_root / formatted_str
            return final_path.with_suffix(".jpg") # Force jpg as output is always cropped jpg

        except KeyError as e:
            # Fallback for bad template
            safe_name = f"{vars['date']}_{vars['species_cn']}_{vars['filename']}.jpg"
            return self.output_root / safe_name
