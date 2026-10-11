# minidspd source-mapping patch (Flex Eight, hw_id 30)

**Status: DEPLOYED 2026-10-10 — patched daemon live on our Pi.
This page is the full record: what was broken, the exact patch, how the binary was built,
how it was deployed, and how to rebuild it from scratch.

## Symptom

Source control over the daemon was dead on the miniDSP Flex Eight while volume/mute/preset
worked: `GET /devices/0` always reported `"source": "NotInstalled"`, and source writes were
accepted-but-ignored:

```bash
curl -X POST http://192.168.0.146:5380/devices/0/config \
  -H "Content-Type: application/json" -d '{"master_status":{"source":"Usb"}}'
# HTTP 200, but the source never changed
```

This was initially misdiagnosed (2026-10-10, earlier the same day) as a device-side
"source auto-detect" feature. **There is no such feature** — the official Flex Eight (DL)
manual documents none (source selection = front-panel double-press encoder, IR remote, or
Device Console dropdown; per-source enable/disable lives in Audio Source Configuration).

## Root cause

minidsp-rs **v0.1.12** (2024-10-27, the newest release) maps hardware IDs to input sources
in `protocol/src/source.rs` (`Source::mapping`). The Flex Eight probes as
`hw_id: 30, dsp_version: 111` — an arm that does not exist in the table, so the `_`
fallback applies: `&[(NotInstalled, 0)]`.

- **Reads**: any real source byte decodes to `NotInstalled` (only raw byte 0 would decode).
- **Writes**: `set_source()` converts the requested source via `to_id()`, which returns
  `0` from the fallback table — and `0` is not a valid source on a Flex Eight, so the
  device acks the `0x34 0x00` command and ignores it.

Evidence chain: upstream [issue #566](https://github.com/mrene/minidsp-rs/issues/566)
(identical unit, identical symptoms; the reporter proved the raw command works —
`minidsp debug send 3401/3402/3403` = Toslink/Spdif/Usb) and
[PR #768](https://github.com/mrene/minidsp-rs/pulls/768) (adds the hw_id 30 arm; still
unmerged, so no released binary carries the fix). `SetSource` already serializes to
`0x34 <id>` — only the mapping table is wrong.

## The patch

One line in `protocol/src/source.rs` (v0.1.12 tag), inserted before the `_` arm. It
follows PR #768's values but **omits `(Analog, 0)`**: the Flex Eight has no analog input
(issue #566), and leaving it out means HA can never select a nonexistent input.

```diff
             32 => &[(Analog, 0), (Toslink, 1), (Spdif, 2), (Usb, 3), (Hdmi, 4)],
+            30 => &[(Toslink, 1), (Spdif, 2), (Usb, 3), (Bluetooth, 4)],
             _ => &[(NotInstalled, 0)],
```

`(Bluetooth, 4)` comes from issue #566's probing ("bluetooth is 04") and is a real Flex
Eight input. Result: reads report `Usb`/`Toslink`/… correctly, and writes send ids 1/2/3/4.

## Build (aarch64, on the Pi itself)

No rust toolchain on the laptop and no aarch64 cross-linker, so the build ran natively on
`rvpi` (4×Cortex-A76, 8 GB, 1m38s wall for the release profile) with the toolchain
confined to `/var/tmp/minidsp-build`. Apt additions: `pkg-config`, `libudev-dev`,
`libusb-1.0-0-dev` (hidapi needs BOTH libudev and libusb-1.0; the first build failed on
the missing libusb .pc file). The tree is KEPT after deploy — it re-patches in ~2 min
when upstream merges #768 or a firmware change needs retesting; delete the directory to
remove every trace.

```bash
ssh andy@rvpi
sudo -n apt-get install -y pkg-config libudev-dev libusb-1.0-0-dev
export B=/var/tmp/minidsp-build && mkdir -p $B && cd $B
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o rustup-init.sh
sh rustup-init.sh -y --profile minimal --no-modify-path --default-toolchain stable
export PATH=$HOME/.cargo/bin:$PATH        # --no-modify-path: the env file is ~/.cargo/env, NOT $B/env
git clone --depth 1 --branch v0.1.12 https://github.com/mrene/minidsp-rs && cd minidsp-rs
# apply the one-line patch above to protocol/src/source.rs
cargo build --release -p minidsp -p minidsp-daemon   # package names: minidsp, minidsp-daemon (dir is daemon/)
# artifacts: target/release/minidsp  target/release/minidspd
```

## Deploy + rollback

```bash
# swap (the cp-backup of the STOCK binaries was attempted non-root and FAILED before the
# install — the stock v0.1.12 binaries are gone from /usr/local/bin; rollback-to-stock =
# remove the patch line and rebuild (~2 min). Patched-binary backups DO exist:
#   /usr/local/bin/minidsp{,d}.patched-hw30   (this exact patched build)
sudo -n install -m 755 target/release/minidspd /usr/local/bin/minidspd
sudo -n install -m 755 target/release/minidsp  /usr/local/bin/minidsp
sudo -n systemctl restart minidspd

# rollback to stock: un-patch (delete the `30 =>` line), rebuild, reinstall — the
# version string is identical (0.1.12), so verify by `minidsp status` reading
# NotInstalled again (stock behavior).
```

## Verification (2026-10-10, live)

- `minidsp status` reports the **real** source (`Toslink` at the time of the swap — the
  TV optical feed Andy last used) instead of `NotInstalled`.
- API round-trip both ways: `POST /devices/0/config {"master_status":{"source":"Usb"}}`
  → device latches `Usb` (read back via API + CLI); `Toslink` restores likewise.
- HA end-to-end: `automation.minidsp_input_music` → `select.minidsp_source` = Usb +
  `number.minidsp_volume` = −30.0, daemon oracle confirms; `automation.minidsp_input_tv`
  → Toslink + −24.0 likewise. `select.minidsp_source` options trimmed to the Flex
  Eight's real inputs (Usb, Toslink, Spdif, Bluetooth, NotInstalled).
- Volume/mute/preset behavior unchanged (patch touches only the source table).

## Firmware state (checked 2026-10-10)

Three firmware layers on a Flex Eight; `ReadHardwareId` reports the **XMOS (USB bridge)
firmware: ours is 1.55**.

| Layer | Ours | Latest known | Notes |
|---|---|---|---|
| XMOS USB bridge | **1.55** | 1.85 ("all models", 2025); Flex-HT-only 1.88/1.91 later | v1.85 changelog notes "resolving firmware update issues when jumping too many firmware versions (Flex/Flex8)" |
| DSP firmware | unreadable via daemon (`dsp_version: 111` is a structure id, not a fw number) | v2.1 for Flex Eight (21 Jan 2025: output delay 25→60 ms on non-Dirac structure) | Device Console reads/reports it |
| Device Console | n/a | 1.2.5 Beta8 (29 Sep 2026) | handles upgrades |

**Upgrading is a Device Console job** (USB to a PC — the daemon cannot push firmware), or
the miniDSP BT Update app over Bluetooth. **Not urgent for this integration**: the
source-control fix is daemon-side and firmware-independent (units on dsp 110 *and* 111
need it). Sensible moment: the same USB session Andy uses in Device Console to build
preset 2 (nighttime, sub off) — check for offered updates then, and note the changelog's
"jumping too many versions" caveat if it offers a big XMOS jump.

Changelog: [miniDSP Device Console ChangeLog](https://www.minidsp.com/support/device-console-changelog)
