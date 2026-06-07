from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class PositionSnapshot:
    is_ready: bool
    positions: dict[str, int]


@dataclass
class OrderResult:
    order_id: str
    status: str          # 'submitted' | 'filled' | 'cancelled' | 'error'
    filled_price: Optional[float] = None
    filled_qty:   Optional[int]   = None
    error_msg:    Optional[str]   = None
    error_code:   Optional[int]   = None
    reason:       Optional[str]   = None


class BrokerBase(ABC):

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self): ...

    @abstractmethod
    async def is_connected(self) -> bool: ...

    @abstractmethod
    async def ensure_connected(self): ...

    @abstractmethod
    async def get_price(self, ticker: str) -> float: ...

    @abstractmethod
    async def get_bid_ask(self, ticker: str) -> tuple[float, float]: ...

    @abstractmethod
    async def get_wallet_balance(self) -> float: ...

    @abstractmethod
    async def get_net_liquidation_value(self) -> Optional[float]: ...

    @abstractmethod
    async def get_next_order_id(self) -> str: ...

    @abstractmethod
    async def place_bracket_order(
        self, ticker: str, action: str,  # 'BUY' | 'SELL'
        qty: int, limit_price: float, profit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None
    ) -> OrderResult: ...

    @abstractmethod
    async def place_stop_limit_order(
        self, ticker: str, action: str,
        qty: int, stop_price: float, limit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None,
        order_id: Optional[str] = None
    ) -> OrderResult: ...

    @abstractmethod
    async def place_limit_order(
        self, ticker: str, action: str,
        qty: int, limit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None,
        order_id: Optional[str] = None
    ) -> OrderResult: ...

    @abstractmethod
    def subscribe_to_updates(self, order_id: str, on_update: Callable): ...

    @abstractmethod
    def subscribe_to_executions(self, on_execution: Callable): ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_open_orders(self) -> list[dict]: ...

    @abstractmethod
    async def get_positions(self) -> dict[str, int]: ...

    @abstractmethod
    async def get_position_snapshot(self) -> PositionSnapshot: ...

    @abstractmethod
    async def get_portfolio_item(self, ticker: str) -> Optional[dict]: ...
