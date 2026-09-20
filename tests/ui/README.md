# HUD browser tests

Covers what the Python suite cannot: the rendered panels, the controls,
and the two behaviours that only a real browser proves —

- a note filename containing markup renders as **text**, not markup;
- the HUD survives the backend going away and coming back, blanking to
  `—` in between rather than showing stale numbers.

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
