"""Helpers that create test records directly in the database (faster than via the API)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_token, generate_device_key, hash_password
from app.models import Device, Flat, Gate, Resident, Society, User, Vehicle
from app.models.enums import LaneDirection, ResidentType, UserRole, VehicleType

TEST_PASSWORD = "correct-horse-battery"  # noqa: S105 - test-only credential
# Argon2 is slow on purpose; hash once and reuse for every test user.
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


async def make_society(db: AsyncSession, name: str = "Test Society") -> Society:
    society = Society(name=name)
    db.add(society)
    await db.commit()
    return society


async def make_user(
    db: AsyncSession,
    society: Society,
    role: UserRole,
    *,
    email: str,
    full_name: str = "Test Person",
    is_active: bool = True,
) -> User:
    user = User(
        society_id=society.id,
        email=email,
        full_name=full_name,
        role=role,
        password_hash=TEST_PASSWORD_HASH,
        is_active=is_active,
    )
    db.add(user)
    await db.commit()
    return user


async def make_flat(db: AsyncSession, society: Society, block: str, number: str) -> Flat:
    flat = Flat(society_id=society.id, block=block, number=number, floor=int(number[0]))
    db.add(flat)
    await db.commit()
    return flat


async def make_resident(
    db: AsyncSession, society: Society, flat: Flat, *, email: str, full_name: str = "Priya Sharma"
) -> User:
    user = User(
        society_id=society.id,
        email=email,
        full_name=full_name,
        role=UserRole.RESIDENT,
        password_hash=TEST_PASSWORD_HASH,
    )
    db.add(Resident(user=user, flat=flat, resident_type=ResidentType.OWNER))
    await db.commit()
    return user


async def make_vehicle(
    db: AsyncSession, society: Society, flat: Flat, plate: str = "UP16AB1234"
) -> Vehicle:
    vehicle = Vehicle(
        society_id=society.id,
        flat=flat,
        plate_raw=plate,
        plate_normalized=plate,
        vehicle_type=VehicleType.CAR,
    )
    db.add(vehicle)
    await db.commit()
    return vehicle


async def make_gate(db: AsyncSession, society: Society, name: str = "Main Gate") -> Gate:
    gate = Gate(society_id=society.id, name=name)
    db.add(gate)
    await db.commit()
    return gate


async def make_device(
    db: AsyncSession, gate: Gate, direction: LaneDirection = LaneDirection.ENTRY
) -> tuple[Device, str]:
    key = generate_device_key()
    device = Device(
        gate=gate,
        name=f"{gate.name} {direction.value}",
        direction=direction,
        api_key_hash=key.hash,
        api_key_prefix=key.prefix,
    )
    db.add(device)
    await db.commit()
    return device, key.plaintext


def auth_headers(user: User) -> dict[str, str]:
    token, _ = create_token(get_settings(), user.id, "access")
    return {"Authorization": f"Bearer {token}"}
