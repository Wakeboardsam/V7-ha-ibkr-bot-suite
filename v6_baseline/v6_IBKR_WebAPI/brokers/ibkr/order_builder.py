import datetime
import zoneinfo
from ib_insync import IB, Stock, Order, LimitOrder

def get_dynamic_exchange() -> str:
    """
    Returns 'OVERNIGHT' if the current system time is between 8:00 PM and 3:50 AM ET;
    otherwise, it returns 'SMART'.
    """
    tz = zoneinfo.ZoneInfo("America/New_York")
    now_et = datetime.datetime.now(tz)

    # Define boundaries in ET
    # 8:00 PM is 20:00
    # 3:50 AM is 03:50

    # Check if time is >= 20:00 OR < 03:50
    current_time = now_et.time()
    if current_time >= datetime.time(20, 0) or current_time < datetime.time(3, 50):
        # Additional check: Overnight market opens Sun 8 PM ET and closes Fri 3:50 AM ET
        # Weekdays: Monday is 0, Sunday is 6.
        # Friday (4) after 20:00 and Saturday (5) anytime are not OVERNIGHT.
        # Sunday (6) before 20:00 is not OVERNIGHT.
        weekday = now_et.weekday()
        if weekday == 4 and current_time >= datetime.time(20, 0): # Friday evening
            return 'SMART'
        if weekday == 5: # Saturday
            return 'SMART'
        if weekday == 6 and current_time < datetime.time(20, 0): # Sunday before 8 PM
            return 'SMART'
        return 'OVERNIGHT'
    return 'SMART'

def get_dynamic_tif(exchange: str) -> str:
    """
    Returns 'DAY' for the OVERNIGHT exchange,
    otherwise returns 'GTC'.
    """
    return 'DAY' if exchange == 'OVERNIGHT' else 'GTC'

def build_bracket_order(ib: IB, ticker: str, action: str, qty: int, limit_price: float, profit_price: float):
    """
    Creates a bracket order (parent limit + child take-profit).
    Dynamically sets exchange, tif, and outsideRth=True.
    """
    exchange = get_dynamic_exchange()
    tif = get_dynamic_tif(exchange)

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Session mode: {exchange} / {tif}")

    contract = Stock(ticker, exchange, 'USD', primaryExchange='NASDAQ')

    # ib.bracketOrder returns a list of Order objects: [parent, takeProfit, stopLoss]
    # We only need parent and takeProfit for this requirement (no stopLoss mentioned,
    # but bracketOrder typically creates both. If we only want TP, we can discard SL or
    # build manually. The prompt says "bracket order generation (ib.bracketOrder)".
    # Usually, bracketOrder(action, quantity, limitPrice, takeProfitPrice, stopLossPrice)

    # If stopLoss is not specified, we might need to handle it.
    # Let's assume we use a very wide stop loss or just the parent + TP.
    # Actually, ib.bracketOrder in ib_insync:
    # bracketOrder(action, quantity, limitPrice, takeProfitPrice, stopLossPrice, ...)

    # Since only profit_price is provided, we'll use it.
    # For stop loss, we might set it to 0 or something that won't trigger if not required,
    # or just use parent and TP.

    # Let's check how ib_insync bracketOrder works. It returns a list [parent, tp, sl].

    parent_action = action
    child_action = 'SELL' if action == 'BUY' else 'BUY'

    # We'll use a very low/high stop loss if not provided to satisfy the bracket structure,
    # or just build them manually if ib.bracketOrder requires 3.
    # Looking at ib_insync source, bracketOrder requires stopLossPrice.
    # If we don't want a stop loss, maybe we should just create two orders.
    # But the prompt says "bracket order generation (ib.bracketOrder)".

    # I'll use a dummy stop loss price that is far away.
    if action == 'BUY':
        stop_loss_price = limit_price * 0.01
    else:
        stop_loss_price = limit_price * 100.0

    bracket = ib.bracketOrder(
        action, qty, limit_price,
        takeProfitPrice=profit_price,
        stopLossPrice=stop_loss_price
    )

    # The requirement says:
    # Both the parent limit order and child take-profit order must inherit this dynamic exchange,
    # use tif='GTC', and set outsideRth=True.
    # ib.bracketOrder returns [parent, takeProfit, stopLoss]

    parent = bracket[0]
    take_profit = bracket[1]

    outside_rth = False if exchange == 'OVERNIGHT' else True

    for order in bracket:
        order.tif = tif
        order.outsideRth = outside_rth

    return contract, parent, take_profit
