import json
import sys
from pydantic import ValidationError
from config.schema import AppConfig
from config.migrate_options import SECTIONS


def validate_ibkr_settings(config: AppConfig) -> list[str]:
    """
    Validates that paper_trading and trading_mode agree. Returns a list of
    warning messages. The API port is not checked against the mode: the bot
    and its own Gateway always use the same configured port.
    """
    warnings = []
    if config.active_broker == "ibkr":
        if config.trading_mode == "paper" and config.paper_trading is False:
            warnings.append(
                "LOUD WARNING: trading_mode='paper' but paper_trading=False. "
                "Gateway is configured for paper while bot runtime is configured as live."
            )

        if config.trading_mode == "live" and config.paper_trading is True:
            warnings.append(
                "LOUD WARNING: trading_mode='live' but paper_trading=True. "
                "Gateway is configured for live while bot runtime is configured as paper."
            )

    return warnings


import logging
from utils.log_sanitizer import mask_account_ids_in_text

logger = logging.getLogger(__name__)

def flatten_options(data: dict) -> dict:
    """
    The Configuration page groups options into sections; the bot reads them
    under their own names. trading_mode also sets paper_trading, so the two
    cannot disagree. A flat dictionary is returned unchanged.
    """
    if not isinstance(data, dict) or not any(isinstance(data.get(s), dict) for s in SECTIONS):
        return data
    flat = {k: v for k, v in data.items() if k not in SECTIONS}
    for section in SECTIONS:
        values = data.get(section)
        if isinstance(values, dict):
            flat.update(values)
    if "trading_mode" in flat:
        flat["paper_trading"] = flat["trading_mode"] == "paper"
    return flat


def load_config(path: str = "/data/options.json") -> AppConfig:
    data = {}
    try:
        with open(path, "r") as f:
            data = flatten_options(json.load(f))

        return AppConfig(**data)
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        known_acct = data.get("ibkr_account_id") if isinstance(data, dict) else None
        known_list = [known_acct] if known_acct else []
        safe_msg = mask_account_ids_in_text(f"Error: Invalid JSON format in {path}: {e}", known_list, enabled=True)
        print(safe_msg, file=sys.stderr)
        sys.exit(1)
    except ValidationError as e:
        known_acct = data.get("ibkr_account_id") if isinstance(data, dict) else None
        known_list = [known_acct] if known_acct else []
        print("Error: Missing or invalid required configuration fields:", file=sys.stderr)
        safe_e = mask_account_ids_in_text(str(e), known_list, enabled=True)
        print(safe_e, file=sys.stderr)
        sys.exit(1)
