import asyncio
import logging
from typing import Optional, Callable
from datetime import datetime, timedelta
import os
import signal
from ib_insync import IB, Stock, Order, Trade, LimitOrder

from brokers.base import BrokerBase, OrderResult, PositionSnapshot, SymbolSnapshot
from brokers.ibkr.connection import async_connect
from brokers.ibkr.order_builder import build_bracket_order
from utils.log_sanitizer import mask_account_id, mask_account_ids_in_text

logger = logging.getLogger(__name__)


# INFO codes: farm connection OK or normal inactive state
IBKR_INFO_CODES = {2104, 2106, 2158, 2107, 2108, 1102}

# WARNING codes: temporary disconnects or degraded status
IBKR_WARNING_CODES = {2103, 2105, 1100, 1101, 2109, 10349}

# ERROR codes: explicit order failures and actionable codes
IBKR_ERROR_CODES = {10329}

def classify_ibkr_error(error_code: int, error_string: str) -> tuple[str, int]:
    if error_code in IBKR_INFO_CODES:
        return "IBKR status", logging.INFO
    elif error_code in IBKR_WARNING_CODES:
        return "IBKR warning", logging.WARNING
    elif error_code in IBKR_ERROR_CODES:
        return "IBKR order failure", logging.ERROR
    else:
        # Everything else defaults to ERROR
        return "IBKR API/order error", logging.ERROR

class IBKRAdapter(BrokerBase):
    def __init__(self, host: str, port: int, client_id: int, paper: bool, account_id: Optional[str] = None, mask_account_ids_in_logs: bool = True, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        self.host = host
        self.port = port
        self.client_id = client_id
        self.paper = paper
        self.account_id = account_id
        self.mask_account_ids_in_logs = mask_account_ids_in_logs
        self.ib = IB()
        self._on_update_callbacks: dict[str, Callable] = {}
        self._on_execution_callbacks: list[Callable] = []
        self._selected_cash_tag: Optional[str] = None
        self._last_error: dict[int, tuple[int, str]] = {}  # reqId -> (errorCode, errorString)
        self._disconnect_time: Optional[datetime] = None
        self._broker_state_ready = False
        self._connected_not_ready_since: Optional[datetime] = None
        self._degraded_reconnect_attempted: bool = False

        # Subscribe to order status and execution events
        self.ib.orderStatusEvent += self._on_order_status
        self.ib.execDetailsEvent += self._on_exec_details
        self.ib.errorEvent += self._on_error

    def _mask_account(self, acct: str) -> str:
        return mask_account_id(acct, enabled=self.mask_account_ids_in_logs)

    def _on_error(self, reqId, errorCode, errorString, contract):
        known_accts = [self.account_id] if self.account_id else []
        safe_error_string = mask_account_ids_in_text(errorString, known_account_ids=known_accts, enabled=self.mask_account_ids_in_logs)

        category, level = classify_ibkr_error(errorCode, safe_error_string)

        if level == logging.INFO:
            logger.info("%s %s: %s", category, errorCode, safe_error_string)
        elif level == logging.WARNING:
            logger.warning("%s %s: %s", category, errorCode, safe_error_string)
        else:
            logger.error("%s %s: %s", category, errorCode, safe_error_string)
            self._last_error[reqId] = (errorCode, safe_error_string)

    async def connect(self) -> bool:
        self._broker_state_ready = False
        connected = await async_connect(self.ib, self.host, self.port, self.client_id)
        if connected:
            self.ib.reqMarketDataType(3)
            self._connected_not_ready_since = datetime.now()
            self._degraded_reconnect_attempted = False
        return connected

    async def disconnect(self):
        self._broker_state_ready = False
        self._connected_not_ready_since = None
        self._degraded_reconnect_attempted = False
        self.ib.disconnect()

    async def is_connected(self) -> bool:
        return self.ib.isConnected()

    async def _check_broker_state_health(self):
        if self._broker_state_ready:
            return

        # Flag indicating if we successfully validated state
        is_state_valid = False

        if not self.ib.accountValues():
            # Missing account values
            logger.info("IBKR transport connected but accountValues is empty.")
        else:
            # Account values exist, but we must explicitly prove the connection isn't returning
            # an empty wrapper cache. reqPositionsAsync() forces a live fetch from the broker
            # and only completes when the positionEnd marker is received.
            try:
                await asyncio.wait_for(self.ib.reqPositionsAsync(), timeout=10.0)
                is_state_valid = True
            except Exception as e:
                logger.warning(f"Active positions fetch timed out or failed during health check: {e}. Sync is stuck.")

        if is_state_valid:
            # Successfully forced a live fetch and got account values
            self._broker_state_ready = True
            self._connected_not_ready_since = None
            self._degraded_reconnect_attempted = False
            logger.info("Broker state transitioned to READY (accountValues populated and positions synced).")
            return

        # Account not ready yet.
        if self._connected_not_ready_since is None:
            self._connected_not_ready_since = datetime.now()
            logger.info("Entering degraded recovery watchdog: account state not ready.")

        time_waiting = datetime.now() - self._connected_not_ready_since
        if time_waiting > timedelta(minutes=2):
            logger.warning(f"Degraded timeout exceeded: transport connected but account state not ready for {time_waiting}.")
            if not self._degraded_reconnect_attempted:
                logger.info("Attempting full IB object reset/reconnect due to degraded state...")

                try:
                    self.ib.disconnect()
                except Exception:
                    pass

                self.ib = IB()
                self._broker_state_ready = False
                self.ib.orderStatusEvent += self._on_order_status
                self.ib.execDetailsEvent += self._on_exec_details
                self.ib.errorEvent += self._on_error

                try:
                    connected = await async_connect(self.ib, self.host, self.port, self.client_id)
                    if connected:
                        logger.info("Degraded state recovery: successfully reconnected with fresh IB object. Giving account sync 2 minutes.")
                        self.ib.reqMarketDataType(3)
                        self._connected_not_ready_since = datetime.now()
                        self._degraded_reconnect_attempted = True
                    else:
                        logger.error("Degraded state recovery reconnect failed.")
                except Exception as e:
                    logger.error(f"Degraded state recovery reconnect exception: {e}")
            else:
                logger.critical("Degraded state watchdog: reconnect failed to restore account state. Triggering full container restart via SIGTERM to PID 1.")
                try:
                    os.kill(1, signal.SIGTERM)
                except Exception as e:
                    logger.error(f"Failed to send SIGTERM to PID 1: {e}")
                raise ConnectionError("Degraded state watchdog triggered container restart after failing to recover account state.")
        else:
            logger.info(f"Waiting for account sync (elapsed: {time_waiting})...")

    async def ensure_connected(self):
        if await self.is_connected():
            self._disconnect_time = None
            await self._check_broker_state_health()
            return

        self._broker_state_ready = False
        logger.warning("IBKR disconnected. Watchdog attempting reconnection...")

        if self._disconnect_time is None:
            self._disconnect_time = datetime.now()

        # Stage 1: Try to reconnect on the existing IB object
        logger.info("Stage 1: Disconnecting and reconnecting existing IB object...")
        try:
            self.ib.disconnect()
        except Exception as e:
            logger.debug(f"Error disconnecting existing IB object: {e}")

        # Clear cached state on the wrapper so we don't prematurely trigger readiness
        # based on stale values surviving the disconnect
        self.ib.wrapper.accountValues.clear()
        self.ib.wrapper.positions.clear()
        self.ib.wrapper.portfolio.clear()

        await asyncio.sleep(1) # Give socket a moment to clear

        try:
            await asyncio.wait_for(
                self.ib.connectAsync(self.host, self.port, clientId=self.client_id),
                timeout=30
            )
            if await self.is_connected():
                logger.info("Watchdog Stage 1 successfully reconnected.")
                self.ib.reqMarketDataType(3)
                self._disconnect_time = None
                self._connected_not_ready_since = datetime.now()
                self._degraded_reconnect_attempted = False
                return
        except Exception as e:
            logger.error(f"Stage 1 reconnect failed: {e}")

        # Stage 2: Fully recreate the IB object
        logger.info("Stage 2: Recreating IB object and attempting fresh connection...")
        try:
            self.ib.disconnect()
        except Exception:
            pass

        self.ib = IB()
        self._broker_state_ready = False
        self.ib.orderStatusEvent += self._on_order_status
        self.ib.execDetailsEvent += self._on_exec_details
        self.ib.errorEvent += self._on_error

        try:
            await asyncio.wait_for(
                self.ib.connectAsync(self.host, self.port, clientId=self.client_id),
                timeout=30
            )
            if await self.is_connected():
                logger.info("Watchdog Stage 2 successfully reconnected with fresh IB object.")
                self.ib.reqMarketDataType(3)
                self._disconnect_time = None
                self._connected_not_ready_since = datetime.now()
                self._degraded_reconnect_attempted = False
                return
        except Exception as e:
            logger.error(f"Stage 2 reconnect failed: {e}")

        # Stage 3: Check if we have been disconnected for > 15 minutes
        time_disconnected = datetime.now() - self._disconnect_time
        if time_disconnected > timedelta(minutes=15):
            logger.critical("Watchdog: IBKR disconnected for > 15 minutes. Triggering full container restart via SIGTERM to PID 1.")
            try:
                # PID 1 is usually supervisord or the init process in Docker
                os.kill(1, signal.SIGTERM)
            except Exception as e:
                logger.error(f"Failed to send SIGTERM to PID 1: {e}")
            raise ConnectionError("Watchdog triggered container restart after 15 minutes of downtime.")
        else:
            logger.warning(f"Watchdog reconnect failed. Disconnected for {time_disconnected}. Will try again on next engine tick.")
            raise ConnectionError("Watchdog failed to reconnect during this tick.")

    async def get_price(self, ticker: str) -> float:
        from brokers.ibkr.order_builder import get_dynamic_exchange
        exchange = get_dynamic_exchange()
        contract = Stock(ticker, exchange, 'USD', primaryExchange='NASDAQ')
        await self.ib.qualifyContractsAsync(contract)

        try:
            # Request market data
            ticker_data = self.ib.reqMktData(contract, '', False, False)
            logger.info(f"Raw price response: {ticker_data}")

            # Wait for price to be available
            await asyncio.sleep(2)

            if ticker_data.last > 0:
                return ticker_data.last
            if ticker_data.close > 0:
                return ticker_data.close

            logger.error("API call returned empty — possible Gateway auth or subscription issue")
            raise RuntimeError(f"Could not get price for {ticker}")
        except Exception as e:
            if not isinstance(e, RuntimeError):
                logger.error(f"Error fetching price: {e}")
            raise
        finally:
            self.ib.cancelMktData(contract)

    async def get_bid_ask(self, ticker: str) -> tuple[float, float]:
        from brokers.ibkr.order_builder import get_dynamic_exchange
        exchange = get_dynamic_exchange()
        contract = Stock(ticker, exchange, 'USD', primaryExchange='NASDAQ')
        await self.ib.qualifyContractsAsync(contract)
        ticker_data = self.ib.reqMktData(contract, '', False, False)

        try:
            for _ in range(50):
                if ticker_data.bid > 0 and ticker_data.ask > 0:
                    return ticker_data.bid, ticker_data.ask
                await asyncio.sleep(0.1)

            # Fallback to last/close prices if bid/ask is unavailable
            fallback_price = None
            if ticker_data.last > 0:
                fallback_price = ticker_data.last
            elif ticker_data.close > 0:
                fallback_price = ticker_data.close

            if fallback_price is not None:
                logger.warning(f"Bid/Ask unavailable for {ticker}, falling back to last/close price: {fallback_price}")
                return fallback_price, fallback_price

            logger.error("API call returned empty — possible Gateway auth or subscription issue")
            raise RuntimeError(f"Could not get bid/ask for {ticker}")
        except Exception as e:
            if not isinstance(e, RuntimeError):
                logger.error(f"Error fetching bid/ask: {e}")
            raise
        finally:
            self.ib.cancelMktData(contract)

    async def get_next_order_id(self) -> str:
        """
        Returns the next available order ID from IBKR.
        """
        return str(self.ib.client.getReqId())

    async def get_wallet_balance(self) -> float:
        """
        Returns the USD balance from the selected conservative account tag.
        """
        try:
            account_values = self.ib.accountValues()
            if self.account_id:
                account_values = [v for v in account_values if getattr(v, "account", None) == self.account_id]

            if not account_values:
                logger.error("API call returned empty — possible Gateway auth or subscription issue")
                return 0.0

            # Filter for USD only
            usd_values = [v for v in account_values if v.currency == 'USD']

            if not self._selected_cash_tag:
                # 1. Search for "Settled" (case-insensitive)
                settled_tag = next((v.tag for v in usd_values if "settled" in v.tag.lower()), None)
                if settled_tag:
                    self._selected_cash_tag = settled_tag
                else:
                    # 2. Fallback to confirmed tags
                    for fallback in ["TotalCashValue", "TotalCashBalance"]:
                        if any(v.tag == fallback for v in usd_values):
                            self._selected_cash_tag = fallback
                            break

                if self._selected_cash_tag:
                    logger.info(f"Selected IBKR cash field: {self._selected_cash_tag}")
                else:
                    available_tags = [v.tag for v in usd_values]
                    logger.warning(f"No preferred conservative cash tags found. Available USD tags: {available_tags}")
                    return 0.0

            # Retrieve value for the selected tag
            balance_entry = next((v for v in usd_values if v.tag == self._selected_cash_tag), None)
            if balance_entry:
                return float(balance_entry.value)

            return 0.0
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return 0.0

    async def get_net_liquidation_value(self) -> Optional[float]:
        """
        Returns Net Liquidation Value (NLV).

        Implementation detail:
        - Reads the 'NetLiquidation' tag from ib_insync's accountValues().
        - Prefers USD if present; otherwise falls back to BASE/blank currency or the first match.
        """
        try:
            account_values = self.ib.accountValues()
            if self.account_id:
                account_values = [v for v in account_values if getattr(v, "account", None) == self.account_id]

            if not account_values:
                logger.error("API call returned empty \u2014 possible Gateway auth or subscription issue")
                return None

            netliq_values = [v for v in account_values if getattr(v, "tag", None) == "NetLiquidation"]
            if not netliq_values:
                logger.warning("NetLiquidation not found in accountValues()")
                return None

            preferred = next((v for v in netliq_values if getattr(v, "currency", None) == "USD"), None)
            if preferred is None:
                preferred = next((v for v in netliq_values if getattr(v, "currency", None) in ("BASE", "")), None) or netliq_values[0]

            return float(preferred.value)

        except Exception as e:
            logger.error(f"Error fetching NetLiquidation: {e}")
            return None

    async def place_limit_order(
        self, ticker: str, action: str,
        qty: int, limit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None,
        order_id: Optional[str] = None
    ) -> OrderResult:
        self._check_account_safety_for_orders()

        if self.dry_run:
            logger.info(f"DRY RUN BLOCKED ORDER PLACE: limit action={action} ticker={ticker} qty={qty} limit={limit_price}")
            return OrderResult(
                order_id="DRY_RUN_NO_ORDER",
                status="dry_run_blocked",
                error_msg="DRY RUN: order was not submitted to broker"
            )


        from brokers.ibkr.order_builder import get_dynamic_exchange, get_dynamic_tif
        exchange = get_dynamic_exchange()
        tif = get_dynamic_tif(exchange)
        logger.info(f"Session mode: {exchange} / {tif}")
        contract = Stock(ticker, exchange, 'USD', primaryExchange='NASDAQ')
        await self.ib.qualifyContractsAsync(contract)

        order = LimitOrder(action, qty, limit_price)
        order.tif = tif
        order.outsideRth = False if exchange == 'OVERNIGHT' else True
        order.overridePercentageConstraints = True

        if self.account_id:
            order.account = self.account_id

        if order_id:
            order.orderId = int(order_id)
        else:
            # If no ID provided, let ib_insync assign one or get it now
            order.orderId = self.ib.client.getReqId()

        final_order_id = str(order.orderId)

        if on_update:
            self._on_update_callbacks[final_order_id] = on_update

        trade = self.ib.placeOrder(contract, order)

        # Wait for status to be 'Submitted', 'PreSubmitted', or terminal
        while not trade.isDone() and trade.orderStatus.status not in ('Submitted', 'PreSubmitted'):
            await asyncio.sleep(0.1)
            if order.orderId in self._last_error:
                err_code, err_msg = self._last_error[order.orderId]
                # If it's a known terminal error for the order
                if err_code == 10329:
                    return OrderResult(
                        order_id=final_order_id,
                        status='error',
                        error_code=err_code,
                        error_msg=err_msg
                    )

        status = trade.orderStatus.status
        if status in ('Submitted', 'PreSubmitted'):
            return OrderResult(order_id=final_order_id, status='submitted')
        elif status == 'Filled':
            return OrderResult(
                order_id=final_order_id,
                status='filled',
                filled_price=trade.orderStatus.avgFillPrice,
                filled_qty=trade.orderStatus.filled
            )
        else:
            err_code = None
            raw_err_msg = trade.orderStatus.whyHeld or f"Order failed with status: {status}"
            if order.orderId in self._last_error:
                err_code, raw_err_msg = self._last_error[order.orderId]

            known_accts = [self.account_id] if self.account_id else []
            safe_err_msg = mask_account_ids_in_text(raw_err_msg, known_account_ids=known_accts, enabled=self.mask_account_ids_in_logs) if raw_err_msg else None

            return OrderResult(
                order_id=final_order_id,
                status='error',
                error_code=err_code,
                error_msg=safe_err_msg,
                reason=status
            )

    async def place_stop_limit_order(
        self, ticker: str, action: str,
        qty: int, stop_price: float, limit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None,
        order_id: Optional[str] = None
    ) -> OrderResult:
        self._check_account_safety_for_orders()

        if self.dry_run:
            logger.info(f"DRY RUN BLOCKED ORDER PLACE: stop limit action={action} ticker={ticker} qty={qty} stop={stop_price} limit={limit_price}")
            return OrderResult(
                order_id="DRY_RUN_NO_ORDER",
                status="dry_run_blocked",
                error_msg="DRY RUN: order was not submitted to broker"
            )

        from brokers.ibkr.order_builder import get_dynamic_exchange, get_dynamic_tif
        from ib_insync import StopLimitOrder
        exchange = get_dynamic_exchange()
        tif = get_dynamic_tif(exchange)
        logger.info(f"Session mode: {exchange} / {tif} (Stop Limit)")
        contract = Stock(ticker, exchange, 'USD', primaryExchange='NASDAQ')
        await self.ib.qualifyContractsAsync(contract)

        order = StopLimitOrder(action, totalQuantity=qty, lmtPrice=limit_price, stopPrice=stop_price)
        order.tif = tif
        order.outsideRth = False if exchange == 'OVERNIGHT' else True
        order.overridePercentageConstraints = True

        if self.account_id:
            order.account = self.account_id

        if order_id:
            order.orderId = int(order_id)
        else:
            order.orderId = self.ib.client.getReqId()

        final_order_id = str(order.orderId)

        if on_update:
            self._on_update_callbacks[final_order_id] = on_update

        trade = self.ib.placeOrder(contract, order)

        while not trade.isDone() and trade.orderStatus.status not in ('Submitted', 'PreSubmitted'):
            await asyncio.sleep(0.1)
            if order.orderId in self._last_error:
                err_code, err_msg = self._last_error[order.orderId]
                if err_code == 10329:
                    return OrderResult(
                        order_id=final_order_id,
                        status='error',
                        error_code=err_code,
                        error_msg=err_msg
                    )

        status = trade.orderStatus.status
        if status in ('Submitted', 'PreSubmitted'):
            return OrderResult(order_id=final_order_id, status='submitted')
        elif status == 'Filled':
            return OrderResult(
                order_id=final_order_id,
                status='filled',
                filled_price=trade.orderStatus.avgFillPrice,
                filled_qty=trade.orderStatus.filled
            )
        else:
            err_code = None
            raw_err_msg = trade.orderStatus.whyHeld or f"Order failed with status: {status}"
            if order.orderId in self._last_error:
                err_code, raw_err_msg = self._last_error[order.orderId]

            known_accts = [self.account_id] if self.account_id else []
            safe_err_msg = mask_account_ids_in_text(raw_err_msg, known_account_ids=known_accts, enabled=self.mask_account_ids_in_logs) if raw_err_msg else None

            return OrderResult(
                order_id=final_order_id,
                status='error',
                error_code=err_code,
                error_msg=safe_err_msg,
                reason=status
            )

    def subscribe_to_updates(self, order_id: str, on_update: Callable):
        self._on_update_callbacks[order_id] = on_update

    def subscribe_to_executions(self, on_execution: Callable):
        if on_execution not in self._on_execution_callbacks:
            self._on_execution_callbacks.append(on_execution)

    def _check_account_safety_for_orders(self):
        if not self.account_id and not self.dry_run:
            logger.critical("No account_id is configured. Live trading operations are strictly disabled without an explicit account_id.")
            raise ValueError("No account_id configured for live trading.")

        accounts = list(set([v.account for v in self.ib.accountValues() if getattr(v, "account", None)]))
        if len(accounts) > 1:
            masked_accounts = [self._mask_account(a) for a in accounts]
            logger.info(f"Visible accounts: {', '.join(masked_accounts)}")
            if not self.account_id:
                logger.critical("Multiple accounts visible but no account_id is configured. Aborting order placement to prevent unsafe trading.")
                raise ValueError("Multiple accounts visible but no account_id configured.")

    async def place_bracket_order(
        self, ticker: str, action: str,
        qty: int, limit_price: float, profit_price: float,
        extended_hours: bool = True,
        on_update: Optional[Callable] = None
    ) -> OrderResult:
        self._check_account_safety_for_orders()

        if self.dry_run:
            logger.info(f"DRY RUN BLOCKED ORDER PLACE: bracket action={action} ticker={ticker} qty={qty} limit={limit_price} profit={profit_price}")
            return OrderResult(
                order_id="DRY_RUN_NO_ORDER",
                status="dry_run_blocked",
                error_msg="DRY RUN: order was not submitted to broker"
            )

        contract, parent, take_profit = build_bracket_order(
            self.ib, ticker, action, qty, limit_price, profit_price
        )

        if self.account_id:
            parent.account = self.account_id
            take_profit.account = self.account_id

        # Save callback for fills by orderId (both parent and TP)
        if on_update:
            self._on_update_callbacks[str(parent.orderId)] = on_update
            self._on_update_callbacks[str(take_profit.orderId)] = on_update

        # Ensure contract is qualified
        await self.ib.qualifyContractsAsync(contract)

        # Place parent order
        self.ib.placeOrder(contract, parent)
        # Place child order
        self.ib.placeOrder(contract, take_profit)

        return OrderResult(
            order_id=f"{parent.orderId}|{take_profit.orderId}",
            status='submitted'
        )

    async def cancel_order(self, order_id: str) -> bool:
        if not self.account_id and not self.dry_run:
            logger.critical("No account_id configured. Refusing to cancel order for live safety.")
            return False

        if self.dry_run:
            logger.info(f"DRY RUN BLOCKED ORDER CANCEL: order_id={order_id}")
            return False

        # Find the order
        for trade in self.ib.trades():
            if str(trade.order.orderId) == order_id:
                if self.account_id:
                    trade_account = getattr(trade.order, "account", None)
                    if trade_account != self.account_id:
                        logger.warning(f"Refusing to cancel order {order_id} because it belongs to account {self._mask_account(trade_account) if trade_account else 'None'}, expected {self._mask_account(self.account_id)}.")
                        return False
                self.ib.cancelOrder(trade.order)
                return True
        return False

    async def get_open_orders(self) -> list[dict]:
        orders = []
        for trade in self.ib.trades():
            if self.account_id:
                trade_account = getattr(trade.order, "account", None)
                if trade_account != self.account_id:
                    if trade_account is None:
                        logger.debug(f"get_open_orders: excluding order {trade.order.orderId} due to missing account_id")
                    continue

            if trade.isActive():
                orders.append({
                    'order_id': str(trade.order.orderId),
                    'ticker': trade.contract.symbol,
                    'action': trade.order.action,
                    'qty': trade.order.totalQuantity,
                    'limit_price': trade.order.lmtPrice,
                    'status': trade.orderStatus.status,
                    'aux_price': trade.order.auxPrice,
                    'order_type': trade.order.orderType,
                    'tif': trade.order.tif,
                    'exchange': trade.contract.exchange
                })
        return orders

    async def get_positions(self) -> dict[str, int]:
        positions = {}
        for pos in self.ib.positions():
            if self.account_id:
                pos_account = getattr(pos, "account", None)
                if pos_account != self.account_id:
                    continue
            positions[pos.contract.symbol] = int(pos.position)
        return positions

    async def get_position_snapshot(self) -> PositionSnapshot:
        if not self._broker_state_ready:
            return PositionSnapshot(is_ready=False, positions={})

        positions = await self.get_positions()
        return PositionSnapshot(is_ready=True, positions=positions)

    async def get_portfolio_item(self, ticker: str) -> Optional[dict]:
        """
        Returns a dictionary containing portfolio details for the ticker:
        position, marketPrice, marketValue, averageCost.
        """
        for item in self.ib.portfolio():
            if self.account_id:
                item_account = getattr(item, "account", None)
                if item_account != self.account_id:
                    continue

            if item.contract.symbol == ticker:
                return {
                    'position': item.position,
                    'marketPrice': item.marketPrice,
                    'marketValue': item.marketValue,
                    'averageCost': item.averageCost
                }
        return None

    async def get_verified_symbol_snapshot(self, symbol: str) -> SymbolSnapshot:
        if not self.account_id:
            return SymbolSnapshot(
                symbol=symbol,
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

        account_masked = self._mask_account(self.account_id)
        if not self._broker_state_ready:
            return SymbolSnapshot(
                symbol=symbol,
                account_id_masked=account_masked,
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
                snapshot_error="Broker connection state is not ready or valid"
            )

        try:
            # Gather all necessary data
            portfolio_item = await self.get_portfolio_item(symbol)
            all_open_orders = await self.get_open_orders()

            # Use best-effort for net liquidation and cash so we don't fail the snapshot if they fail
            net_liq = None
            cash = None
            try:
                net_liq = await self.get_net_liquidation_value()
            except Exception as e:
                logger.warning(f"Failed to fetch net liquidation value for snapshot: {e}")

            try:
                cash = await self.get_wallet_balance()
            except Exception as e:
                logger.warning(f"Failed to fetch cash for snapshot: {e}")

            # Open orders are already filtered by account ID in get_open_orders
            active_broker_orders = [o for o in all_open_orders if o.get('ticker') == symbol]

            working_buy_qty = sum(o.get('qty', 0) for o in active_broker_orders if o.get('action') == 'BUY')
            working_sell_qty = sum(o.get('qty', 0) for o in active_broker_orders if o.get('action') == 'SELL')

            if portfolio_item is not None:
                position_qty = int(portfolio_item['position'])
                market_price = portfolio_item['marketPrice']
                market_value = portfolio_item['marketValue']
                avg_cost = portfolio_item['averageCost']
            else:
                # If portfolio fetch succeeds but symbol is missing, we consider position 0
                position_qty = 0
                market_price = None
                market_value = None
                avg_cost = None

            return SymbolSnapshot(
                symbol=symbol,
                account_id_masked=account_masked,
                position_qty=position_qty,
                market_price=market_price,
                market_value=market_value,
                avg_cost=avg_cost,
                net_liquidation=net_liq,
                cash=cash,
                open_orders_count=len(active_broker_orders),
                working_buy_qty=working_buy_qty,
                working_sell_qty=working_sell_qty,
                active_broker_orders=active_broker_orders,
                snapshot_status="OK",
                snapshot_error=""
            )

        except Exception as e:
            logger.error(f"Error fetching position snapshot for {symbol}: {e}")
            return SymbolSnapshot(
                symbol=symbol,
                account_id_masked=account_masked,
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
                snapshot_status="PARTIAL",
                snapshot_error=f"Exception during snapshot fetch: {str(e)}"
            )

    def _on_exec_details(self, trade: Trade, fill):
        """
        Handles execution events from IBKR.
        """
        try:
            execution = fill.execution
            if self.account_id:
                exec_account = getattr(execution, "acctNumber", None)
                if exec_account != self.account_id:
                    if exec_account is None:
                        logger.debug(f"_on_exec_details: ignoring fill for unknown account, expected {self._mask_account(self.account_id)}")
                    return

            side_map = {
                'BOT': 'BUY',
                'SLD': 'SELL'
            }
            action = side_map.get(execution.side, execution.side)

            exec_data = {
                "exec_id": getattr(execution, "execId", ""),
                "order_id": str(getattr(execution, "orderId", "")),
                "perm_id": str(getattr(execution, "permId", "")),
                "symbol": getattr(trade.contract, "symbol", ""),
                "type": action,
                "filled_qty": int(getattr(execution, "shares", 0)),
                "filled_price": float(getattr(execution, "price", 0.0)),
                "order_type": getattr(trade.order, "orderType", None),
                "tif": getattr(trade.order, "tif", None),
                "aux_price": getattr(trade.order, "auxPrice", None),
                "limit_price": getattr(trade.order, "lmtPrice", None),
                "exchange": getattr(trade.contract, "exchange", None),
                "action": getattr(trade.order, "action", None)
            }

            for callback in self._on_execution_callbacks:
                callback(exec_data)

        except Exception as e:
            logger.error(f"Error processing execution details: {e}")

    def _on_order_status(self, trade: Trade):
        status = trade.orderStatus.status
        order_id = str(trade.order.orderId)

        if self.account_id:
            trade_account = getattr(trade.order, "account", None)
            if trade_account != self.account_id:
                if trade_account is None:
                    logger.debug(f"_on_order_status: ignoring status update for order {order_id} (missing account), expected {self._mask_account(self.account_id)}")
                return

        callback = self._on_update_callbacks.get(order_id)

        known_accts = [self.account_id] if self.account_id else []

        unified_status = None
        if status in ('Submitted', 'PreSubmitted'):
            unified_status = 'submitted'
        elif status == 'Filled':
            unified_status = 'filled'
        elif status in ('Cancelled', 'Inactive', 'Rejected'):
            unified_status = 'cancelled' if status == 'Cancelled' else 'error'

            # LOUD ALERT for terminal failures
            raw_reason = trade.orderStatus.whyHeld or "No reason provided"
            err_code = None
            if trade.order.orderId in self._last_error:
                err_code, err_msg = self._last_error[trade.order.orderId]
                raw_reason = f"{err_msg} (Code: {err_code})"

            safe_reason = mask_account_ids_in_text(raw_reason, known_account_ids=known_accts, enabled=self.mask_account_ids_in_logs)

            logger.warning(
                f"\n"
                f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                f"LOUD ALERT: ORDER {order_id} {status.upper()}!\n"
                f"Ticker: {trade.contract.symbol}\n"
                f"Action: {trade.order.action}\n"
                f"Reason: {safe_reason}\n"
                f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            )

        if callback and unified_status:
            err_code = None
            raw_err_msg = trade.orderStatus.whyHeld
            if trade.order.orderId in self._last_error:
                err_code, raw_err_msg = self._last_error[trade.order.orderId]

            safe_err_msg = mask_account_ids_in_text(raw_err_msg, known_account_ids=known_accts, enabled=self.mask_account_ids_in_logs) if raw_err_msg else None

            result = OrderResult(
                order_id=order_id,
                status=unified_status,
                filled_price=trade.orderStatus.avgFillPrice if status == 'Filled' else None,
                filled_qty=trade.orderStatus.filled if status == 'Filled' else None,
                error_msg=safe_err_msg,
                error_code=err_code,
                reason=status
            )
            callback(result)
            logger.info(f"Update callback called for order {order_id} status {status}")
