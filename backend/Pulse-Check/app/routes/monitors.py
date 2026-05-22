from fastapi import APIRouter, HTTPException, status

from app.models.monitor import Monitor, MonitorCreate, MonitorResponse, MonitorStatus
from app.services import monitor_service as svc

router = APIRouter(prefix="/monitors", tags=["Monitors"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=MonitorResponse,
    summary="Register a monitor",
)
async def register_monitor(payload: MonitorCreate):
    """
    Create a new monitor or replace an existing one.
    Starts a countdown timer of `timeout` seconds immediately.
    """
    monitor, created = svc.register(payload)
    return MonitorResponse(
        message="Monitor registered." if created else "Monitor replaced and timer restarted.",
        monitor_id=monitor.id,
        status=monitor.status,
        expires_at=monitor.expires_at,
    )


@router.post(
    "/{monitor_id}/heartbeat",
    response_model=MonitorResponse,
    summary="Send a heartbeat — resets the countdown",
)
async def heartbeat(monitor_id: str):
    """
    Reset the countdown timer for the given monitor.
    Also un-pauses a paused monitor automatically.
    Returns 404 if the monitor does not exist or has already gone down.
    """
    monitor = svc.heartbeat(monitor_id)

    if monitor is None:
        # Distinguish between "never existed" and "went down" with a clear message
        existing = svc.get_one(monitor_id)
        if existing and existing.status == MonitorStatus.down:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Monitor '{monitor_id}' has already triggered a down alert. Re-register it with POST /monitors.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )

    return MonitorResponse(
        message="Heartbeat received. Timer reset.",
        monitor_id=monitor.id,
        status=monitor.status,
        expires_at=monitor.expires_at,
    )


@router.post(
    "/{monitor_id}/pause",
    response_model=MonitorResponse,
    summary="Pause a monitor — stops the countdown",
)
async def pause_monitor(monitor_id: str):
    """
    Freeze the countdown. No alert will fire while paused.
    Sending a heartbeat will automatically un-pause and restart the timer.
    """
    monitor = svc.pause(monitor_id)

    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )

    return MonitorResponse(
        message="Monitor paused." if monitor.status == MonitorStatus.paused else "Monitor is already paused.",
        monitor_id=monitor.id,
        status=monitor.status,
        expires_at=monitor.expires_at,
    )


@router.get(
    "",
    response_model=list[Monitor],
    summary="List all monitors — O(n)",
)
async def list_monitors():
    """Return every registered monitor. O(n) in the number of monitors."""
    return svc.get_all()


@router.get(
    "/{monitor_id}",
    response_model=Monitor,
    summary="Get a single monitor — O(1)",
)
async def get_monitor(monitor_id: str):
    """Fetch a specific monitor by ID. O(1) hash-map lookup."""
    monitor = svc.get_one(monitor_id)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )
    return monitor


@router.delete(
    "/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a monitor — O(1)",
)
async def delete_monitor(monitor_id: str):
    """Remove a monitor and cancel its countdown. O(1) hash-map delete."""
    deleted = svc.delete(monitor_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )
