"""Who a user met at an event. Shared by the dashboard and the post-event email,
so both apply the same privacy rule: only the fields each person chose to share.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlmodel import Session, col, or_, select

from .models import SHAREABLE_FIELDS, Connection, Preferences, Star, User


@dataclass
class ConnectedPerson:
    connection: Connection
    person: User
    prefs: Optional[Preferences]
    # The user (whose list this is) starred this person from their bracelet.
    starred: bool = False


def shared_contact(person: User, prefs: Optional[Preferences]) -> dict[str, str]:
    """The person's contact fields they opted to share, in a stable order.

    No saved preferences means share nothing optional (the safe default).
    """
    shared = set(prefs.shared_fields) if prefs else set()
    return {f: value for f in SHAREABLE_FIELDS if f in shared and (value := getattr(person, f, None))}


def connected_people(
    session: Session, event_id: int, user_id: int, *, newest_first: bool = False
) -> list[ConnectedPerson]:
    """Everyone ``user_id`` tapped at the event, in tap order.

    Four queries total (connections, users, preferences, stars), however many
    connections there are. People whose accounts were deleted are skipped.
    """
    order = col(Connection.tapped_at).desc() if newest_first else col(Connection.tapped_at)
    rows = session.exec(
        select(Connection)
        .where(Connection.event_id == event_id)
        .where(or_(Connection.user_a_id == user_id, Connection.user_b_id == user_id))
        .order_by(order)
    ).all()
    other_ids = {r.user_b_id if r.user_a_id == user_id else r.user_a_id for r in rows}
    if not other_ids:
        return []
    users = {u.id: u for u in session.exec(select(User).where(col(User.id).in_(other_ids))).all()}
    prefs = {p.user_id: p for p in session.exec(select(Preferences).where(col(Preferences.user_id).in_(other_ids))).all()}
    starred = set(
        session.exec(
            select(Star.connection_id)
            .where(Star.user_id == user_id)
            .where(col(Star.connection_id).in_([r.id for r in rows]))
        ).all()
    )

    out = []
    for r in rows:
        other_id = r.user_b_id if r.user_a_id == user_id else r.user_a_id
        if other_id in users:
            out.append(
                ConnectedPerson(connection=r, person=users[other_id], prefs=prefs.get(other_id), starred=r.id in starred)
            )
    return out
