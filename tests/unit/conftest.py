"""Unit test configuration.

Stubs optional heavy dependencies so unit tests run without requiring production
packages to be installed. conftest.py is loaded by pytest before any test module
is imported, so sys.modules patches applied here take effect at collection time.
"""
import sys
from unittest.mock import MagicMock

# Stub snowflake-connector-python (optional dep, not installed in bare dev env).
# SnowflakeConnector unit tests inject mock connections directly via _pool,
# so no real Snowflake driver behaviour is needed here.
if "snowflake" not in sys.modules:
    _sf_mock = MagicMock()
    _sf_mock.DictCursor = MagicMock()
    sys.modules["snowflake"] = MagicMock()
    sys.modules["snowflake.connector"] = _sf_mock
