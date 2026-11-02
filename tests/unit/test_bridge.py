import pytest
from quimia_ingestion.core.exceptions import ConfigurationError
from quimia_ingestion.integrations.bridgesds import BridgeSDSProvider


def test_bridge_is_explicitly_blocked_without_contract():
    with pytest.raises(ConfigurationError):
        list(BridgeSDSProvider("", "").documents())
