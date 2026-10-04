# HUD browser tests

Covers what the Python suite cannot: the rendered panels, the controls,
and the two behaviours that only a real browser proves —

- a note filename containing markup renders as **text**, not markup;
- the HUD survives the backend going away and coming back, blanking to
  `—` in between rather than showing stale numbers;
- the voice path works end to end — the HUD's own WAV encoder produces
  something the server accepts, a transcript routes like a typed command,
  and synthesised audio plays back with the output meter driven by its
  own samples.

These are kept separate from `tests/test_server.py` because they need
Node and a Chromium build. The Python suite stays dependency-free and is
the one to run by default.

## Run

```sh
cd tests/ui
npm install
npm test
```

The suite starts its own server on port 7870 against a throwaway vault it
generates in a temp directory, so it never touches your real vault. It
refuses to start if something is already serving that port — otherwise
the offline test would pass against the wrong process.

The voice phase restarts that server with stand-in speech tools it writes
itself, so no model has to be installed to run the suite.

**Microphone capture is not covered here.** It needs an audio device, and
a container usually has none — not even a fake one, since Chromium's
`--use-fake-device-for-media-capture` still wants an audio backend. On a
machine without a microphone the suite asserts the honest failure instead
(`microphone unavailable`, `MIC BLOCKED`, meters left at rest), and drives
the rest of the chain — encoding, upload, transcription, routing and
playback — through the HUD's own functions. `getUserMedia` and
`MediaRecorder` are the two steps you have to try by hand.

## Options

| Variable | Purpose |
| --- | --- |
| `PORT` | Serve on a different port (default 7870) |
| `CHROMIUM_PATH` | Use a Chromium already on the machine instead of Playwright's own |

`CHROMIUM_PATH` matters when the installed Playwright expects a browser
build you do not have:

```sh
CHROMIUM_PATH=/path/to/chrome npm test
```
