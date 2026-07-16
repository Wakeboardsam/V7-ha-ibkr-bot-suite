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

    opts2 = conf2.get("options", {})
    if opts2.get("paper_trading") is not True:
        errors.append("Account 2 'paper_trading' must be true")
    if opts2.get("dry_run") is not True:
        errors.append("Account 2 'dry_run' must be true")
    if opts2.get("trading_mode") != "paper":
        errors.append("Account 2 'trading_mode' must be 'paper'")
    if opts2.get("readonly_api") is not True:
        errors.append("Account 2 'readonly_api' must be true")
    if opts2.get("enable_vnc") is not False:
        errors.append("Account 2 'enable_vnc' must be false")
    if opts2.get("mask_account_ids_in_logs") is not True:
        errors.append("Account 2 'mask_account_ids_in_logs' must be true")
    if opts2.get("ibkr_host") != "127.0.0.1":
        errors.append("Account 2 'ibkr_host' must be '127.0.0.1'")
    if opts2.get("ibkr_port") != 7497:
        errors.append("Account 2 'ibkr_port' must be 7497")
    if opts2.get("ibkr_client_id") != 1:
        errors.append("Account 2 'ibkr_client_id' must be 1")
    if opts2.get("ibkr_account_id") != "DU1234567":
        errors.append("Account 2 'ibkr_account_id' must be exactly the placeholder 'DU1234567'")
    if opts2.get("google_sheet_id") != "your_google_sheet_id_here":
        errors.append("Account 2 'google_sheet_id' must be exactly 'your_google_sheet_id_here'")
    if opts2.get("ibkr_username") != "placeholder_user" or opts2.get("ibkr_password") != "placeholder_password":
        errors.append("Account 2 username and password must remain placeholders")

    # Schema keys check
    schema1_keys = set(conf1.get("schema", {}).keys())
    schema2_keys = set(conf2.get("schema", {}).keys())
    if schema1_keys != schema2_keys:
        errors.append("Both add-ons must expose the same schema keys")

    opts1_keys = set(conf1.get("options", {}).keys())
    opts2_keys = set(conf2.get("options", {}).keys())
    if opts1_keys != opts2_keys:
        errors.append("Both add-ons must retain the same option keys")

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
