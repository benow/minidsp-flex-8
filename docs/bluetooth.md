# Bluetooth audio — pairing, codecs, and findings

The Flex Eight includes Bluetooth audio streaming with **LDAC™ and aptX™ HD** codecs.
Bluetooth is **for audio streaming only** — configuration cannot happen over it
(Device Console needs USB; a Wi-DG dongle is the only wireless-config path).

## Pairing a phone (from the official manual — verified working)

1. On the Flex front panel: press the **encoder twice**, rotate until the display
   shows **"Bluetooth"**.
2. While it still says Bluetooth, **press and hold** the encoder until the display
   changes to **"BTPairing"**, then release. The panel now shows **BT(P)** — the Flex
   is discoverable.
3. On the phone: Bluetooth settings → pair with the Flex Eight (like any headphone).
4. **Enable LDAC**: after pairing, tap the gear icon next to the Flex in the phone's
   Bluetooth device settings and select **LDAC** (Android supports it; without it you
   get a lower-bitrate codec — SBC/AAC depending on the phone).

Display legend:

| Panel shows | Meaning |
|---|---|
| `BT(C)` | paired, connected |
| `BT(NC)` | no device paired |
| `BT(P)` | pairing mode (discoverable) |

Physical check if pairing fails: the **rear-panel screw-on Bluetooth antenna** must
be attached.

## Two things that bite

### 1. Phone volume ≠ Flex volume

The manual is explicit: the phone's volume control does not drive the Flex's master
volume. Over Bluetooth the phone's absolute volume scales the *stream level* before
transmission — so **keep the phone's media volume at max** for full headroom, and do
the listening-level control on the Flex itself (our HA widgets, or the front panel).

### 2. The Bluetooth input runs ~10 dB quieter than USB

Observed 2026-10-11: at the phone's max volume, the Bluetooth input needed the Flex
at about −20 dB to match what USB delivers at −30 dB. The designed fix is the
**per-source Input Volume Offset** in Device Console → Audio Source Configuration
(−12…+12 dB each; the manual's stated purpose is "match volume levels from different
sources"). **Set Bluetooth to +10 dB** (try +12 if needed), after which Bluetooth and
USB feel equally loud at the same master position.

Until the offset is applied, our HA package carries a dedicated
`bluetooth_level` helper (default −20) so the Bluetooth widget lands at a comfortable
level by itself.

### 3. "Disabling" a source doesn't disable it

Device Console's Audio Source Configuration lets you Enable/Disable each input — but
disabling only removes the source from the **front-panel/remote cycling list**.
Digital source-selection commands (via the daemon API) still latch a "disabled"
input — verified live: the unit accepted `Bluetooth` while disabled. If you want an
input truly dead, that's a different (firmware-level) mechanism; the disable is just
cycling convenience.

## The control-plane caveat

A Bluetooth **connection event** (phone connecting/reconnecting) can kill the
daemon's USB receive loop — see [troubleshooting.md](troubleshooting.md). Audio keeps
playing (the daemon is control-only); control freezes until the daemon restarts.
