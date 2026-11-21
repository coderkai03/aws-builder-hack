"""Builds the demo soundtrack: Kokoro TTS narration + synthesized SFX, timed to the recording.

Usage: python demo/soundtrack.py <kokoro.onnx> <voices.bin> <video.mp4> <out.mp4>
Cue times come from demo/record.js's log of a live run.
"""
import subprocess
import sys

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

SR = 24000
VOICE = "af_heart"

# (start second, line, latest second it must end by)
NARRATION = [
    (0.6, "Meet North Star: an autonomous growth P.M. that runs your A/B tests, end to end.", 7.3),
    (7.8, "Growth teams ship maybe one experiment a week. North Star runs the whole loop: observe, diagnose, "
          "design, launch, protect revenue, decide, and learn. The model makes the judgment calls. "
          "Code enforces the safety.", 20.6),
    (21.2, "This is the control room. Every sponsor integration is live.", 26.2),
    (26.8, "We seed three thousand simulated visitors. The weakest step: only thirty-five percent finish signing up.",
     35.2),
    (35.8, "Now we run the agent. It reads the funnel, split by mobile and desktop, recalls lessons from past "
           "experiments in its Cognee knowledge graph, and reasons over the data with Qwen, "
           "on Superlinked's serverless inference.", 52.0),
    (53.0, "Every decision is logged, with the exact model output and cost.", 64.5),
    (65.2, "It designed an experiment. Variants are just parameters, so nothing needs a deploy. "
           "A stakeholder also asked to test hiding pricing. The revenue guardrail will decide. "
           "Nothing launches without a human, so we approve.", 80.4),
    (82.4, "The experiment is now created and running in Statsig.", 87.9),
    (88.4, "Traffic flows into Amplitude and SingleStore.", 93.7),
    (94.3, "There it is. Hiding pricing got more signups, but crushed revenue per user, "
           "so North Star killed that variant in Statsig, automatically.", 112.8),
    (113.8, "We have a clear winner. North Star shipped it in Statsig and wrote a decision memo with the numbers. "
            "The learnings go into Cognee, for the next experiment.", 129.0),
    (129.6, "And every step is in the audit trail.", 135.6),
    (136.2, "None of this is a mock-up. This slide reads live state back from Statsig, SingleStore, "
            "Amplitude, Cognee, and Superlinked.", 151.5),
    (152.2, "North Star. Your experiments on autopilot, with revenue protected.", 160.0),
]

# (second, kind)
SFX = [(7.5, "whoosh"), (20.8, "whoosh"), (26.3, "click"), (35.3, "click"), (80.6, "click"), (88.0, "click"),
       (93.9, "alert"), (113.4, "chime"), (129.2, "click"), (135.8, "whoosh"), (151.8, "whoosh")]


def tone(freq, dur, vol=0.5, decay=6.0):
    t = np.arange(int(SR * dur)) / SR
    return vol * np.sin(2 * np.pi * freq * t) * np.exp(-decay * t)


def sfx(kind):
    rng = np.random.default_rng(7)
    if kind == "click":
        n = int(SR * 0.05)
        return 0.6 * rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * 0.006)) + tone(1800, 0.05, 0.3, 80)
    if kind == "whoosh":
        n = int(SR * 0.6)
        noise = rng.standard_normal(n)
        # simple moving-average low-pass with a sweeping window, shaped by a rise/fall envelope
        out = np.convolve(noise, np.ones(24) / 24, mode="same")
        env = np.sin(np.linspace(0, np.pi, n)) ** 2
        return 0.9 * out * env
    if kind == "alert":
        a = np.concatenate([tone(880, 0.16, 0.45, 4), np.zeros(int(SR * 0.05)), tone(660, 0.28, 0.45, 4)])
        return a
    if kind == "chime":
        parts = [tone(f, 0.9, 0.3, 3.5) for f in (523.25, 659.25, 783.99)]
        out = np.zeros(int(SR * 1.3))
        for i, p in enumerate(parts):
            s = int(SR * 0.12 * i)
            out[s:s + len(p)] += p
        return out
    raise ValueError(kind)


def place(track, clip, at):
    s = int(at * SR)
    e = min(len(track), s + len(clip))
    track[s:e] += clip[: e - s]


def main(model, voices, video, out):
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                         "-of", "csv=p=0", video]).strip())
    kokoro = Kokoro(model, voices)
    voice = np.zeros(int(SR * (dur + 1)))
    for start, text, end_by in NARRATION:
        speed = 1.0
        for _ in range(4):
            samples, sr = kokoro.create(text, voice=VOICE, speed=speed, lang="en-us")
            assert sr == SR
            length = len(samples) / SR
            if start + length <= end_by:
                break
            speed = min(1.35, speed * (length / (end_by - start)) * 1.02)
        print(f"{start:6.1f}s  {length:5.1f}s  speed {speed:.2f}  {text[:60]}")
        place(voice, samples, start)
    fx = np.zeros_like(voice)
    for at, kind in SFX:
        place(fx, sfx(kind), at)
    mix = voice * 1.0 + fx * 0.35
    mix = mix / max(1.0, np.abs(mix).max() / 0.95)
    sf.write(out + ".wav", mix.astype(np.float32), SR)
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", out + ".wav",
                           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out])


if __name__ == "__main__":
    main(*sys.argv[1:5])
