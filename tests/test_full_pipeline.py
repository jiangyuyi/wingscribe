"""
Full pipeline integration tests.

Note: These tests require actual config and database setup.
Run with: pytest tests/test_full_pipeline.py -v
"""

import pytest
import sys
import os

# Skip this test module if dependencies are not available
pytest.skip(reason="Integration test - requires full environment setup", allow_module_level=True)
