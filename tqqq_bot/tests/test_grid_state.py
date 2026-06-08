from engine.grid_state import GridState, GridRow

def test_distal_y_row():
    rows = {
        7: GridRow(row_index=7, status="", has_y=True, sell_price=10.0, buy_price=9.0, shares=10),
        8: GridRow(row_index=8, status="", has_y=False, sell_price=11.0, buy_price=10.0, shares=10),
        9: GridRow(row_index=9, status="", has_y=True, sell_price=12.0, buy_price=11.0, shares=10),
        10: GridRow(row_index=10, status="", has_y=False, sell_price=13.0, buy_price=12.0, shares=10),
    }
    state = GridState(rows=rows)
    assert state.distal_y_row == 9

def test_distal_y_row_none():
    rows = {
        7: GridRow(row_index=7, status="", has_y=False, sell_price=10.0, buy_price=9.0, shares=10),
    }
    state = GridState(rows=rows)
    assert state.distal_y_row == 0
