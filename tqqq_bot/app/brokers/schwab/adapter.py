import logging
from typing import Optional, Callable
from brokers.base import BrokerBase, OrderResult, PositionSnapshot, SymbolSnapshot

logger = logging.getLogger(__name__)


class SchwabAdapter(BrokerBase):
    def __init__(self, dry_run: bool = False):
        super().__init__(dry_run=dry_run)

    async def connect(self) -> bool:
        raise NotImplementedError

    async def disconnect(self):
        raise NotImplementedError

    async def is_connected(self) -> bool:
        raise NotImplementedError

    async def ensure_connected(self):
        raise NotImplementedError

    async def get_price(self, ticker: str) -> float:
        raise NotImplementedError

    async def get_bid_ask(self, ticker: str) -> tuple[float, float]:
        raise NotImplementedError

    async def get_wallet_balance(self) -> float:
        raise NotImplementedError

    async def get_net_liquidation_value(self) -> Optional[float]:
        raise NotImplementedError

    async def get_next_order_id(self) -> str:
        raise NotImplementedError

    async def place_bracket_order(
        self, ticker: str, action: str,
        qty: int, limit_price: float, profit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None
    ) -> OrderResult:
        if self.dry_run:
            logger.info(f"DRY RUN BLOCKED ORDER PLACE: bracket action={action} ticker={ticker} qty={qty} limit={limit_price} profit={profit_price}")
            return OrderResult(
                order_id="DRY_RUN_NO_ORDER",
                status="dry_run_blocked",
                error_msg="DRY RUN: order was not submitted to broker"
            )
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> bool:
        if self.dry_run:
            logger.info(f"DRY RUN BLOCKED ORDER CANCEL: order_id={order_id}")
            return False
        raise NotImplementedError

    async def get_open_orders(self) -> list[dict]:
        raise NotImplementedError

    async def place_stop_limit_order(
        self, ticker: str, action: str,
        qty: int, stop_price: float, limit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None,
        order_id: Optional[str] = None
    ) -> OrderResult:
        if self.dry_run:
            logger.info(f"DRY RUN BLOCKED ORDER PLACE: stop limit action={action} ticker={ticker} qty={qty} stop={stop_price} limit={limit_price}")
            return OrderResult(
                order_id="DRY_RUN_NO_ORDER",
                status="dry_run_blocked",
                error_msg="DRY RUN: order was not submitted to broker"
            )
        raise NotImplementedError

    async def place_limit_order(
        self, ticker: str, action: str,
        qty: int, limit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None,
        order_id: Optional[str] = None
    ) -> OrderResult:
        if self.dry_run:
            logger.info(f"DRY RUN BLOCKED ORDER PLACE: limit action={action} ticker={ticker} qty={qty} limit={limit_price}")
            return OrderResult(
                order_id="DRY_RUN_NO_ORDER",
                status="dry_run_blocked",
                error_msg="DRY RUN: order was not submitted to broker"
            )
        raise NotImplementedError

    def subscribe_to_updates(self, order_id: str, on_update: Callable):
        raise NotImplementedError

    async def get_positions(self) -> dict[str, int]:
        raise NotImplementedError

    async def get_position_snapshot(self) -> PositionSnapshot:
        raise NotImplementedError

    async def get_portfolio_item(self, ticker: str) -> Optional[dict]:
        raise NotImplementedError

    async def get_verified_symbol_snapshot(self, symbol: str) -> SymbolSnapshot:
        raise NotImplementedError
