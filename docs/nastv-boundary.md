# NASTV ↔ Flex boundary — who may talk to what

The standing rule (Andy, 2026-10-11): **NASTV talks to Home Assistant; Home
Assistant talks to the Flex.** No miniDSP-specific knowledge (daemon API, source
enums, dB semantics) belongs in the nastv repo — it lives here. This page is the
coordination point: which package automations serve which NASTV-side task, and
what NASTV code is allowed to do.

## The three wires

| Wire | Carries | Owner | Rule |
|---|---|---|---|
| NASTV → HA | control requests (scripts/automations, entity states) | NASTV HA plugin (`Nastv.Plugin.Sdk.HomeAutomation`, power→automation mapping) | The ONLY control path. NASTV code must never address `:5380` directly — not the backend, not plugins, not the frontend. |
| HA → minidspd | REST writes + REST sensor reads (`rest_command` / `rest` platforms) | this repo's HA package | The daemon has no auth and is LAN-only; only HA touches it. |
| NASTV player → Flex | bit-perfect USB **audio** (ALSA `hw:` from `rvpi-flex8`) | nastv `nastv-linux-player` | Playback data path, deliberately NOT routed through HA (HA cannot carry the stream). Control-only coexistence with the daemon is proven (different USB interface). Never "fix" this into HA. |

## Package automations and their NASTV consumers

| Package automation/script | Fires when | Triggered from |
|---|---|---|
| `minidsp_input_toslink` (+ TV level) | TV becomes the active source | nastv HA plugin's power→automation mapping ("TV Android" power-on: wake-on-LAN → wait webOS → select_source retry) |
| `minidsp_input_usb` (music level) | Pi playback is the active source | manual (widget) today |
| `minidsp_input_bluetooth` | phone streaming | manual (widget) |
| `late_night_listening` / `daytime_listening` | scene pair | manual (widget) |
| `minidsp_volume_up/down`, mute | runtime level | manual (widget); NASTV does not drive these |
| `minidsp daemon watchdog` | sensor unavailable 2 min | HA only (phone notification) |

Adding a NASTV-driven behavior = add/extend an automation HERE, then point the
nastv side at the HA automation/script name. The nastv side should know entity
names, never daemon semantics.

## Open coordination item — W4: plugin-triggered automations

The nastv HA plugin can declare/trigger HA automations from server events
(playback state, power events). Roadmap (from the original weekend plan, now
owned here): map server playback events to the input automations so source +
level follow the playing device automatically. When picked up: design the
trigger surface here, wire the plugin-side subscription in nastv, and record the
entity-name contract in the table above.

## What nastv keeps locally (reference only)

- A thin `AGENTS.minidsp.md` pointer: "knowledge lives in
  github.com/benow/minidsp-flex-8" plus the three-wire rule above.
- Device-inventory facts (rvpi hosts `minidspd` on :5380; the renderer chain) in
  `AGENTS.infrastructure.md` / `docs/app/infrastructure.md` — where-it-runs only,
  not how-it-works.
