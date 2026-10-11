#!/usr/bin/env bash
# End-to-end music playback probe — the effectiveness gate for the Flex push path.
#
# Chain exercised per attempt (push mechanism — the station session is the
# playback engine, as designed; we do NOT touch station scheduling/curator):
#   album selected via API → POST /api/music/playlists/now-playing/play-album {albumId,targetDeviceId}
#   → server publishes player.play with ticketed /audio?ticket= URL
#   → rvpi-flex8 StreamReceiver attaches (journal) → alsaplay/ffmpeg → ALSA hw consuming
#   (hw_ptr advancing) → Flex Eight shows Usb input, unmuted (HA sensor)
#   → POST /api/player/stop → clean teardown (ALSA closed, player idle).
#
# Gate: N consecutive attempts must ALL pass (default 5). One failure fails the run.
# Usage: e2e-music-probe.sh [attempts=5] [albumId] [playSeconds=20]
set -u
SERVER="${SERVER:-http://192.168.0.9:8500}"
DEVICE_ID="${DEVICE_ID:-e75ad365-c8e6-4f47-b440-84bc3e4871b8}"   # rvpi-flex8
RVPI="${RVPI:-andy@rvpi}"
HA_TOKEN_FILE="${HA_TOKEN_FILE:-/tmp/.htok}"
ATTEMPTS="${1:-5}"
ALBUM_ID="${2:-}"
PLAY_SECONDS="${3:-20}"
PASS=0; FAIL=0

log() { echo "[probe $(date +%H:%M:%S)] $*"; }

command -v jq >/dev/null || { echo "jq required"; exit 2; }

TOKEN=$(curl -s -m 10 -X POST "$SERVER/api/auth/login" -H "Content-Type: application/json" \
  -d '{"username":"andy","password":"vagrant"}' | jq -r .accessToken)
[ -n "$TOKEN" ] && [ "$TOKEN" != null ] || { log "FATAL: login failed"; exit 2; }

HTOK=$(cat "$HA_TOKEN_FILE" 2>/dev/null || true)

# The DL card's pcm0p on rvpi (probe target for "samples actually flowing")
ALSA_DIR=$(ssh -o ConnectTimeout=10 "$RVPI" "ls -d /proc/asound/DL/pcm0p/sub0 2>/dev/null" 2>/dev/null)
[ -n "$ALSA_DIR" ] || { log "FATAL: /proc/asound/DL/pcm0p/sub0 not found on rvpi"; exit 2; }

# NOTE: hw_ptr/appl_ptr live INSIDE the status file (there is no separate hw_ptr file)
alsa_hw_ptr() { ssh -o ConnectTimeout=10 "$RVPI" "awk '/^hw_ptr/{print \$3}' $ALSA_DIR/status 2>/dev/null" 2>/dev/null; }
# status is "state: RUNNING"-style when live, bare "closed" when idle — first line covers both
alsa_state()  { ssh -o ConnectTimeout=10 "$RVPI" "head -1 $ALSA_DIR/status 2>/dev/null" 2>/dev/null | sed 's/^state: *//'; }
flex_state()  { curl -s -m 5 -H "Authorization: Bearer $HTOK" \
  http://192.168.0.11:8123/api/states/sensor.minidsp_master | jq -r '"\(.attributes.source) vol=\(.state) mute=\(.attributes.mute)"' 2>/dev/null; }
player_journal() { ssh -o ConnectTimeout=10 "$RVPI" "sudo -n journalctl -u nastv-player --since '-2 min' --no-pager 2>/dev/null" 2>/dev/null; }

# Pick album deterministically: first album with >=5 tracks unless given
if [ -z "$ALBUM_ID" ]; then
  ALBUM_ID=$(curl -s -m 10 -H "Authorization: Bearer $TOKEN" "$SERVER/api/music/albums?page=1&pageSize=50" \
    | jq -r '[.items[] | select(.trackCount >= 5)][0].id')
fi
[ -n "$ALBUM_ID" ] && [ "$ALBUM_ID" != null ] || { log "FATAL: no album found"; exit 2; }
TRACKS=$(curl -s -m 10 -H "Authorization: Bearer $TOKEN" "$SERVER/api/music/albums/$ALBUM_ID" | jq -r '[.tracks[].id]')
ALBUM_TITLE=$(curl -s -m 10 -H "Authorization: Bearer $TOKEN" "$SERVER/api/music/albums/$ALBUM_ID" | jq -r '.title + " — " + .artist')
log "album $ALBUM_ID \"$ALBUM_TITLE\" ($(echo "$TRACKS" | jq length) tracks)"

for i in $(seq 1 "$ATTEMPTS"); do
  TRACK_ID=$(echo "$TRACKS" | jq -r ".[(($i - 1)) % length]")  # which album track this attempt starts from
  log "--- attempt $i/$ATTEMPTS: track $TRACK_ID ---"

  # 1. collision guard: never fire while a session is already live (a second
  # play command splices the mount and produces fast-playback + static artifacts
  # — root-caused 2026-10-11). Stop + settle if the surface claims playing.
  NP=$(curl -s -m 10 -H "Authorization: Bearer $TOKEN" "$SERVER/api/music/playlists/now-playing" | jq -r .state)
  if [ "$NP" = "playing" ]; then
    log "now-playing already 'playing' — stopping + settling 5s to avoid a mount splice"
    curl -s -o /dev/null -m 10 -X POST "$SERVER/api/music/playlists/now-playing/stop" \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{}"
    sleep 5
  fi

  # 1. push — album-level: play-album with the target device (the real album path)
  HTTP=$(curl -s -m 15 -o /tmp/probe-play.json -w '%{http_code}' -X POST "$SERVER/api/music/playlists/now-playing/play-album" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"albumId\":$ALBUM_ID,\"targetDeviceId\":\"$DEVICE_ID\"}")
  if [ "$HTTP" != "200" ]; then log "FAIL: POST play HTTP $HTTP: $(head -c 200 /tmp/probe-play.json)"; FAIL=$((FAIL+1)); continue; fi

  # 2. attach: StreamReceiver line in the player journal within 15s
  ATTACHED=no
  for t in $(seq 1 15); do
    sleep 1
    if player_journal | grep -q "music-play.*command received — player-push"; then ATTACHED=yes; break; fi
  done
  if [ "$ATTACHED" != yes ]; then log "FAIL: no player-push attach line in player journal (15s)"; FAIL=$((FAIL+1)); curl -s -o /dev/null -X POST "$SERVER/api/player/stop" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"targetDeviceId\":\"$DEVICE_ID\"}"; continue; fi

  # 3. audio flowing: ALSA RUNNING + hw_ptr advancing. The sink PREBUFFERS 512KB
  # before opening the device (~5-6s at ~100KB/s) — poll up to 20s for RUNNING.
  FLOWING=no
  for t in $(seq 1 20); do
    [ "$(alsa_state)" = "RUNNING" ] && break
    sleep 1
  done
  P1=$(alsa_hw_ptr); sleep 3; P2=$(alsa_hw_ptr)
  if [ "$(alsa_state)" = "RUNNING" ] && [ -n "$P1" ] && [ -n "$P2" ] && [ "$P2" -gt "$P1" ] 2>/dev/null; then
    # confirm still advancing (not a stalled pointer)
    sleep 2; P3=$(alsa_hw_ptr)
    if [ "$P3" -gt "$P2" ] 2>/dev/null; then FLOWING=yes; fi
  fi
  if [ "$FLOWING" != yes ]; then
    log "FAIL: ALSA not flowing (state=$(alsa_state), hw_ptr $P1 → $P2 → ${P3:-?})"
    FAIL=$((FAIL+1))
    curl -s -o /dev/null -X POST "$SERVER/api/music/playlists/now-playing/stop" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{}"
    continue
  fi

  # 4. Flex on Usb, unmuted
  FS=$(flex_state)
  case "$FS" in
    Usb*mute=false*|*mute=false*Usb*) : ;;
    *) log "FAIL: Flex state wrong: '$FS'"; FAIL=$((FAIL+1)); curl -s -o /dev/null -X POST "$SERVER/api/music/playlists/now-playing/stop" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{}"; continue ;;
  esac

  log "PLAYING: ALSA $P1→$P3, Flex: $FS — holding ${PLAY_SECONDS}s"
  sleep "$PLAY_SECONDS"

  # 5. still flowing at the end of the hold (intermittent-drop check)
  P4=$(alsa_hw_ptr); sleep 3; P5=$(alsa_hw_ptr)
  if ! { [ "$P5" -gt "$P4" ] 2>/dev/null; }; then
    log "FAIL: stream dropped during hold (hw_ptr $P4 → $P5)"; FAIL=$((FAIL+1))
    curl -s -o /dev/null -X POST "$SERVER/api/music/playlists/now-playing/stop" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{}"
    continue
  fi

  # 6. clean stop (station stop, like the UI). The endpoint returns 204; teardown
  # is mount-closure-driven (read ends → 404 → idle → sink disposed), which is
  # normally ~5s but can take longer when the station's own DELETE is slow
  # (the known session-flap pathology) — poll up to 30s (each poll is an SSH
  # round trip, so ~20 iterations ≈ 30s wall).
  HTTP=$(curl -s -m 15 -o /dev/null -w '%{http_code}' -X POST "$SERVER/api/music/playlists/now-playing/stop" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{}")
  STOP_STATE=unknown
  for t in $(seq 1 20); do
    sleep 1
    STOP_STATE=$(alsa_state)
    case "$STOP_STATE" in RUNNING|DRAINING|SETUP) ;; *) break ;; esac
  done
  if [ "$HTTP" != "204" ] && [ "$HTTP" != "200" ]; then
    log "FAIL: stop HTTP $HTTP"; FAIL=$((FAIL+1)); continue
  fi
  if [ "$STOP_STATE" = "RUNNING" ] || [ "$STOP_STATE" = "DRAINING" ]; then
    log "FAIL: ALSA still $STOP_STATE ~30s after stop"; FAIL=$((FAIL+1)); continue
  fi

  log "PASS attempt $i (track $TRACK_ID)"
  PASS=$((PASS+1))
done

log "RESULT: $PASS/$ATTEMPTS passed"
if [ "$PASS" -eq "$ATTEMPTS" ]; then log "GATE: GREEN"; exit 0; else log "GATE: RED"; exit 1; fi
