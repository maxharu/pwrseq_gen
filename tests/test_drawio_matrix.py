"""Legacy layered draw.io matrix tests (superseded by test_drawio_cell.py)."""
import pytest

pytestmark = pytest.mark.skip(
    reason="layered draw.io layout removed; see tests/test_drawio_cell.py"
)
