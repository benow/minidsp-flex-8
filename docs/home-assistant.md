# Home Assistant integration — the package

All Flex control entities and automations live in **one Home Assistant package**:
`/config/packages/minidsp.yaml` on the HA box (HAOS on a Pi at `192.168.0.11`). The
snapshot in this repo is [`ha/minidsp.yaml`](../ha/minidsp.yaml). Packages are enabled
with one line in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

## Entity architecture

```
sensor.minidsp_master        REST sensor, 2 s scan of GET /devices/0
                             (volume is the STATE; source/preset/mute are attributes)
number.minidsp_volume        template number, −80…0 dB step 0.5 → rest_command write
switch.minidsp_mute          template switch → rest_command
select.minidsp_source        template select, options = the four REAL inputs
                             (Usb, Toslink, Spdif, Bluetooth + NotInstalled sentinel)
input_number.*_level         per-context listening levels (see below)
automation.*                 the logic (clamp math, input+level combos)
script.*                     widget/plugin surface — thin wrappers that trigger the automations
```

rest_commands (`minidsp_volume/mute/source/preset`) POST to the daemon's
`/devices/0/config`.

**Level helpers** (`input_number`, sliders Andy owns in the UI) — one listening level
per context, so automations stay declarative:

| Helper | Default | Context |
|---|---|---|
| `music_level` | −30 dB | USB (Pi playback) |
| `bluetooth_level` | −20 dB | Bluetooth (input runs ~10 dB quiet; see bluetooth.md) |
| `tv_level` | −24 dB | TOSLINK (TV) |
| `iem_level` | −35 dB | headphones (7Hz Timeless via the Rotel's headphone extender) |

**Automations** (no triggers — called explicitly): `minidsp_volume_up/down` (±3 dB
clamped to [−80, 0] — the device itself clamps silently at −127.5), one
`minidsp_input_<X>` per input (select source + set the matching level), and the scene
pair `late_night_listening` (Rotel speaker-A toggle cuts the mains → IEM level → TV
off) / `daytime_listening` (restore).

## The widget lesson (learned the hard way)

The Home Assistant **Android Action widget's "Configure action" picker lists ACTIONS
(services)**:

- **Automations never surface as actions** — only the generic
  `automation.trigger/toggle/...` appear. You cannot bind a widget to
  "automation.foo" directly.
- **Template button entities don't appear either** (the picker is action-based).
- **Scripts DO** — every script gets its own action (`script.foo`), exactly like a
  `shell_command` or the built-in script services.

So the pattern is: **logic in automations, widget face in scripts** — a thin script
per automation:

```yaml
script:
  minidsp_input_usb:
    alias: MiniDSP input USB
    icon: mdi:usb
    sequence:
      - action: automation.trigger
        target:
          entity_id: automation.minidsp_input_usb
```

Two registry gotchas from the same lesson:

- Template-entity `entity_id` slugs from the **friendly name**, not `unique_id`.
- Removing an entity from YAML config does **not** unregister it — it lingers as an
  `unavailable` husk. Clean removal = WS
  `config/entity_registry/remove` (Node ≥24's built-in WebSocket client is enough;
  auth frame, then id'd commands).

## Package automations are read-only in the HA UI — by design

The UI editor manages only `automations.yaml`; package-defined automations show
"cannot be edited from the UI". That's correct behavior, not a bug: Run /
enable / disable still work from the UI; edits go through the package file. Keep
personal widget automations in `automations.yaml` (UI-editable) and infrastructure
like this package in `packages/`.

## Deploy recipe

Canonical copy lives in the nastv repo (`deploy/ha/packages/minidsp.yaml`); this
repo's `ha/minidsp.yaml` is a synced snapshot. To deploy:

```bash
cat deploy/ha/packages/minidsp.yaml | ssh <ha-host> "cat > /config/packages/minidsp.yaml"
# verify the transfer
ssh <ha-host> md5sum /config/packages/minidsp.yaml && md5sum deploy/ha/packages/minidsp.yaml
# reload the touched platforms (all return 200; no HA restart needed)
curl -X POST http://<ha>:8123/api/services/template/reload      -H "Authorization: Bearer $TOKEN"
curl -X POST http://<ha>:8123/api/services/input_number/reload  -H "Authorization: Bearer $TOKEN"
curl -X POST http://<ha>:8123/api/services/rest_command/reload  -H "Authorization: Bearer $TOKEN"
curl -X POST http://<ha>:8123/api/services/automation/reload    -H "Authorization: Bearer $TOKEN"
curl -X POST http://<ha>:8123/api/services/script/reload        -H "Authorization: Bearer $TOKEN"
```

Notes: `homeassistant/refresh_all` is not a service in current HA (400s). New
`rest`/`rest_command` platforms may need a core restart to appear; template, input_number,
automation and script reload fine.

## The TV side (context)

TV power-on used to drop the Flex's TV input intermittently; the reworked "TV
Android" automation does wake-on-LAN → wait for the webOS media_player to leave
off/unavailable (45 s timeout) → settle → select_source with retry (up to 8 attempts,
4 s apart). The Flex's TOSLINK input + TV level is set by `minidsp_input_toslink`
before the receiver path wakes (wired through the plugin's power-action mapping on
the server side).
