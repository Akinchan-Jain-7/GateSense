"""Email content: every message has a plain-text and an HTML version.

Plain text is what some mail apps (and spam filters) read; HTML is what most people see.
Everything inserted into HTML is escaped, so a visitor named `<script>` stays text.
"""

from dataclasses import dataclass
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ACCENT = "#4f46e5"


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


def local_time(value: datetime) -> str:
    """'4:30 PM, 22 Nov' in Indian time, which is what people at the gate expect.

    Built by hand: strftime's "no leading zero" flag differs between Linux and Windows.
    """
    local = value.astimezone(IST)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}, {local.day} {local:%b}"


def _layout(title: str, paragraphs: list[str], button: tuple[str, str] | None = None) -> str:
    body = "".join(f'<p style="margin:0 0 12px">{p}</p>' for p in paragraphs)
    if button:
        label, url = button
        body += (
            f'<p style="margin:20px 0"><a href="{escape(url)}" style="background:{ACCENT};'
            "color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;"
            f'font-weight:600">{escape(label)}</a></p>'
        )
    return (
        '<!doctype html><html><body style="margin:0;background:#f5f5f7;font-family:Inter,'
        'Segoe UI,Arial,sans-serif;color:#111827">'
        '<div style="max-width:520px;margin:24px auto;background:#fff;border:1px solid #e5e7eb;'
        'border-radius:12px;padding:24px">'
        f'<div style="font-weight:700;color:{ACCENT};margin-bottom:16px">GateSense</div>'
        f'<h1 style="font-size:18px;margin:0 0 16px">{escape(title)}</h1>{body}'
        '<p style="margin:24px 0 0;font-size:12px;color:#6b7280">Sent by the society gate '
        "system. Please don't reply to this email.</p></div></body></html>"
    )


def visit_welcome(visitor: str, flat: str, ends_at: datetime, link: str) -> Email:
    when = local_time(ends_at)
    return Email(
        subject=f"Welcome! Your visit to {flat} ends at {when}",
        text=(
            f"Hi {visitor},\n\nYou're checked in at the gate for {flat}. Please leave by {when}.\n"
            f"See the time remaining: {link}\n"
        ),
        html=_layout(
            f"You're checked in for {flat}",
            [f"Hi {escape(visitor)},", f"Please leave by <b>{escape(when)}</b>."],
            ("See time remaining", link),
        ),
    )


def overstay_notice(
    name: str, visitor: str, flat: str, ended_at: datetime, *, to_visitor: bool
) -> Email:
    when = local_time(ended_at)
    if to_visitor:
        lead = f"Your visit to {flat} was due to end at {when}. Please head to the gate."
    else:
        lead = f"Your visitor {visitor} was due to leave by {when} and is still inside."
    return Email(
        subject=f"Visit time is up ({flat})",
        text=f"Hi {name},\n\n{lead}\n",
        html=_layout("Visit time is up", [f"Hi {escape(name)},", escape(lead)]),
    )


def overstay_reminder(
    name: str, visitor: str, flat: str, minutes_over: int, *, to_visitor: bool
) -> Email:
    if to_visitor:
        lead = (
            f"You're {minutes_over} minutes past the end of your visit to {flat}. Please leave now."
        )
    else:
        lead = (
            f"{visitor} is {minutes_over} minutes past their visit time. The guard will call you "
            "if they're still inside in 30 minutes."
        )
    return Email(
        subject=f"Reminder: visit is {minutes_over} minutes over ({flat})",
        text=f"Hi {name},\n\n{lead}\n",
        html=_layout("Reminder: visit time is over", [f"Hi {escape(name)},", escape(lead)]),
    )
