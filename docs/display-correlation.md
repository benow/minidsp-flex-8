# Display ↔ audio correlation — the music now-playing chain

Andy's bar (2026-10-11): "the information for display, should it be happening,
correlates with what is being played." This doc records the chain, the sweep that
verifies it, the divergences found, and their fixes.

## The chain (who knows what is playing)

```
station agent pump ──track.started──► StationEventIngestor
  (AUDIO truth: the pump feeding the mount/player)      │
                                        ┌──────────────┴───────────────┐
                                        ▼                              ▼
                     now-playing store (per-user)          SSE music.track-changed
                     → GET /api/music/playlists/now-playing   (title/artist/album payload
                       {state, currentTrackId, position,        the UI listens to)
                        items[]}                                     │
                                        │                             ▼
                          every display consumer            NowPlayingDialog invalidates
                          (web UI, TV overlay, phone,        → refetches now-playing
                           HA integration)                   → renders
```

Structural skew (by design, measured): the display fires at the **boundary** — the
moment the agent starts feeding a track — while the ear hears it ~3-6 s later (the
player's 512 KB prebuffer + ALSA buffer). Display LEADS audio by a small constant;
that is correct behavior. The bugs this sweep hunts are the *gross* divergences:
display trackless, display stuck on an old track, display "paused/stopped" while
audio plays.

## The sweep

`scripts/display-correlation-sweep.py` — drives every queue permutation and asserts
the display (API + SSE + boundary log) each time:

| Step | Permutation | What must correlate |
|---|---|---|
| S1 | play-album | state playing + a currentTrackId immediately (even before the station serves) + queue + art + SSE track-changed at the first boundary |
| S2/S3 | next-track ×2 | currentTrackId follows each skip |
| S4 | prev-track | restarts the current track (documented semantics) |
| S5 | pause | state paused AND audio actually stops |
| S6 | resume | state playing AND audio resumes (cold restart, slow) |
| S7 | enqueue album | queue grows, current untouched |
| S8 | next-album | display jumps to the next album group's first track |
| S9 | play-from item | display jumps to the tapped item |
| S10 | queue-next album | inserted right after current |
| S11 | delete item | only the target leaves |
| S12 | boundary crossing | short track (58.5 s) ends → display advances to the NEXT track; audio keeps flowing |
| S13 | clear | queue empties AND audio stops |
| S14 | stop | state stopped AND ALSA closes |

Run: `SSE_LOG=/tmp/sse2.log python3 scripts/display-correlation-sweep.py` with a
token in /tmp/.ntok, an SSE capture (`curl -sN '…/api/events/stream?access_token=…'
> /tmp/sse2.log`) and a backend-log capture (`ssh … docker logs -f`) running.

## Divergences found (2026-10-11) and their fixes

1. **currentTrackId was never written by the audio path** (nastv d6e42810, live —
   log line `now-playing → track N at index i` observed). The ingestor published the
   SSE event but only explicit controller actions wrote the store — an album play and
   every skip left `currentTrackId: null` for 55 s+ while the station served. Fix:
   `StationEventIngestor` writes the store at each audio-true `track.started`.
2. **play-album showed "playing" with no track during the cold-start window**
   (12-56 s measured). Fix: `PlayAlbum` seeds from the session snapshot, resume-aware
   (`TrackIds[Cursor]` when a parked cursor exists); the ingestor overrides at the
   first real boundary.
3. **Pause was a display lie** — it flipped the state string only; the station kept
   pumping and the player kept playing (measured: 30 s of full-rate hw_ptr advance
   under `paused`). Fix: pause parks the station (audio genuinely stops; resume
   re-starts from the parked cursor via the existing play path). Pause is slug-wide
   (shared broadcast) — per-listener pause is a later design reach.
4. **Clear wiped the display but left audio running** (`state=stopped`,
   `alsa=RUNNING` observed). Fix: clear parks the station too — audio, queue and
   display end together.
5. **A mid-session queue mutation was invisible to the live station** (S8's
   persistent 409): the session's TrackIds are a start-time snapshot — enqueueing
   an album while playing showed it in the queue pane but the pump could never
   reach it and next-album returned 409. Fix: `RefreshQueueAsync` re-places the
   cursor on the currently-playing track after every queue mutation
   (enqueue/remove; queue-next already had its own live insert). Unit test added.
6. **A failed audio-ticket issuance silently degraded to the icecast mount** — the
   resume that never resumed (S6, 2026-10-11): `playerUrl = ticket ?? mount`, and the
   VLC path cannot play the un-sourced mount ("mount not sourced yet"), logged only
   at Debug. Fix: 3× retry in the session start + WARNING (client log Debug→Warning)
   naming the consequence.

## Results (2026-10-11, after all fixes, one stable build)

Sweep: **17/18 assertions green**, and the one red is agent-side, not display-side:
mid-hold the agent's icecast sink stalled and dropped the short track early
(`sink 'icecast' stalled — dropped` at 21:13:11), the pump pulled the next track
(boundary 21:13:13) but the agent never emitted `track.started` for it — so the
display stayed on the dropped track while the audio moved on. Every healthy
boundary correlated within ~1-2 ms server-side (track.started 21:12:33.499 →
now-playing 21:12:33.500). Evidence lives in the outstanding item
`music/station-start-flap-and-double-publish` (the recurring hang: agent icecast
sink stall + missing post-drop started event).

Rendered UI (Playwright, live): bottom bar showed "Everyone's In Love With You ·
15 Big Ones · 5/29" == API `currentTrackId` 69750; a next-track updated it live via
SSE with no reload; a full page reload re-seeded the same; screenshot clean (no
layout/error issues; the only console errors are the known boot-order 401s).

## Sweep gotchas (why earlier runs read red on a broken backend)

- **Deploy restarts wipe in-memory session state** (finding
  `music/station-session-lost-on-backend-restart`): run the sweep only after the
  deploy queue has been quiet for a few minutes, or the reds are handover noise.
- The SSE assertion needs the capture to catch up (poll ≤10 s); curl captures must
  be restarted per run (append offsets on a live stream go sparse).
- next-track under rapid fire can be refused (409) while the agent is mid-boundary —
  a user pressing next quickly sees no-ops; the sweep paces skips accordingly.
- The queue for album "+" is 32 items (Deluxe: 16 + 16), not the 16 the detail view
  shows first — skip-counting tests must not assume track counts.

## The conditional-pass caveat (the real remaining reliability item)

A sweep run only proves anything against a **stable backend**. The in-memory station
session state wipes on every backend restart while the agent/icecast mount keep
serving — during the 20:44-20:49 window three deploy-driven restarts produced
exactly the sweep's "S1 never served / skips 409" reds, and a fresh play after the
next restart served in 0.3 s. Filed as
`music/station-session-lost-on-backend-restart` (findings dir); the station
lifecycle cluster is outstanding item
`music/station-start-flap-and-double-publish` (P1). Until that lands: expect a
deploy during listening to degrade control until the next play, and re-run this
sweep only after the deploy queue has been quiet for a few minutes.
