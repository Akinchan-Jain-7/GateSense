"""Pages and endpoints that need no login: the visitor's "time remaining" link."""

import json
from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import selectinload

from app.api.deps import AppSettings, DbSession
from app.models import Visit
from app.models.enums import VisitStatus
from app.services import visit_links

router = APIRouter(tags=["public"])


class VisitorView(BaseModel):
    """Only what the visitor needs: no phone numbers, no resident names."""

    first_name: str | None
    flat_label: str
    status: VisitStatus
    entered_at: datetime | None
    expected_exit_at: datetime | None
    seconds_remaining: int | None


async def _visitor_view(db: DbSession, settings: AppSettings, token: str) -> VisitorView:
    visit_id = visit_links.read_token(settings, token)
    visit = (
        await db.get(
            Visit, visit_id, options=[selectinload(Visit.visitor), selectinload(Visit.flat)]
        )
        if visit_id
        else None
    )
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This link is invalid or has expired")
    remaining = None
    if visit.expected_exit_at and visit.status in {
        VisitStatus.INSIDE,
        VisitStatus.OVERSTAYED,
        VisitStatus.ESCALATED,
    }:
        remaining = int((visit.expected_exit_at - datetime.now(UTC)).total_seconds())
    return VisitorView(
        first_name=visit.visitor.full_name.split()[0] if visit.visitor else None,
        flat_label=visit.flat.label,
        status=visit.status,
        entered_at=visit.entered_at,
        expected_exit_at=visit.expected_exit_at,
        seconds_remaining=remaining,
    )


@router.get("/api/v1/public/visits/{token}", response_model=VisitorView)
async def visitor_status(token: str, db: DbSession, settings: AppSettings) -> VisitorView:
    return await _visitor_view(db, settings, token)


@router.get("/visit/{token}", response_class=HTMLResponse, include_in_schema=False)
async def visitor_page(token: str, db: DbSession, settings: AppSettings) -> HTMLResponse:
    """The page the email links to: a live countdown, readable on any phone."""
    try:
        view = await _visitor_view(db, settings, token)
    except HTTPException:
        return HTMLResponse(
            _page("Link expired", "<p>This link is no longer valid.</p>", None), status_code=404
        )
    hello = f"Hi {escape(view.first_name)}, you" if view.first_name else "You"
    if view.seconds_remaining is None:
        state = view.status.value.replace("_", " ")
        body = f"<p>Your visit to <b>{escape(view.flat_label)}</b> is <b>{state}</b>.</p>"
        deadline = None
    else:
        body = (
            f"<p>{hello}'re visiting <b>{escape(view.flat_label)}</b>.</p>"
            '<p class="big" id="left">…</p><p id="note">time remaining</p>'
        )
        deadline = view.expected_exit_at.isoformat() if view.expected_exit_at else None
    return HTMLResponse(_page("Your visit", body, deadline))


STYLE = """
body { font-family: Inter, system-ui, sans-serif; background: #f5f5f7; color: #111827;
       margin: 0; display: grid; place-items: center; min-height: 100vh }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 28px;
        max-width: 360px; width: calc(100% - 32px); text-align: center }
.brand { color: #4f46e5; font-weight: 700 }
.big { font-size: 40px; font-weight: 700; margin: 16px 0 4px }
"""

COUNTDOWN = """
const end = new Date(%s);
function tick() {
  const s = Math.round((end - new Date()) / 1000), a = Math.abs(s);
  const minutes = String(Math.floor(a / 60) %% 60).padStart(2, "0");
  document.getElementById("left").textContent = Math.floor(a / 3600) + "h " + minutes + "m";
  document.getElementById("note").textContent =
    s >= 0 ? "time remaining" : "over time: please leave";
}
tick(); setInterval(tick, 30000);
"""


def _page(title: str, body: str, deadline: str | None) -> str:
    script = f"<script>{COUNTDOWN % json.dumps(deadline)}</script>" if deadline else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} · GateSense</title><style>{STYLE}</style></head>"
        "<body><div class='card'><div class='brand'>GateSense</div>"
        f"{body}</div>{script}</body></html>"
    )
