# miniDSP Flex Eight — setup, control, and learnings

Everything we learned integrating a **miniDSP Flex Eight (DL)** into a home theatre /
hi-fi chain with **Home Assistant** as the control plane and a **Raspberry Pi** as the
audio renderer — the daemon quirks, the firmware bug we had to patch, the Bluetooth
findings, the Dirac Live setup, and a full offline copy of the official manual.

Written for two audiences: **us**, as the go-to place for tweaking the Flex; and
**anyone else** attempting "network control of a Flex Eight" — a journey with several
landmines this project documents in full.

## The chain (our setup)

```
phone / TV / NAS
      │
      ▼
 Raspberry Pi 5 ("rvpi")  ──── minidspd :5380 (HTTP+WS control API, LAN-only)
      │  nastv-linux-player (StreamReceiver → alsaplay)
      │  ALSA hw: bit-perfect
      ▼ USB (audio + control)
 miniDSP Flex Eight (DL)  ───── TOSLINK ◄── LG OLED TV
      │  8 outputs, Dirac Live, 4 presets
      ▼ XLR
 Rotel power amp (speaker A/B) ──► mains + (headphone extender)
      └► subwoofer (output 3, crossed over)
```

Key architectural decision: **Home Assistant mediates every Flex control action.**
Nothing in the playback chain talks to the daemon directly — the Pi renders audio,
HA owns control (volume, input, presets), and NASTV (our media server) only asks HA.
The daemon owns the USB control interface exclusively — never open a second USB
control client alongside `minidspd`.

## Document map

| Doc | What's in it |
|---|---|
| [docs/daemon.md](docs/daemon.md) | `minidspd` setup on the Pi: API facts, write paths, gotchas |
| [docs/source-mapping-patch.md](docs/source-mapping-patch.md) | **Input switching is broken in stock minidsp-rs v0.1.12** for the Flex Eight (hw_id 30) — the one-line patch, full build + deploy recipe, firmware state |
| [docs/bluetooth.md](docs/bluetooth.md) | Phone pairing, LDAC/aptX HD, the quiet Bluetooth input (+ the device-side offset fix), and why "disabling" a source doesn't |
| [docs/dirac.md](docs/dirac.md) | Dirac Live: how calibration works, our preset 1 state, the preset roadmap |
| [docs/home-assistant.md](docs/home-assistant.md) | The HA package: entity architecture, level helpers, automations + scripts — and the widget lesson (scripts surface, automations don't) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | The daemon's `EmptyPacket` control-loop death (Bluetooth-triggered), the watchdog, REST sensor semantics |
| [docs/manual-notes.md](docs/manual-notes.md) | Front-panel gestures, presets, inputs — the manual distilled, with the full text one click away |
| [reference/flex-eight-dl-manual.txt](reference/flex-eight-dl-manual.txt) | The complete official Flex Eight (DL) manual as text (fetched from docs.minidsp.com `print_page.html`) |
| [ha/minidsp.yaml](ha/minidsp.yaml) | The live Home Assistant package (snapshot — canonical copy is in our nastv repo at `deploy/ha/packages/minidsp.yaml`) |

## If you're setting up a Flex Eight for network control, read these first

1. **[docs/source-mapping-patch.md](docs/source-mapping-patch.md)** — stock
   `minidsp-rs` (v0.1.12, newest release) cannot read or switch the Flex Eight's
   input: every read says `NotInstalled`, every write is silently ignored. This is a
   daemon mapping-table bug (upstream [#566](https://github.com/mrene/minidsp-rs/issues/566),
   fix in unmerged [#768](https://github.com/mrene/minidsp-rs/pull/768)) — not a
   device limitation, and there is no "auto-detect" feature to blame. You need the
   one-line patch and a rebuild; the recipe is proven and takes ~5 minutes.
2. **[docs/daemon.md](docs/daemon.md)** — the write path is `POST /devices/0/config`
   (the OpenAPI declares a body only there; `POST /devices/0` is a silent no-op read).
   Volume is dB in [-127, 0] with **silent clamping** out of range.
3. **[docs/home-assistant.md](docs/home-assistant.md)** — wrap automations in
   **scripts** if you want them on the Home Assistant Android Action widget: the
   widget lists *actions*, and only scripts get their own action.
4. **[docs/troubleshooting.md](docs/troubleshooting.md)** — a Bluetooth connection
   event can kill the daemon's USB receive loop (`ParseError(EmptyPacket)`, upstream
   [#697](https://github.com/mrene/minidsp-rs/issues/697)). Audio survives; control
   freezes until `systemctl restart minidspd`.

## Status (2026-10-11)

- Input switching, volume, mute: **live** via HA, verified end to end.
- Dirac Live preset 1: **calibrated** (stereo + sub, see [docs/dirac.md](docs/dirac.md)).
- Preset 2 (nighttime, sub off): **pending** — to be built in the official Device Console.
- Firmware: XMOS bridge 1.55 (latest universal is 1.85); DSP firmware update via
  Device Console recommended at the next USB session (see the patch doc's firmware table).
- Bluetooth playback from phone: **paired and working**; level offset pending the
  Device Console visit.

## House keeping

- `ha/minidsp.yaml` is a synced snapshot. Canonical copy + deploy pipeline live in our
  nastv repo (`deploy/ha/packages/minidsp.yaml`, deployed with
  `cat <file> | ssh <ha-host> "cat > /config/packages/minidsp.yaml"` + platform
  reloads — recipe in [docs/home-assistant.md](docs/home-assistant.md)).
- No secrets anywhere in this repo: the daemon is unauthenticated by design and
  **LAN-only** (never port-forward :5380); HA tokens live outside this tree.
