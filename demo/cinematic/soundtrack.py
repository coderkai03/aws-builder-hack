"""Step 3: launch-video soundtrack = Kokoro narration + synthesized music bed + SFX, timed to launch.html.

Usage: python demo/cinematic/soundtrack.py <kokoro.onnx> <voices.bin> <video.mp4> <out.mp4>
"""
import subprocess
import sys

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

SR = 24000
VOICE = "af_heart"
BPM = 118
BEAT = 60 / BPM

# (start, line, must end by): near-continuous voice, beats every few seconds
NARRATION = [
    (0.2, "Your A/B test is losing money.", 2.6),
    (2.7, "And nobody's watching it.", 4.7),
    (4.9, "Meet North Star, the autonomous growth P.M.", 8.1),
    (8.3, "It runs your experiments end to end, from diagnosis to decision.", 12.6),
    (12.9, "First, it finds the leak: mobile users finish signup far less often than desktop users.", 18.6),
    (18.9, "Then it designs the test. You approve with one click, and it goes live in Statsig.", 24.8),
    (25.1, "When a variant starts losing money,", 27.7),
    (27.9, "revenue down forty-two percent,", 29.9),
    (30.0, "North Star kills it, automatically, before it costs you more.", 33.9),
    (34.1, "Then it ships the winner.", 35.6),
    (35.7, "Thirty-five percent more signups, shipped in Statsig.", 39.3),
    (39.6, "And it remembers what it learned, so the next test is smarter.", 42.9),
    (43.1, "Built on Superlinked, Statsig, Amplitude, SingleStore, and Cognee.", 49.3),
    (49.6, "Under a cent per experiment. A human approves every launch. Every decision is audited.", 54.4),
    (54.7, "North Star. Ship experiments on autopilot.", 59.5),
]

WHOOSH = [2.5, 4.7, 8.1, 12.7, 18.7, 24.9, 33.9, 39.4, 42.9, 49.4, 54.4]
IMPACT = [4.8, 27.8, 54.5]
CHIME = [35.6]
CLICK = [22.8]
TICKS = [43.2 + i * 0.62 for i in range(5)]
RISERS = [(3.3, 4.8), (26.3, 27.8)]
DRUMS_IN, HATS_IN, BREAK, OUTRO = 4.8, 8.2, (26.3, 27.8), 54.5


def env(n, a=0.005, r=0.2):
    t = np.arange(n) / SR
    return np.minimum(1, t / a) * np.exp(-t / r)


def osc(freq, dur, kind="sine"):
    t = np.arange(int(SR * dur)) / SR
    ph = 2 * np.pi * freq * t
    if kind == "saw":
        return 2 * ((freq * t) % 1) - 1
    if kind == "tri":
        return 2 * np.abs(2 * ((freq * t) % 1) - 1) - 1
    return np.sin(ph)


def lowpass(x, k=12):
    return np.convolve(x, np.ones(k) / k, mode="same")


def kick():
    n = int(SR * 0.45)
    t = np.arange(n) / SR
    f = 50 + 110 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)


def hat(rng):
    n = int(SR * 0.06)
    x = rng.standard_normal(n)
    x = x - lowpass(x, 4)
    return 0.35 * x * np.exp(-np.arange(n) / (SR * 0.012))


def pad_chord(freqs, dur):
    out = np.zeros(int(SR * dur))
    for f in freqs:
        for det in (-0.15, 0.15):
            out += lowpass(osc(f * (1 + det / 100), dur, "saw"), 30) * 0.12
    n = len(out)
    fade = np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (SR * 0.6))
    return out * fade


def music(total, rng):
    out = np.zeros(int(SR * total))
    # A minor progression: Am - F - C - G, two bars each
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [261.63, 329.63, 392.0], [196.0, 246.94, 293.66]]
    bar = BEAT * 4
    t, i = 0.0, 0
    while t < total:
        c = pad_chord(chords[i % 4], bar * 2 + 0.6)
        place(out, c * (0.55 if t < DRUMS_IN else 1.0), t)
        bass = lowpass(osc(chords[i % 4][0] / 2, bar * 2, "tri"), 8) * 0.22
        if t >= DRUMS_IN:
            place(out, bass * np.minimum(1, np.arange(len(bass)) / (SR * 0.02)), t)
        t += bar * 2
        i += 1
    # drums from the logo reveal on, pause during the kill's suspense, full energy after
    b = DRUMS_IN
    while b < total - 2:
        quiet = BREAK[0] <= b < BREAK[1] or b >= OUTRO
        if not quiet:
            place(out, kick() * 0.8, b)
            if b >= HATS_IN:
                place(out, hat(rng), b + BEAT / 2)
        b += BEAT
    return out


def sfx_whoosh(rng):
    n = int(SR * 0.7)
    x = lowpass(rng.standard_normal(n), 20)
    return 0.9 * x * np.sin(np.linspace(0, np.pi, n)) ** 3


def sfx_impact(rng):
    n = int(SR * 1.6)
    t = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(40 + 60 * np.exp(-t * 10)) / SR) * np.exp(-t * 2.2)
    noise = lowpass(rng.standard_normal(n), 6) * np.exp(-t * 9) * 0.5
    return boom + noise


def sfx_riser(dur, rng):
    n = int(SR * dur)
    t = np.arange(n) / SR
    sweep = np.sin(2 * np.pi * np.cumsum(200 + 1400 * (t / dur) ** 2) / SR) * 0.25
    noise = lowpass(rng.standard_normal(n), 10) * 0.5
    return (sweep + noise) * (t / dur) ** 2


def sfx_chime():
    out = np.zeros(int(SR * 1.8))
    for i, f in enumerate((523.25, 659.25, 783.99, 1046.5)):
        s = int(SR * 0.09 * i)
        tone = osc(f, 1.4) * env(int(SR * 1.4), 0.004, 0.45) * 0.35
        out[s:s + len(tone)] += tone
    return out


def sfx_click(rng):
    n = int(SR * 0.05)
    return 0.7 * rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * 0.005))


def sfx_tick():
    return osc(1600, 0.08) * env(int(SR * 0.08), 0.001, 0.02) * 0.5


def place(track, clip, at):
    s = int(at * SR)
    e = min(len(track), s + len(clip))
    if e > s:
        track[s:e] += clip[: e - s]


def main(model, voices, video, out):
    total = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                           "-of", "csv=p=0", video]).strip())
    rng = np.random.default_rng(11)
    kokoro = Kokoro(model, voices)
    voice = np.zeros(int(SR * (total + 1)))
    for start, text, end_by in NARRATION:
        speed = 1.12
        for _ in range(4):
            samples, sr = kokoro.create(text, voice=VOICE, speed=speed, lang="en-us")
            length = len(samples) / SR
            if start + length <= end_by:
                break
            speed = min(1.35, speed * (length / (end_by - start)) * 1.02)
        print(f"{start:5.1f}s {length:4.1f}s x{speed:.2f} {text}")
        place(voice, samples, start)

    mus = np.zeros_like(voice)
    place(mus, music(total, rng), 0)
    # duck the music under the voice
    level = np.sqrt(lowpass(voice ** 2, int(SR * 0.25)))
    duck = 1 - 0.55 * np.clip(level / 0.05, 0, 1)
    mus *= lowpass(duck, int(SR * 0.1))
    fade = np.ones_like(mus)
    end = int(SR * (total - 2.5))
    fade[end:] = np.linspace(1, 0, len(fade) - end)
    mus *= fade

    fx = np.zeros_like(voice)
    for t in WHOOSH:
        place(fx, sfx_whoosh(rng) * 0.5, t)
    for t in IMPACT:
        place(fx, sfx_impact(rng) * 0.8, t)
    for a, b in RISERS:
        place(fx, sfx_riser(b - a, rng) * 0.6, a)
    for t in CHIME:
        place(fx, sfx_chime(), t)
    for t in CLICK:
        place(fx, sfx_click(rng), t)
    for t in TICKS:
        place(fx, sfx_tick(), t)

    mix = voice * 1.0 + mus * 0.32 + fx * 0.45
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    sf.write(out + ".wav", mix.astype(np.float32), SR)
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", out + ".wav",
                           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out])


if __name__ == "__main__":
    main(*sys.argv[1:5])
