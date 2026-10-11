# minidspd — the control daemon on the Pi

`minidsp-rs` ([mrene/minidsp-rs](https://github.com/mrene/minidsp-rs)) **v0.1.12**
(2024-10-27, the newest release) — systemd unit `minidspd.service` on the Pi,
listening on **0.0.0.0:5380** (HTTP + WebSocket) and `/tmp/minidsp.sock`.
The application-level view (what it is, deployment shape, the hw_id-30 patch it
required, ops table, upgrade policy) is [helper-app.md](helper-app.md); this page
is the API detail.

Runs with **no config file** (all defaults; `/etc/minidsp/` does not exist) and **no
authentication** — LAN trust only. **Never port-forward :5380.**

## Device identity

```
minidsp probe
→ 0: Found Generic with serial 902490 at ws://localhost/devices/0/ws
    [hw_id: 30, dsp_version: 111]
```

`hw_id 30` = Flex Eight. `dsp_version 111` is the DSP *structure* version (not a
firmware number) — and the combination is **unsupported by stock v0.1.12**; see
[source-mapping-patch.md](source-mapping-patch.md) for the consequences and the fix.

`ReadHardwareId` reports the **XMOS (USB bridge) firmware**: ours is **1.55**.

## API facts (all verified live)

### Read

- `GET /devices` — device list (the Flex = `usb:3-2:1.3`).
- `GET /devices/0` — master summary:
  ```json
  {"master": {"preset": 0, "source": "Toslink", "volume": -24.0, "mute": false}}
  ```
  This is the health check (fast 200). `minidsp status` (CLI) is the CLI oracle.
- Source enum is **Capitalized**: `NotInstalled, Analog, Toslink, Spdif, Usb, Aesebu,
  Rca, Xlr, Lan, I2S, Bluetooth, Hdmi`. Lowercase is rejected with a ParseError that
  lists the valid variants (handy). The CLI takes lowercase and maps.
  Only `Toslink`, `Spdif`, `Usb`, `Bluetooth` are real on a Flex Eight.

### Write — the gotcha that cost us a discovery round

- **`POST /devices/0/config`** with a partial `{"master_status": {...}}` — fields
  merge; this is the ONLY write path.
- **`POST /devices/0` is a READ that 200s and silently no-ops.** The OpenAPI declares
  a request body only on `/config` — but the daemon accepts the body on `/devices/0`
  and drops it. Any write "verified" against `/devices/0` is not a write.

```bash
curl -X POST http://<pi>:5380/devices/0/config \
  -H "Content-Type: application/json" \
  -d '{"master_status":{"volume":-30.0}}'
```

### Volume / mute / preset / source

- **Volume**: dB float, range [-127, 0], 0.5 dB steps, applies instantly.
  **Out-of-range values CLAMP silently** (POST −200 → device shows −127.5). Always
  clamp client-side to a sane range.
- **Mute**: boolean, round-trips.
- **Preset**: 0–3 in master_status. Switching loads a whole new DSP config (Dirac
  filters included; takes a few seconds, display shows "Pls wait..."). Preset writes
  from the API are verified-working (used for preset selection; see dirac.md for the
  preset plan).
- **Source**: with the [mapping patch](source-mapping-patch.md) applied, reads report
  the real input and writes latch (verified round-trip Usb ⇄ Toslink ⇄ Bluetooth ⇄
  Spdif on this unit). **Without the patch: reads say `NotInstalled`, writes are
  silently ignored** (stock v0.1.12 sends nonexistent source id 0).

### DSP config writes — don't

The daemon can *write* DSP parameters (input gain, PEQ, ...) via the config endpoint,
but for this unit the device profile is unsupported (same hw_id-30 gap), so *where*
parameters land is unverified — and there is **no read-back** (`GET /config` is 404).
Writing DSP structure blind is how you ruin a calibration. Runtime controls
(volume/mute/source/preset) via the daemon; anything structural via the official
Device Console over USB.

### WebSocket

`ws://<pi>:5380/devices/0?poll=true` → full status on connect, then deltas within
~2 s (poll cadence) after any change. Add `&levels=true` for input/output meters.
**Multi-client is proven**: HTTP writes + WS deltas + CLI concurrently. The daemon
still exclusively owns the USB control interface — multiple *network* clients are
fine; a second *USB* client is not.

## Firmware state (checked 2026-10-11)

| Layer | Ours | Latest known | Notes |
|---|---|---|---|
| XMOS USB bridge | **1.55** | 1.85 ("all models", 2025); Flex-HT-only 1.88/1.91 later | v1.85 changelog: "resolving firmware update issues when jumping too many firmware versions (Flex/Flex8)" |
| DSP firmware | unreadable via daemon | v2.1 for Flex Eight (21 Jan 2025: output delay 25→60 ms on the non-Dirac structure) | Device Console reads/reports it |
| Device Console | — | 1.2.5 Beta8 (29 Sep 2026) | handles upgrades |

Upgrades run through **Device Console over USB** (the daemon cannot push firmware) or
the miniDSP BT Update app over Bluetooth. Changelog:
[minidsp.com/support/device-console-changelog](https://www.minidsp.com/support/device-console-changelog).

## USB audio input constraints (probe of hw:CARD=DL,DEV=0, 2026-10-10)

The Flex's USB audio interface is **S32_LE-only** — anything driving it over ALSA
`hw:` must deliver 32-bit little-endian samples:

| Constraint | Value |
|---|---|
| Formats | **S32_LE only** (S16_LE and S24_3LE both rejected at hw_params install) |
| Channels | 2 (stereo only) |
| Rate | 44 100 – 192 000 Hz |
| Period size | 8 – 192 000 frames |
| Periods per buffer | 2 – 1024 |
| Buffer size | 16 – 384 000 frames |

The ranges are generous — a naive "invalid argument" from `snd_pcm_hw_params` with
16/24-bit data is the FORMAT being rejected, not the buffer sizes. Feeding 16/24-bit
sources works by widening each sample into the S32 MSBs (bit-exact shift, no dither);
the player's `alsaplay` does exactly that, plus mono→stereo upmix.
