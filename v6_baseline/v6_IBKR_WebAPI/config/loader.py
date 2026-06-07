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


def load_config(path: str = "/data/options.json") -> AppConfig:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return AppConfig(**data)
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {path}", file=sys.stderr)
        sys.exit(1)
    except ValidationError as e:
        print("Error: Missing or invalid required configuration fields:", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)
