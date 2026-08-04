import re

def patch_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    new_tests = """
@pytest.mark.asyncio
async def test_working_sell_missing_and_shares_match(engine, mock_broker, mock_sheet):
    \"\"\"
    If broker_shares perfectly matches expected AND there are no unresolved issues,
    a missing WORKING_SELL should self-heal to OWNED:0 rather than halting.
    \"\"\"
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101)
    })

    open_orders = [] # missing

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=101)
    # The tick should be halted safely to allow regeneration, but not a hard error halt
    assert engine._halted_reconciliation is False
    assert engine.grid_state.rows[7].status == "OWNED:0"
    mock_sheet.append_error.assert_not_called()


@pytest.mark.asyncio
async def test_working_buy_missing_and_shares_match(engine, mock_broker, mock_sheet):
    \"\"\"
    If broker_shares perfectly matches expected AND there are no unresolved issues,
    a missing WORKING_BUY should self-heal to IDLE rather than halting.
    \"\"\"
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, sell_price=10.0, buy_price=9.0, shares=100),
        8: GridRow(row_index=8, status="WORKING_BUY:102", has_y=False, sell_price=10.0, buy_price=9.0, shares=100)
    })

    open_orders = [] # missing

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=100)
    assert engine._halted_reconciliation is False
    assert engine.grid_state.rows[8].status == "IDLE"
    mock_sheet.append_error.assert_not_called()


@pytest.mark.asyncio
async def test_stale_orders_regression(engine, mock_broker, mock_sheet):
    \"\"\"
    Regression case from prompt:
    broker_shares = 1251
    open_orders = []

    rows 0-16 = OWNED (skipped here for brevity, represent with one aggregate row)
    row 17 = WORKING_SELL, 46 shares
    row 18 = WORKING_SELL, 44
    row 19 = WORKING_SELL, 43
    row 20 = WORKING_SELL, 41
    row 21 = WORKING_BUY, 40
    row 22 = WORKING_BUY, 39
    row 23 = WORKING_BUY, 37
    row 24 = IDLE

    Total shares = aggregate + 46+44+43+41 = 1251
    Expected: NO error halt, rows self-heal, tick safely returns to allow regen next cycle.
    \"\"\"
    engine.grid_state = GridState(rows={
        16: GridRow(row_index=16, status="OWNED:0", has_y=True, sell_price=10.0, buy_price=9.0, shares=1077),
        17: GridRow(row_index=17, status="WORKING_SELL:117", has_y=True, sell_price=10.0, buy_price=9.0, shares=46),
        18: GridRow(row_index=18, status="WORKING_SELL:118", has_y=True, sell_price=10.0, buy_price=9.0, shares=44),
        19: GridRow(row_index=19, status="WORKING_SELL:119", has_y=True, sell_price=10.0, buy_price=9.0, shares=43),
        20: GridRow(row_index=20, status="WORKING_SELL:120", has_y=True, sell_price=10.0, buy_price=9.0, shares=41),
        21: GridRow(row_index=21, status="WORKING_BUY:121", has_y=False, sell_price=10.0, buy_price=9.0, shares=40),
        22: GridRow(row_index=22, status="WORKING_BUY:122", has_y=False, sell_price=10.0, buy_price=9.0, shares=39),
        23: GridRow(row_index=23, status="WORKING_BUY:123", has_y=False, sell_price=10.0, buy_price=9.0, shares=37),
        24: GridRow(row_index=24, status="IDLE", has_y=False, sell_price=10.0, buy_price=9.0, shares=36)
    })

    open_orders = []

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=1251)

    assert engine._halted_reconciliation is False
    mock_sheet.append_error.assert_not_called()

    assert engine.grid_state.rows[17].status == "OWNED:0"
    assert engine.grid_state.rows[18].status == "OWNED:0"
    assert engine.grid_state.rows[19].status == "OWNED:0"
    assert engine.grid_state.rows[20].status == "OWNED:0"

    assert engine.grid_state.rows[21].status == "IDLE"
    assert engine.grid_state.rows[22].status == "IDLE"
    assert engine.grid_state.rows[23].status == "IDLE"
    assert engine.grid_state.rows[24].status == "IDLE"

@pytest.mark.asyncio
async def test_two_tick_stale_order_recovery(engine, mock_broker, mock_sheet):
    \"\"\"
    Two-tick regression test.
    First _tick() with stale WORKING_SELL/WORKING_BUY IDs:
      - self-heals Tracker
      - places zero orders
      - _halted_reconciliation remains False
    Second _tick() with the corrected Tracker:
      - normal existing grid logic runs
      - missing SELL/BUY orders are recreated
      - recreated SELLs still pass through _run_pre_sell_guard()
    \"\"\"
    engine.grid_state = GridState(rows={
        16: GridRow(row_index=16, status="OWNED:0", has_y=True, sell_price=10.0, buy_price=9.0, shares=1077),
        17: GridRow(row_index=17, status="WORKING_SELL:117", has_y=True, sell_price=10.0, buy_price=9.0, shares=46),
        18: GridRow(row_index=18, status="WORKING_SELL:118", has_y=True, sell_price=10.0, buy_price=9.0, shares=44),
        19: GridRow(row_index=19, status="WORKING_SELL:119", has_y=True, sell_price=10.0, buy_price=9.0, shares=43),
        20: GridRow(row_index=20, status="WORKING_SELL:120", has_y=True, sell_price=10.0, buy_price=9.0, shares=41),
        21: GridRow(row_index=21, status="WORKING_BUY:121", has_y=False, sell_price=10.0, buy_price=9.0, shares=40),
        22: GridRow(row_index=22, status="WORKING_BUY:122", has_y=False, sell_price=10.0, buy_price=9.0, shares=39),
        23: GridRow(row_index=23, status="WORKING_BUY:123", has_y=False, sell_price=10.0, buy_price=9.0, shares=37),
        24: GridRow(row_index=24, status="IDLE", has_y=False, sell_price=10.0, buy_price=9.0, shares=36)
    })

    mock_sheet.fetch_grid.return_value = engine.grid_state

    # First tick: Stale orders missing
    mock_broker.get_open_orders.return_value = []
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 1251})

    from unittest.mock import patch, PropertyMock
    with patch('app.engine.grid_state.GridState.distal_y_row', new_callable=PropertyMock, return_value=20):
        await engine._tick()

    assert engine._halted_reconciliation is False
    assert mock_broker.place_limit_order.call_count == 0
    assert engine.grid_state.rows[17].status == "OWNED:0"
    assert engine.grid_state.rows[21].status == "IDLE"

    # Second tick: Orders get placed
    mock_broker.get_open_orders.return_value = []
    # simulate grid_state loaded correctly from first tick changes
    mock_sheet.fetch_grid.return_value = engine.grid_state

    # Needs to pass pre_sell_guard, meaning we need active open_orders to reflect the placed orders if they fill quickly,
    # but initially they are empty and broker_shares handles the calculation.

    with patch.object(engine, '_run_pre_sell_guard', wraps=engine._run_pre_sell_guard) as mock_guard:
        with patch('app.engine.grid_state.GridState.distal_y_row', new_callable=PropertyMock, return_value=20):
            await engine._tick()

            assert engine._halted_reconciliation is False
            assert mock_guard.call_count == 4 # rows 17, 18, 19, 20
            assert mock_broker.place_limit_order.call_count == 7 # 4 SELL, 3 BUY (21, 22, 23 within window of 20 - 3 to 20 + 3)
"""

    search_str = """async def test_remaining_qty_none_and_shares_match(engine, mock_broker, mock_sheet):"""

    content = content.replace(search_str, new_tests + search_str)

    with open(filepath, 'w') as f:
        f.write(content)

patch_file('tqqq_bot/tests/test_reconciliation.py')
patch_file('tqqq_bot_account_2/tests/test_reconciliation.py')

def patch_guard_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    search_str = """raw, adj, part, rem, invalid = _calculate_partial_fill_adjusted_required_shares(grid.rows, [], None)"""
    replace_str = """raw, adj, part, rem, invalid, missing = _calculate_partial_fill_adjusted_required_shares(grid.rows, [], None)"""

    content = content.replace(search_str, replace_str)

    with open(filepath, 'w') as f:
        f.write(content)

patch_guard_file('tqqq_bot/tests/test_pre_sell_guard.py')
patch_guard_file('tqqq_bot_account_2/tests/test_pre_sell_guard.py')
