import yaml
import sys
import os

def load_yaml(filepath):
    with open(filepath, "r") as f:
        return yaml.safe_load(f)

def check_prohibited_files(directory):
    errors = []
    prohibited_exts = {".env", ".pem", ".key", ".json"}
    allowed_json = {}  # Could allow specific JSONs if necessary
    for root, _, files in os.walk(directory):
        for f in files:
            path = os.path.join(root, f)
            if any(f.endswith(ext) for ext in prohibited_exts):
                errors.append(f"Prohibited file type found: {path}")
    return errors

def validate():
    try:
        conf1 = load_yaml("tqqq_bot/config.yaml")
        conf2 = load_yaml("tqqq_bot_account_2/config.yaml")
    except Exception as e:
        print(f"Failed to load config files: {e}")
        sys.exit(1)

    errors = []

    if conf1.get("name") == conf2.get("name"):
        errors.append("Add-on names must be unique")
    if conf1.get("slug") == conf2.get("slug"):
        errors.append("Add-on slugs must be unique")

    if conf2.get("slug") != "tqqq_bot_account_2":
        errors.append("Account 2 slug must be exactly 'tqqq_bot_account_2'")
    if conf2.get("name") != "V7_tqqq_bot_account_2":
        errors.append("Account 2 name must be exactly 'V7_tqqq_bot_account_2'")

    if conf2.get("boot") != "manual":
        errors.append("Account 2 'boot' must be 'manual'")

    # Both add-ons start a fresh install unable to trade, with placeholder values only.
    safe_defaults = {
        ("account", "trading_mode"): "paper",
        ("account", "dry_run"): True,
        ("account", "readonly_api"): True,
        ("account", "ibkr_account_id"): "DU1234567",
        ("account", "ibkr_username"): "placeholder_user",
        ("account", "ibkr_password"): "placeholder_password",
        ("google_sheet", "google_sheet_id"): "your_google_sheet_id_here",
        ("google_sheet", "google_credentials_json"): "",
        ("advanced", "ibkr_port"): 7497,
        ("advanced", "ibkr_client_id"): 1,
        ("advanced", "enable_vnc"): False,
        ("advanced", "mask_account_ids_in_logs"): True,
        ("notifications", "webhook_url"): "",
    }
    for label, conf in (("Account 1", conf1), ("Account 2", conf2)):
        opts = conf.get("options", {})
        for (section, key), expected in safe_defaults.items():
            actual = (opts.get(section) or {}).get(key)
            if actual != expected:
                errors.append(f"{label} default '{section}.{key}' must be {expected!r}")

    # The two add-ons expose the same page with the same defaults.
    if conf1.get("schema") != conf2.get("schema"):
        errors.append("Both add-ons must have identical schemas")
    if conf1.get("options") != conf2.get("options"):
        errors.append("Both add-ons must have identical default options")
    if conf1.get("version") != conf2.get("version"):
        errors.append("Both add-ons must have the same version")

    prohibited_errors = check_prohibited_files("tqqq_bot_account_2")
    errors.extend(prohibited_errors)

    if errors:
        print("Configuration and Placeholder Validation Failed:")
        for e in errors:
            print(f" - {e}")
        sys.exit(1)
    else:
        print("Configuration and Placeholder Validation Passed!")

if __name__ == "__main__":
    validate()
