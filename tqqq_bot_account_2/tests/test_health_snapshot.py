import unittest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from brokers.base import SymbolSnapshot
from engine.engine import GridEngine

class TestHealthSnapshot(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_broker = AsyncMock()
        self.mock_sheet = AsyncMock()
        self.mock_config = MagicMock()
        self.mock_config.dry_run = False
        self.mock_config.health_log_interval_seconds = 1

        self.engine = GridEngine(self.mock_broker, self.mock_sheet, self.mock_config)
        self.engine._shutdown_event.set() # Don't loop forever

    async def test_health_snapshot_ok_position(self):
        snapshot = SymbolSnapshot(
            symbol="TQQQ",
            account_id_masked="DU1***456",
            position_qty=50,
            market_price=10.0,
            market_value=500.0,
            avg_cost=9.5,
            net_liquidation=1000.0,
            cash=500.0,
            open_orders_count=1,
            working_buy_qty=10,
            working_sell_qty=0,
            active_broker_orders=[{"order_id": "1", "action": "BUY", "qty": 10, "ticker": "TQQQ"}],
            snapshot_status="OK",
            snapshot_error=""
        )
        self.mock_broker.get_verified_symbol_snapshot.return_value = snapshot
        self.engine.order_manager.get_tracked_order_ids = MagicMock(return_value=["1"])



        import asyncio
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.mock_sheet.log_health.assert_called_once()
        health_data = self.mock_sheet.log_health.call_args[0][0]
        self.assertEqual(health_data["position"], 50)
        self.assertEqual(health_data["snapshot_status"], "OK")
        self.assertEqual(health_data["order_match_status"], "MATCH")
        self.assertEqual(health_data["last_fill_time"], "Broker position exists; no bot buy fill found")
        self.assertEqual(health_data["working_buy_qty"], 10)

        # Ensure errors are not spammed
        self.mock_sheet.log_error.assert_not_called()

    async def test_health_snapshot_zero_position_ok(self):
        snapshot = SymbolSnapshot(
            symbol="TQQQ",
            account_id_masked="DU1***456",
            position_qty=0,
            market_price=None,
            market_value=None,
            avg_cost=None,
            net_liquidation=1000.0,
            cash=1000.0,
            open_orders_count=0,
            working_buy_qty=0,
            working_sell_qty=0,
            active_broker_orders=[],
            snapshot_status="OK",
            snapshot_error=""
        )
        self.mock_broker.get_verified_symbol_snapshot.return_value = snapshot
        self.engine.order_manager.get_tracked_order_ids = MagicMock(return_value=[])



        import asyncio
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.mock_sheet.log_health.assert_called_once()
        health_data = self.mock_sheet.log_health.call_args[0][0]
        self.assertEqual(health_data["position"], 0)
        self.assertEqual(health_data["snapshot_status"], "OK")
        self.assertEqual(health_data["order_match_status"], "MATCH")

        self.mock_sheet.log_error.assert_not_called()

    async def test_health_snapshot_unavailable_error_logged_once(self):
        snapshot = SymbolSnapshot(
            symbol="TQQQ",
            account_id_masked="DU1***456",
            position_qty=None,
            market_price=None,
            market_value=None,
            avg_cost=None,
            net_liquidation=None,
            cash=None,
            open_orders_count=0,
            working_buy_qty=0,
            working_sell_qty=0,
            active_broker_orders=[],
            snapshot_status="UNAVAILABLE",
            snapshot_error="Timeout"
        )
        self.mock_broker.get_verified_symbol_snapshot.return_value = snapshot
        self.engine.order_manager.get_tracked_order_ids = MagicMock(return_value=[])

        # Run first time


        import asyncio
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.mock_sheet.log_error.assert_called_once()
        self.assertTrue(self.engine._snapshot_error_logged)

        self.mock_sheet.log_health.assert_called_once()
        health_data = self.mock_sheet.log_health.call_args[0][0]
        self.assertEqual(health_data["position"], "") # Not zero silently
        self.assertEqual(health_data["snapshot_status"], "UNAVAILABLE")

        # Run second time
        self.mock_sheet.log_error.reset_mock()


        import asyncio
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self.mock_sheet.log_error.assert_not_called() # Deduplicated

    async def test_health_snapshot_mismatch(self):
        snapshot = SymbolSnapshot(
            symbol="TQQQ",
            account_id_masked="DU1***456",
            position_qty=50,
            market_price=10.0,
            market_value=500.0,
            avg_cost=9.5,
            net_liquidation=1000.0,
            cash=500.0,
            open_orders_count=1,
            working_buy_qty=10,
            working_sell_qty=0,
            active_broker_orders=[{"order_id": "1", "action": "BUY", "qty": 10, "ticker": "TQQQ"}],
            snapshot_status="OK",
            snapshot_error=""
        )
        self.mock_broker.get_verified_symbol_snapshot.return_value = snapshot
        self.engine.order_manager.get_tracked_order_ids = MagicMock(return_value=[]) # Expected nothing



        import asyncio
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        health_data = self.mock_sheet.log_health.call_args[0][0]
        self.assertEqual(health_data["order_match_status"], "MISMATCH")
        self.assertEqual(health_data["unmatched_broker_orders"], "1")


    async def test_health_snapshot_account_scope_missing(self):
        snapshot = SymbolSnapshot(
            symbol="TQQQ",
            account_id_masked="",
            position_qty=None,
            market_price=None,
            market_value=None,
            avg_cost=None,
            net_liquidation=None,
            cash=None,
            open_orders_count=0,
            working_buy_qty=0,
            working_sell_qty=0,
            active_broker_orders=[],
            snapshot_status="ACCOUNT_SCOPE_MISSING",
            snapshot_error="Account ID is missing or unconfigured"
        )
        self.mock_broker.get_verified_symbol_snapshot.return_value = snapshot
        self.engine.order_manager.get_tracked_order_ids = MagicMock(return_value=[])

        import asyncio
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.mock_sheet.log_error.assert_called_once()
        self.assertTrue(self.engine._snapshot_error_logged)

        # Run second time
        self.mock_sheet.log_error.reset_mock()
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self.mock_sheet.log_error.assert_not_called() # Deduplicated

    async def test_health_snapshot_mismatch_qty(self):
        # Even if order ID is tracked, if qty doesn't match grid state, it's a mismatch
        snapshot = SymbolSnapshot(
            symbol="TQQQ",
            account_id_masked="DU1***456",
            position_qty=50,
            market_price=10.0,
            market_value=500.0,
            avg_cost=9.5,
            net_liquidation=1000.0,
            cash=500.0,
            open_orders_count=1,
            working_buy_qty=20, # Broker has 20
            working_sell_qty=0,
            active_broker_orders=[{"order_id": "1", "action": "BUY", "qty": 20, "ticker": "TQQQ"}],
            snapshot_status="OK",
            snapshot_error=""
        )
        self.mock_broker.get_verified_symbol_snapshot.return_value = snapshot

        self.engine.order_manager.get_tracked_order_ids = MagicMock(return_value=["1"])
        self.engine.order_manager.get_row_and_action = MagicMock(return_value=(8, "BUY"))

        # Grid expects 10 shares
        from engine.grid_state import GridState, GridRow
        self.engine.grid_state = GridState(rows={
            8: GridRow(row_index=8, status="WORKING_BUY:1", shares=10, buy_price=100.0, sell_price=102.0, has_y=False)
        })

        import asyncio
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        health_data = self.mock_sheet.log_health.call_args[0][0]
        self.assertEqual(health_data["order_match_status"], "MISMATCH")
        self.assertEqual(health_data["unmatched_broker_orders"], "1")

    async def test_health_snapshot_portfolio_missing_position_fallback(self):
        # Verify that if broker_market_price/value are empty, they are passed as empty strings/None
        # and avgCost is fetched.
        snapshot = SymbolSnapshot(
            symbol="TQQQ",
            account_id_masked="DU1***456",
            position_qty=50,
            market_price=None,
            market_value=None,
            avg_cost=15.0,
            net_liquidation=1000.0,
            cash=1000.0,
            open_orders_count=0,
            working_buy_qty=0,
            working_sell_qty=0,
            active_broker_orders=[],
            snapshot_status="OK",
            snapshot_error="Position exists but broker portfolio item unavailable; broker market fields withheld."
        )
        self.mock_broker.get_verified_symbol_snapshot.return_value = snapshot
        self.engine.order_manager.get_tracked_order_ids = MagicMock(return_value=[])

        import asyncio
        self.engine._shutdown_event.clear()
        task = asyncio.create_task(self.engine._log_health_periodic())
        await asyncio.sleep(0.01) # Yield to event loop to let it run one cycle
        self.engine._shutdown_event.set()
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.mock_sheet.log_health.assert_called_once()
        health_data = self.mock_sheet.log_health.call_args[0][0]
        self.assertEqual(health_data["position"], 50)
        self.assertEqual(health_data["broker_market_price"], "")
        self.assertEqual(health_data["broker_market_value"], "")
        self.assertEqual(health_data["broker_avg_cost"], 15.0)
        self.assertEqual(health_data["snapshot_status"], "OK")
        self.assertEqual(health_data["snapshot_error"], "Position exists but broker portfolio item unavailable; broker market fields withheld.")
