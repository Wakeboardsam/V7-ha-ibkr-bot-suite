import sys
from unittest.mock import MagicMock, AsyncMock
import pytest

sys.modules['ib_insync'] = MagicMock()

@pytest.fixture
def mock_ib():
    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock()
    ib.connectAsync = AsyncMock()
    ib.reqPositionsAsync = AsyncMock()
    return ib
