# Rotel RA-1570 amplifier — RS-232 control (HA box)

The Rotel **RA-1570** is the power amp fed by the Flex's XLR outputs (speaker A/B +
headphone extender). Since the Flex took pre-amp duty (2026-10), the Rotel runs as
**power amp only** — no input switching, no volume. What remains controllable is
serial, wired to the HA box (USB→serial, `/dev/ttyUSB0`).

## The core constraint: no read-back (verified empirically 2026-10-11)

The speaker-A/B state CANNOT be inspected on this link — verified live, not assumed:

- Queries (`speaker_a?`, `speaker_a_on?`, `volume?`, `mute?`, `power?`) → **zero
  response bytes**.
- Valid SET commands (`volume_up!` then `volume_down!`) → also **zero bytes** — the
  amp transmits nothing at all on this link (either the RA-1570 protocol has no
  status messages for these, or the serial adapter's RX line isn't wired; functionally
  identical: HA is deaf to the amp).

`speaker_a!` is a **toggle with no true on/off**. Andy's long-standing approach was
"known good state by convention, mostly correct" (the old Daily Reset automation
blindly toggled at 05:00 — which flips mains OFF whenever they were already ON).
The replacement pattern, now in the package:

- **`input_boolean.rotel_speakers_a`** — the assumed mains state (initialized `on`,
  the amp-runs-full-time baseline). Every automation that toggles the mains MUST
  maintain it. Mains-ensure = *toggle only when the boolean says off*.
- Maintained by: `late_night_listening` (off), `daytime_listening` (ensure on),
  `morning_reset` (ensure on), Sleep (off).
- Residual drift source: the amp's own front-panel/remote speaker button — invisible
  to HA; if used, flip the boolean once to re-sync.

## HA shell_command layer (on the HA box, `/config/configuration.yaml`)

```yaml
shell_command:
  rotel_x: echo -e -n "<CMD>!" > /dev/ttyUSB0   # serial_init: stty -F /dev/ttyUSB0 115200
```

Commands: `opt1, opt2, usb, pc_usb, aux1, aux2, power_on/off, volume_40..80
(+up/down), mute, mute_on/off, speaker_a, speaker_b` (speaker A/B are **toggles**;
`mute_on/off` are true sets — the morning reset uses `rotel_mute_off` as a known-good).

## What's obsolete vs alive

- The legacy `automation.rotel_*` input/volume scenes are **OBSOLETE** — the Flex owns
  input and volume now.
- The `shell_command` layer itself **SURVIVES**: `rotel_speaker_a` (mains ensure/cut via
  the tracker), `rotel_mute_off` (morning reset), power on/off.
- **Daily Reset is RESTORED** (05:00 unconditional `rotel_speaker_a` toggle, now with
  a boolean `toggle` alongside so the tracker stays honest) — Andy's speaker-toggle
  paths (`daytime_listening`, Daily Reset) must stay UNCONDITIONAL TOGGLES; a
  tracker-guarded "ensure" broke his widgets (2026-10-11) and was reverted same-day.
  `morning_reset` (07:45, tracker-guarded ensure) still handles the hands-off case.
- **Amp-wedge incident (2026-10-11)**: the amp itself once stopped responding to
  EVERYTHING — front-panel speaker buttons AND serial (all commands accepted with zero
  effect/response) — during the tracker work; a power cycle healed both. The no-read-back
  evidence above was gathered while in this state, so "the amp never transmits" is
  slightly less certain than it looks; the practical conclusion (no feedback available)
  stands.
- HA never touches the Flex's USB — only `minidspd` does; the Rotel serial port and
  the daemon are unrelated transports.

## The three-mode + reset model (2026-10-11)

| Mode | Flex | Rotel mains | Set by |
|---|---|---|---|
| TV watching | TOSLINK + TV level (−24) | on | `tv_android` / `tv_ps3` (automations.yaml) |
| Daytime music | USB + music level (−30) | on | `morning_reset` (07:45) / `script.minidsp_input_usb` |
| Nighttime music | USB→IEM level; **preset 2 (sub unmapped) pending** in Device Console | off (IEM via extender) | `late_night_listening` |
| Morning reset | → daytime music | ensure on, mute off | `morning_reset` (idempotent) |

See [nastv-boundary.md](nastv-boundary.md) for how the NASTV side reaches any of this
(answer: through Home Assistant, never directly).
