"""All version-1 routes, mounted under /api/v1 in main.py."""

from fastapi import APIRouter

from app.api.v1 import auth, flats, gates, guards, residents, vehicles, watchlist

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(flats.router)
api_router.include_router(residents.router)
api_router.include_router(vehicles.router)
api_router.include_router(guards.router)
api_router.include_router(gates.gates_router)
api_router.include_router(gates.devices_router)
api_router.include_router(watchlist.router)
