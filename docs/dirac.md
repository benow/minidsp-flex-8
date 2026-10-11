# Dirac Live — overview and our calibration

The Flex Eight (DL) implements **stereo** Dirac Live: two channels of full-range room
correction applied FIRST, after which the corrected signal routes to the eight output
channels for per-output processing (PEQ, crossovers, delays).

## How calibration works (the manual's flow, distilled)

Everything Dirac happens through the **miniDSP Device Console** on a computer with a
**USB connection to the Flex** — calibration cannot run over the network, and the
Dirac application can only detect the Flex when launched **from inside Device
Console** via the **START CALIBRATION** button (launching the Dirac app directly from
the OS finds nothing).

Flow: connect USB → Device Console → START CALIBRATION → the Dirac Live application
takes over → measure with a calibration mic (UMIK-1/2 class) at 9–13 listening
positions (one position minimum; more = better bass handling) → set the **target
curve** (Auto-Match recalculates target level + EQ on every measurement by default —
turn it off to hand-tune) → adjust the **frequency-range curtains** (don't drag the
low curtain too low; boost = distortion) → export → filters load into the Flex's DSP
working memory.

Two distinct "Dirac" switches — worth keeping straight:

- **Dirac filters** are loaded **per preset** (each preset carries its own exported
  filter set).
- **Dirac on/off** is a *runtime* control — front-panel knob (three presses), IR
  remote, or Device Console button. It is **not stored in presets**; selecting a
  preset only changes which filters are loaded, not whether correction is bypassed.

## Our calibration — preset 1 (done; Andy solo, pre-dating this project)

Preset 1 = the daily configuration:

- **Dirac Live: ON** (stereo correction, mains + sub measured).
- Outputs: **out 1 = left main, out 2 = right main, out 3 = subwoofer**; filters send
  low frequencies to the sub and high-pass the mains.
- Amp: Rotel as **power amp only** (speaker A/B) — all pre-amp duty (input switching,
  volume) moved to the Flex; that swap is the reason this project exists.

## Preset roadmap

| Preset | Purpose | State |
|---|---|---|
| 1 | Daily: Dirac + mains + sub | **live** |
| 2 | Nighttime: mains only, **sub fully unmapped** (out 3 silent) | **pending** — build in Device Console by cloning preset 1 and unmapping out 3; audible verification beats blind writes |
| 3 | Hearing-correction parameterization + a 7Hz Timeless IEM EQ profile | future |

Once preset 2 exists, selecting it is a runtime call the daemon/HA can make
(`POST /devices/0/config {"master_status":{"preset":N}}`), so "night mode" becomes a
one-tap HA action — that's the point of doing structural edits in Device Console and
runtime switching through HA.

Practical notes for the Device Console session (from [daemon.md](daemon.md) and
[bluetooth.md](bluetooth.md)): it's also the moment to take the **firmware upgrades**
it offers (XMOS bridge 1.55 → 1.85-class; watch the "jumping too many versions"
caveat) and the **Bluetooth Input Volume Offset (+10 dB)**.
