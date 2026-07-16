import os
import sys
import filecmp
from pathlib import Path

ADDON1 = "tqqq_bot"
ADDON2 = "tqqq_bot_account_2"
IGNORED_FILES = {"config.yaml", "README.md"}
IGNORED_DIRS = {"__pycache__", ".pytest_cache"}
IGNORED_EXTS = {".pyc"}

def get_all_files(directory):
    files = []
    for root, d_names, f_names in os.walk(directory):
        d_names[:] = [d for d in d_names if d not in IGNORED_DIRS]
        for f in f_names:
            if f in IGNORED_FILES or any(f.endswith(ext) for ext in IGNORED_EXTS):
                continue
            files.append(os.path.relpath(os.path.join(root, f), directory))
    return set(files)

def normalize_run_sh(content: str) -> str:
    content = content.replace("V7_tqqq_bot_account_2", "V7_tqqq_bot")
    content = content.replace("(Account 2) ", "")
    content = content.replace("bundled tqqq_bot_account_2", "bundled tqqq_bot")
    return content

def check_parity():
    files1 = get_all_files(ADDON1)
    files2 = get_all_files(ADDON2)

    missing_in_2 = files1 - files2
    extra_in_2 = files2 - files1

    errors = []
    if missing_in_2:
        errors.append(f"Missing in {ADDON2}: {', '.join(missing_in_2)}")
    if extra_in_2:
        errors.append(f"Extra in {ADDON2}: {', '.join(extra_in_2)}")

    common_files = files1.intersection(files2)
    for f in common_files:
        path1 = os.path.join(ADDON1, f)
        path2 = os.path.join(ADDON2, f)

        # Check executable mode parity
        mode1 = os.stat(path1).st_mode
        mode2 = os.stat(path2).st_mode
        if mode1 != mode2:
            errors.append(f"Executable mode mismatch for {f}")

        if f == "run.sh":
            with open(path1, "r") as f1, open(path2, "r") as f2:
                content1 = f1.read()
                content2 = normalize_run_sh(f2.read())
                if content1 != content2:
                    errors.append(f"Content mismatch for {f} after normalization")
        else:
            if not filecmp.cmp(path1, path2, shallow=False):
                errors.append(f"Content mismatch for {f}")

    if errors:
        print("Parity Check Failed:")
        for error in errors:
            print(f" - {error}")
        sys.exit(1)
    else:
        print("Parity Check Passed!")

if __name__ == "__main__":
    check_parity()
