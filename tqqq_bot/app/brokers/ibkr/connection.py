import asyncio
import logging
from ib_insync import IB

logger = logging.getLogger(__name__)

async def async_connect(ib: IB, host: str, port: int, client_id: int) -> bool:
    """
    Connects to IBKR with exponential backoff retry.
    Max 10 attempts, starting at 5s, doubling each retry.
    """
    delay = 5
    for attempt in range(1, 11):
        logger.info(f"Connection attempt {attempt}/10 to {host}:{port}...")
        try:
            await ib.connectAsync(host, port, clientId=client_id)
            if ib.isConnected():
                logger.info(f"Successfully connected to IBKR on attempt {attempt}")
                return True
        except Exception as e:
            logger.error(f"Connection attempt {attempt} failed: {e}")

        if attempt < 10:
            logger.info(f"Retrying in {delay} seconds...")
            await asyncio.sleep(delay)
            delay *= 2

    raise ConnectionError(f"Failed to connect to IBKR after 10 attempts at {host}:{port}")
