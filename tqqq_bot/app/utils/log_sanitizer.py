import logging
import traceback
import re
import json
from typing import Optional, List, Any

# Match typical IBKR account IDs like DU1234567, U1234567, F1234567
# Conservative: requires a prefix letter (or letters) and at least 5 digits/chars
# We use [DdUuFf] possibly followed by 'U' then at least 5 digits (preventing "Unknown" from matching)
ACCOUNT_REGEX = re.compile(r'\b([DdUuFf][Uu]?[0-9]{5,15})\b')

def mask_account_id(value: Any, enabled: bool = True) -> str:
    """
    Masks an IBKR account ID.
    DU1234567 becomes DU1****567.
    Preserves enough prefix/suffix for diagnostics.
    Safely handles None, empty strings, non-strings, short strings.
    """
    if value is None:
        return "None"

    val_str = str(value)
    if not val_str:
        return ""

    if not enabled:
        return val_str

    if len(val_str) > 6:
        return f"{val_str[:3]}****{val_str[-3:]}"
    elif len(val_str) > 2:
        return f"{val_str[:1]}****{val_str[-1:]}"
    return "****"

def mask_account_ids_in_text(text: Any, known_account_ids: Optional[List[str]] = None, enabled: bool = True) -> str:
    """
    Finds and masks known account IDs within a larger string, and falls back to regex
    for unknown but obvious account IDs.
    """
    if text is None:
        return "None"

    text_str = str(text)
    if not text_str:
        return ""

    if not enabled:
        return text_str

    if known_account_ids:
        for acct_id in known_account_ids:
            if acct_id:
                acct_id_str = str(acct_id)
                masked = mask_account_id(acct_id_str, enabled=True)
                text_str = text_str.replace(acct_id_str, masked)

    # Regex fallback for obvious account IDs not in the known list
    def regex_replace(match):
        return mask_account_id(match.group(1), enabled=True)

    text_str = ACCOUNT_REGEX.sub(regex_replace, text_str)

    return text_str

def _sanitize_nested(obj: Any, known_account_ids: Optional[List[str]], enabled: bool) -> Any:
    """Recursively sanitizes dicts, lists, and tuples."""
    if not enabled:
        return obj

    if isinstance(obj, str):
        return mask_account_ids_in_text(obj, known_account_ids, enabled)
    elif isinstance(obj, dict):
        return {k: _sanitize_nested(v, known_account_ids, enabled) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_nested(v, known_account_ids, enabled) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(_sanitize_nested(v, known_account_ids, enabled) for v in obj)
    else:
        # For ib_insync objects or other complex types, try getting the repr and masking it.
        # But we must return the original object if we want standard logging format strings like %d to work.
        # If it's a known generic type (int, float, bool, None), return as is.
        if obj is None or isinstance(obj, (int, float, bool)):
            return obj

        try:
            repr_str = repr(obj)
            masked_repr = mask_account_ids_in_text(repr_str, known_account_ids, enabled)
            # If the string actually changed, we have to return the string to hide the account ID.
            if repr_str != masked_repr:
                return masked_repr
        except Exception:
            pass

        return obj


class AccountMaskingFilter(logging.Filter):
    """
    A logging filter that intercepts log records and sanitizes message, arguments,
    and exception text for known account IDs.
    """
    def __init__(self, known_account_ids: Optional[List[str]] = None, enabled: bool = True):
        super().__init__()
        self.known_account_ids = known_account_ids or []
        self.enabled = enabled

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.enabled:
            return True

        # Sanitize main message
        if isinstance(record.msg, str):
            record.msg = mask_account_ids_in_text(record.msg, self.known_account_ids, self.enabled)
        elif record.msg is not None:
            # If the main message isn't a string (e.g. log(INFO, my_dict)), stringify and mask it
            record.msg = mask_account_ids_in_text(str(record.msg), self.known_account_ids, self.enabled)

        # Sanitize arguments (can be dict or tuple)
        if record.args:
            if isinstance(record.args, dict):
                record.args = _sanitize_nested(record.args, self.known_account_ids, self.enabled)
            elif isinstance(record.args, tuple):
                record.args = _sanitize_nested(record.args, self.known_account_ids, self.enabled)

        # Sanitize formatted exception if it exists
        if record.exc_text:
            record.exc_text = mask_account_ids_in_text(record.exc_text, self.known_account_ids, self.enabled)

        # Sanitize exc_info if it hasn't been formatted yet but is present
        # We don't overwrite exc_info, but if the formatter formats it later,
        # it might bypass us. So we pre-format and sanitize it into exc_text here.
        if record.exc_info and not record.exc_text:
            try:
                exc_text = "".join(traceback.format_exception(*record.exc_info))
                record.exc_text = mask_account_ids_in_text(exc_text, self.known_account_ids, self.enabled)
                # clear exc_info so the formatter uses our sanitized exc_text instead
                record.exc_info = None
            except Exception:
                pass

        return True