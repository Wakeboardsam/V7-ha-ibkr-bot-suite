import json
import sys
from pydantic import ValidationError
from config.schema import AppConfig


def validate_ibkr_settings(config: AppConfig) -> list[str]:
    """
    Validates that paper_trading and ibkr_port are consistent with IBKR defaults.
    Returns a list of warning messages.
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

        if config.paper_trading:
            if config.ibkr_port != 7497:
                warnings.append(
                    f"Inconsistency detected: paper_trading=True but ibkr_port={config.ibkr_port}. "
                    "IBKR default paper port is 7497."
                )
        else:
            if config.ibkr_port != 7496:
                warnings.append(
                    f"Inconsistency detected: paper_trading=False (LIVE) but ibkr_port={config.ibkr_port}. "
                    "IBKR default live port is 7496."
                )
    return warnings


import logging
from utils.log_sanitizer import mask_account_ids_in_text

logger = logging.getLogger(__name__)

def load_config(path: str = "/data/options.json") -> AppConfig:
    data = {}
    try:
        with open(path, "r") as f:
            data = json.load(f)

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
