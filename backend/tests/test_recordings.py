"""Conversation recording, who-said-what, notes, voice notes, email and deletion.

The AI service is replaced by FakeAI, so these tests never call the network.
The audio is synthetic but real: two "voices" (modulated noise) mixed the
way two bracelets would hear them, so the speaker attribution runs on
actual WAV files.
"""

from __future__ import annotations

import dataclasses
import io
import wave

import numpy as np
import pytest
from sqlmodel import select

from app import ai as ai_module
from app import notes_ai, recordings, speakers
from app.models import Connection, ConversationNote, Recording, VoiceNote
from conftest import ADMIN, BRACELET, email_html, email_text, outbox

SR = 16000

# Who talks when (seconds from the start of bracelet 1's clip) and what they say.
SCRIPT = [
    ("A", 0.5, 3.0, "Hi, I'm Alice, I study computer science at Viterbi."),
    ("B", 3.0, 5.5, "Nice to meet you, I'm Bob, I run the GPU tooling team at a chip company."),
    ("A", 5.5, 7.0, "That sounds great. I'd love to hear about internships."),
    ("B", 7.0, 11.0, "We hire interns every summer. I'll send you the application link tonight."),
    ("A", 11.0, 13.0, "Thank you. I'll email you my resume tomorrow."),
    ("B", 13.0, 14.0, "Perfect."),
]


def _voice(rng, n):
    t = np.arange(n) / SR
    env = (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t + rng.uniform(0, 6))) ** 2
    return rng.normal(0, 0.3, n) * env


def _wav(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def two_clips(b_starts_late_s: float = 0.6, seed: int = 7) -> tuple[bytes, bytes]:
    """(Alice's bracelet, Bob's bracelet): each wearer ~12 dB louder on their own."""
    rng = np.random.default_rng(seed)
    n = int(15 * SR)
    va, vb = np.zeros(n), np.zeros(n)
    for who, start, end, _ in SCRIPT:
        i, j = int(start * SR), int(end * SR)
        (va if who == "A" else vb)[i:j] += _voice(rng, j - i)
    room = rng.normal(0, 0.02, n)
    clip_a = va + 0.25 * vb + room + rng.normal(0, 0.003, n)
    clip_b = (vb + 0.25 * va + 0.8 * room + rng.normal(0, 0.003, n)) * 0.5  # quieter mic
    lag = int(b_starts_late_s * SR)
    return _wav(clip_a), _wav(clip_b[lag:])


SEGMENTS = [{"start": s, "end": e, "text": t} for _, s, e, t in SCRIPT]


class FakeAI:
    """Stands in for Whisper + the chat model."""

    def __init__(self):
        self.transcribed: list[str] = []
        self.chats: list[tuple[str, str]] = []
        self.voice_answer = {"category": "idea", "person_id": None, "text": "Start a hardware club.", "follow_up": None}
        self.voice_text = "Start a hardware club at Viterbi."

    def transcribe(self, audio, filename, content_type):
        self.transcribed.append(filename)
        if len(audio) < 200_000:  # a short clip is a voice note
            return [{"start": 0.0, "end": 3.0, "text": self.voice_text}]
        return [dict(s) for s in SEGMENTS]

    def chat_json(self, system, user):
        self.chats.append((system, user))
        if system == notes_ai.CONVERSATION_SYSTEM:
            return {
                "speakers": {"0": "B", "5": "A"},  # 0 is measured, so this must be ignored
                "notes_for_A": {
                    "summary": "You and Bob talked about GPU tooling and summer internships.",
                    "topics": ["GPU tooling", "internships"],
                    "about_them": ["Runs the GPU tooling team"],
                    "commitments": [
                        {"who": "them", "what": "send you the application link", "quote": "I'll send you the application link tonight"},
                        {"who": "you", "what": "email Bob your resume", "quote": "I'll email you my resume tomorrow."},
                        # Not in the transcript: must be dropped.
                        {"who": "them", "what": "refer you to their manager", "quote": "I'll refer you to my manager"},
                    ],
                    "follow_ups": ["Email Bob your resume tomorrow"],
                },
                "notes_for_B": {
                    "summary": "You met Alice, a CS student at Viterbi interested in internships.",
                    "topics": ["internships"],
                    "about_them": ["Studies computer science at Viterbi"],
                    # The model mixed up who said it; the measured speaker wins.
                    "commitments": [{"who": "you", "what": "email her resume", "quote": "I'll email you my resume tomorrow"}],
                    "follow_ups": ["Send Alice the internship application link"],
                },
            }
        return dict(self.voice_answer)


@pytest.fixture
def fake_ai(app):
    fake = FakeAI()
    app.state.ai_factory = lambda: fake
    return fake


def _wear(client, make_user, event_id, bracelet, name, **kw):
    uid, headers = make_user(name=name, **kw)
    resp = client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": bracelet}, headers=headers)
    assert resp.status_code == 200, resp.text
    return uid, headers


def _pair(client, a="TRO-1", b="TRO-2") -> int:
    client.post("/bracelets/tap", json={"device": a, "peer": b}, headers=BRACELET)
    resp = client.post("/bracelets/tap", json={"device": b, "peer": a}, headers=BRACELET).json()
    assert resp["status"] == "paired"
    return resp["connection_id"]


def _upload(client, device, data, kind="conversation", **params):
    return client.post(
        "/bracelets/recordings",
        params={"device": device, "kind": kind, **params},
        content=data,
        headers={**BRACELET, "Content-Type": "audio/wav"},
    )


@pytest.fixture
def pair(client, make_user, make_event):
    event_id = make_event()
    alice, alice_h = _wear(client, make_user, event_id, "TRO-1", "Alice Ng")
    bob, bob_h = _wear(client, make_user, event_id, "TRO-2", "Bob Li")
    conn = _pair(client)
    return dict(event=event_id, alice=alice, alice_h=alice_h, bob=bob, bob_h=bob_h, conn=conn)


# --- Speaker attribution ----------------------------------------------------------


def _envelope(data: bytes):
    return speakers.envelope(*speakers.decode_wav(data))


def test_two_bracelets_tell_speakers_apart():
    clip_a, clip_b = two_clips(0.6)
    env_a, env_b = _envelope(clip_a), _envelope(clip_b)
    expected = [who for who, *_ in SCRIPT]
    # With the bracelets' clocks (slightly off), and with no clock at all.
    for gap in (0.4, None):
        result = speakers.attribute(SEGMENTS, env_a, env_b, start_gap_s=gap)
        assert result.method == "two_bracelets"
        assert result.offset_s == pytest.approx(0.6, abs=0.05)
        assert result.labels == expected
    # From Bob's side the labels flip.
    flipped = speakers.attribute(
        [{**s, "start": s["start"] - 0.6, "end": s["end"] - 0.6} for s in SEGMENTS[1:]], env_b, env_a, start_gap_s=-0.6
    )
    assert flipped.labels == ["A" if w == "B" else "B" for w in expected[1:]]


def test_one_bracelet_uses_loud_vs_quiet():
    clip_a, _ = two_clips()
    result = speakers.attribute(SEGMENTS, _envelope(clip_a))
    assert result.method == "one_bracelet"
    assert result.labels == [who for who, *_ in SCRIPT]


def test_no_audio_measurement_leaves_it_to_context():
    assert speakers.attribute(SEGMENTS, None).labels == ["unsure"] * len(SEGMENTS)
    with pytest.raises(ValueError):
        speakers.decode_wav(b"not a wav")


def test_find_quote_rejects_paraphrases():
    lines = [s["text"] for s in SEGMENTS]
    assert notes_ai.find_quote("I'll send you the application link tonight", lines) == 3
    assert notes_ai.find_quote("ill email you my resume tomorrow", lines) == 4
    assert notes_ai.find_quote("I will refer you to my manager", lines) is None


# --- Conversation recordings --------------------------------------------------------


def test_conversation_notes_end_to_end(client, pair, fake_ai, db, settings):
    clip_a, clip_b = two_clips(0.6)
    r1 = _upload(client, "TRO-1", clip_a, connection_id=pair["conn"], started_at=1_763_190_000_000)
    assert r1.status_code == 201, r1.text
    assert r1.json()["duration_s"] == pytest.approx(15.0)
    r2 = _upload(client, "TRO-2", clip_b, connection_id=pair["conn"], started_at=1_763_190_000_500)
    assert r2.status_code == 201, r2.text

    # Only the first clip was transcribed; the second was only measured.
    assert len(fake_ai.transcribed) == 1
    db.expire_all()
    recs = db.exec(select(Recording)).all()
    assert {r.status for r in recs} == {"done"}
    assert all(r.audio_path is None for r in recs)  # audio deleted once used
    assert not list((settings.media_dir / "recordings").glob("*"))
    assert db.get(Connection, pair["conn"]).recorded is True

    # Alice's notes on Bob.
    alice = client.get(f"/events/{pair['event']}/notes/{pair['bob']}", headers=pair["alice_h"]).json()
    assert alice["conversation_status"] == "ready"
    convo = alice["conversation"]
    assert convo["speaker_method"] == "two_bracelets"
    assert [line["speaker"] for line in convo["transcript"]] == ["you", "them", "you", "them", "you", "them"]
    assert convo["summary"].startswith("You and Bob")
    whats = [(c["who"], c["what"]) for c in convo["commitments"]]
    assert whats == [("them", "send you the application link"), ("you", "email Bob your resume")]
    assert convo["follow_ups"] == ["Email Bob your resume tomorrow"]

    # Bob's notes on Alice: the promise is credited to Alice by the audio, not the model.
    bob = client.get(f"/events/{pair['event']}/notes/{pair['alice']}", headers=pair["bob_h"]).json()
    assert bob["conversation"]["commitments"] == [
        {"who": "them", "what": "email her resume", "quote": "Thank you. I'll email you my resume tomorrow."}
    ]
    assert [line["speaker"] for line in bob["conversation"]["transcript"]][:2] == ["them", "you"]

    # The connection card's preview line.
    card = client.get(f"/events/{pair['event']}/connections", headers=pair["alice_h"]).json()[0]
    assert card["recorded"] is True
    assert card["notes"] == {"conversation": "ready", "voice_notes": 0, "follow_ups": 1}

    # The model got names and measured labels, not raw "A"/"B".
    _, prompt = fake_ai.chats[-1]
    assert "[Alice Ng] Hi, I'm Alice" in prompt and "[Bob Li] Nice to meet you" in prompt


def test_no_recording_without_both_consents(client, make_user, make_event, fake_ai, db, settings):
    event_id = make_event()
    _wear(client, make_user, event_id, "TRO-1", "Alice Ng")
    _wear(client, make_user, event_id, "TRO-2", "Bob Li", consent=False)
    conn = _pair(client)
    resp = _upload(client, "TRO-1", two_clips()[0], connection_id=conn)
    assert resp.status_code == 403
    assert db.exec(select(Recording)).all() == []
    assert not (settings.media_dir / "recordings").exists() or not list((settings.media_dir / "recordings").glob("*"))
    db.expire_all()
    assert db.get(Connection, conn).recorded is False


def test_consent_withdrawn_after_tap_blocks_upload(client, pair, fake_ai):
    body = {"recording_consent": False, "recommendations_opt_in": True}
    assert client.put("/users/me/preferences", json=body, headers=pair["bob_h"]).status_code == 200
    assert _upload(client, "TRO-1", two_clips()[0], connection_id=pair["conn"]).status_code == 403


def test_upload_validation(client, pair, fake_ai, make_user, make_event):
    clip = two_clips()[0]
    assert client.post("/bracelets/recordings", params={"device": "TRO-1", "kind": "conversation"}, content=clip).status_code == 401
    assert _upload(client, "TRO-1", clip).status_code == 422  # no connection_id
    assert _upload(client, "TRO-1", clip, kind="song").status_code == 422
    assert _upload(client, "TRO-9", clip, connection_id=pair["conn"]).status_code == 409
    assert _upload(client, "TRO-1", b"", connection_id=pair["conn"]).status_code == 422
    # A bracelet can't attach audio to someone else's conversation.
    _wear(client, make_user, pair["event"], "TRO-3", "Cara Wu")
    assert _upload(client, "TRO-3", clip, connection_id=pair["conn"]).status_code == 422


def test_waits_for_ai_key_then_processes(client, pair, app, settings, db):
    def no_key():
        raise ai_module.AIError("AI_API_KEY isn't set")

    app.state.ai_factory = no_key
    resp = _upload(client, "TRO-1", two_clips()[0], connection_id=pair["conn"])
    assert resp.status_code == 201
    db.expire_all()
    rec = db.get(Recording, resp.json()["id"])
    assert rec.status == "waiting_for_ai"
    assert rec.audio_path and rec.envelope  # audio kept, loudness already measured
    note = client.get(f"/events/{pair['event']}/notes/{pair['bob']}", headers=pair["alice_h"]).json()
    assert note["conversation_status"] == "waiting_for_ai" and note["conversation"] is None

    fake = FakeAI()
    app.state.ai_factory = lambda: fake
    report = client.post("/admin/process", headers=ADMIN).json()
    assert report["processed"] == 1 and report["waiting"] == 0
    note = client.get(f"/events/{pair['event']}/notes/{pair['bob']}", headers=pair["alice_h"]).json()
    assert note["conversation_status"] == "ready"
    assert note["conversation"]["speaker_method"] == "one_bracelet"


def test_notes_are_private(client, pair, fake_ai, make_user):
    clip_a, _ = two_clips()
    _upload(client, "TRO-1", clip_a, connection_id=pair["conn"])
    _, stranger_h = make_user(name="Eve Stone")
    assert client.get(f"/events/{pair['event']}/notes/{pair['bob']}", headers=stranger_h).status_code == 404
    assert client.get(f"/events/{pair['event']}/notes", headers=stranger_h).json()["people"] == []
    assert client.get(f"/events/{pair['event']}/notes/{pair['bob']}").status_code == 401


# --- Voice notes ----------------------------------------------------------------------


def _short_clip() -> bytes:
    rng = np.random.default_rng(3)
    return _wav(_voice(rng, 3 * SR))


def test_voice_note_sorted_by_name(client, pair, fake_ai):
    fake_ai.voice_text = "Bob said to ping him Monday about the internship."
    fake_ai.voice_answer = {"category": "idea", "person_id": None, "text": "Bob said to ping him Monday.", "follow_up": "Message Bob on Monday"}
    resp = _upload(client, "TRO-1", _short_clip(), kind="voice_note")
    assert resp.status_code == 201
    notes = client.get(f"/events/{pair['event']}/notes", headers=pair["alice_h"]).json()
    vn = notes["people"][0]["voice_notes"]
    assert len(vn) == 1 and vn[0]["matched_by"] == "name" and vn[0]["person_name"] == "Bob Li"
    assert vn[0]["category"] == "person"
    assert notes["other"] == []
    card = client.get(f"/events/{pair['event']}/connections", headers=pair["alice_h"]).json()[0]
    assert card["notes"]["voice_notes"] == 1 and card["notes"]["follow_ups"] == 1


def test_voice_note_ai_pick_and_bad_pick(client, pair, fake_ai, db):
    fake_ai.voice_text = "He said their team uses a lot of CUDA, worth learning."
    fake_ai.voice_answer = {"category": "person", "person_id": pair["conn"], "text": "Their team uses CUDA.", "follow_up": None}
    _upload(client, "TRO-1", _short_clip(), kind="voice_note")
    fake_ai.voice_answer = {"category": "person", "person_id": 999, "text": "Someone mentioned a hackathon.", "follow_up": None}
    _upload(client, "TRO-1", _short_clip(), kind="voice_note")
    notes = client.get(f"/events/{pair['event']}/notes", headers=pair["alice_h"]).json()
    assert [v["matched_by"] for v in notes["people"][0]["voice_notes"]] == ["ai"]
    assert [(v["category"], v["text"]) for v in notes["other"]] == [("other", "Someone mentioned a hackathon.")]


def test_move_voice_note(client, pair, fake_ai, db):
    _upload(client, "TRO-1", _short_clip(), kind="voice_note")
    note_id = client.get(f"/events/{pair['event']}/notes", headers=pair["alice_h"]).json()["other"][0]["id"]
    url = f"/events/{pair['event']}/voice-notes/{note_id}"
    moved = client.patch(url, json={"person_user_id": pair["bob"]}, headers=pair["alice_h"])
    assert moved.status_code == 200 and moved.json()["person_name"] == "Bob Li" and moved.json()["matched_by"] == "user"
    assert client.patch(url, json={"person_user_id": 12345}, headers=pair["alice_h"]).status_code == 422
    assert client.patch(url, json={}, headers=pair["alice_h"]).status_code == 422
    assert client.patch(url, json={"category": "task"}, headers=pair["bob_h"]).status_code == 404  # not Bob's note
    # Re-processing never undoes a hand-made move.
    db.expire_all()
    rec = db.exec(select(Recording)).first()
    recordings.process_voice_note(db, lambda: fake_ai, rec)
    db.expire_all()
    assert db.get(VoiceNote, note_id).connection_id == pair["conn"]


# --- Email and deletion -------------------------------------------------------------------


def test_email_has_notes_then_audio_and_transcripts_are_deleted(client, pair, fake_ai, settings, db):
    clip_a, clip_b = two_clips()
    _upload(client, "TRO-1", clip_a, connection_id=pair["conn"])
    _upload(client, "TRO-2", clip_b, connection_id=pair["conn"])
    _upload(client, "TRO-1", _short_clip(), kind="voice_note")

    report = client.post(f"/events/{pair['event']}/send-summaries", headers=ADMIN).json()
    assert report["sent"] == 2 and report["recordings_purged"] == 3

    by_to = {m["To"]: m for m in outbox(settings)}
    text = email_text(by_to["user1@usc.edu"])
    assert "What you talked about: You and Bob talked about GPU tooling" in text
    assert "Promised: Bob said they'd send you the application link" in text
    assert "Promised: You said you'd email Bob your resume" in text
    assert "Follow up: Email Bob your resume tomorrow" in text
    assert "Idea: Start a hardware club." in text
    assert "now deleted" in text
    assert "refer you to their manager" not in text
    assert "Your other notes" in email_html(by_to["user1@usc.edu"])

    db.expire_all()
    assert all(r.transcript is None and r.envelope is None and r.audio_path is None for r in db.exec(select(Recording)).all())
    notes = db.exec(select(ConversationNote)).all()
    assert len(notes) == 2 and all(n.transcript == [] and n.summary for n in notes)


def test_deleting_account_removes_recordings_and_notes(client, pair, app, settings, db):
    def no_key():
        raise ai_module.AIError("no key")

    app.state.ai_factory = no_key
    _upload(client, "TRO-1", two_clips()[0], connection_id=pair["conn"])  # audio still on disk
    assert list((settings.media_dir / "recordings").glob("*"))
    assert client.delete("/users/me", headers=pair["bob_h"]).status_code == 204
    db.expire_all()
    assert db.exec(select(Recording)).all() == []
    assert db.exec(select(ConversationNote)).all() == []
    assert not list((settings.media_dir / "recordings").glob("*"))


def test_ai_client_parses_groq_responses(settings):
    import httpx

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "hi there", "segments": [{"start": 0, "end": 1.2, "text": " hi there "}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    cfg = dataclasses.replace(settings, ai_api_key="k")
    client = ai_module.OpenAICompatibleClient(cfg, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.transcribe(b"RIFF....", "a.wav", "audio/wav") == [{"start": 0.0, "end": 1.2, "text": "hi there"}]
    assert client.chat_json("s", "u") == {"ok": True}
    assert seen[0].headers["authorization"] == "Bearer k"
    assert str(seen[0].url).startswith("https://api.groq.com/openai/v1/")
    with pytest.raises(ai_module.AIError):
        ai_module.OpenAICompatibleClient(dataclasses.replace(settings, ai_api_key=""))
