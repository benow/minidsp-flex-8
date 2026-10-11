# Music playback pipeline — end-to-end map, logs, and the failure modes

The push path (album → rvpi-flex8 → Flex Eight), as of 2026-10-11. Station
scheduling/curator machinery is out of scope here; this is the transport.

## The chain, hop by hop

```
app/API: POST /api/music/playlists/now-playing/play-album {albumId, targetDeviceId}
  │  MusicPlaylistController.PlayAlbum → ReplaceQueue → StartBroadcastSessionOrFail
  │  → publishes ONE player.play (ticketed URL) targeted at the device
  ▼
backend log line:  "Published music player.play (stream): ... session=<id> ... url=.../audio?ticket=<t>"
  ▼
SSE → rvpi nastv-player.service (PlayerWorker.HandlePlayCommand, url contains /audio?ticket=)
  │  player log: "[music-play <sessionId>] command received — player-push stream <url>"
  ▼
StreamReceiver (HTTP byte pull; 512KB prebuffer before the sink starts; stall=15s,
  │  sink-write=8s, retries ≤20)                          player log: "attached, first bytes flowing",
  │                                                       then a heartbeat "N bytes in 10.0s (total M)"
  ▼
ffmpeg (decode Ogg/FLAC → WAV on stdout)
  ▼
alsaplay (WAV stdin → hw:CARD=DL,DEV=0; period 2048, buffer 65536; S16/24/32 → S32_LE)
  │  player log (aplay stderr passthrough): "alsaplay: 2ch 44100Hz 16bit → hw:CARD=DL,DEV=0",
  │  "alsaplay: period 2048, buffer 65536 frames"; ffmpeg warnings likewise on "sink ffmpeg:"
  ▼
Flex Eight (USB audio; input must be Usb — HA owns that via automation.minidsp_input_usb)

stop: POST /api/music/playlists/now-playing/stop (204) → mount closes → player read ends
  → re-attach attempt gets 404 → HTTP/404 is TERMINAL (old build retried 20×; fixed
  2026-10-11) → state idle → sink disposed → ALSA closed.
```

## Where to look when it misbehaves (the diagnostic ladder)

| Symptom | Look at | Reading |
|---|---|---|
| No sound, app says playing | backend: `Published music player.play` has a `url`? · player: "command received"? | missing url = server-side publish gap; missing command = SSE/targeting gap |
| Command received, no sound | player: "attached, first bytes flowing" + heartbeats | no attach = ticket/mount problem; attach but no heartbeats = read stall |
| Sound is fast/glitched ("chipmunks") | `/proc/asound/DL/pcm0p/sub0/hw_params` rate+format vs the track; player "alsaplay:" lines | 2026-10-11 root cause: alsaplay's S32 conversion stride bug (fixed, sample-exact test below) |
| Cuts out mid-track | player: "stalled — no bytes for 15s" / "stream ended prematurely" / "connection lost (…)" retries · backend: boundary/park lines | mount teardown; see station session flap below |
| Stop doesn't stop | ALSA `status` still RUNNING · backend: `DELETE … failed (station down?)` + `parked` | the mount kept feeding after stop — station lifecycle, not the player |
| Control dead but audio fine | HA `sensor.minidsp_master` unavailable (2 min watchdog) | minidspd `EmptyPacket` — see troubleshooting.md |

## ALSA truth on rvpi (the ground truth for "is audio really flowing")

```bash
ssh andy@rvpi 'cat /proc/asound/DL/pcm0p/sub0/hw_params'   # rate MUST equal the track's
ssh andy@rvpi 'head -3 /proc/asound/DL/pcm0p/sub0/status'  # RUNNING/closed; hw_ptr advances
ssh andy@rvpi "awk '/^hw_ptr/{print \$3}' /proc/asound/DL/pcm0p/sub0/status; sleep 2; awk '/^hw_ptr/{print \$3}' /proc/asound/DL/pcm0p/sub0/status"
```
`hw_ptr` must advance at the hw rate (44100/s @ 44.1k). advancing = samples ARE being
consumed; `appl_ptr − hw_ptr` ≈ buffer margin (a collapsing margin precedes an xrun).

## The effectiveness gate (automated)

`scripts/e2e-music-probe.sh [attempts] [albumId] [playSeconds]` (this repo) — per
attempt: play-album targeted at rvpi-flex8 → attach line in the player journal →
ALSA RUNNING (waits out the 512KB prebuffer, ≤20s) → hw_ptr advancing twice → Flex
`Usb` + unmuted (HA) → hold → still advancing → stop → ALSA closed (≤~30s). N
consecutive passes = green. Collision guard: stops a 'playing' surface first (a
second play command splices the mount — that splice is audible as fast/glitched
audio; learned 2026-10-11 when a probe run overlapped live listening).

## Logging + retention (installed 2026-10-11)

| Hop | Where | Retention |
|---|---|---|
| backend/plugins | NAS `/app/Logs/nastv-.log` (Serilog, day+size rolling) | 7 files (existing) |
| rvpi player + alsaplay + ffmpeg stderr | journald, `journalctl -u nastv-player` | drop-in `/etc/systemd/journald.conf.d/nastv-retention.conf`: persistent, 500 MB cap, keep-free 1 GB, MaxFileSec 30d (was UNCAPPED — default 10% of disk) |

## Known failure modes (open)

1. **Station session lifecycle** (outstanding item `music/station-start-flap-and-double-publish`):
   a cold/badly-parked station can let a new play attach to a dying mount — the
   player then sees garbage bytes (ffmpeg "Cannot identify new stream", alsaplay
   "no fmt chunk"), retries, and the ticket 404s mid-start (observed 2026-10-11
   14:11: attempt 1 of a gate run; a fresh play seconds later succeeded). A stop
   whose station DELETE times out (15s, "station down?") leaves the mount feeding
   — playback survives the stop (observed 14:14). Part 2 of that item
   (double-publish republish) did NOT reproduce in the 14:16 gate window
   (1 player.play per POST).
2. **alsaplay S32 conversion stride** — FIXED + sample-exact verified 2026-10-11
   (nastv commit da698cc2: old binary 0.1% sample match, fixed 88200/88200 = 100%
   via the ALSA file plugin; /app/alsaplay on rvpi replaced, backup at
   /tmp/alsaplay.broken-20261011, container image picks it up next player build).
3. **Stale player binary on rvpi** — the `/opt/nastv-player` build was 4 days old
   (pre-2026-10-08) and retried expired tickets 20× instead of going idle; refreshed
   2026-10-11 to current main (backup /opt/nastv-player.bak-20261011). Re-run of
   `scripts/setup-linux-player.sh`-style provisioning after player-code changes:
   `dotnet publish -r linux-arm64 --self-contained true` + rsync to
   `/opt/nastv-player`, restart `nastv-player.service`.
