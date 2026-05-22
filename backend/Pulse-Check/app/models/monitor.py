from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class MonitorStatus(str, Enum):
    active = "active"
    paused = "paused"
    down = "down"


class MonitorCreate(BaseModel):
    id: str = Field(..., examples=["device-123"])
    timeout: int = Field(..., gt=0, examples=[60], description="Countdown duration in seconds")
    alert_email: str = Field(..., examples=["admin@critmon.com"])
    # Developer's Choice: optional webhook URL for real-time push alerts
    webhook_url: Optional[str] = Field(None, examples=["https://hooks.example.com/alert"])


class Monitor(BaseModel):
    id: str
    timeout: int
    alert_email: str
    webhook_url: Optional[str] = None
    status: MonitorStatus = MonitorStatus.active
    created_at: datetime
    expires_at: datetime
    last_heartbeat: Optional[datetime] = None
    # Tracks how many times this device has gone down — useful for maintenance history
    alert_count: int = 0


class MonitorResponse(BaseModel):
    message: str
    monitor_id: str
    status: MonitorStatus
    expires_at: datetime
