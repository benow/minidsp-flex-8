# The helper application — `minidspd` (minidsp-rs)

This is the one piece of **software** in the chain (everything else is the device,
HA config, or documentation). It lives here as its own category: what it is, how
it's deployed, the patch it required to work with this unit's DSP, and how to
operate it. API-level detail is in [daemon.md](daemon.md); the patch's full
evidence chain is in [source-mapping-patch.md](source-mapping-patch.md).

## What it is

[minidsp-rs](https://github.com/mrene/minidsp-rs) (by mrene) — an open-source Rust
project shipping two binaries from the same tree:

- **`minidspd`** — the daemon. It opens the Flex's **USB control interface** and
  re-exposes it as an unauthenticated HTTP + WebSocket API on `0.0.0.0:5380`
  (plus a unix socket). It is the ONLY software allowed to touch that USB
  interface — a second USB control client corrupts the device's control state.
  All other consumers (HA, CLI, curl, WS clients) are network clients of it.
- **`minidsp`** — the CLI. Talks to the daemon over the network/socket
  (`minidsp status` is the human-readable oracle; `minidsp probe` shows the
  hardware identity).

**Version: v0.1.12** (2024-10-27) — still the newest upstream *release*, which is
why the local patch below exists: the fix that would make it unnecessary
([PR #768](https://github.com/mrene/minidsp-rs/pull/768)) is unmerged.

## Why a patch was required (the short version)

The Flex Eight announces itself as `hw_id: 30, dsp_version: 111` — a
hardware/DSP-structure combination that stock v0.1.12's source-mapping table has
no arm for. The fallback maps every source to a nonexistent id 0: **reads**
always reported `NotInstalled`, and **writes** were acked by the device then
silently ignored — so input switching (the core of the HA integration) simply
did not work. Volume/mute/preset were unaffected.

The fix is one line in `protocol/src/source.rs` — a mapping arm for hw_id 30
with the Flex Eight's four real inputs and their wire ids
(`Toslink=1, Spdif=2, Usb=3, Bluetooth=4`), deliberately omitting the upstream
PR's `(Analog, 0)` since the Flex Eight has no analog input. With it, reads
report the true input and writes latch. **Deployed 2026-10-10, verified live**
(round-trip across all four inputs, HA end-to-end). Full record — symptom,
root cause, upstream issue [#566](https://github.com/mrene/minidsp-rs/issues/566),
rebuild recipe, rollback:
[source-mapping-patch.md](source-mapping-patch.md).

## Deployment shape (on rvpi, verified 2026-10-11)

```
/etc/systemd/system/minidspd.service    ExecStart=/usr/local/bin/minidspd,
                                        Restart=always, RestartSec=5
/usr/local/bin/minidspd                 patched release build (v0.1.12 + hw30 arm)
/usr/local/bin/minidsp                  matching patched CLI
/usr/local/bin/minidsp{,d}.patched-hw30 byte-identical backups of this build
/var/tmp/minidsp-build/minidsp-rs       kept build tree (v0.1.12 @ 8cfa96d with the
                                        patch as a working-tree modification) —
                                        re-patch + rebuild takes ~2 min; delete the
                                        directory to purge (toolchain included)
```

- No config file (all defaults; `/etc/minidsp/` does not exist). No auth —
  **LAN trust only, never port-forward :5380**.
- The stock v0.1.12 binaries were lost in the swap (a non-root backup attempt
  failed before install), so rollback-to-stock = delete the `30 =>` line and
  rebuild — the version string is identical either way; verify by `minidsp
  status` showing `NotInstalled` again (stock behavior).
- Build ran natively on the Pi (aarch64, ~1m38s release build; deps
  `pkg-config libudev-dev libusb-1.0-0-dev` — hidapi needs BOTH libudev and
  libusb-1.0). Rebuild recipe: [source-mapping-patch.md](source-mapping-patch.md).

## Operations

| Task | Command |
|---|---|
| Health | `curl -m 5 http://<rvpi>:5380/devices/0` (fast 200 = alive) |
| Truth | `minidsp status` (CLI oracle) / `minidsp probe` (hw identity) |
| Restart (heal) | `ssh andy@rvpi "sudo -n systemctl restart minidspd"` |
| Logs | `journalctl -u minidspd` (the `EmptyPacket` death signature lives here) |

Known failure mode: a Bluetooth connection event can kill the daemon's USB
receive loop (`ParseError(EmptyPacket)`, upstream #697) — audio survives, control
freezes until restart; the HA watchdog in the package notifies Andy. See
[troubleshooting.md](troubleshooting.md).

## Upgrade policy

Upgrading the helper app = re-apply the patch on the new tree and rebuild (the
kept build tree makes this ~2 min) — **check first** that the new version either
still needs it or has absorbed PR #768. Upgrading the *device firmware* is a
separate, Device Console job (see the firmware table in daemon.md); the two are
independent — the source fix is daemon-side and firmware-independent.
