# Launch video playbook

How we make hackathon demo videos. Judges watch dozens of projects back to back, so the video has
to land within the first minute. Treat it as a **startup launch video**, not a conference talk.

## Rules

1. **60 seconds.** No dead air: keep the narration continuous and every beat short.
2. **Hook in the first 5 seconds.** Open on the problem as a punchy, slightly provocative line
   ("Your A/B test is losing money."), not on the product name or a title slide.
3. **Name and one-line promise next.** Logo reveal plus a single tagline.
4. **Never show a whole page.** Show the one element that matters (a number, a badge, a button)
   and move the camera to it: push-ins, pans, slight 3D tilt. Crop everything else.
5. **Few words on screen, big type.** One short headline per beat. Put the key number huge and
   animate it (count up). If a sentence needs reading, it's too long.
6. **One beat per idea, about 8–10 seconds each.** Number the beats ("01 · Diagnose") so the
   structure is obvious.
7. **Lead with the money moment.** Give the most dramatic proof (here: the guardrail killing a
   variant) the longest beat, a flash, an impact sound and a pause in the music.
8. **Sound carries the energy.** Short narration lines that match the on-screen beat, a music bed
   that ducks under the voice, whooshes on cuts, an impact on the big number, a chime on success.
9. **Partners as a fast wall.** One verb each ("Superlinked thinks, Statsig acts…"), not a table.
10. **End card: name, tagline, link.** Hold it for 5 seconds.
11. **Be honest in a footnote.** If data is simulated, say so in small text once. Every number on
    screen must come from a real run.

## Pipeline (in `demo/cinematic/`)

1. `capture.js`: drive a live run and save crisp element screenshots at 2x plus the run's numbers.
2. `launch.html`: the motion-graphics timeline (kinetic type, camera moves on the screenshots),
   reading real numbers from `assets/run.js`.
3. `render.js`: record the timeline at 1920×1080 with Playwright.
4. `soundtrack.py`: Kokoro narration + synthesized music bed + SFX, timed to the same cue sheet,
   then muxed into the final MP4.
