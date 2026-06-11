import sys
import asyncio
import logging
from config.loader import load_config, validate_ibkr_settings
from brokers.ibkr.adapter import IBKRAdapter
from brokers.schwab.adapter import SchwabAdapter
from engine.engine import GridEngine
from sheets.interface import SheetInterface
from utils.log_sanitizer import AccountMaskingFilter, mask_account_ids_in_text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

async def main():
    try:
        config = load_config()

        # Apply global log masking filter
        known_accounts = []
        if config.ibkr_account_id:
            known_accounts.append(config.ibkr_account_id)

        masking_filter = AccountMaskingFilter(
            known_account_ids=known_accounts,
            enabled=config.mask_account_ids_in_logs
        )
        for handler in logging.getLogger().handlers:
            handler.addFilter(masking_filter)

        # Suppress noisy ib_insync logs
        logging.getLogger('ib_insync').setLevel(logging.WARNING)
        logging.getLogger('ib_insync.ib').setLevel(logging.WARNING)
        logging.getLogger('ib_insync.wrapper').setLevel(logging.WARNING)
        logging.getLogger('ib_insync.client').setLevel(logging.WARNING)

    except Exception as e:
        # Before config/filter is loaded, manually sanitize prints
        safe_msg = mask_account_ids_in_text(f"Error loading config: {e}")
        print(safe_msg, file=sys.stderr)
        sys.exit(1)

    # Perform IBKR port/mode validation
    ibkr_warnings = validate_ibkr_settings(config)
    for warning in ibkr_warnings:
        logger.warning(warning)

    if config.active_broker == "ibkr" and config.ibkr_host not in ("127.0.0.1", "localhost"):
        logger.warning(
            "Bundled tqqq_bot only supports local Gateway access. "
            "Forcing ibkr_host to 127.0.0.1."
        )
        config.ibkr_host = "127.0.0.1"

    if config.active_broker == "ibkr":
        broker = IBKRAdapter(
            host=config.ibkr_host,
            port=config.ibkr_port,
            client_id=config.ibkr_client_id,
            paper=config.paper_trading,
            account_id=config.ibkr_account_id,
            mask_account_ids_in_logs=config.mask_account_ids_in_logs
        )
    elif config.active_broker == "schwab":
        broker = SchwabAdapter()
    else:
        logger.error(f"Error: Unsupported broker '{config.active_broker}'")
        sys.exit(1)

    sheet = SheetInterface(config)
    engine = GridEngine(broker, sheet, config)

    mode = "paper" if config.paper_trading else "live"
    logger.info(f"Bot initialized with {config.active_broker} in {mode} mode")

    logger.info("")
    logger.info("* TQQQ GRID BOT V6 OFFICIALLY STARTED!       *")
    logger.info("")

    try:
        await engine.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
