import logging

logger = logging.getLogger(__name__)

class SpreadGuard:
    def __init__(self, max_spread_pct: float):
        self.max_spread_pct = max_spread_pct

    def is_too_wide(self, bid: float, ask: float) -> bool:
        if ask <= 0:
            return True
        spread_pct = (ask - bid) / ask * 100
        if spread_pct > self.max_spread_pct:
            logger.warning(f"Spread blocked: {spread_pct:.2f}% (max: {self.max_spread_pct}%) [Bid: {bid}, Ask: {ask}]")
            return True
        return False
