"""
Replay of the 2026-10-02 Bridge Anchor incident, plus the behaviour the
re-anchor sequence must have.

What happened that day (bot log, local time):

  06:59  Row 8 BUY (order 820) placed from the old grid: 62 shares @ 80.39.
         Rows 9 and 10 already had old-grid BUYs (762, 253), 60 shares each.
  08:24  Row 7 SELL filled 65 @ 82.52 and the Bridge Anchor bought 65 @ 82.525.
         G7 was re-anchored, so the Sheet recalculated every level:
         row 7 -> 64 shares, row 8 -> 61 @ 81.70, rows 9/10 -> 59 shares.
  08:25  1 share trimmed, new row 7 SELL placed, bridge re-armed.
         The three old-grid BUYs were left working at the broker.
  09:25  Old order 820 filled for 62 shares; the Sheet said 61.
         Broker 126 vs Sheet 125 -> circuit breaker, every minute.

Required sequence after a Bridge Anchor fill:

  1. cancel every standing order left from the old grid, and wait until the
     broker no longer shows them
  2. the fill price becomes the G7 anchor
  3. wait for the Sheet to recalculate (two identical consecutive reads)
  4. trim excess shares if needed
  5. only then place the new row 7 SELL, the new window BUYs and the bridge

These tests use a small stateful broker and Sheet instead of loose mocks so
that the real state transitions are exercised.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brokers.base import OrderResult, PositionSnapshot
from config.schema import AppConfig, NotificationSettings
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

    async def log_error(self, msg, *args, **kwargs):
        self.errors.append(str(msg))
        return True

    async def append_error(self, *args, **kwargs):
        self.errors.append(str(kwargs.get("details", args)))
        return True

    async def log_health(self, *args, **kwargs):
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


@pytest.fixture
def config():
    return AppConfig(
        active_broker="ibkr",
        paper_trading=True,
        ibkr_host="127.0.0.1",
        ibkr_port=7497,
        ibkr_client_id=1,
        google_sheet_id="fake_id",
        google_credentials_json="{}",
        anchor_buy_offset=1.5,
        enable_bridge_anchor=True,
        bridge_max_auto_trim_shares=5,
        share_mismatch_mode="halt",
        maintenance_enabled=False,
    )


@pytest.fixture(autouse=True)
def regular_session():
    """Pin the session so the replay does not depend on the wall clock."""
    with patch("brokers.ibkr.order_builder.get_dynamic_exchange", return_value="SMART"), \
         patch("brokers.ibkr.order_builder.get_dynamic_tif", return_value="GTC"), \
         patch.object(GridEngine, "_is_session_boundary", return_value=False), \
         patch.object(GridEngine, "_is_in_maintenance_window", return_value=False):
        yield


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


@pytest.mark.asyncio
async def test_friday_replay_old_grid_buys_are_flushed_after_bridge_fill(config):
    """The incident itself: no old-grid BUY may survive the re-anchor."""
    broker, sheet, engine = friday_state(config)

    await run_ticks(engine, 1)          # steady state before the move
    assert set(broker.orders) == {"223", "818", "820", "762", "253"}

    await bridge_fires(broker)
    await run_ticks(engine, 8)

    # 1. The three old-grid BUYs are gone from the broker.
    assert not {"820", "762", "253"} & set(broker.orders), \
        f"old-grid BUYs still working: {sorted({'820', '762', '253'} & set(broker.orders))}"

    # 2. Whatever BUYs are working now were sized and priced from the new grid.
    assert buys_match_sheet(broker, NEW_GRID) == []

    # 3. The anchor was written with the bridge fill price and position was trimmed to the Sheet.
    assert 82.525 in sheet.anchor_writes
    assert broker.position == NEW_GRID[7][2] == 64

    # 4. Row 7 is protected again: new SELL and a re-armed bridge, both for 64 @ 83.87.
    sells = broker.live(action="SELL")
    assert [(o["qty"], o["limit_price"]) for o in sells] == [(64, 83.87)]
    bridges = broker.live(action="BUY", order_type="STP LMT")
    assert [(o["qty"], o["aux_price"]) for o in bridges] == [(64, 83.87)]

    # 5. Price falls and the row 8 BUY fills: broker and Sheet still agree.
    row8_buy = next(o for o in broker.live(action="BUY", order_type="LMT")
                    if o["limit_price"] == NEW_GRID[8][1])
    broker.fill(row8_buy["order_id"])
    await run_ticks(engine, 3)

    assert broker.position == NEW_GRID[7][2] + NEW_GRID[8][2] == 125
    assert not [e for e in sheet.errors if "CIRCUIT BREAKER" in e]
    assert engine._bridge_state != "BRIDGE_HALTED"
    assert engine._halted_reconciliation is False


@pytest.mark.asyncio
async def test_reanchor_sequence_order_cancel_then_trim_then_new_orders(config):
    """Nothing new is placed until the old orders are gone and the Sheet has settled."""
    broker, sheet, engine = friday_state(config)
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 8)

    last_old_cancel = max(
        broker.event_index("cancel", lambda e, oid=oid: e[1] == oid) for oid in ("820", "762", "253")
    )
    trim_placed = broker.event_index("place", lambda e: e[2] == "SELL" and e[3] == 1)
    new_sell_placed = broker.event_index("place", lambda e: e[2] == "SELL" and e[3] == 64)
    first_new_buy = broker.event_index("place", lambda e: e[2] == "BUY")
    bridge_rearmed = broker.event_index("place_stop", lambda e: e[3] == 64)

    assert None not in (trim_placed, new_sell_placed, first_new_buy, bridge_rearmed)
    assert last_old_cancel < trim_placed < new_sell_placed
    assert new_sell_placed <= first_new_buy
    assert new_sell_placed < bridge_rearmed


@pytest.mark.asyncio
async def test_reanchor_waits_for_sheet_to_settle_before_trimming(config):
    """A Sheet that is slow to recalculate must not produce a trim from stale share counts."""
    broker, sheet, engine = friday_state(config)
    sheet.recalc_lag_reads = 3
    await run_ticks(engine, 1)
    await bridge_fires(broker)

    await run_ticks(engine, 3)
    # Still on the old grid (row 7 = 65 shares, equal to the position): nothing may be placed yet.
    assert broker.event_index("place") is None
    assert broker.event_index("place_stop") is None
    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"

    await run_ticks(engine, 8)
    assert broker.position == 64
    assert buys_match_sheet(broker, NEW_GRID) == []


@pytest.mark.asyncio
async def test_reanchor_waits_for_old_row7_sell_before_reconciling_shares(config):
    """Bridge fills while the old row 7 SELL is still working: wait, do not halt the bridge flow."""
    broker, sheet, engine = friday_state(config)
    await run_ticks(engine, 1)

    broker.fill("818", price=82.525)      # bridge first; SELL 223 still working, position 130
    await asyncio.sleep(0.01)
    await run_ticks(engine, 4)

    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"
    assert broker.event_index("place") is None, "no trim or new order while the old SELL is live"

    broker.fill("223", price=82.52)       # the delayed SELL fill arrives
    await asyncio.sleep(0.01)
    await run_ticks(engine, 8)

    assert engine._bridge_state != "BRIDGE_HALTED"
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]


@pytest.mark.asyncio
async def test_reanchor_resends_a_cancel_whose_confirmation_was_lost(config):
    """A cancel the broker never confirms must be sent again, not waited on forever."""
    broker, sheet, engine = friday_state(config)
    engine._cancel_resend_seconds = 0
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 10)

    assert broker.event_index("cancel_lost", lambda e: e[1] == "820") is not None
    assert "820" not in broker.orders
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]
    assert buys_match_sheet(broker, NEW_GRID) == []


@pytest.mark.asyncio
async def test_reanchor_does_not_resend_a_recent_cancel(config):
    """Within the resend window a pending cancel is left alone."""
    broker, sheet, engine = friday_state(config)
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 5)

    assert "820" in broker.orders
    assert len([e for e in broker.events if e[0] in ("cancel", "cancel_lost") and e[1] == "820"]) == 1
    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"
    assert broker.event_index("place") is None


@pytest.mark.asyncio
async def test_reanchor_releases_old_buy_that_vanished_without_a_callback(config):
    """An old BUY the broker no longer shows, with no callback, must not block the row 7 SELL."""
    broker, sheet, engine = friday_state(config)
    await run_ticks(engine, 1)
    broker.orders.pop("820")              # gone at the broker, no cancel or fill callback
    await bridge_fires(broker)
    await run_ticks(engine, 10)

    assert not engine.order_manager.is_tracked("820")
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]
    assert buys_match_sheet(broker, NEW_GRID) == []
    assert engine._bridge_state != "BRIDGE_HALTED"


@pytest.mark.asyncio
async def test_stale_grid_buy_needs_two_consecutive_ticks(config):
    """A sighting followed by a tick that does not evaluate the grid does not count."""
    broker = FakeBroker(position=64)
    broker.seed_order("986", "SELL", 64, 83.87)
    broker.seed_order("820", "BUY", 62, 80.39)
    sheet = FakeSheet({7: "WORKING_SELL:986", 8: "WORKING_BUY:820"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config)
    engine.last_broker_shares = 64
    engine.order_manager.track(7, OrderResult(order_id="986", status="submitted"), "SELL",
                               broker=broker, on_update=engine._handle_order_update)
    engine.order_manager.track(8, OrderResult(order_id="820", status="submitted"), "BUY",
                               broker=broker, on_update=engine._handle_order_update)

    await run_ticks(engine, 1)                         # first sighting
    engine._session_cancel_settlement_required = True  # next tick ends before grid evaluation
    await run_ticks(engine, 1)
    await run_ticks(engine, 1)                         # sighting again: still only the first in a row
    assert "820" in broker.orders

    await run_ticks(engine, 1)
    assert "820" not in broker.orders


@pytest.mark.asyncio
async def test_stale_grid_buy_is_replaced_when_sheet_row_changes(config):
    """Standing check: a working BUY that no longer matches its row is cancelled and re-placed."""
    broker = FakeBroker(position=64)
    broker.seed_order("986", "SELL", 64, 83.87)
    broker.seed_order("820", "BUY", 62, 80.39)          # old-grid order on row 8
    sheet = FakeSheet({7: "WORKING_SELL:986", 8: "WORKING_BUY:820"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config)
    engine.last_broker_shares = 64
    engine.order_manager.track(7, OrderResult(order_id="986", status="submitted"), "SELL",
                               broker=broker, on_update=engine._handle_order_update)
    engine.order_manager.track(8, OrderResult(order_id="820", status="submitted"), "BUY",
                               broker=broker, on_update=engine._handle_order_update)

    await run_ticks(engine, 1)
    assert "820" in broker.orders, "one mismatching read is not enough to cancel"

    await run_ticks(engine, 3)
    assert "820" not in broker.orders
    row8 = [o for o in broker.live(action="BUY", order_type="LMT") if o["limit_price"] == 81.70]
    assert [(o["qty"]) for o in row8] == [61]


@pytest.mark.asyncio
async def test_stale_grid_buy_check_ignores_unreadable_sheet_row(config):
    """A row that reads as zero shares / zero price must never cause a cancel."""
    broker = FakeBroker(position=64)
    broker.seed_order("986", "SELL", 64, 83.87)
    broker.seed_order("820", "BUY", 61, 81.70)
    sheet = FakeSheet({7: "WORKING_SELL:986", 8: "WORKING_BUY:820"})
    sheet.grid = dict(NEW_GRID)
    sheet.grid[8] = (0.0, 0.0, 0)
    engine = GridEngine(broker, sheet, config)
    engine.last_broker_shares = 64
    engine.order_manager.track(7, OrderResult(order_id="986", status="submitted"), "SELL",
                               broker=broker, on_update=engine._handle_order_update)
    engine.order_manager.track(8, OrderResult(order_id="820", status="submitted"), "BUY",
                               broker=broker, on_update=engine._handle_order_update)

    await run_ticks(engine, 4)
    assert "820" in broker.orders


@pytest.mark.asyncio
async def test_share_mismatch_cancels_live_bridge_and_notifies_once(config):
    """
    The state the account was left in on 2026-10-02: two rows owned, broker one
    share above the Sheet, Bridge Anchor 990 still armed. The mismatch check must
    not leave the bridge live, and must tell the operator once, not every minute.
    """
    config.notifications = NotificationSettings(enabled=True, webhook_url="http://example.invalid/hook",
                                                notify_on_halts=True)
    notifier = MagicMock()

    broker = FakeBroker(position=126)
    broker.seed_order("986", "SELL", 64, 83.87)
    broker.seed_order("990", "BUY", 64, 85.37, order_type="STP LMT", aux_price=83.87)
    sheet = FakeSheet({7: "WORKING_SELL:986|BRIDGE_BUY:990", 8: "OWNED:820"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config, notifier=notifier)
    engine._startup_ok_notification_sent = True
    engine.last_broker_shares = 126
    engine.order_manager.track(7, OrderResult(order_id="986", status="submitted"), "SELL",
                               broker=broker, on_update=engine._handle_order_update)
    engine.order_manager.track(7, OrderResult(order_id="990", status="submitted"), "BRIDGE_BUY",
                               broker=broker, on_update=engine._handle_order_update)

    await run_ticks(engine, 3)

    assert "990" not in broker.orders, "Bridge Anchor must not stay armed during a share mismatch"
    assert "986" in broker.orders, "the protective row 7 SELL is left alone"
    assert broker.event_index("place") is None, "a mismatch places nothing"
    assert "BRIDGE_BUY" not in sheet.statuses[7]

    mismatch_calls = [c for c in notifier.send.call_args_list
                      if c.kwargs.get("event_type") == "SHARE_MISMATCH"]
    assert len(mismatch_calls) == 1
    assert mismatch_calls[0].kwargs["extra"]["broker_shares"] == 126
    assert mismatch_calls[0].kwargs["extra"]["sheet_shares"] == 125
