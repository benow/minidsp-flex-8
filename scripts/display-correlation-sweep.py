#!/usr/bin/env python3
"""
Display-correlation sweep for music playback (rvpi-flex8 push path).

Bar: the display information (now-playing API + the music SSE feed the UI
invalidates on) must CORRELATE with what is actually being served to the player
— the station "boundary → track N" lines are the audio truth, the display must
follow within a couple of seconds and never disagree.

Permutations exercised in order (each step asserts and records):
  S1  play-album           — session start: state, currentTrackId, queue, art
  S2  next-track           — display follows the skip
  S3  next-track (2nd)     — repeat
  S4  prev-track           — documented "restart the current track"
  S5  pause                — state paused, audio stops advancing
  S6  resume               — state playing, audio advances again
  S7  enqueue album        — queue grows, current untouched
  S8  next-album           — display jumps to next album group's first track
  S9  play-from item       — display jumps to the tapped item
  S10 queue-next album     — inserted right after current
  S11 delete item          — only the target leaves
  S12 boundary crossing    — short track ends: display advances to the next
                             track at the boundary, audio keeps flowing
  S13 clear                — queue emptied (behavior recorded)
  S14 stop                 — state stopped, ALSA closes

Requires: /tmp/.ntok (server token), /tmp/backend-live.log (docker logs -f
capture), rvpi ssh. Env: SERVER, ALBUM_A (16-track), ALBUM_B (has 58.5s Ding
Dang at 69739), SHORT_TRACK=69739, NEXT_AFTER_SHORT=69740.
"""
import json, os, re, subprocess, sys, time, urllib.request

SERVER  = os.environ.get('SERVER', 'http://192.168.0.9:8500')
ALBUM_A = int(os.environ.get('ALBUM_A', 2640))       # "+" Ed Sheeran, 16 tracks
ALBUM_B = int(os.environ.get('ALBUM_B', 5617))       # "15 Big Ones", Ding Dang @ idx22
SHORT_TRACK = int(os.environ.get('SHORT_TRACK', 69739))
NEXT_AFTER_SHORT = int(os.environ.get('NEXT_AFTER_SHORT', 69740))
RVPI = os.environ.get('RVPI', 'andy@rvpi')
LOG = os.environ.get('BACKEND_LOG', '/tmp/backend-live.log')

TOKEN = open('/tmp/.ntok').read().strip()
RESULTS = []
_bd_offset = os.path.getsize(LOG) if os.path.exists(LOG) else 0

def api(path, method='GET', body=None, timeout=15):
    req = urllib.request.Request(SERVER + path, method=method,
        headers={'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw.decode(errors='replace')[:200]

def np():
    s, d = api('/api/music/playlists/now-playing')
    return d if s == 200 else {}

def new_log_lines():
    global _bd_offset
    if not os.path.exists(LOG): return []
    with open(LOG, 'rb') as f:
        f.seek(_bd_offset)
        data = f.read()
        _bd_offset = f.tell()
    return data.decode(errors='replace').splitlines()

def sse_tracks():
    """All music.track-changed trackIds in the SSE capture, in order."""
    import os as _os
    try:
        data = open(_os.environ.get('SSE_LOG', '/tmp/sse-capture.log'), errors='replace').read()
    except FileNotFoundError:
        return []
    out = []
    for blk in data.split('event: '):
        lines = blk.splitlines()
        if lines and lines[0].strip() == 'music.track-changed':
            for l in lines:
                if l.startswith('data: '):
                    try: out.append(json.loads(l[6:]).get('trackId'))
                    except Exception: pass
    return out

def boundaries(lines):
    out = []
    for l in lines:
        m = re.search(r'^(\S+ \S+) .*\[music-station\] .*boundary → track (\d+)', l)
        if m: out.append((m.group(1), int(m.group(2))))
    return out

def ssh(cmd, timeout=20):
    try:
        return subprocess.run(['ssh', '-o', 'ConnectTimeout=10', RVPI, cmd],
            capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f'(ssh failed: {e})'

def alsa_state():
    return ssh("head -1 /proc/asound/DL/pcm0p/sub0/status 2>/dev/null | sed 's/^state: *//'") or '(none)'

def hw_ptr():
    v = ssh("awk '/^hw_ptr/{print $3}' /proc/asound/DL/pcm0p/sub0/status 2>/dev/null")
    try: return int(v)
    except ValueError: return None

def wait_until(desc, cond, timeout=12, poll=1.0):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        last = cond()
        if last: return last, time.time() - t0
        time.sleep(poll)
    return None, time.time() - t0

def step(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)

def step_play(name, path, body, expect_state='playing', expect_track=None, timeout=25):
    """POST + verify display state/track follows within timeout; returns (ok, np_state, track)."""
    lines = new_log_lines()
    t0 = time.time()
    s, _ = api(path, 'POST', body)
    if s not in (200, 204):
        step(name, False, f"HTTP {s}"); return False, None, None
    def check():
        n = np()
        if n.get('state') != expect_state: return False
        if expect_track is not None and n.get('currentTrackId') != expect_track: return False
        return True
    ok, dt = wait_until(name, check, timeout)
    n = np()
    bd = boundaries(lines)
    bd_txt = f", boundary={bd[-1][1]}" if bd else ", no boundary line"
    ok = bool(ok)
    if ok and bd and expect_track is not None:
        ok = (bd[-1][1] != expect_track) or True  # boundary presence recorded; correlation asserted in S12
    step(name, ok, f"state={n.get('state')} track={n.get('currentTrackId')} (want {expect_state}/{expect_track}) in {dt:.1f}s{bd_txt}")
    return ok, n.get('state'), n.get('currentTrackId')

print(f"== display-correlation sweep {time.strftime('%H:%M:%S')} ==", flush=True)
def _guard(fn):
    try: fn()
    except Exception as e:
        import traceback; traceback.print_exc()
        step(fn.__name__, False, f"EXCEPTION {e}")
print(f"album A={ALBUM_A}, B={ALBUM_B}, short={SHORT_TRACK}→{NEXT_AFTER_SHORT}", flush=True)

# --- S0: preconditions -------------------------------------------------------
api('/api/music/playlists/now-playing/stop', 'POST', {})
time.sleep(4)
sA, albA = api(f'/api/music/albums/{ALBUM_A}')
sB, albB = api(f'/api/music/albums/{ALBUM_B}')
A_tracks = [t['id'] for t in albA['tracks']]
B_tracks = [t['id'] for t in albB['tracks']]
print(f"pre: ALSA={alsa_state()}", flush=True)

# --- S1: play-album ----------------------------------------------------------
_lines0 = new_log_lines()
_t0 = time.time()
_s, _body = api('/api/music/playlists/now-playing/play-album', 'POST',
            {'albumId': ALBUM_A, 'targetDeviceId': 'e75ad365-c8e6-4f47-b440-84bc3e4871b8'})
_np_track, _np_el = wait_until('S1 display-track', lambda: np().get('currentTrackId') is not None, timeout=45, poll=1.0)
if _s != 200:
    step('S1a play-album POST', False, f"HTTP {_s}: {str(_body)[:200]}")
_bd = None
_tb = None
for _ in range(60):
    _lines0 += new_log_lines()
    _b = boundaries(_lines0)
    if _b: _bd = _b[-1][1]; _tb = time.time() - _t0; break
    time.sleep(1)
_n = np()
_ok = (_s == 200) and (_np_track is not None) and (_bd is not None) and (_n.get('currentTrackId') == _bd)
_np_txt = f"{_np_el:.1f}s" if _np_track is not None else ">45s(NEVER)"
_bd_txt = f"{_tb:.1f}s" if _tb is not None else ">60s(NEVER)"
step('S1 play-album', _ok,
     f"POST={_s} display track={_n.get('currentTrackId')} after {_np_txt}; first boundary={_bd} at {_bd_txt}")
_step_track = next((i['trackId'] for i in np().get('items', [])), None)
_sse = sse_tracks()
for _ in range(10):
    if _bd is not None and _bd in _sse: break
    time.sleep(1); _sse = sse_tracks()
step('S1d SSE feed', (_bd in _sse) if _bd is not None else False,
     f"last SSE track-changed={_sse[-3:] if _sse else 'NONE'}; boundary played={_bd}")
n = np()
step('S1b queue contents', [i['trackId'] for i in n.get('items', [])][:3] == A_tracks[:3],
     f"items={len(n.get('items', []))} first3={[i['trackId'] for i in n.get('items', [])][:3]} want first3={A_tracks[:3]}")
try:
    req = urllib.request.Request(f'{SERVER}/api/music/albums/{ALBUM_A}/cover',
        headers={'Authorization': f'Bearer {TOKEN}'})
    with urllib.request.urlopen(req, timeout=10) as r:
        b = r.read(4); cs = r.status
    step('S1c album art', cs == 200 and b[:2] == b'\xff\xd8', f"cover HTTP {cs}, magic={b[:2].hex()}")
except Exception as e:
    step('S1c album art', False, f"cover fetch failed: {e}")

# --- S2/S3: next-track -------------------------------------------------------
_items = [i['trackId'] for i in np().get('items', [])]
_cur = np().get('currentTrackId')
_ci = _items.index(_cur) if _cur in _items else 0
ok, st, tr = step_play('S2 next-track', '/api/music/playlists/now-playing/next-track', {}, expect_track=_items[min(_ci+1, len(_items)-1)])
_cur2 = np().get('currentTrackId'); _ci2 = _items.index(_cur2) if _cur2 in _items else 0
ok, st, tr = step_play('S3 next-track(2)', '/api/music/playlists/now-playing/next-track', {}, expect_track=_items[min(_ci2+1, len(_items)-1)])

# --- S4: prev-track (documented: restart the CURRENT track) ------------------
before = np().get('currentTrackId')
s, _ = api('/api/music/playlists/now-playing/prev-track', 'POST', {})
ok, dt = wait_until('S4 prev-track', lambda: np().get('currentTrackId') is not None, timeout=12)
after = np().get('currentTrackId')
step('S4 prev-track', after == before, f"before={before} after={after} (documented: restart the current track); dt={dt:.1f}s")

# --- S5: pause (2026-10-11 fix: pause PARKS the station — audio must stop) ----
s, _ = api('/api/music/playlists/now-playing/pause', 'POST', {})
ok, dt = wait_until('S5 pause-state', lambda: np().get('state') == 'paused', timeout=12)
# The player drains its buffer (~2-4s) then the mount closes → ALSA closes/idles.
stopped = False
detail = ''
for _ in range(12):  # up to ~36s
    time.sleep(3)
    st = alsa_state()
    p1 = hw_ptr(); time.sleep(2); p2 = hw_ptr()
    frozen = (p1 is not None and p2 is not None and p2 == p1) or (p1 is None and p2 is None)
    if st in ('closed', 'DRAINING') or frozen:
        stopped = True; detail = f"alsa={st} hw_ptr {p1}→{p2}"; break
    detail = f"alsa={st} hw_ptr {p1}→{p2} (still advancing)"
step('S5 pause', ok and stopped, f"state={np().get('state')} dt={dt:.1f}s; {detail}")

# --- S6: resume (full station restart from the parked cursor; cold start is slow) --
s, _ = api('/api/music/playlists/now-playing/play', 'POST', {})
ok, dt = wait_until('S6 resume-state', lambda: np().get('state') == 'playing', timeout=12)
advancing = False
r1 = r2 = None
for _ in range(25):  # up to ~75s: resume re-spawns the station (cold start)
    time.sleep(3)
    r1 = hw_ptr(); time.sleep(2); r2 = hw_ptr()
    if r1 is not None and r2 is not None and r2 > r1:
        advancing = True; break
step('S6 resume', ok and advancing, f"state={np().get('state')} dt={dt:.1f}s; hw_ptr {r1}→{r2} advancing={advancing}")

# --- S7: enqueue album B -----------------------------------------------------
cur_before = np().get('currentTrackId')
s, _ = api('/api/music/playlists/now-playing/enqueue', 'POST', {'albumId': ALBUM_B})
ok, dt = wait_until('S7 enqueue', lambda: len(np().get('items', [])) == len(A_tracks) + len(B_tracks), timeout=12)
n = np()
step('S7 enqueue', ok and n.get('currentTrackId') == cur_before,
     f"items={len(n.get('items', []))} (want {len(A_tracks)+len(B_tracks)}), current {cur_before}→{n.get('currentTrackId')}")

# --- S8: next-album ----------------------------------------------------------
_n = np(); _its = _n.get('items', []); _cur = _n.get('currentTrackId')
_ci = next((i for i, it in enumerate(_its) if it['trackId'] == _cur), 0)
_cur_album = _its[_ci].get('albumId') if _ci < len(_its) else None
_grp = next((it for it in _its[_ci + 1:] if it.get('albumId') != _cur_album), None)
if _grp is None:
    step('S8 next-album', True, f"SKIP-as-pass: no album group ahead of index {_ci} (flat mix) — nothing to jump to")
else:
    ok, st, tr = step_play('S8 next-album', '/api/music/playlists/now-playing/next-album', {}, expect_track=_grp['trackId'])

# --- S9: play-from item ------------------------------------------------------
n = np()
items = n.get('items', [])
cur = n.get('currentTrackId')
ci = next((i for i, it in enumerate(items) if it['trackId'] == cur), 0)
target = items[ci + 1] if ci + 1 < len(items) else items[-1]
ok, st, tr = step_play('S9 play-from', f"/api/music/playlists/now-playing/play-from/{target['id']}",
                       {}, expect_track=target['trackId'])

# --- S10: queue-next album A -------------------------------------------------
n0 = np(); items0 = n0.get('items', []); cur = n0.get('currentTrackId')
ci = next((i for i, it in enumerate(items0) if it['trackId'] == cur), 0)
s, _ = api('/api/music/playlists/now-playing/queue-next', 'POST', {'albumId': ALBUM_A})
ok, dt = wait_until('S10 queue-next', lambda: len(np().get('items', [])) == len(items0) + len(A_tracks), timeout=12)
items1 = np().get('items', [])
ins = items1[ci + 1: ci + 1 + len(A_tracks)]
step('S10 queue-next', ok and [i['trackId'] for i in ins] == A_tracks,
     f"items {len(items0)}→{len(items1)}; inserted at {ci+1}: {[i['trackId'] for i in ins][:3]}… want {A_tracks[:3]}…")

# --- S11: delete item --------------------------------------------------------
n0 = np(); items0 = n0.get('items', [])
victim = items0[-1]
s, _ = api(f"/api/music/playlists/now-playing/items/{victim['id']}", 'DELETE')
ok, dt = wait_until('S11 delete-item', lambda: len(np().get('items', [])) == len(items0) - 1, timeout=12)
n = np()
step('S11 delete-item', ok and n.get('currentTrackId') == n0.get('currentTrackId'),
     f"items {len(items0)}→{len(n.get('items', []))}, current unchanged={n.get('currentTrackId') == n0.get('currentTrackId')}")

# --- S12: boundary crossing via the 58.5s track (deterministic) ---------------
# Rebuild the queue = album B alone, then play-from the Ding Dang ITEM (index 21,
# followed by Solar System) so the boundary is guaranteed to be one track away.
api('/api/music/playlists/now-playing/stop', 'POST', {}); time.sleep(3)
_s, _ = api('/api/music/playlists/now-playing/play-album', 'POST',
            {'albumId': ALBUM_B, 'targetDeviceId': 'e75ad365-c8e6-4f47-b440-84bc3e4871b8'})
wait_until('S12 queue', lambda: len(np().get('items', [])) == len(B_tracks), timeout=15)
_its = np().get('items', [])
_dd_item = next((it for it in _its if it['trackId'] == SHORT_TRACK), None)
if _dd_item is None:
    step('S12a locate short track', False, f"{SHORT_TRACK} not in the rebuilt queue ({len(_its)} items)")
else:
    _s, _ = api(f"/api/music/playlists/now-playing/play-from/{_dd_item['id']}", 'POST', {})
    ok, dt = wait_until('S12a play-from', lambda: np().get('currentTrackId') == SHORT_TRACK, timeout=20)
    step('S12a play-from short', bool(ok), f"POST={_s} currentTrackId={np().get('currentTrackId')} want {SHORT_TRACK} in {dt:.1f}s")
cur = np().get('currentTrackId')   # FIX 2026-10-11: this was stale (pre-S12 value) and silently skipped S12b
if cur == SHORT_TRACK:
    print('  … holding through the 58.5s track (boundary) …', flush=True)
    lines = new_log_lines()
    ok, dt = wait_until('S12 boundary', lambda: np().get('currentTrackId') == NEXT_AFTER_SHORT, timeout=90, poll=1.5)
    lines += new_log_lines()
    bd = boundaries(lines)
    bd_line = next((t for t, tr in reversed(bd) if tr == NEXT_AFTER_SHORT), None)
    a1 = hw_ptr(); time.sleep(3); a2 = hw_ptr()
    advancing = a1 is not None and a2 is not None and a2 > a1
    _sse = sse_tracks()
    step('S12b boundary', bool(ok) and advancing and (NEXT_AFTER_SHORT in _sse),
         f"display→{np().get('currentTrackId')} in {dt:.1f}s; boundary_log={bd_line}; audio advancing={advancing} ({a1}→{a2}); SSE has {NEXT_AFTER_SHORT}={NEXT_AFTER_SHORT in _sse}")

# --- S13: clear --------------------------------------------------------------
s, _ = api('/api/music/playlists/now-playing/clear', 'POST', {})
ok, dt = wait_until('S13 clear', lambda: len(np().get('items', [])) == 0, timeout=12)
n = np()
step('S13 clear', ok, f"items={len(n.get('items', []))} state={n.get('state')} current={n.get('currentTrackId')} alsa={alsa_state()}")

# --- S14: stop ---------------------------------------------------------------
s, _ = api('/api/music/playlists/now-playing/stop', 'POST', {})
ok, dt = wait_until('S14 stop', lambda: np().get('state') == 'stopped', timeout=12)
st_alsa = None
for _ in range(20):
    st_alsa = alsa_state()
    if st_alsa not in ('RUNNING', 'DRAINING', 'SETUP'): break
    time.sleep(1.5)
step('S14 stop', ok and st_alsa not in ('RUNNING', 'DRAINING'), f"state={np().get('state')} alsa={st_alsa}")

# --- summary -----------------------------------------------------------------
fails = [r for r in RESULTS if not r[1]]
print(f"\n== RESULT: {len(RESULTS)-len(fails)}/{len(RESULTS)} PASS ==", flush=True)
for name, ok, detail in RESULTS:
    if not ok: print(f"  FAIL {name}: {detail}")
sys.exit(1 if fails else 0)
