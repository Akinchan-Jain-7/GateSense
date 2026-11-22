"""All version-1 routes, mounted under /api/v1 in main.py."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    approvals,
    auth,
    escalations,
    flats,
    gate_events,
    gates,
    guards,
    guest_passes,
    notifications,
    realtime,
    residents,
    settings,
    telegram,
    vehicles,
    visits,
    watchlist,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(flats.router)
api_router.include_router(residents.router)
api_router.include_router(vehicles.router)
api_router.include_router(guards.router)
api_router.include_router(gates.gates_router)
api_router.include_router(gates.devices_router)
api_router.include_router(watchlist.router)
api_router.include_router(gate_events.router)
api_router.include_router(alerts.router)
api_router.include_router(visits.router)
api_router.include_router(approvals.router)
api_router.include_router(guest_passes.router)
api_router.include_router(settings.router)
api_router.include_router(telegram.router)
api_router.include_router(realtime.router)
api_router.include_router(escalations.router)
api_router.include_router(notifications.router)
