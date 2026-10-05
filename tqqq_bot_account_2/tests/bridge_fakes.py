"""
Stateful broker and Tracker stand-ins for Bridge Anchor tests, plus the grid
values and starting position of the 2026-10-02 incident. Tests drive the real
engine, order callbacks and Sheet sync through these instead of loose mocks.
"""
import asyncio

from brokers.base import OrderResult, PositionSnapshot, SymbolSnapshot
from engine.engine import GridEngine
from engine.grid_state import GridRow, GridState

TICKER = "TQQQ"

# (sell_price, buy_price, shares) per row, before and after the re-anchor.
OLD_GRID = {
    7: (82.52, 81.20, 65),
    8: (81.70, 80.39, 62),
    9: (80.87, 79.58, 60),
    10: (80.05, 78.76, 60),
    11: (79.22, 77.95, 58),
    12: (78.40, 77.14, 55),
}
NEW_GRID = {
    7: (83.87, 82.53, 64),
    8: (83.03, 81.70, 61),
    9: (82.19, 80.87, 59),
    10: (81.35, 80.05, 59),
    11: (80.52, 79.22, 57),
    12: (79.70, 78.40, 56),
}


class FakeBroker:
    """Stateful stand-in for the IBKR adapter."""

    def __init__(self, position: int = 0, bid: float = 82.06, ask: float = 82.08):
        self.position = position
        self.bid = bid
        self.ask = ask
        self.orders: dict[str, dict] = {}
        self.callbacks: dict[str, object] = {}
        self.events: list[tuple] = []
        self._next_id = 900
        # Marketable SELLs fill inside place_limit_order, as the trim did.
        self.fill_marketable_sells = True
        # Order ids whose next cancel request is accepted but then lost.
        self.lose_next_cancel: set[str] = set()

    # --- test helpers -------------------------------------------------
    def seed_order(self, order_id, action, qty, limit_price, order_type="LMT", aux_price=None):
        self.orders[str(order_id)] = {
            "order_id": str(order_id),
            "ticker": TICKER,
            "action": action,
            "qty": qty,
            "limit_price": limit_price,
            "aux_price": aux_price,
            "order_type": order_type,
            "tif": "GTC",
            "exchange": "SMART",
            "status": "Submitted",
            "filled_qty": 0.0,
            "remaining_qty": float(qty),
        }

    def fill(self, order_id, price=None):
        order = self.orders.pop(str(order_id))
        qty = order["qty"]
        self.position += qty if order["action"] == "BUY" else -qty
        fill_price = price if price is not None else order["limit_price"]
        self.events.append(("fill", str(order_id), order["action"], qty, fill_price))
        callback = self.callbacks.get(str(order_id))
        if callback:
            callback(OrderResult(order_id=str(order_id), status="filled",
                                 filled_price=fill_price, filled_qty=qty, reason="Filled"))

    def partial_fill(self, order_id, qty):
        """Some shares execute; the order keeps working. IBKR sends no terminal status."""
        order = self.orders[str(order_id)]
        order["filled_qty"] += qty
        order["remaining_qty"] -= qty
        self.position += qty if order["action"] == "BUY" else -qty
        self.events.append(("partial_fill", str(order_id), order["action"], qty))

    def complete_cancel(self, order_id):
        """The broker finally confirms a cancel that was pending."""
        oid = str(order_id)
        self.orders.pop(oid)
        self.events.append(("cancel", oid))
        callback = self.callbacks.get(oid)
        if callback:
            callback(OrderResult(order_id=oid, status="cancelled", filled_qty=None, reason="Cancelled"))

    def live(self, action=None, order_type=None):
        return [
            o for o in self.orders.values()
            if (action is None or o["action"] == action)
            and (order_type is None or o["order_type"] == order_type)
        ]

    def event_index(self, kind, predicate=lambda e: True):
        for i, event in enumerate(self.events):
            if event[0] == kind and predicate(event):
                return i
        return None

    # --- adapter surface used by the engine ---------------------------
    async def ensure_connected(self):
        return True

    async def get_position_snapshot(self):
        return PositionSnapshot(is_ready=True, positions={TICKER: self.position})

    async def get_verified_symbol_snapshot(self, ticker):
        orders = [dict(o) for o in self.orders.values()]
        return SymbolSnapshot(
            symbol=ticker,
            account_id_masked="DU1****567",
            position_qty=self.position,
            market_price=self.bid,
            market_value=self.bid * self.position,
            avg_cost=self.bid,
            net_liquidation=110000.0,
            cash=100000.0,
            open_orders_count=len(orders),
            working_buy_qty=sum(o["qty"] for o in orders if o["action"] == "BUY"),
            working_sell_qty=sum(o["qty"] for o in orders if o["action"] == "SELL"),
            active_broker_orders=orders,
            snapshot_status="OK",
            snapshot_error="",
        )

    async def get_open_orders(self):
        return [dict(o) for o in self.orders.values()]

    async def get_next_order_id(self):
        self._next_id += 2
        return str(self._next_id)

    async def get_wallet_balance(self):
        return 100000.0

    async def get_price(self, ticker):
        return self.bid

    async def get_bid_ask(self, ticker):
        return self.bid, self.ask

    def subscribe_to_updates(self, order_id, on_update):
        self.callbacks[str(order_id)] = on_update

    async def place_limit_order(self, ticker, action, qty, limit_price, on_update=None, order_id=None):
        oid = str(order_id)
        self.seed_order(oid, action, qty, limit_price)
        if on_update:
            self.callbacks[oid] = on_update
        self.events.append(("place", oid, action, qty, limit_price))
        if action == "SELL" and self.fill_marketable_sells and limit_price <= self.bid:
            self.fill(oid, price=self.bid)
        return OrderResult(order_id=oid, status="submitted")

    async def place_stop_limit_order(self, ticker, action, qty, stop_price, limit_price,
                                     on_update=None, order_id=None):
        oid = str(order_id)
        self.seed_order(oid, action, qty, limit_price, order_type="STP LMT", aux_price=stop_price)
        if on_update:
            self.callbacks[oid] = on_update
        self.events.append(("place_stop", oid, action, qty, stop_price))
        return OrderResult(order_id=oid, status="submitted")

    async def cancel_order(self, order_id):
        oid = str(order_id)
        if oid not in self.orders:
            return False
        if oid in self.lose_next_cancel:
            # The adapter returns True once the request is sent; nothing else happens.
            self.lose_next_cancel.discard(oid)
            self.events.append(("cancel_lost", oid))
            return True
        self.orders.pop(oid)
        self.events.append(("cancel", oid))
        callback = self.callbacks.get(oid)
        if callback:
            # The adapter reports filled_qty only on a fill.
            callback(OrderResult(order_id=oid, status="cancelled", filled_qty=None, reason="Cancelled"))
        return True


class FakeSheet:
    """Stateful stand-in for the Tracker tab: G7 drives the grid values."""

    def __init__(self, statuses: dict[int, str]):
        self.statuses = dict(statuses)
        self.grid = OLD_GRID
        self.anchor_writes: list[float] = []
        self.errors: list[str] = []
        self.error_rows: list[dict] = []
        self.health: list[dict] = []
        self.fetches_since_anchor_write = None
        # Number of reads the "formulas" need before the new values show up.
        self.recalc_lag_reads = 0

    async def fetch_grid(self):
        grid = self.grid
        if self.fetches_since_anchor_write is not None:
            if self.fetches_since_anchor_write >= self.recalc_lag_reads:
                grid = NEW_GRID
                self.grid = NEW_GRID
            self.fetches_since_anchor_write += 1
        rows = {}
        for row_index, (sell_price, buy_price, shares) in grid.items():
            status = self.statuses.get(row_index, "IDLE")
            first = status.split("|")[0]
            rows[row_index] = GridRow(
                row_index=row_index,
                status=status,
                has_y=first.startswith("OWNED:") or first.startswith("WORKING_SELL:"),
                sell_price=sell_price,
                buy_price=buy_price,
                shares=shares,
            )
        return GridState(rows=rows)

    async def update_row_status(self, row_index, status):
        self.statuses[row_index] = status

    async def write_anchor_ask(self, value):
        self.anchor_writes.append(value)
        if self.fetches_since_anchor_write is None:
            self.fetches_since_anchor_write = 0

    async def log_error(self, msg=None, *args, **kwargs):
        text = str(kwargs.get("details") or msg)
        self.errors.append(text)
        self.error_rows.append({"details": text, "code": kwargs.get("code", "ERROR"),
                                "severity": kwargs.get("severity", "ERROR"),
                                "bot_status": kwargs.get("bot_status", "")})
        return True

    async def append_error(self, *args, **kwargs):
        self.errors.append(str(kwargs.get("details", args)))
        return True

    async def log_health(self, health_data, *args, **kwargs):
        self.health.append(dict(health_data))
        return True

    async def log_fill(self, *args, **kwargs):
        return True

    async def write_cash_value(self, value):
        return None

    async def write_heartbeat(self, value):
        return None

    def is_exec_id_seen(self, exec_id):
        return False

    def mark_exec_id_seen(self, exec_id):
        return None


def track_all(engine, broker, tracked):
    """Registers (row, order_id, action) with the engine as the running bot would have."""
    for row, oid, action in tracked:
        engine.order_manager.track(row, OrderResult(order_id=oid, status="submitted"), action,
                                   broker=broker, on_update=engine._handle_order_update)


async def health_row(engine, sheet):
    """Writes one Health row through the real path and returns it."""
    await engine._log_health_once()
    return sheet.health[-1]


def friday_state(config, notifier=None):
    """Broker, Sheet and engine exactly as they stood just before 08:24."""
    broker = FakeBroker(position=65)
    broker.seed_order("223", "SELL", 65, 82.52)
    broker.seed_order("818", "BUY", 65, 84.02, order_type="STP LMT", aux_price=82.52)
    broker.seed_order("820", "BUY", 62, 80.39)
    broker.seed_order("762", "BUY", 60, 79.58)
    broker.seed_order("253", "BUY", 60, 78.76)

    sheet = FakeSheet({
        7: "WORKING_SELL:223|BRIDGE_BUY:818",
        8: "WORKING_BUY:820",
        9: "WORKING_BUY:762",
        10: "WORKING_BUY:253",
    })

    engine = GridEngine(broker, sheet, config, notifier=notifier)
    engine.last_broker_shares = 65
    for row, oid, action in ((7, "223", "SELL"), (7, "818", "BRIDGE_BUY"),
                             (8, "820", "BUY"), (9, "762", "BUY"), (10, "253", "BUY")):
        engine.order_manager.track(row, OrderResult(order_id=oid, status="submitted"), action,
                                   broker=broker, on_update=engine._handle_order_update)
    return broker, sheet, engine


async def run_ticks(engine, count):
    for _ in range(count):
        await engine._tick()
        await asyncio.sleep(0.01)  # let fire-and-forget sheet writes land


async def bridge_fires(broker):
    """08:24:47 - the row 7 SELL fills and the Bridge Anchor buys."""
    broker.fill("223", price=82.52)
    broker.fill("818", price=82.525)
    await asyncio.sleep(0.01)


def buys_match_sheet(broker, grid):
    """Every working limit BUY must equal some Sheet row's (buy_price, shares)."""
    wanted = {(buy_price, shares) for (_, buy_price, shares) in grid.values()}
    return [
        o for o in broker.live(action="BUY", order_type="LMT")
        if (o["limit_price"], o["qty"]) not in wanted
    ]
