# Distributed Operations — working phase plan

Derived from the *OBEOS Assistant HUD Distributed Operations Patch*. The
patch's architecture is sound; this plan changes the **order** it is built
in and pins down four decisions the patch leaves open.

Numbers here are measured on this repository, not estimated. Re-measure
with `tools/bench.py` rather than trusting this file.

---

## Why the order changes

The patch puts instrumentation last (AO-11) while every success criterion
in §32 is comparative — "improves compared with the pre-patch baseline."
You cannot build the baseline after eleven phases of change and still have
a pre-patch baseline. Measurement has to come first.

Two further reorderings follow from risk: authentication must land before
anything is exposed on a network, and the local-only phases deliver most
of the latency win with none of the distributed-systems risk, so they go
before the cloud half.

| Order | Phase | State | Risk |
| --- | --- | --- | --- |
| 1 | **AO-0** Instrumentation + baseline | **done** | none |
| 2 | **AO-2** Prepared state (local) | **done** | none |
| 3 | **AO-4** HUD fast path | mostly done | none |
| 4 | **Auth** (new, was implicit in §27) | not started | blocks AO-5/6 |
| 5 | **AO-3** Local workers | not started | local only |
| 6 | **AO-5a** Cloud workers, no model | not started | first network hop |
| 7 | **AO-6** Local ↔ cloud sync | not started | distributed |
| 8 | **AO-5b** Cloud reasoning | unjustified so far | cost |
| 9 | AO-7 Task router, AO-8 Alerts, AO-9 DAISE bridge, AO-10 Lathe | not started | — |

Steps 1–3 are shipped and are independently useful even if the cloud half
never happens.

---

## Measured so far

Captured with `tools/bench.py` against a generated 842-note vault — the
same note count the original mock HUD displayed.

| | Before | After AO-2 |
| --- | --- | --- |
| `/api/vault/stats` | 20.2 ms | 0.8 ms |
| `/api/vault/activity` | 16.8 ms | 0.8 ms |
| `/api/vault/graph` | 23.2 ms | 0.8 ms |
| **HUD vault refresh** (all three, concurrent) | **188.0 ms** | **2.1 ms** |

Against the patch's §17 target of `< 250 ms` for a cached HUD render: the
pre-patch code passed at 842 notes but scaled linearly with the vault and
would have missed it around ~1,100 notes. It now has roughly two orders of
magnitude of headroom.

The cause was three independent full traversals per refresh. `vault.scan()`
now walks once, and `vault_cache` keeps that snapshot warm in the
background, so a request reads prepared state instead of the filesystem.

**Known outlier:** `/api/vitals` measures ~97 ms under back-to-back
polling, because the `/proc/stat` CPU probe takes a fresh 100 ms sample
when the counters have not moved enough to be meaningful. At the HUD's
real 5-second cadence it is sub-millisecond. Moving that probe into a
worker belongs to **AO-3**, not here.

---

## Four decisions the patch leaves open

### 1. Ownership replaces conflict resolution

§10 asks the sync layer to reject stale and out-of-order updates, and
AO-6 lists "conflict policy" as a deliverable, but no policy is given.
Do not write one — make conflicts impossible by construction:

- `blackcomputer.*`, `lathe.*` → **local is the only writer.** Cloud caches, never writes.
- `cloud.*`, external API polls → **cloud is the only writer.** Local caches, never writes.

Every key has exactly one authoritative node, so sync is last-writer-wins
within a single writer, which is trivially correct. No merge logic, no
split brain.

### 2. Order by sequence, never by clock

§10's example orders by wall-clock timestamp. Two machines drift, and
rejecting "stale" updates by comparing timestamps *across* nodes will
silently drop valid data. Order by the per-node `sequence` number the
patch already carries; treat timestamps as display metadata only.

### 3. Authentication before the tailnet

§27 requires authenticated nodes and per-node permissions. Today the
server has **no authentication at all** — it is safe only because it binds
`127.0.0.1`. Tailscale provides transport encryption and network identity,
not per-request authorization. The moment the API is on a tailnet, every
device there can `POST /api/command` unauthenticated. This is a hard
prerequisite for AO-5 and AO-6, not parallel work.

### 4. "The same brain" needs a model named

§4 and §7 say both instances share reasoning behaviour, but the patch
never says what model the cloud Assistant runs. Local runs Ollama. Same
skills plus a different model is not one brain in two places; it is one
set of instructions read by two different intelligences, and they will
disagree on exactly the ambiguous operational calls where consistency
matters most.

Decide explicitly. If the answer is different models, drop the "same
brain" framing and define which decisions each node may make on its own.

---

## Smaller corrections

**Alerts need hysteresis.** §23–24 list rule types but no debounce. A
naive `cpu > 80` on a 5-second poll will flap and produce alert storms,
and people mute alert storms. Alerts need sustained-duration conditions
(`> 80% for 60s`), separate clear thresholds (fire at 80, clear at 70),
and per-rule cooldowns.

**Age travels with every value.** §20 puts `last_event_age_ms` in the
Lathe state; that is right and should be universal. A number crossing a
node boundary with no age is a number you cannot trust. The vault
endpoints already return `built_at` and `age_ms`, and the HUD shows the
snapshot age in the Vault Intelligence header.

**"Restart monitored service" is not low-risk.** §22 lists it among safe
controls. Restarting Ollama mid-inference, or the Lathe connector with
positions open, has real blast radius. Wire it to the §27 command
allowlist, per service, with confirmation and audit.

**State is not memory, and the boundary needs to be mechanical.** §28
draws the distinction but never reconciles it with this project's own
first rule — *if it is not in the vault, it did not happen*. Proposal:
SQLite holds state with a retention window (raw metrics ~7 days, hourly
rollups ~90 days) and is explicitly disposable; only alerts and incidents
graduate to the vault as durable notes.

---

## Dependencies outside this repository

AO-10 assumes Lathe already publishes the twelve events listed in §19.
Neither Lathe, Earth, BlackForge, Sentinel nor `event_backbone` exists in
this repository, and the patch carries no dependency ordering on whether
those subsystems are ready to publish. Confirm that before scheduling
AO-10.
