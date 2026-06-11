import logging
from app.utils.log_sanitizer import mask_account_id, mask_account_ids_in_text, AccountMaskingFilter

def test_mask_account_id():
    assert mask_account_id("DU1234567") == "DU1****567"
    assert mask_account_id("U123456") == "U12****456"
    assert mask_account_id("D12") == "D****2"
    assert mask_account_id("DU") == "****"
    assert mask_account_id(None) == "None"
    assert mask_account_id("") == ""
    assert mask_account_id(123456789) == "123****789"
    assert mask_account_id("DU1234567", enabled=False) == "DU1234567"

def test_mask_account_ids_in_text():
    assert mask_account_ids_in_text("Account DU1234567 has issues.", ["DU1234567"]) == "Account DU1****567 has issues."
    assert mask_account_ids_in_text("Multiple: DU1234567 and DU9876543.", ["DU1234567", "DU9876543"]) == "Multiple: DU1****567 and DU9****543."
    assert mask_account_ids_in_text("Account DU1234567 has issues.", ["DU1234567"], enabled=False) == "Account DU1234567 has issues."
    assert mask_account_ids_in_text("No known accounts here.", ["DU1234567"]) == "No known accounts here."
    assert mask_account_ids_in_text(None) == "None"
    assert mask_account_ids_in_text("") == ""

    # Regex fallback tests
    assert mask_account_ids_in_text("Unknown U1234567 found.") == "Unknown U12****567 found."
    assert mask_account_ids_in_text("Unknown DU9876543 here.", ["DU1111111"]) == "Unknown DU9****543 here."
    assert mask_account_ids_in_text("Short DU1 is ignored unless known") == "Short DU1 is ignored unless known"
    assert mask_account_ids_in_text("Short DU1 is known", ["DU1"]) == "Short D****1 is known"

def test_account_masking_filter():
    filter = AccountMaskingFilter(["DU1234567"])

    # Test simple message
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Logging DU1234567 in msg", (), None)
    filter.filter(record)
    assert record.msg == "Logging DU1****567 in msg"

    # Test dictionary args (when passing a tuple with one dict, python logging unpacks it into kwargs under the hood sometimes, or keeps it. LogRecord does args[0] extraction for dicts)
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Msg", ({"acct": "DU1234567", "other": 123},), None)
    filter.filter(record)
    assert record.args["acct"] == "DU1****567"
    assert record.args["other"] == 123

    # Test tuple args
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Msg", ("DU1234567", 123), None)
    filter.filter(record)
    assert record.args[0] == "DU1****567"
    assert record.args[1] == 123

    # Test nested dict/tuple args
    nested_args = {
        "user": {"id": "DU1234567", "data": [1, 2, "DU9876543"]},
        "flags": (True, "U1234567")
    }
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Msg", (nested_args,), None)
    filter.filter(record)
    assert record.args["user"]["id"] == "DU1****567"
    assert record.args["user"]["data"][2] == "DU9****543"
    assert record.args["flags"][1] == "U12****567"

    # Test disabled
    record = logging.LogRecord("name", logging.INFO, "path", 1, "DU1234567", ({"acct": "DU1234567"},), None)
    disabled_filter = AccountMaskingFilter(["DU1234567"], enabled=False)
    disabled_filter.filter(record)
    assert record.msg == "DU1234567"
    assert record.args["acct"] == "DU1234567"

    # Test exc_text
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Msg", (), None)
    record.exc_text = "Exception with DU1234567"
    filter.filter(record)
    assert record.exc_text == "Exception with DU1****567"

    # Test early validation-style text
    msg_with_json_error = "Error: Invalid JSON format: Account DU1234567 invalid"
    record = logging.LogRecord("name", logging.INFO, "path", 1, msg_with_json_error, (), None)
    filter.filter(record)
    assert "DU1****567" in record.msg
