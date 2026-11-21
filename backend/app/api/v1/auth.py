from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.models import Resident
from app.models.enums import UserRole
from app.schemas.auth import CurrentUserResponse, RefreshRequest, TokenResponse
from app.schemas.flat import FlatSummary
from app.services import auth as auth_service
from app.services.auth import TokenPair

router = APIRouter(tags=["auth"])


def _token_response(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession, settings: AppSettings
) -> TokenResponse:
    """Log in with email (in the `username` field) and password.

    Sent as a form (OAuth2 password flow), which is what the **Authorize** button in
    `/docs` uses.
    """
    return _token_response(await auth_service.login(db, settings, form.username, form.password))


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: DbSession, settings: AppSettings) -> TokenResponse:
    """Swap a refresh token for a new pair. Each refresh token works only once."""
    return _token_response(await auth_service.refresh(db, settings, body.refresh_token))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, db: DbSession, settings: AppSettings) -> None:
    """Revoke a refresh token. The short-lived access token simply expires."""
    await auth_service.logout(db, settings, body.refresh_token)


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: CurrentUser, db: DbSession) -> CurrentUserResponse:
    """The logged-in user, with their flats if they are a resident."""
    response = CurrentUserResponse.model_validate(user)
    if user.role == UserRole.RESIDENT:
        residents = await db.scalars(
            select(Resident).where(Resident.user_id == user.id).options(selectinload(Resident.flat))
        )
        response.flats = [FlatSummary.model_validate(r.flat) for r in residents]
    return response
