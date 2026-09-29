#!/usr/bin/env python3
"""Original, quiet pentatonic underscore for the Cizheng collection demo.

These are original synthesized instrument *impressions*, not sampled instruments
or a claim of an authentic guqin, guzheng, or xiao performance. No external audio,
network, model, API, credential, or music library is used. NumPy is the only Python
dependency. FFmpeg is optional and, when installed, is used only to measure LUFS.

Example:
  python3 generate_music.py --duration 205 --out cizheng_original_205s.wav

Output: deterministic stereo 48 kHz / 24-bit PCM WAV, plus a JSON metrics sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np


SR = 48_000
SEED = 20260929
TARGET_LUFS = -29.0
PEAK_CEILING_DBFS = -12.0

# D gong / major pentatonic: D, E, F#, A, B. All scored notes belong to this set.
SCALE = np.array([50, 52, 54, 57, 59, 62, 64, 66, 69, 71], dtype=int)


def frequency(midi: int) -> float:
    return 440.0 * 2.0 ** ((int(midi) - 69) / 12.0)


def db(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-12))


def filtered_noise(n: int, rng: np.random.Generator, low: float, high: float) -> np.ndarray:
    """Soft band-limited texture, with no brittle high-frequency breath hiss."""
    noise = rng.normal(0.0, 1.0, n)
    spectrum = np.fft.rfft(noise)
    hz = np.fft.rfftfreq(n, 1.0 / SR)
    weight = np.exp(-np.power(hz / high, 4.0))
    if low:
        weight *= 1.0 - np.exp(-np.power(hz / low, 2.0))
    result = np.fft.irfft(spectrum * weight, n=n)
    result /= max(float(np.std(result)), 1e-8)
    return result.astype(np.float32)


def pluck(midi: int, length: float, rng: np.random.Generator, silk: bool = False) -> np.ndarray:
    """Rounded string partials and brief, muted finger contact."""
    n = max(1, round(length * SR))
    t = np.arange(n, dtype=np.float64) / SR
    f = frequency(midi)
    body = np.zeros(n, dtype=np.float64)
    # Higher strings get a little more sheen, still with a steep spectral rolloff.
    base_decay = (2.7 if silk else 3.5) * (146.83 / f) ** 0.18
    for harmonic in range(1, 10):
        partial_f = f * harmonic * (1.0 + 0.000055 * harmonic * harmonic)
        amplitude = harmonic ** (-1.7 if silk else -1.9)
        amplitude *= math.exp(-((partial_f / 1850.0) ** 2.8))
        decay = base_decay / harmonic ** 0.64
        phase = rng.uniform(-0.18, 0.18)
        # A very small initial relaxation replaces a hard electronic attack.
        relaxed_phase = 2.0 * math.pi * partial_f * (t + 0.00013 * (1.0 - np.exp(-t / 0.08)))
        body += amplitude * np.sin(relaxed_phase + phase) * np.exp(-t / decay)
    body += 0.045 * np.sin(2.0 * math.pi * f * 1.0017 * t) * np.exp(-t / (base_decay * 0.86))
    attack = 1.0 - np.exp(-t / (0.011 if silk else 0.015))
    tail = np.minimum(1.0, np.maximum(0.0, (length - t) / 0.22)) ** 2
    contact = filtered_noise(n, rng, 120.0, 1450.0)
    contact *= 0.015 * np.exp(-t / 0.022) * attack
    return ((body * attack + contact) * tail).astype(np.float32)


def flute(midi: int, length: float, rng: np.random.Generator) -> np.ndarray:
    """Low, airy xiao-like synthesis with natural swell and delayed vibrato."""
    n = max(1, round(length * SR))
    t = np.arange(n, dtype=np.float64) / SR
    f = frequency(midi)
    vibrato_rate = rng.uniform(4.25, 4.9)
    vibrato_depth = rng.uniform(3.0, 5.0)
    vibrato = vibrato_depth * np.sin(2.0 * math.pi * vibrato_rate * t + rng.uniform(-0.4, 0.4))
    vibrato *= 1.0 - np.exp(-t / 0.75)
    drift = 2.0 * np.sin(2.0 * math.pi * 0.26 * t + rng.uniform(-0.8, 0.8))
    entrance = -5.0 * np.exp(-t / 0.15)
    instantaneous_f = f * np.power(2.0, (vibrato + drift + entrance) / 1200.0)
    phase = 2.0 * math.pi * np.cumsum(instantaneous_f) / SR
    tone = np.sin(phase) + 0.115 * np.sin(2.0 * phase + 0.1)
    tone += 0.040 * np.sin(3.0 * phase - 0.3) + 0.012 * np.sin(4.0 * phase)
    attack = np.clip(t / rng.uniform(0.26, 0.40), 0.0, 1.0)
    attack = attack * attack * (3.0 - 2.0 * attack)
    release = np.clip((length - t) / min(0.85, length * 0.34), 0.0, 1.0)
    release = release * release * (3.0 - 2.0 * release)
    swell = 0.83 + 0.15 * np.sin(math.pi * t / max(length, 0.1))
    breath = filtered_noise(n, rng, 340.0, 1300.0)
    # Breath is only a quiet texture under the fundamental, not broad-band hiss.
    tone += 0.016 * breath
    return (tone * attack * release * swell).astype(np.float32)


def write_pcm24(path: Path, signal: np.ndarray) -> None:
    """Write standard signed little-endian 24-bit PCM using the standard library."""
    integer = np.rint(np.clip(signal, -1.0, 1.0) * 8_388_607).astype(np.int32).reshape(-1)
    packed = np.empty((len(integer), 3), dtype=np.uint8)
    packed[:, 0] = integer & 255
    packed[:, 1] = (integer >> 8) & 255
    packed[:, 2] = (integer >> 16) & 255
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(3)
        wav.setframerate(SR)
        wav.writeframes(packed.tobytes())


def loudness(path: Path) -> dict | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-af",
         "loudnorm=I=-29:TP=-9:LRA=8:print_format=json", "-f", "null", "-"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False,
    )
    matches = re.findall(r'\{\s*"input_i".*?\}', result.stderr, flags=re.S)
    if result.returncode or not matches:
        return None
    measured = json.loads(matches[-1])
    return {
        "integrated_lufs": float(measured["input_i"]),
        "true_peak_dbtp": float(measured["input_tp"]),
        "loudness_range_lu": float(measured["input_lra"]),
        "gating_threshold_lufs": float(measured["input_thresh"]),
        "method": "FFmpeg EBU R128 / loudnorm measurement only",
    }


def spectral_metrics(signal: np.ndarray) -> dict:
    # Averaged Hann-windowed spectra sampled across the whole finished score.
    n_fft = 16_384
    window = np.hanning(n_fft)
    mono = np.mean(signal, axis=1, dtype=np.float64)
    power = np.zeros(n_fft // 2 + 1)
    starts = range(0, max(1, len(mono) - n_fft), SR)
    for start in starts:
        frame = mono[start:start + n_fft]
        if len(frame) != n_fft:
            frame = np.pad(frame, (0, n_fft - len(frame)))
        power += np.abs(np.fft.rfft(frame * window)) ** 2
    hz = np.fft.rfftfreq(n_fft, 1.0 / SR)
    total = max(float(np.sum(power)), 1e-24)
    bands = [(0, 100), (100, 250), (250, 1000), (1000, 2000), (2000, 4000), (4000, 24000)]
    cumulative = np.cumsum(power) / total
    return {
        "centroid_hz": round(float(np.sum(hz * power) / total), 2),
        "rolloff_95_percent_hz": round(float(hz[min(int(np.searchsorted(cumulative, 0.95)), len(hz) - 1)]), 2),
        "energy_above_3000_hz_percent": round(float(np.sum(power[hz >= 3000]) / total * 100.0), 5),
        "energy_bands_percent": {
            f"{lo}-{hi}_hz": round(float(np.sum(power[(hz >= lo) & (hz < hi)]) / total * 100.0), 4)
            for lo, hi in bands
        },
        "method": "1-second-spaced 16384-point Hann FFT of mono sum",
    }


def compose(duration: float) -> tuple[np.ndarray, list[dict]]:
    rng = np.random.default_rng(SEED)
    count = round(duration * SR)
    signal = np.zeros((count, 2), dtype=np.float32)
    events: list[dict] = []

    def add(start: float, midi: int, length: float, amplitude: float, pan: float, kind: str) -> None:
        if start >= duration or length <= 0:
            return
        start = max(0.0, start)
        i = round(start * SR)
        n = min(round(length * SR), count - i)
        if n <= 0:
            return
        rendered = flute(midi, length, rng) if kind == "xiao_impression" else pluck(midi, length, rng, kind == "zheng_impression")
        rendered = rendered[:n] * amplitude
        # Close and restrained stereo placement, leaving a stable center for speech.
        angle = (float(np.clip(pan, -1.0, 1.0)) + 1.0) * math.pi / 4.0
        signal[i:i + n, 0] += rendered * math.cos(angle)
        signal[i:i + n, 1] += rendered * math.sin(angle)
        events.append({"time_seconds": round(start, 4), "midi": int(midi),
                       "duration_seconds": round(length, 4), "instrument_impression": kind})

    coda_length = min(20.0, max(7.0, duration * 0.12))
    coda_start = max(0.5, duration - coda_length)
    intro_length = min(10.3, max(1.0, duration * 0.09))
    add(0.35, 50, 6.7, 0.095, -0.17, "qin_impression")
    add(min(2.60, intro_length * 0.32), 57, 5.4, 0.050, 0.19, "qin_impression")
    if duration > 25:
        add(5.9, 64, 4.8, 0.036, 0.13, "zheng_impression")
        add(8.6, 59, 4.8, 0.032, -0.09, "qin_impression")

    # Breath-length timing varies continuously around 44 bpm and never quantizes
    # every onset. The score consists of related, newly written 4-bar sentences.
    beat_times = [intro_length]
    beat_index = 0
    while beat_times[-1] < coda_start + 24.0:
        local_bpm = 44.0 + 0.65 * math.sin(beat_index / 23.0) + 0.25 * math.sin(beat_index / 9.0)
        step = (60.0 / local_bpm) * rng.uniform(0.979, 1.021)
        beat_times.append(beat_times[-1] + step)
        beat_index += 1

    def at_beat(beat: float) -> float:
        whole = int(math.floor(beat))
        part = beat - whole
        return beat_times[whole] * (1.0 - part) + beat_times[whole + 1] * part

    # Each supporting gesture is sparse; bass strings omit bars to keep air under
    # speech. Roots are all in the same D pentatonic pitch collection.
    bass_roots = [38, 38, 47, 45, 40, 47, 45, 38]
    support_pairs = [(50, 57), (52, 59), (54, 59), (50, 57), (52, 57), (54, 59), (52, 57), (50, 57)]
    bar = 0
    while at_beat(bar * 4.0) < coda_start - 2.0:
        bar_start = at_beat(bar * 4.0)
        root = bass_roots[bar % len(bass_roots)]
        if bar % 2 == 0 or rng.random() < 0.19:
            add(bar_start + rng.uniform(-0.04, 0.08), root, 7.0,
                rng.uniform(0.038, 0.052), rng.uniform(-0.07, 0.07), "qin_impression")
        pair = support_pairs[bar % len(support_pairs)]
        offsets = [rng.uniform(0.65, 1.3), rng.uniform(2.35, 3.1)]
        if bar % 7 == 4:
            offsets = offsets[:1]
        for note_index, offset in enumerate(offsets):
            start = at_beat(bar * 4 + offset)
            if start < coda_start - 1.0:
                add(start, pair[note_index % 2], rng.uniform(4.3, 5.8),
                    rng.uniform(0.019, 0.032), rng.uniform(-0.24, 0.24), "qin_impression")
        bar += 1

    motifs = [
        # Original melodic sentences, rather than public-domain tune quotations.
        [(0.8, 5, 1.1), (3.0, 6, 1.4), (5.3, 7, 2.1), (8.4, 6, 1.0), (10.2, 4, 1.3), (12.4, 3, 1.2), (14.1, 5, 1.4)],
        [(1.0, 4, 1.5), (3.2, 5, 1.4), (5.4, 7, 1.7), (8.0, 8, 1.6), (10.4, 7, 1.2), (12.5, 6, 1.3), (14.4, 5, 1.3)],
        [(0.9, 7, 1.8), (3.8, 6, 1.2), (5.8, 5, 1.9), (8.7, 4, 1.3), (10.8, 3, 1.3), (12.7, 4, 1.1), (14.5, 5, 1.1)],
        [(1.3, 5, 1.6), (4.0, 3, 1.2), (6.1, 2, 1.6), (8.8, 3, 1.2), (10.7, 4, 1.1), (12.7, 6, 1.3), (14.5, 5, 1.2)],
    ]
    # Large-scale contour: establish, open up, breathe, return. A few phrases
    # carry the xiao image; others remain all strings or contain deliberate rests.
    phrase_order = [0, 2, 1, 3, 1, 2, 3, 0, 2, 1, 3, 0]
    phrase = 0
    while at_beat(phrase * 16.0) < coda_start - 7.0:
        use_flute = phrase % 4 in (1, 2)
        motif = motifs[phrase_order[phrase % len(phrase_order)]]
        phrase_amp = [0.072, 0.054, 0.050, 0.064][phrase % 4]
        for note_index, (offset, scale_index, beats_held) in enumerate(motif):
            if phrase % 5 == 3 and note_index in (1, 4):
                continue
            # A sentence keeps its contour while changing one passing tone, one
            # rest, breathing time, and articulation. No looped waveform is used.
            if phrase > 3 and note_index == 2 and phrase % 2 == 0:
                scale_index = max(2, scale_index - 1)
            start = at_beat(phrase * 16 + offset) + rng.uniform(-0.055, 0.095)
            if start > coda_start - 3.0:
                continue
            midi = int(SCALE[scale_index])
            kind = "xiao_impression" if use_flute else ("zheng_impression" if scale_index >= 6 else "qin_impression")
            if use_flute:
                length = (at_beat(phrase * 16 + offset + beats_held) - at_beat(phrase * 16 + offset)) + rng.uniform(0.05, 0.30)
                length = min(length, coda_start - start + 0.25)
                amp = phrase_amp * rng.uniform(0.89, 1.06)
                pan = rng.uniform(0.04, 0.13)
            else:
                length = rng.uniform(4.4, 6.0)
                amp = phrase_amp * rng.uniform(0.84, 1.05)
                pan = rng.uniform(-0.21, 0.18)
            add(start, midi, length, amp, pan, kind)
        phrase += 1

    # Warm resolution: B -> A -> E -> D, then low D and A. Final sounding note
    # starts before the four-second master fade, so the end releases naturally.
    for position, midi, amp in [(0.02, 59, 0.047), (0.19, 57, 0.051),
                                (0.37, 64, 0.038), (0.56, 62, 0.047),
                                (0.67, 50, 0.061), (0.70, 38, 0.034),
                                (0.73, 57, 0.020)]:
        start = coda_start + coda_length * position
        add(start, midi, min(7.8, duration - start), amp, -0.12 if midi < 60 else 0.08, "qin_impression")
    if duration > 35:
        start = coda_start + coda_length * 0.41
        add(start, 62, min(coda_length * 0.30, 5.8), 0.034, 0.10, "xiao_impression")

    # Small dark room: many quiet, non-periodic reflections instead of a loud
    # conspicuous echo. Stereo cross-reflections soften each isolated pluck.
    dry = signal.copy()
    for delay, gain, cross in [(0.039, 0.034, True), (0.083, 0.027, False),
                              (0.149, 0.022, True), (0.239, 0.017, False),
                              (0.367, 0.018, True), (0.523, 0.015, False),
                              (0.719, 0.011, True), (0.947, 0.009, False),
                              (1.213, 0.006, True), (1.571, 0.004, False)]:
        shift = round(delay * SR)
        if shift < count:
            source = dry[:-shift, ::-1] if cross else dry[:-shift]
            signal[shift:] += source * gain

    # Exact endpoint fades apply to all synthesis and reflections.
    fade_in = min(3.0, duration / 3.0)
    fade_out = min(4.0, duration / 3.0)
    in_n, out_n = round(fade_in * SR), round(fade_out * SR)
    signal[:in_n] *= (np.sin(np.linspace(0.0, math.pi / 2.0, in_n)) ** 2).astype(np.float32)[:, None]
    signal[-out_n:] *= (np.sin(np.linspace(math.pi / 2.0, 0.0, out_n)) ** 2).astype(np.float32)[:, None]
    # The track is deliberately quiet beneath spoken Chinese. No compression or
    # limiters pump the tails; a linear gain preserves articulation and silence.
    rms = float(np.sqrt(np.mean(signal.astype(np.float64) ** 2)))
    signal *= (10.0 ** (-31.0 / 20.0)) / max(rms, 1e-9)
    peak = float(np.max(np.abs(signal)))
    signal *= min(1.0, (10.0 ** (PEAK_CEILING_DBFS / 20.0)) / max(peak, 1e-9))
    signal[0] = 0.0
    signal[-1] = 0.0
    return signal, sorted(events, key=lambda event: event["time_seconds"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duration", type=float, default=205.0, help="Duration in seconds (10 to 1800).")
    parser.add_argument("--out", type=Path, required=True, help="Output 48 kHz stereo 24-bit PCM WAV path.")
    args = parser.parse_args()
    if not math.isfinite(args.duration) or not 10.0 <= args.duration <= 1800.0:
        parser.error("--duration must be a finite value from 10 to 1800 seconds")
    out = args.out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    signal, events = compose(args.duration)
    write_pcm24(out, signal)
    meter = loudness(out)
    if meter and math.isfinite(meter["integrated_lufs"]):
        gain = 10.0 ** ((TARGET_LUFS - meter["integrated_lufs"]) / 20.0)
        sample_peak = float(np.max(np.abs(signal)))
        gain = min(gain, (10.0 ** (PEAK_CEILING_DBFS / 20.0)) / max(sample_peak, 1e-9))
        signal *= gain
        write_pcm24(out, signal)
        meter = loudness(out)
    peak = float(np.max(np.abs(signal)))
    rms = np.sqrt(np.mean(signal.astype(np.float64) ** 2, axis=0))
    metrics = {
        "title": "瓷证·藏影疏弦",
        "provenance": "Original deterministic procedural score and synthesis; instrument impressions only; no external samples or tune quotations.",
        "seed": SEED,
        "duration_seconds": len(signal) / SR,
        "sample_rate_hz": SR,
        "channels": 2,
        "encoding": "24-bit signed little-endian PCM WAV",
        "pitch_collection": "D major pentatonic (D, E, F#, A, B)",
        "pulse_bpm": "Approximately 44, with gradual drift and uneven breath-length timing",
        "fade_in_seconds": min(3.0, args.duration / 3.0),
        "fade_out_seconds": min(4.0, args.duration / 3.0),
        "sample_peak_dbfs": round(db(peak), 3),
        "rms_dbfs_per_channel": [round(db(float(value)), 3) for value in rms],
        "dc_offset_per_channel": [round(float(value), 10) for value in np.mean(signal, axis=0, dtype=np.float64)],
        "clipped_samples": int(np.count_nonzero(np.abs(signal) >= 1.0)),
        "first_sample": signal[0].tolist(),
        "last_sample": signal[-1].tolist(),
        "event_count": len(events),
        "loudness": meter,
        "spectrum": spectral_metrics(signal),
        "wav_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    sidecar = out.with_suffix(".metrics.json")
    sidecar.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.with_suffix(".score.json").write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wav": str(out), "metrics": str(sidecar), "duration_seconds": metrics["duration_seconds"],
                      "sample_peak_dbfs": metrics["sample_peak_dbfs"], "loudness": meter,
                      "spectrum": metrics["spectrum"], "sha256": metrics["wav_sha256"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
