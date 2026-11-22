"""Set-ups for the Playwright end-to-end tests that the public API can't create.

An overstay needs a visit that entered hours ago, and the API (rightly) has no way to
backdate a visit. This script writes one straight into the database, then runs the real
escalation ladder, exactly as Celery Beat would, so the guard console receives the call
task over the WebSocket.

    cd backend && uv run python -m tests.e2e_fixtures overstay "Visitor Name"

Only for a local or CI test database: it changes data.
"""

import argparse
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select

from app.core import event_loop
from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.models import Flat, User, Visit, Visitor, VisitStatusChange
from app.models.enums import UserRole, VisitCategory, VisitStatus, VisitTrigger
from app.services import escalation


async def overstay(name: str, flat_label: str) -> None:
    settings = get_settings()
    block, number = flat_label.split("-")
    redis = Redis.from_url(settings.redis_url)
    async with SessionLocal() as db:
        flat = await db.scalar(select(Flat).where(Flat.block == block, Flat.number == number))
        guard = await db.scalar(select(User).where(User.role == UserRole.GUARD).limit(1))
        if flat is None or guard is None:
            raise SystemExit("Seed the database first: uv run python -m app.seed --reset")
        now = datetime.now(UTC)
        entered = now - timedelta(hours=2)
        visitor = Visitor(society_id=flat.society_id, full_name=name, phone="+919812300000")
        db.add(visitor)
        await db.flush()
        visit = Visit(
            id=uuid.uuid4(),
            society_id=flat.society_id,
            flat_id=flat.id,
            visitor_id=visitor.id,
            category=VisitCategory.CAB,
            purpose="Ola pickup",
            status=VisitStatus.INSIDE,
            registered_by_id=guard.id,
            entered_at=entered,
            expected_exit_at=entered + timedelta(minutes=10),
        )
        db.add(visit)
        await db.flush()
        db.add(
            VisitStatusChange(
                visit_id=visit.id,
                from_status=VisitStatus.APPROVED,
                to_status=VisitStatus.INSIDE,
                trigger=VisitTrigger.ENTER,
                changed_at=entered,
            )
        )
        await db.commit()
        # Each run moves every overdue visit one step at most; two runs reach the call task.
        for _ in range(3):
            await escalation.run_ladder(db, redis, settings, now=now)
        print(visit.id)
    await redis.aclose()
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    over = sub.add_parser("overstay", help="a visit 2 hours past entry, escalated to the guard")
    over.add_argument("name")
    over.add_argument("--flat", default="B-402")
    args = parser.parse_args()
    event_loop.run(overstay(args.name, args.flat))


if __name__ == "__main__":
    main()
