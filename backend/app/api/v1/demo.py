from fastapi import APIRouter

from app.api.deps import AdminUser, AppSettings, DbSession
from app.schemas.analytics import DemoAccount, DemoInfo, DemoResetResult
from app.services import demo
from app.services.visitors import utcnow

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("", response_model=DemoInfo)
async def demo_info(settings: AppSettings) -> DemoInfo:
    """Public. In demo mode: the demo accounts and their shared password, for the landing
    page's one-click logins. Otherwise `enabled: false` and nothing else."""
    if not settings.demo_mode:
        return DemoInfo(enabled=False, password=None, accounts=[])
    return DemoInfo(
        enabled=True,
        password=settings.demo_password,
        accounts=[DemoAccount(role=r, email=e, name=n) for r, e, n in demo.ACCOUNTS],
    )


@router.post("/reset", response_model=DemoResetResult)
async def reset_demo(admin: AdminUser, db: DbSession, settings: AppSettings) -> DemoResetResult:
    """Admin, demo mode only (404 otherwise): wipe all data and seed it again, with two
    weeks of fresh history. Everyone is signed out."""
    summary = await demo.reset(db, settings, admin, now=utcnow())
    return DemoResetResult(
        flats=summary.flats,
        residents=summary.residents,
        vehicles=summary.vehicles,
        history_visits=summary.history_visits,
        history_gate_events=summary.history_gate_events,
    )
