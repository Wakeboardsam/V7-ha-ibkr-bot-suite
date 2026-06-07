import gspread
import asyncio
import json
import re
import logging
from datetime import datetime
from typing import Any
from google.oauth2.service_account import Credentials
from config.schema import AppConfig
from engine.grid_state import GridState, GridRow
from sheets.schema import (
    GRID_TAB_NAME, FILLS_TAB_NAME, HEALTH_TAB_NAME, ERRORS_TAB_NAME,
    COL_STATUS, COL_STRATEGY, COL_SELL_PRICE, COL_BUY_PRICE, COL_SHARES,
    ROW_HEARTBEAT, COL_HEARTBEAT, ROW_CASH, COL_CASH, ROW_ANCHOR_ASK, COL_ANCHOR_ASK,
    GRID_START_ROW, GRID_END_ROW,
    FILLS_HEADERS, HEALTH_HEADERS, ERRORS_HEADERS
)

logger = logging.getLogger(__name__)

class SheetInterface:
    def __init__(self, config: AppConfig):
        self.config = config
        self.scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        self._creds = Credentials.from_service_account_info(
            json.loads(config.google_credentials_json),
            scopes=self.scopes
        )
        self._client = gspread.authorize(self._creds)
        self._sheet = self._client.open_by_key(config.google_sheet_id)
        self._verified_tabs = set()
        self._seen_exec_ids = set()
        self._fill_queue = asyncio.Queue()
        self._worker_task = None

    def _parse_numeric(self, value: str) -> float:
        """
        Safely parses Google Sheets formatted numbers.
        Strips accounting formatting, commas, currency symbols, and handles errors like #DIV/0!.
        """
        val = str(value).strip()
        if not val or val.startswith('#') or val in ('-', '$ -'):
            return 0.0

        # Remove all non-numeric characters EXCEPT period (.) and minus (-)
        clean_val = re.sub(r'[^\d.-]', '', val)

        # Handle cases where stripping leaves us with nothing valid
        if not clean_val or clean_val in ('-', '.', '-.'):
            return 0.0

        try:
            return float(clean_val)
        except ValueError:
            return 0.0

    async def fetch_grid(self) -> GridState:
        """Reads cols C through H (rows 7 to 100) and returns GridState."""
        data = await asyncio.to_thread(self._get_grid_range)

        rows = {}
        # Start row in sheet is 7. Data starts at row index 0.
        for i, row_values in enumerate(data):
            row_index = 7 + i

            # Pad row_values to length 6 if gspread truncates trailing empty cells
            row_values = row_values + [''] * max(0, 6 - len(row_values))

            try:
                status = str(row_values[0]).strip() if row_values[0] else "IDLE"
                has_y = str(row_values[1]).strip().upper() == "Y"
                # row_values[2] is Column E (empty or notes in legacy)

                # Use robust parsing for numeric fields to handle formatted accounting cells
                sell_price = self._parse_numeric(row_values[3])
                buy_price = self._parse_numeric(row_values[4])
                shares = int(self._parse_numeric(row_values[5]))

                rows[row_index] = GridRow(
                    row_index=row_index,
                    status=status,
                    has_y=has_y,
                    sell_price=sell_price,
                    buy_price=buy_price,
                    shares=shares
                )
            except Exception as e:
                logger.debug(f"Skipping malformed row {row_index}: {e}")
                continue

        return GridState(rows=rows)

    def _get_grid_range(self):
        worksheet = self._sheet.worksheet(GRID_TAB_NAME)
        # C7:H100 range. get_values is 0-indexed for the result, but gspread range is 1-indexed.
        # Column C is 3, Column H is 8.
        return worksheet.get_values("C7:H100")

    async def update_row_status(self, row_index: int, status: str):
        """Writes exclusively to Column C for the given row index."""
        await asyncio.to_thread(self._update_cell_with_guard, GRID_TAB_NAME, row_index, COL_STATUS, status)

    async def write_heartbeat(self, value: str):
        """Writes heartbeat to C1."""
        await asyncio.to_thread(self._update_cell_with_guard, GRID_TAB_NAME, ROW_HEARTBEAT, COL_HEARTBEAT, value)

    async def write_cash_value(self, value: float):
        """Writes cash value to C2."""
        await asyncio.to_thread(self._update_cell_with_guard, GRID_TAB_NAME, ROW_CASH, COL_CASH, value)

    async def write_anchor_ask(self, value: float):
        """Writes anchor ask price to G7."""
        await asyncio.to_thread(self._update_cell_with_guard, GRID_TAB_NAME, ROW_ANCHOR_ASK, COL_ANCHOR_ASK, value)

    def _update_cell_with_guard(self, worksheet_name: str, row: int, col: int, value: Any):
        """Guarded write method to ensure only approved cells/tabs are modified."""
        if worksheet_name == GRID_TAB_NAME:
            # Check special cells
            is_special = (
                (row == ROW_HEARTBEAT and col == COL_HEARTBEAT) or
                (row == ROW_CASH and col == COL_CASH) or
                (row == ROW_ANCHOR_ASK and col == COL_ANCHOR_ASK)
            )
            # Check grid status column
            is_grid_status = (GRID_START_ROW <= row <= GRID_END_ROW and col == COL_STATUS)

            if not (is_special or is_grid_status):
                raise ValueError(f"Unauthorized write attempt to {worksheet_name} at cell ({row}, {col})")
        elif worksheet_name in [FILLS_TAB_NAME, HEALTH_TAB_NAME, ERRORS_TAB_NAME]:
            raise ValueError(f"Use append_row for {worksheet_name}, not update_cell")
        else:
            raise ValueError(f"Unauthorized worksheet: {worksheet_name}")

        worksheet = self._sheet.worksheet(worksheet_name)
        worksheet.update_cell(row, col, value)

    async def log_fill(self, fill_data: dict) -> bool:
        """Queues the fill data for background logging."""
        try:
            await self._fill_queue.put(fill_data)
            return True
        except Exception as e:
            logger.error(f"Failed to queue fill logging: {e}")
            return False

    async def log_error(self, error_msg: str) -> bool:
        logger.error(f"BOT ERROR: {error_msg}")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            await asyncio.to_thread(self._append_row_with_guard, ERRORS_TAB_NAME, [timestamp, error_msg], ERRORS_HEADERS)
            return True
        except Exception as e:
            logger.error(f"Failed to log error to sheet: {e}")
            return False

    async def log_health(self, health_data: dict) -> bool:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # TIMESTAMP, LAST_PRICE, OPEN_ORDERS_COUNT, LAST_FILL_TIME, STATUS, POSITION, MARKET_PRICE, MARKET_VALUE, AVG_COST, NET_LIQUIDATION_VALUE
        row = [
            timestamp,
            health_data.get("last_price"),
            health_data.get("open_orders_count"),
            health_data.get("last_fill_time"),
            health_data.get("status"),
            health_data.get("position"),
            health_data.get("market_price"),
            health_data.get("market_value"),
            health_data.get("avg_cost"),
            health_data.get("net_liquidation_value")
        ]

        try:
            await asyncio.to_thread(self._append_row_with_guard, HEALTH_TAB_NAME, row, HEALTH_HEADERS)
            return True
        except Exception as e:
            logger.error(f"Failed to log health status: {e}")
            return False

    def _append_row_with_guard(self, worksheet_name: str, row_data: list, expected_headers: list = None):
        """Guarded append method to ensure only approved tabs are appended to."""
        if worksheet_name not in [FILLS_TAB_NAME, HEALTH_TAB_NAME, ERRORS_TAB_NAME]:
            raise ValueError(f"Unauthorized append attempt to {worksheet_name}")

        try:
            worksheet = self._sheet.worksheet(worksheet_name)

            if worksheet_name not in self._verified_tabs:
                # Check if empty (no headers)
                first_cell = worksheet.get_values("A1:A1")
                if not first_cell and expected_headers:
                    worksheet.append_row(expected_headers)
                self._verified_tabs.add(worksheet_name)

            worksheet.append_row(row_data)
        except gspread.exceptions.WorksheetNotFound:
            logger.error(f"Worksheet '{worksheet_name}' not found in the spreadsheet.")
            raise

    async def load_recent_exec_ids(self, limit: int = 50):
        """Loads recent EXEC_IDs from the Fills tab to prepopulate the deduplication set."""
        try:
            worksheet = await asyncio.to_thread(self._sheet.worksheet, FILLS_TAB_NAME)

            # Fetch all values to safely find the EXEC_ID column index and get last N rows
            all_values = await asyncio.to_thread(worksheet.get_all_values)
            if not all_values or len(all_values) <= 1:
                logger.info("Fills tab is empty or only has headers. No recent exec_ids loaded.")
                return

            headers = all_values[0]
            try:
                exec_id_idx = headers.index("EXEC_ID")
            except ValueError:
                logger.warning("'EXEC_ID' column not found in Fills tab. Cannot load recent exec_ids.")
                return

            recent_rows = all_values[-(limit):]
            loaded_count = 0
            for row in recent_rows:
                if len(row) > exec_id_idx:
                    exec_id = row[exec_id_idx].strip()
                    if exec_id and exec_id != "EXEC_ID":
                        self._seen_exec_ids.add(exec_id)
                        loaded_count += 1

            logger.info(f"Loaded {loaded_count} recent exec_ids from Fills tab for deduplication.")

        except gspread.exceptions.WorksheetNotFound:
            logger.info("Fills tab not found yet. Skipping recent exec_ids load.")
        except Exception as e:
            logger.error(f"Failed to load recent exec_ids: {e}")

    def is_exec_id_seen(self, exec_id: str) -> bool:
        return exec_id in self._seen_exec_ids

    def mark_exec_id_seen(self, exec_id: str):
        self._seen_exec_ids.add(exec_id)

    def unmark_exec_id_seen(self, exec_id: str):
        self._seen_exec_ids.discard(exec_id)

    async def start_fill_worker(self):
        """Starts the background worker to process the fill logging queue."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._process_fill_queue())

    async def stop_fill_worker(self):
        """Stops the background worker after draining the queue."""
        if self._worker_task and not self._worker_task.done():
            # Wait for all queued items to be processed
            await self._fill_queue.join()
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def _process_fill_queue(self):
        """Background worker loop to append fills to the Google Sheet with backoff retries."""
        logger.info("Started background fill logging worker.")
        while True:
            try:
                fill_data = await self._fill_queue.get()

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # TIMESTAMP, EXEC_ID, ROW_ID, TYPE, FILLED_PRICE, FILLED_QTY, ORDER_ID, PERM_ID, SYMBOL
                row = [
                    timestamp,
                    fill_data.get("exec_id", ""),
                    fill_data.get("row_id", ""),
                    fill_data.get("type", ""),
                    fill_data.get("filled_price", ""),
                    fill_data.get("filled_qty", ""),
                    fill_data.get("order_id", ""),
                    fill_data.get("perm_id", ""),
                    fill_data.get("symbol", "")
                ]

                max_retries = 3
                retry_delay = 2
                success = False

                for attempt in range(max_retries):
                    try:
                        await asyncio.to_thread(self._append_row_with_guard, FILLS_TAB_NAME, row, FILLS_HEADERS)
                        success = True
                        break
                    except Exception as e:
                        logger.warning(f"Failed to append fill to sheet (attempt {attempt + 1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff

                if not success:
                    logger.error(f"Permanently failed to append fill to sheet after {max_retries} attempts: {row}")
                    # Unmark the exec_id so it can be retried if the event comes again
                    exec_id = fill_data.get("exec_id")
                    if exec_id:
                        self.unmark_exec_id_seen(exec_id)
                else:
                    logger.info(f"Successfully logged execution {fill_data.get('exec_id')} to Fills tab.")

                self._fill_queue.task_done()

            except asyncio.CancelledError:
                logger.info("Fill logging worker cancelled.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in fill logging worker: {e}", exc_info=True)
                await asyncio.sleep(5) # Prevent tight loop on unexpected errors
