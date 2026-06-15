import re

with open("tqqq_bot/app/engine/engine.py", "r") as f:
    content = f.read()

replacement = """    async def _log_health_periodic(self):
        while not self._shutdown_event.is_set():
            try:
                # Use canonical account-scoped snapshot
                snapshot = await self.broker.get_verified_symbol_snapshot(TICKER)

                if snapshot.snapshot_status in ("PARTIAL", "UNAVAILABLE", "ACCOUNT_SCOPE_MISSING"):
                    if not self._snapshot_error_logged:
                        error_details = (
                            f"Account: {snapshot.account_id_masked}. "
                            f"Status: {snapshot.snapshot_status}. "
                            f"Error: {snapshot.snapshot_error}. "
                            "Health tab withholding values. "
                            f"Bot state: {'HALTED' if self._halted_reconciliation else 'RUNNING'}."
                        )
                        await self.sheet.log_error(
                            severity="ERROR",
                            code="POSITION_SNAPSHOT_UNAVAILABLE",
                            symbol=TICKER,
                            row="Health",
                            action="Health Check",
                            bot_status="HALTED_RECONCILIATION" if self._halted_reconciliation else "Running",
                            details=error_details
                        )
                        self._snapshot_error_logged = True
                elif snapshot.snapshot_status == "OK":
                    if self._snapshot_error_logged:
                        # Recovered
                        self._snapshot_error_logged = False

                if self._halted_reconciliation:
                    run_status = "HALTED_RECONCILIATION"
                else:
                    run_status = "Running (Mode=DRY_RUN)" if self.config.dry_run else "Running"

                # Calculate Tracker Expected Orders
                tracker_expected_ids = set(self.order_manager.get_tracked_order_ids())
                tracker_expected_count = len(tracker_expected_ids)

                broker_open_ids = set(str(o.get('order_id')) for o in snapshot.active_broker_orders)
                broker_open_count = len(broker_open_ids)

                unmatched_broker = set()
                missing_broker = set()

                # We replicate PR14 reconciliation strictness for Health matching
                # Check broker against tracker
                for o in snapshot.active_broker_orders:
                    oid = str(o.get('order_id'))
                    if oid in tracker_expected_ids:
                        continue

                    # Not in active tracking, check if it matches an untracked sheet state order STRICTLY
                    sheet_matched = False
                    if self.grid_state:
                        for row in self.grid_state.rows.values():
                            status_parts = row.status.split('|')
                            for part in status_parts:
                                if ':' in part:
                                    prefix, parsed_oid = part.split(':', 1)
                                    if parsed_oid == oid:
                                        # Match found
                                        expected_action = ""
                                        expected_qty = 0
                                        if prefix == "WORKING_BUY":
                                            expected_action = "BUY"
                                            expected_qty = row.shares
                                            if expected_action == o.get('action') and abs(expected_qty - o.get('qty', 0)) < 0.01 and abs(row.buy_price - o.get('limit_price', 0)) < 0.01:
                                                sheet_matched = True
                                        elif prefix == "WORKING_SELL":
                                            expected_action = "SELL"
                                            expected_qty = row.shares
                                            if expected_action == o.get('action') and abs(expected_qty - o.get('qty', 0)) < 0.01 and abs(row.sell_price - o.get('limit_price', 0)) < 0.01:
                                                sheet_matched = True
                                        elif prefix == "BRIDGE_BUY":
                                            # Bridge matches
                                            expected_action = "BUY"
                                            expected_qty = row.shares
                                            if expected_action == o.get('action') and abs(expected_qty - o.get('qty', 0)) < 0.01 and o.get('order_type') == "STP LMT":
                                                if abs(row.sell_price - o.get('aux_price', 0)) < 0.01 and abs(row.buy_price - o.get('limit_price', 0)) < 0.01:
                                                    sheet_matched = True
                    if not sheet_matched:
                        unmatched_broker.add(oid)

                # Find missing expected orders
                for tracker_id in tracker_expected_ids:
                    if tracker_id not in broker_open_ids:
                        missing_broker.add(tracker_id)

                # Check for Match Status.
                if len(unmatched_broker) == 0 and len(missing_broker) == 0:
                    order_match_status = "MATCH"
                elif len(unmatched_broker) > 0 and len(missing_broker) == 0:
                    order_match_status = "MISMATCH"
                elif len(missing_broker) > 0 and len(unmatched_broker) == 0:
                    order_match_status = "PARTIAL"
                else:
                    order_match_status = "MISMATCH"

                # Update Last fill time explicitly as requested
                if self.last_fill_time:
                    last_fill_str = self.last_fill_time.strftime("%Y-%m-%d %H:%M:%S")
                elif snapshot.position_qty is not None and snapshot.position_qty > 0:
                    last_fill_str = "Broker position exists; no bot buy fill found"
                else:
                    last_fill_str = "No bot fill found"

                health_data = {
                    "last_price": self.last_price,
                    "open_orders_count": snapshot.open_orders_count,
                    "last_fill_time": last_fill_str,
                    "status": run_status,
                    "position": snapshot.position_qty if snapshot.position_qty is not None else "",
                    "market_price": snapshot.market_price if snapshot.market_price is not None else "",
                    "market_value": snapshot.market_value if snapshot.market_value is not None else "",
                    "avg_cost": snapshot.avg_cost if snapshot.avg_cost is not None else "",
                    "net_liquidation_value": snapshot.net_liquidation if snapshot.net_liquidation is not None else "",
                    "configured_account": snapshot.account_id_masked,
                    "snapshot_status": snapshot.snapshot_status,
                    "snapshot_error": snapshot.snapshot_error,
                    "broker_open_orders": broker_open_count,
                    "tracker_expected_orders": tracker_expected_count,
                    "order_match_status": order_match_status,
                    "working_buy_qty": snapshot.working_buy_qty,
                    "working_sell_qty": snapshot.working_sell_qty,
                    "unmatched_broker_orders": ",".join(list(unmatched_broker)) if unmatched_broker else "",
                    "missing_broker_orders": ",".join(list(missing_broker)) if missing_broker else ""
                }

                success = await self.sheet.log_health(health_data)
                if success:
                    logger.info("Health status logged to Google Sheets")
            except Exception as e:
                logger.error(f"Failed to log health status: {e}")

            # Wait for interval or until shutdown
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.config.health_log_interval_seconds)
            except asyncio.TimeoutError:
                pass"""

pattern = re.compile(r"    async def _log_health_periodic\(self\):.*?            except asyncio\.TimeoutError:\n                pass", re.DOTALL)
new_content = pattern.sub(replacement, content)

with open("tqqq_bot/app/engine/engine.py", "w") as f:
    f.write(new_content)
