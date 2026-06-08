import logging
from typing import Dict, Set, Tuple, List, Optional, Any, Callable
from brokers.base import OrderResult

logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self):
        # Mapping of row_index to set of active order_ids (parent and child)
        self._row_to_orders: Dict[Any, Set[str]] = {}
        # Mapping of order_id to (row_index, action)
        self._order_map: Dict[str, Tuple[Any, str]] = {}
        # Mapping of row_index to action ('BUY' or 'SELL'). Kept for backwards compatibility.
        self._row_actions: Dict[Any, str] = {}

    def track(self, row_index: Any, order_result: OrderResult, action: str = None,
              broker: Optional[Any] = None, on_update: Optional[Callable] = None):
        """
        Track one or more orders for a grid row.
        order_result.order_id can be a single ID or multiple IDs separated by '|'.
        If broker and on_update are provided, subscribes to updates for each order.
        """
        if action:
            final_action = action.upper()
            if final_action in ('BUY', 'SELL'):
                self._row_actions[row_index] = final_action
        else:
            final_action = self._row_actions.get(row_index, "UNKNOWN")

        order_ids = order_result.order_id.split('|')

        if row_index not in self._row_to_orders:
            self._row_to_orders[row_index] = set()

        for oid in order_ids:
            self._row_to_orders[row_index].add(oid)
            self._order_map[oid] = (row_index, final_action)
            if broker and on_update:
                broker.subscribe_to_updates(oid, on_update)

        logger.info(f"Tracking {final_action} row {row_index} with order(s): {order_ids}")

    def has_open_buy(self, row_index: Any) -> bool:
        return self.has_open_action(row_index, 'BUY')

    def has_open_sell(self, row_index: Any) -> bool:
        return self.has_open_action(row_index, 'SELL')

    def has_open_action(self, row_index: Any, target_action: str) -> bool:
        if row_index not in self._row_to_orders: return False
        for oid in self._row_to_orders[row_index]:
            if self._order_map.get(oid, (None, None))[1] == target_action.upper():
                return True
        return False

    def get_order_ids_for_action(self, row_index: Any, target_action: str) -> List[str]:
        if row_index not in self._row_to_orders: return []
        return [oid for oid in self._row_to_orders[row_index] if self._order_map.get(oid, (None, None))[1] == target_action.upper()]

    def clear_action_for_row(self, row_index: Any, target_action: str) -> List[str]:
        """
        Clears all tracking for orders matching the target action on the given row.
        Returns the list of order_ids that were removed.
        """
        removed = []
        if row_index not in self._row_to_orders:
            return removed

        oids_to_remove = [oid for oid in self._row_to_orders[row_index] if self._order_map.get(oid, (None, None))[1] == target_action.upper()]
        for oid in oids_to_remove:
            self._row_to_orders[row_index].discard(oid)
            self._order_map.pop(oid, None)
            removed.append(oid)

        if not self._row_to_orders[row_index]:
            del self._row_to_orders[row_index]

        return removed
    def mark_filled(self, order_id: str) -> Tuple[Optional[Any], Optional[str]]:
        return self._remove_order(order_id, "filled")

    def mark_cancelled(self, order_id: str) -> Tuple[Optional[Any], Optional[str]]:
        return self._remove_order(order_id, "cancelled")

    def _remove_order(self, order_id: str, reason: str) -> Tuple[Optional[Any], Optional[str]]:
        if order_id in self._order_map:
            row_index, action = self._order_map.pop(order_id)
            if row_index in self._row_to_orders:
                self._row_to_orders[row_index].discard(order_id)
                if not self._row_to_orders[row_index]:
                    # All orders for this row are gone (either filled or cancelled)
                    del self._row_to_orders[row_index]
                    logger.info(f"Row {row_index} is now clear (last order {order_id} was {reason})")
                else:
                    logger.info(f"Order {order_id} for row {row_index} was {reason}. Remaining orders for row: {self._row_to_orders[row_index]}")
            return row_index, action
        return None, None

    def get_tracked_order_ids(self) -> List[str]:
        return list(self._order_map.keys())

    def is_tracked(self, order_id: str) -> bool:
        return order_id in self._order_map

    def get_row_and_action(self, order_id: str) -> Tuple[Optional[Any], Optional[str]]:
        if order_id in self._order_map:
            return self._order_map[order_id]
        return None, None
