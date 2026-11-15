"""Who said what: telling the two people in a conversation apart.

Both bracelets record the same conversation, each about 15 cm from its
wearer's mouth and about a meter from the other person's. So whenever
someone speaks, *their own* bracelet hears them much louder (roughly 10-15
dB) than the other bracelet does. Comparing the two clips moment by moment
tells us who is talking, with no voice training and no extra AI call:

    1. Measure each clip's loudness every 50 ms (an "envelope").
    2. Line the two clips up. The bracelets start recording within a fraction
       of a second of each other; cross-correlating the envelopes finds the
       exact offset (both mics hear the same pauses and bursts of speech).
    3. For each transcript segment, compare how loud it was on each bracelet.
       Louder on Grace's bracelet = Grace said it.

The level difference between two mics also depends on each mic's gain, so
we don't assume 0 dB is the dividing line: the differences form two groups
(one per speaker) and we split them at the midpoint between the groups.

If only one bracelet uploaded, the wearer's own voice is still the loud one
on that clip, so we split its segments into a loud group (the wearer) and a
quiet group (the other person), but only when the two are clearly apart.

Anything we can't call confidently is labelled "unsure" and handed to the
chat model, which decides from context ("I'm Jordan, I run the GPU team").
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

ENVELOPE_MS = 50
_FRAMES_PER_S = 1000 // ENVELOPE_MS

# How far the two clips' starts may disagree beyond what the bracelets
# reported (clock error, request latency), in seconds.
ALIGN_SEARCH_S = 2.0
# Without start times, search this far either way.
ALIGN_SEARCH_NO_CLOCK_S = 6.0

# A segment must be this many dB louder on one bracelet (after correcting
# for mic gain) to be credited to that bracelet's wearer.
TWO_MIC_MARGIN_DB = 2.0
# With one clip, the loud and quiet groups must be this far apart to trust the split.
ONE_MIC_MIN_GAP_DB = 6.0


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    """PCM WAV bytes -> (mono float samples in [-1, 1], sample rate).

    Raises ValueError for anything that isn't PCM WAV (e.g. a phone's webm),
    in which case speaker attribution falls back to context.
    """
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"not a PCM WAV file: {exc}") from exc
    if width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648
    else:
        raise ValueError(f"unsupported sample width {width}")
    if channels > 1:
        x = x[: len(x) - len(x) % channels].reshape(-1, channels).mean(axis=1)
    return x, rate


def envelope(samples: np.ndarray, rate: int) -> list[float]:
    """Loudness (dBFS) of every 50 ms frame.

    A pre-emphasis filter first takes out DC offset and low rumble (HVAC,
    handling noise), so the numbers follow speech, which is where the two
    mics differ.
    """
    if len(samples) < 2:
        return []
    x = np.empty_like(samples)
    x[0] = 0.0
    x[1:] = samples[1:] - 0.97 * samples[:-1]
    hop = max(1, rate * ENVELOPE_MS // 1000)
    n = len(x) // hop
    if n == 0:
        return []
    frames = x[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    return [round(float(v), 2) for v in db]


def _detail(env: np.ndarray, window: int = 10) -> np.ndarray:
    """The envelope minus its half-second moving average.

    Which person is talking changes each mic's *overall* level in opposite
    directions, which would pull the alignment off. Syllables and pauses
    show up on both mics at the same moments, so we align on those.
    """
    if len(env) < window:
        return env - env.mean() if len(env) else env
    kernel = np.ones(window) / window
    return env - np.convolve(env, kernel, mode="same")


def estimate_offset_frames(env_a: Sequence[float], env_b: Sequence[float], guess_frames: int, search_frames: int) -> int:
    """How many frames later B's clip started than A's (negative = earlier).

    Returns the lag that best lines up the two loudness curves within
    ``guess_frames ± search_frames``. Event at frame t in A is at t - lag in B.
    """
    a, b = _detail(np.asarray(env_a, dtype=np.float64)), _detail(np.asarray(env_b, dtype=np.float64))
    if len(a) < 10 or len(b) < 10:
        return guess_frames
    best_lag, best_score = guess_frames, -np.inf
    for lag in range(guess_frames - search_frames, guess_frames + search_frames + 1):
        # A frame t lines up with B frame t - lag.
        start = max(0, lag)
        end = min(len(a), len(b) + lag)
        if end - start < max(20, min(len(a), len(b)) // 3):
            continue
        sa, sb = a[start:end], b[start - lag : end - lag]
        sa, sb = sa - sa.mean(), sb - sb.mean()
        denom = np.sqrt((sa**2).sum() * (sb**2).sum())
        if denom == 0:
            continue
        score = float((sa * sb).sum() / denom)
        if score > best_score:
            best_lag, best_score = lag, score
    return best_lag


def _two_means(values: np.ndarray) -> Optional[tuple[float, float]]:
    """Split 1-D values into two groups. Returns (low mean, high mean) or None."""
    if len(values) < 4:
        return None
    lo, hi = float(np.percentile(values, 25)), float(np.percentile(values, 75))
    if hi - lo < 1e-6:
        return None
    for _ in range(25):
        mid = (lo + hi) / 2
        low, high = values[values <= mid], values[values > mid]
        if not len(low) or not len(high):
            return None
        new_lo, new_hi = float(low.mean()), float(high.mean())
        if abs(new_lo - lo) < 1e-3 and abs(new_hi - hi) < 1e-3:
            break
        lo, hi = new_lo, new_hi
    return lo, hi


def _voiced(*envs: np.ndarray) -> np.ndarray:
    """Frames where someone is talking: well above every clip's noise floor."""
    mask = np.zeros(len(envs[0]), dtype=bool)
    for env in envs:
        floor = np.percentile(env, 10)
        mask |= env > floor + 10
    return mask


@dataclass
class Attribution:
    # One label per transcript segment: "A" (the primary clip's wearer),
    # "B" (the other person) or "unsure".
    labels: list[str]
    # "two_bracelets", "one_bracelet", or "none" (couldn't measure; context only).
    method: str
    # Seconds B's clip started after A's (two_bracelets only).
    offset_s: Optional[float] = None


def _frames(seg: dict) -> tuple[int, int]:
    i0 = int(float(seg.get("start", 0)) * _FRAMES_PER_S)
    i1 = max(i0 + 1, int(round(float(seg.get("end", 0)) * _FRAMES_PER_S)))
    return i0, i1


def attribute(
    segments: list[dict],
    env_a: Optional[Sequence[float]],
    env_b: Optional[Sequence[float]] = None,
    start_gap_s: Optional[float] = None,
) -> Attribution:
    """Label each segment of A's transcript with who said it.

    ``segments`` are Whisper segments timed against A's clip. ``env_a`` and
    ``env_b`` are the loudness envelopes of A's and B's bracelets (B's may be
    missing). ``start_gap_s`` is how much later B started recording, from
    the bracelets' clocks, if known.
    """
    if not segments:
        return Attribution([], "none")
    if not env_a:
        return Attribution(["unsure"] * len(segments), "none")
    a = np.asarray(env_a, dtype=np.float64)

    if env_b:
        b = np.asarray(env_b, dtype=np.float64)
        guess = int(round((start_gap_s or 0.0) * _FRAMES_PER_S))
        search = int((ALIGN_SEARCH_S if start_gap_s is not None else ALIGN_SEARCH_NO_CLOCK_S) * _FRAMES_PER_S)
        lag = estimate_offset_frames(a, b, guess, search)
        # Shift B onto A's timeline (NaN where B wasn't recording).
        b_on_a = np.full(len(a), np.nan)
        idx = np.arange(len(a)) - lag
        ok = (idx >= 0) & (idx < len(b))
        b_on_a[ok] = b[idx[ok]]
        both = ~np.isnan(b_on_a)
        if both.sum() >= 20:
            diff = a - np.where(both, b_on_a, 0)
            voiced = both & _voiced(a, np.where(both, b_on_a, -120))
            groups = _two_means(diff[voiced]) if voiced.sum() >= 8 else None
            # Two speakers -> two clear groups of differences. Their midpoint
            # cancels out any gain difference between the two mics.
            center = (groups[0] + groups[1]) / 2 if groups and groups[1] - groups[0] >= 4 else 0.0
            labels = []
            for seg in segments:
                i0, i1 = _frames(seg)
                sel = np.zeros(len(a), dtype=bool)
                sel[i0 : min(i1, len(a))] = True
                sel &= voiced
                if sel.sum() == 0:
                    labels.append("unsure")
                    continue
                d = diff[sel] - center
                # Vote frame by frame so a segment where both talked shows up as mixed.
                share_a = float((d > TWO_MIC_MARGIN_DB).sum()) / len(d)
                share_b = float((d < -TWO_MIC_MARGIN_DB).sum()) / len(d)
                mean = float(d.mean())
                if mean > TWO_MIC_MARGIN_DB and share_a >= 0.55:
                    labels.append("A")
                elif mean < -TWO_MIC_MARGIN_DB and share_b >= 0.55:
                    labels.append("B")
                else:
                    labels.append("unsure")
            return Attribution(labels, "two_bracelets", offset_s=lag / _FRAMES_PER_S)

    # One clip: the wearer is the loud voice, the other person the quiet one.
    levels = []
    for seg in segments:
        i0, i1 = _frames(seg)
        chunk = a[i0 : min(i1, len(a))]
        levels.append(float(np.percentile(chunk, 75)) if len(chunk) else np.nan)
    arr = np.array([v for v in levels if not np.isnan(v)])
    groups = _two_means(arr) if len(arr) >= 4 else None
    if not groups or groups[1] - groups[0] < ONE_MIC_MIN_GAP_DB:
        return Attribution(["unsure"] * len(segments), "one_bracelet")
    mid = (groups[0] + groups[1]) / 2
    margin = (groups[1] - groups[0]) / 6
    labels = []
    for v in levels:
        if np.isnan(v) or abs(v - mid) < margin:
            labels.append("unsure")
        else:
            labels.append("A" if v > mid else "B")
    return Attribution(labels, "one_bracelet")
