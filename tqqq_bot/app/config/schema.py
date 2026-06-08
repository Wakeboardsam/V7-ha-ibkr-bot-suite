from typing import Optional
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    active_broker: str = Field(default="ibkr")
    paper_trading: bool = Field(default=True)
    ibkr_host: str = Field(default="127.0.0.1")
    ibkr_port: int = Field(default=7497)
    gateway_host: Optional[str] = Field(default=None)
    gateway_port: Optional[int] = Field(default=None)
    ibkr_client_id: int = Field(default=1)
    ibkr_account_id: Optional[str] = Field(default=None)
    mask_account_ids_in_logs: bool = Field(default=True)
    ibkr_username: Optional[str] = Field(default=None)
    ibkr_password: Optional[str] = Field(default=None)
    poll_interval_seconds: int = Field(default=60)
    heartbeat_interval_seconds: int = Field(default=60)
    health_log_interval_seconds: int = Field(default=300)
    anchor_buy_offset: float = Field(default=0.0)
    share_mismatch_mode: str = Field(default="halt")
    max_spread_pct: float = Field(default=0.5)
    google_sheet_id: str
    google_credentials_json: str
    enable_vnc: bool = Field(default=False)
    maintenance_enabled: bool = Field(default=True)
    maintenance_start_local: str = Field(default="23:44")
    maintenance_end_local: str = Field(default="00:00")
    maintenance_cancel_open_orders: bool = Field(default=True)
    enable_bridge_anchor: bool = Field(default=True)
    bridge_max_auto_trim_shares: int = Field(default=5)
