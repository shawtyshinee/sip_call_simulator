import allure
import pytest

from src.sip_simulator.config import SipConfig, SipTransport
from src.sip_simulator.exceptions import SipConfigurationError


@allure.epic("SIP simulator")
@allure.feature("Configuration")
class TestSipConfig:
    @allure.story("Build SIP URIs")
    @allure.title("Destination without a scheme is converted to a SIP URI")
    def test_builds_destination_uri(self) -> None:
        config = SipConfig(host="pbx.example.test", username="1000", password="secret")

        assert config.transport is SipTransport.UDP
        assert config.account_uri == "sip:1000@pbx.example.test"
        assert config.registrar_uri == "sip:pbx.example.test:5060"
        assert config.destination_uri("1001") == "sip:1001@pbx.example.test"
        assert config.destination_uri("sips:1001@secure.example.test") == "sips:1001@secure.example.test"

    @allure.story("Validate SIP destinations")
    @allure.title("An empty destination produces an SDK configuration error")
    def test_rejects_empty_destination(self) -> None:
        config = SipConfig(host="pbx.example.test", username="1000", password="secret")

        with pytest.raises(SipConfigurationError, match="must not be empty"):
            config.destination_uri("  ")
