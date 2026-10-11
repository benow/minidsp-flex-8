# Troubleshooting — the failure modes we've actually hit

## The daemon's control loop dies on Bluetooth connection events

**Symptom**: audio keeps playing (the daemon is control-only and the BT audio path is
phone → Flex directly), but every control surface freezes: `GET /devices/0` hangs or
returns empty (HTTP 000), HA's sensor goes `unavailable`, widgets time out with a
spinner → red X.

**Evidence** (journalctl -u minidspd):

```
ERROR minidsp::transport::multiplexer] recv loop exit: ParseError(EmptyPacket)
```

It fired at the moment a phone **connected over Bluetooth** while the daemon's stream
was live. Upstream class:
[#697](https://github.com/mrene/minidsp-rs/issues/697) / #516 / #191 — known,
unfixed in v0.1.12; one reporter's was a USB cable, another a reboot — i.e. the
receive loop is fragile to unexpected device events generally (we also saw a
`TransportClosed` variant days earlier, on stock and patched builds alike).

**Heal** (10 seconds, audio unaffected):

```bash
ssh <pi-host> "sudo -n systemctl restart minidspd"
```

**Not reproducible on demand** — re-writing the Bluetooth source afterward latched
fine with the stream surviving, so it's event-timing-dependent, not deterministic.

**Guardrail**: an HA watchdog automation (in the package) —
`sensor.minidsp_master` → `unavailable` for 2 minutes → notification to the phone
with the heal command. Semantics were verified by stopping the daemon live:
the REST sensor flips `unavailable` **within ~20 s** of control death.

**Do NOT replace the watchdog with a last-updated-age check**: a healthy REST sensor
never refreshes `last_updated` when values are unchanged (HA dedupes identical
writes), so an age check false-positives whenever nothing has changed for a few
minutes.

## "Source writes are ignored" / source always reads NotInstalled

Not a device feature — stock minidsp-rs v0.1.12 has no source mapping for the Flex
Eight (hw_id 30, dsp_version 111): reads decode as `NotInstalled`, writes send a
nonexistent source id that the device acks and drops. Full diagnosis, the one-line
patch, and the rebuild recipe: [source-mapping-patch.md](source-mapping-patch.md).
(There is no "source auto-detect" on this device — the official manual documents
none; that was our own early misdiagnosis.)

## Writes that silently do nothing

`POST /devices/0` with a body returns 200 and changes nothing. The write path is
**`POST /devices/0/config`** only. See [daemon.md](daemon.md).

## Widget fires but "cannot be edited from the UI" / widget picker doesn't show it

Package automations are UI-read-only by design, and the Android Action widget only
lists ACTIONS — automations don't get one. Wrap in a script:
[home-assistant.md](home-assistant.md).

## Bluetooth input is quiet

The BT input runs ~10 dB below USB at phone-max volume; fix with the per-source
Input Volume Offset in Device Console (+10 dB on Bluetooth) —
[bluetooth.md](bluetooth.md).

## Out-of-range volume "lost"

The device **silently clamps** out-of-range volume writes to [−127.5, 0]. Our HA
number helper clamps client-side to [−80, 0] to keep the slider meaningful.
