from dataclasses import dataclass
from typing import Dict

@dataclass
class GridRow:
    row_index: int
    status: str
    has_y: bool
    sell_price: float
    buy_price: float
    shares: int

@dataclass
class GridState:
    rows: Dict[int, GridRow]

    @property
    def distal_y_row(self) -> int:
        """Returns the highest row index where has_y == True (or 0 if none)."""
        y_rows = [row.row_index for row in self.rows.values() if row.has_y]
        return max(y_rows) if y_rows else 0
