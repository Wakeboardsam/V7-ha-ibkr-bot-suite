import logging
import traceback
from typing import Optional, List, Any

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
    Finds and masks known account IDs within a larger string.
    """
    if text is None:
        return "None"

    text_str = str(text)
    if not text_str:
        return ""

    if not enabled or not known_account_ids:
        return text_str

    for acct_id in known_account_ids:
        if acct_id:
            acct_id_str = str(acct_id)
            masked = mask_account_id(acct_id_str, enabled=True)
            text_str = text_str.replace(acct_id_str, masked)

    return text_str

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
        if not self.enabled or not self.known_account_ids:
            return True

        # Sanitize main message
        if isinstance(record.msg, str):
            record.msg = mask_account_ids_in_text(record.msg, self.known_account_ids, self.enabled)

        # Sanitize arguments
        if record.args:
            if isinstance(record.args, dict):
                new_args = {}
                for k, v in record.args.items():
                    if isinstance(v, str):
                        new_args[k] = mask_account_ids_in_text(v, self.known_account_ids, self.enabled)
                    else:
                        new_args[k] = v
                record.args = new_args
            elif isinstance(record.args, tuple):
                new_args = []
                for v in record.args:
                    if isinstance(v, str):
                        new_args.append(mask_account_ids_in_text(v, self.known_account_ids, self.enabled))
                    else:
                        new_args.append(v)
                record.args = tuple(new_args)

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