# Manual notes — the Flex Eight distilled

The complete official manual lives at
[reference/flex-eight-dl-manual.txt](../reference/flex-eight-dl-manual.txt) (fetched
from `docs.minidsp.com/product-manuals/flex-eight-dl/print_page.html`). Tip: the docs
site serves a bot challenge to plain curl after a few hits — fetch the print page
with browser headers. This page is the cheat sheet.

## Front panel (single encoder knob)

| Gesture | Function |
|---|---|
| press once, rotate | **Preset** 1–4 (loads a whole DSP config; "Pls wait..." a few seconds) |
| press **twice**, rotate | **Input source** (cycles only *enabled* sources) |
| press **three times**, rotate | **Dirac Live** on/off |
| press & hold → "Mute?" → release | Mute toggle |
| press & hold → "Standby?" → release | Standby |
| while showing "Bluetooth": press & hold → "BTPairing" | Bluetooth pairing mode |

## Inputs (Flex Eight = digital only — exactly four)

| Input | Our use |
|---|---|
| USB | Pi playback (bit-perfect ALSA `hw:`) — the primary music path |
| TOSLINK (optical) | LG OLED TV |
| SPDIF (coax RCA) | unused (spare; samples up to 216 kHz) |
| Bluetooth | phone streaming (LDAC/aptX HD) |

Analog/RCA/XLR/HDMI sources exist only on Flex *family siblings* — never on the
Eight. USB audio and USB configuration share the one port; iOS/Android app control
needs a Wi-DG dongle, which then blocks USB audio.

## Presets

Four onboard presets; each carries the full DSP configuration **including its Dirac
Live filter set**. Volume, mute, input source and Dirac on/off are RUNTIME controls
and are **not stored in presets**. Preset names exist only in Device Console (the
panel shows "Preset N"). Copying a preset = export to file, import into the other
slot. See [dirac.md](dirac.md) for ours.

## Audio Source Configuration (Device Console)

Per-source toggles: **Enable** (only affects the front-panel/remote cycling list —
digital source writes still latch a "disabled" input) and **Input Volume Offset**
(−12…+12 dB, applied as the very first DSP step; the designed way to level-match
sources — e.g. Bluetooth vs USB). Volume offsets are not stored in presets.

## Remote control

Stock IR remote: standby, mute, volume (0.5 dB, held = 3 dB steps), Dirac on/off,
**source cycling** (TOSLINK → SPDIF → USB → Bluetooth), presets 1–4. Third-party
remotes: IR codes at support.minidsp.com (AMX/Crestron article); Harmony can get
*direct* source-selection buttons. The KD-1 knob adds BLE control (volume, mute,
input, preset, Dirac) — may need a firmware update.

## Dirac Live

Stereo correction applied before the 8-output processing stage. Calibration: USB +
Device Console → START CALIBRATION (launched from *inside* Device Console, or the
Dirac app can't see the device) → UMIK-class mic → target curve + curtains → filters
load per preset. Details: [dirac.md](dirac.md).

## Standby/power

No network/API power control exists (the daemon/CLI expose none). Recommended power
sequence (manual): line-level gear on before power amps; reverse when going off.
