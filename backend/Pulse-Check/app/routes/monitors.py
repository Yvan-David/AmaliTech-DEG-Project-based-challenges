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
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=MonitorResponse,
    summary="Register a monitor",
)
async def register_monitor(payload: MonitorCreate):
    """
    Create a new monitor and start its countdown timer.
    Returns 409 if the ID already exists in any state.
    """
    try:
        monitor = svc.register(payload)
    except svc.MonitorAlreadyExistsError as exc:
        m = exc.monitor
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"Monitor '{payload.id}' is already registered.",
                "hint": "Use a different ID, or DELETE this monitor first.",
                "existing_monitor": {
                    "id": m.id,
                    "status": m.status,
                    "alert_email": m.alert_email,
                    "webhook_url": m.webhook_url,
                    "timeout": m.timeout,
                    "created_at": m.created_at.isoformat(),
                    "alert_count": m.alert_count,
                },
            },
        )
    except svc.MonitorIsDownError as exc:
        m = exc.monitor
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"Monitor '{payload.id}' exists but is currently down.",
                "hint": f"Call POST /monitors/{payload.id}/reset to recover it without losing its history.",
                "existing_monitor": {
                    "id": m.id,
                    "status": m.status,
                    "alert_count": m.alert_count,
                    "alert_email": m.alert_email,
                },
            },
        )

    return MonitorResponse(
        message="Monitor registered. Countdown started.",
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
       
        existing = svc.get_one(monitor_id)
        if existing and existing.status == MonitorStatus.down:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": f"Monitor '{monitor_id}' is down.", "hint": f"Call POST /monitors/{monitor_id}/reset to recover it.", "alert_count": existing.alert_count,},
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


@router.get("/{monitor_id}", response_model=Monitor)
async def get_monitor(monitor_id: str):
    monitor = svc.get_one(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail=f"Monitor '{monitor_id}' not found.")

    ttl = svc.get_ttl(monitor_id)
    data = monitor.model_dump()
    data["seconds_remaining"] = max(ttl, 0)
    return data

async def get_monitor(monitor_id: str):
    """Fetch a specific monitor by ID. O(1) hash-map lookup."""
    monitor = svc.get_one(monitor_id)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )
    return monitor
    
@router.post(
    "/{monitor_id}/reset",
    response_model=MonitorResponse,
    summary="Reset a down monitor — brings it back online",
)
async def reset_monitor(monitor_id: str):
    """
    Recover a downed monitor without deleting and re-registering it.
    Clears the 'down' status and restarts the countdown timer.
    All configuration (email, webhook, timeout) is preserved.
    Only works on monitors with status 'down' — returns 409 for active/paused.
    """
    monitor = svc.get_one(monitor_id)

    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )

    if monitor.status != MonitorStatus.down:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"Monitor '{monitor_id}' is not down.",
                "current_status": monitor.status,
                "hint": "Reset is only for recovering a downed monitor.",
            },
        )

    recovered = svc.reset(monitor_id)
    return MonitorResponse(
        message="Monitor recovered. Countdown restarted. Awaiting first heartbeat.",
        monitor_id=recovered.id,
        status=recovered.status,
        expires_at=recovered.expires_at,
    )

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
