"""Live bracelet taps: turning two bracelets' reports into one Connection.

How a tap works (firmware: ``firmware/trO_bracelet``):

  1. Every bracelet broadcasts its id over ESP-NOW about 10 times a second
     and watches the signal strength (RSSI) of the others.
  2. When another bracelet stays very close for about half a second, it
     calls ``POST /bracelets/tap`` with ``{"device": me, "peer": them}`` and
     keeps retrying a few times a second for a few seconds.
  3. The other bracelet does the same. As soon as the two reports agree
     (A says B and B says A, both within ``TAP_WINDOW``), we create the
     Connection, and both bracelets get ``"paired"`` on their next try.

A manual tap (button held) reports ``peer: ""``: it pairs with any other
report at the same event within the window, so two people can connect even
if the radio tap doesn't trigger.

Matching on *both* reports means a bracelet that merely passes close by
can't create a connection on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, or_, select

from .models import BraceletAssignment, Connection, Preferences, Star, TapReport, User, utcnow

# How long a report stays open for the other bracelet to answer. The
# firmware retries for ~6 s, so the two sides always overlap.
TAP_WINDOW = timedelta(seconds=8)


class NotLinked(Exception):
    """The bracelet isn't assigned to anyone (no one has tapped their phone to it yet)."""


@dataclass
class TapResult:
    status: str  # "waiting" or "paired"
    connection: Optional[Connection] = None
    peer: Optional[User] = None
    match_pct: Optional[int] = None
    both_consented: bool = False


def current_assignment(session: Session, bracelet_id: str, event_id: Optional[int] = None) -> Optional[BraceletAssignment]:
    """Who is wearing this bracelet: its newest assignment (or the one for ``event_id``).

    Bracelets are handed back and reused, so the newest assignment is the
    current wearer.
    """
    query = select(BraceletAssignment).where(BraceletAssignment.bracelet_id == bracelet_id)
    if event_id is not None:
        query = query.where(BraceletAssignment.event_id == event_id)
    return session.exec(
        query.order_by(col(BraceletAssignment.assigned_at).desc(), col(BraceletAssignment.id).desc())
    ).first()


def _norm(values) -> set[str]:
    return {v.strip().lower() for v in values or [] if isinstance(v, str) and v.strip()}


def match_pct(a: User, b: User, prefs_a: Optional[Preferences], prefs_b: Optional[Preferences]) -> Optional[int]:
    """A rough 5-99 "how much you have in common" score, or None.

    None unless BOTH people opted in to recommendations, since the score is
    built from both people's profiles. Shared interests count most, then the
    same major and school. Simple on purpose: it lights 1-3 LEDs.
    """
    if not (prefs_a and prefs_a.recommendations_opt_in and prefs_b and prefs_b.recommendations_opt_in):
        return None
    score = 30
    ia, ib = _norm(a.interests), _norm(b.interests)
    if ia and ib:
        score += round(55 * len(ia & ib) / min(len(ia), len(ib)))
    if a.major and b.major and a.major.strip().lower() == b.major.strip().lower():
        score += 10
    if a.school and b.school and a.school.strip().lower() == b.school.strip().lower():
        score += 5
    return max(5, min(99, score))


def _connection_between(session: Session, event_id: int, u1: int, u2: int) -> Optional[Connection]:
    a, b = min(u1, u2), max(u1, u2)
    return session.exec(
        select(Connection).where(
            Connection.event_id == event_id, Connection.user_a_id == a, Connection.user_b_id == b
        )
    ).first()


def _get_or_create_connection(session: Session, event_id: int, u1: int, u2: int) -> Connection:
    existing = _connection_between(session, event_id, u1, u2)
    if existing is not None:
        return existing
    conn = Connection(event_id=event_id, user_a_id=min(u1, u2), user_b_id=max(u1, u2), recorded=False)
    session.add(conn)
    try:
        session.commit()
    except IntegrityError:
        # The other bracelet's request created it a moment ago.
        session.rollback()
        existing = _connection_between(session, event_id, u1, u2)
        assert existing is not None
        return existing
    session.refresh(conn)
    return conn


def _result(session: Session, conn: Connection, me: int) -> TapResult:
    other_id = conn.user_b_id if conn.user_a_id == me else conn.user_a_id
    me_user, peer = session.get(User, me), session.get(User, other_id)
    p_me, p_peer = session.get(Preferences, me), session.get(Preferences, other_id)
    return TapResult(
        status="paired",
        connection=conn,
        peer=peer,
        match_pct=match_pct(me_user, peer, p_me, p_peer) if me_user and peer else None,
        both_consented=bool(p_me and p_me.recording_consent and p_peer and p_peer.recording_consent),
    )


def report_tap(
    session: Session,
    bracelet_id: str,
    peer_id: str,
    *,
    rssi: Optional[int] = None,
    event_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> TapResult:
    """Record one tap report and pair it if the other bracelet has reported too.

    Safe to call repeatedly (the firmware retries): repeats refresh the same
    report instead of adding new ones. Raises NotLinked if nobody is wearing
    ``bracelet_id``.
    """
    now = now or utcnow()
    since = now - TAP_WINDOW
    assignment = current_assignment(session, bracelet_id, event_id)
    if assignment is None:
        raise NotLinked(bracelet_id)
    event_id, me = assignment.event_id, assignment.user_id
    if peer_id == bracelet_id:
        peer_id = ""

    # 1. My own open report for this peer: refresh it, or start one.
    mine = session.exec(
        select(TapReport)
        .where(
            TapReport.event_id == event_id,
            TapReport.bracelet_id == bracelet_id,
            TapReport.peer_bracelet_id == peer_id,
            TapReport.last_at >= since,
        )
        .order_by(col(TapReport.last_at).desc())
    ).first()
    if mine is None:
        mine = TapReport(event_id=event_id, bracelet_id=bracelet_id, user_id=me, peer_bracelet_id=peer_id, first_at=now)
    mine.last_at, mine.rssi = now, rssi if rssi is not None else mine.rssi
    session.add(mine)
    session.commit()
    session.refresh(mine)

    if mine.connection_id is not None:  # paired on an earlier try
        conn = session.get(Connection, mine.connection_id)
        if conn is not None:
            return _result(session, conn, me)

    # 2. Someone else's open report that agrees with mine. They must name
    #    me (or be a manual tap), and I must name them (or be a manual tap).
    query = select(TapReport).where(
        TapReport.event_id == event_id,
        TapReport.bracelet_id != bracelet_id,
        TapReport.user_id != me,
        TapReport.last_at >= since,
        or_(TapReport.peer_bracelet_id == bracelet_id, TapReport.peer_bracelet_id == ""),
    )
    if peer_id:
        query = query.where(TapReport.bracelet_id == peer_id)
    candidates = session.exec(query.order_by(col(TapReport.last_at).desc())).all()

    # Prefer a report that names me exactly over a manual (wildcard) one.
    candidates.sort(key=lambda r: r.peer_bracelet_id != bracelet_id)
    for theirs in candidates:
        if theirs.connection_id is not None:
            # Already paired: only usable if it was paired with me.
            conn = session.get(Connection, theirs.connection_id)
            if conn is None or me not in (conn.user_a_id, conn.user_b_id):
                continue
        else:
            conn = _get_or_create_connection(session, event_id, me, theirs.user_id)
            theirs.connection_id = conn.id
            session.add(theirs)
        mine.connection_id = conn.id
        session.add(mine)
        session.commit()
        return _result(session, conn, me)

    return TapResult(status="waiting")


def star_latest(session: Session, bracelet_id: str, event_id: Optional[int] = None) -> Optional[tuple[Connection, User]]:
    """Star the wearer's most recent connection. Returns (connection, other person), or None if none yet.

    Raises NotLinked if nobody is wearing the bracelet. Starring twice is harmless.
    """
    assignment = current_assignment(session, bracelet_id, event_id)
    if assignment is None:
        raise NotLinked(bracelet_id)
    me = assignment.user_id
    conn = session.exec(
        select(Connection)
        .where(Connection.event_id == assignment.event_id)
        .where(or_(Connection.user_a_id == me, Connection.user_b_id == me))
        .order_by(col(Connection.tapped_at).desc(), col(Connection.id).desc())
    ).first()
    if conn is None:
        return None
    exists = session.exec(select(Star).where(Star.connection_id == conn.id, Star.user_id == me)).first()
    if exists is None:
        session.add(Star(connection_id=conn.id, user_id=me))
        try:
            session.commit()
        except IntegrityError:  # double press racing itself
            session.rollback()
    other = session.get(User, conn.user_b_id if conn.user_a_id == me else conn.user_a_id)
    return conn, other
