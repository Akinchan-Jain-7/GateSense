"""Create a real society and its first admin, on an empty database (self-hosting).

    docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm -it api \
        python -m app.setup_society --society "Aravali Heights" \
        --address "Sector 150, Noida" --admin-email secretary@example.org \
        --admin-name "Anil Mehta"

The password is asked for interactively (or read from ADMIN_PASSWORD), never passed on the
command line, where it would end up in the shell history. Everything else (flats,
residents, guards, gates, cameras) is then added by the admin in the web app.
The public demo doesn't need this: it uses the demo seed (python -m app.seed).
"""

import argparse
import getpass
import os
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import event_loop
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.models import Society, User
from app.models.enums import UserRole
from app.schemas.common import LowerEmail, Password


class FirstAdmin(BaseModel):
    email: LowerEmail
    password: Password


@dataclass
class Created:
    society: Society
    admin: User


class AlreadySetUpError(Exception):
    pass


async def setup(
    db: AsyncSession, *, society: str, address: str | None, name: str, email: str, password: str
) -> Created:
    """Refuses to run on a database that already has a society, so it can't be used to
    add a second admin behind the existing admins' backs."""
    if await db.scalar(select(func.count()).select_from(Society)):
        raise AlreadySetUpError("This database already has a society; admins add admins.")
    admin_in = FirstAdmin(email=email, password=password)
    new_society = Society(name=society, address=address)
    db.add(new_society)
    await db.flush()
    admin = User(
        society_id=new_society.id,
        email=admin_in.email,
        full_name=name,
        role=UserRole.ADMIN,
        password_hash=hash_password(admin_in.password),
    )
    db.add(admin)
    await db.commit()
    return Created(new_society, admin)


async def _main(args: argparse.Namespace, password: str) -> None:
    try:
        async with SessionLocal() as db:
            created = await setup(
                db,
                society=args.society,
                address=args.address,
                name=args.admin_name,
                email=args.admin_email,
                password=password,
            )
        print(f"Created {created.society.name} and its admin {created.admin.email}.")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a society and its first admin.")
    parser.add_argument("--society", required=True, help="society name")
    parser.add_argument("--address")
    parser.add_argument("--admin-name", required=True)
    parser.add_argument("--admin-email", required=True)
    args = parser.parse_args(argv)
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    try:
        event_loop.run(_main(args, password))
    except (AlreadySetUpError, ValidationError) as error:
        print(f"Not created: {error}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
