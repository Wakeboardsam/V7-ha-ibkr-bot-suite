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

def test_account_masking_filter():
    filter = AccountMaskingFilter(["DU1234567"])

    # Test simple message
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Logging DU1234567 in msg", (), None)
    filter.filter(record)
    assert record.msg == "Logging DU1****567 in msg"

    # Test dictionary args
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Msg", {"acct": "DU1234567", "other": 123}, None)
    filter.filter(record)
    assert record.args["acct"] == "DU1****567"
    assert record.args["other"] == 123

    # Test tuple args
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Msg", ("DU1234567", 123), None)
    filter.filter(record)
    assert record.args[0] == "DU1****567"
    assert record.args[1] == 123

    # Test exc_text
    record = logging.LogRecord("name", logging.INFO, "path", 1, "Msg", (), None)
    record.exc_text = "Exception with DU1234567"
    filter.filter(record)
    assert record.exc_text == "Exception with DU1****567"
