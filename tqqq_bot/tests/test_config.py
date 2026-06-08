import pytest
import json
import os
from pydantic import ValidationError
from config.loader import load_config, validate_ibkr_settings
from config.schema import AppConfig


def test_default_values(tmp_path):
    config_file = tmp_path / "options.json"
    config_data = {
        "google_sheet_id": "test_sheet_id",
        "google_credentials_json": "{}"
    }
    with open(config_file, "w") as f:
        json.dump(config_data, f)

    config = load_config(str(config_file))

    assert config.active_broker == "ibkr"
    assert config.paper_trading is True
    assert config.ibkr_host == "127.0.0.1"
    assert config.ibkr_port == 7497
    assert config.ibkr_client_id == 1
    assert config.poll_interval_seconds == 60
    assert config.max_spread_pct == 0.5
    assert config.google_sheet_id == "test_sheet_id"
    assert config.google_credentials_json == "{}"


def test_missing_google_sheet_id(tmp_path):
    config_file = tmp_path / "options.json"
    config_data = {
        "google_credentials_json": "{}"
    }
    with open(config_file, "w") as f:
        json.dump(config_data, f)

    with pytest.raises(SystemExit) as e:
        load_config(str(config_file))

    assert e.type == SystemExit
    assert e.value.code == 1


def test_validate_ibkr_settings_paper_correct():
    config = AppConfig(
        google_sheet_id="id",
        google_credentials_json="{}",
        paper_trading=True,
        ibkr_port=7497
    )
    warnings = validate_ibkr_settings(config)
    assert len(warnings) == 0


def test_validate_ibkr_settings_live_correct():
    config = AppConfig(
        google_sheet_id="id",
        google_credentials_json="{}",
        paper_trading=False,
        ibkr_port=7496
    )
    warnings = validate_ibkr_settings(config)
    assert len(warnings) == 0


def test_validate_ibkr_settings_paper_inconsistent():
    config = AppConfig(
        google_sheet_id="id",
        google_credentials_json="{}",
        paper_trading=True,
        ibkr_port=7496
    )
    warnings = validate_ibkr_settings(config)
    assert len(warnings) == 1
    assert "paper_trading=True but ibkr_port=7496" in warnings[0]


def test_validate_ibkr_settings_live_inconsistent():
    config = AppConfig(
        google_sheet_id="id",
        google_credentials_json="{}",
        paper_trading=False,
        ibkr_port=7497
    )
    warnings = validate_ibkr_settings(config)
    assert len(warnings) == 1
    assert "paper_trading=False (LIVE) but ibkr_port=7497" in warnings[0]


def test_validate_ibkr_settings_custom_port():
    config = AppConfig(
        google_sheet_id="id",
        google_credentials_json="{}",
        paper_trading=True,
        ibkr_port=4001
    )
    warnings = validate_ibkr_settings(config)
    assert len(warnings) == 1
    assert "paper_trading=True but ibkr_port=4001" in warnings[0]
