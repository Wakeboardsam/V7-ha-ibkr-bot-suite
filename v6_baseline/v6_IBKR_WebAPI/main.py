import sys
import asyncio
import logging
from config.loader import load_config, validate_ibkr_settings
from brokers.ibkr.adapter import IBKRAdapter
from brokers.schwab.adapter import SchwabAdapter
from engine.engine import GridEngine
from sheets.interface import SheetInterface

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
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Perform IBKR port/mode validation
    ibkr_warnings = validate_ibkr_settings(config)
    for warning in ibkr_warnings:
        logger.warning(warning)

    if config.active_broker == "ibkr":
        broker = IBKRAdapter(
            host=config.ibkr_host,
            port=config.ibkr_port,
            client_id=config.ibkr_client_id,
            paper=config.paper_trading
        )
    elif config.active_broker == "schwab":
        broker = SchwabAdapter()
    else:
        print(f"Error: Unsupported broker '{config.active_broker}'", file=sys.stderr)
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
