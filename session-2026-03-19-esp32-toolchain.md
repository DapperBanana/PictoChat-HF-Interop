# Session Notes — 2026-03-19 (ESP32 Toolchain + Build)

Continuation from 2026-03-18 sniffing session. Focus: verify ESP32 detected, install Rust/ESP32 toolchain, build and flash `foa_dswifi` PictoThing firmware.

---

## Session Outcome

| Task | Status |
|---|---|
| ESP32 detected on vessel-01 | ✅ `/dev/ttyUSB0` (CP2102, a4:f0:0f:61:9f:b0) |
| Rust ESP32 toolchain (`espup`) | ✅ Already installed from prior session |
| `espflash 3.2.0` installed | ✅ |
| `foa_dswifi` repo cloned | ✅ `~/foa_dswifi/` on vessel-01 |
| Build succeeded | ✅ PictoThing compiles, 59.22s |
| Firmware flashed | ✅ 65.76% flash usage (2.7MB/4MB) |
| Boot output decoded | ❌ Blocked — defmt monitor connection issue |
| ESP32 confirmed running | ✅ Defmt framing bytes on serial (continuous `\n`) |

---

## Hardware Confirmed

```
ESP32-WROOM-32 (ELEGOO 2-pack)
  MAC: a4:f0:0f:61:9f:b0
  Chip: esp32 revision v3.1
  Crystal: 40 MHz
  Flash: 4MB
  Features: WiFi, BT, Dual Core, 240MHz
  Connection: CP2102 USB-UART bridge → /dev/ttyUSB0
```

---

## Build Dependency Hell — Root Cause and Fix

### The Problem

`foa_dswifi` was written against a LOCAL fork of Embassy
(`/home/bread/CLionProjects/embassy/`) that added AP mode methods
to `embassy-net-esp-hosted`:

- `Control::set_ap_mode()` — switch to AP mode
- `Control::start_ap(ApStatus { ... })` — launch AP with SSID/PSK
- `Control::get_mac_addr()` — (public in fork, private in crates.io v0.2.0+)
- Types: `ApStatus`, `Bandwidth::Ht20`, `Security`

None of these exist in the crates.io `embassy-net-esp-hosted` (any version).
The developer's `Cargo.toml` `[patch.crates-io]` section pointed to their local paths.
We removed those patches in the previous session, causing build failures.

### The Fix

1. **Found the developer's Embassy fork:** `https://github.com/mjwells2002/embassy`
   — has all the AP mode additions in `embassy-net-esp-hosted`

2. **Cloned the fork locally on vessel-01:**
   ```bash
   git clone --depth=1 https://github.com/mjwells2002/embassy.git ~/embassy
   ```

3. **Workspace Cargo.toml `[patch.crates-io]`** (path patches, not git — git patches
   don't override when crates.io has a newer semver):
   ```toml
   [patch.crates-io]
   embassy-net-driver = { path = "/home/root-1/embassy/embassy-net-driver" }
   embassy-net-esp-hosted = { path = "/home/root-1/embassy/embassy-net-esp-hosted" }
   embassy-time-driver = { path = "/home/root-1/embassy/embassy-time-driver" }
   embassy-time-queue-utils = { path = "/home/root-1/embassy/embassy-time-queue-utils" }
   ```

4. **PictoThing/Cargo.toml change:** forced exact version to make the patch apply:
   ```toml
   # Changed from:
   embassy-net-esp-hosted = { version = "0.2.0", features = ["defmt"]}
   # To:
   embassy-net-esp-hosted = { version = "=0.2.0", features = ["defmt"]}
   ```
   **Why:** crates.io published v0.2.1 after the developer wrote this code. Without
   `=0.2.0`, Cargo selects v0.2.1 from crates.io and the local path patch (v0.2.0)
   is unused with a warning. The exact version `=0.2.0` forces the patched version.

5. **Both Cargo.toml files have foa pinned** to original commit:
   ```toml
   foa = { git = "https://github.com/esp32-open-mac/FoA.git",
           rev = "36b47cdc4cf30dd8c10babefc9c64119e834b8ba",
           package = "foa", features = ["esp32", "defmt"]}
   ```
   **Why:** FoA's HEAD moved to v0.1.1 which requires `embassy-time ^0.5.0`, but
   the mjwells2002 Embassy fork only has v0.4.0. The original lock file had commit
   `36b47cdc` which uses `embassy-time 0.4.0` and `esp-hal =1.0.0-rc.0`.

---

## Files Modified on vessel-01

| File | Change |
|---|---|
| `~/foa_dswifi/Cargo.toml` | Removed developer's local-path patches; added new `[patch.crates-io]` pointing to `~/embassy/` |
| `~/foa_dswifi/PictoThing/Cargo.toml` | Changed `embassy-net-esp-hosted` to `=0.2.0`; pinned `foa` to commit `36b47cdc` |
| `~/foa_dswifi/foa_dswifi/Cargo.toml` | Pinned `foa` to commit `36b47cdc` |
| `~/embassy/` | New directory — shallow clone of `mjwells2002/embassy` |

---

## Build Output Summary

```
warning: `PictoThing` (bin "PictoThing") generated 9 warnings
Finished `release` profile [optimized + debuginfo] target(s) in 59.22s
```

Binary: `~/foa_dswifi/target/xtensa-esp32-none-elf/release/PictoThing`
Size: 2,714,944 bytes (65.76% of 4MB flash)

Flash command used:
```bash
espflash flash --chip esp32 --port /dev/ttyUSB0 \
  ~/foa_dswifi/target/xtensa-esp32-none-elf/release/PictoThing
```

---

## ESP32 Boot Output Issue

PictoThing uses `defmt` for all logging. This means serial output is binary-encoded
and not human-readable. Raw serial shows all `\n` bytes (defmt framing). To decode:

```bash
# On vessel-01 — CORRECT command (chip already running, skip ROM sync):
. ~/.cargo/env && . ~/export-esp.sh
sudo fuser -k /dev/ttyUSB0 && sleep 0.5
espflash monitor --before no-reset-no-sync \
  --port /dev/ttyUSB0 \
  --elf ~/foa_dswifi/target/xtensa-esp32-none-elf/release/PictoThing
```

**Why `--before no-reset-no-sync`:** The default `--before default-reset` tries to
pull the chip into ROM bootloader mode via DTR/RTS then sync. When the chip is already
running firmware and hasn't been put in download mode, this hangs indefinitely.
`no-reset-no-sync` skips both steps and just opens the serial stream — defmt decode
still works because it's purely a software decode of the byte stream (doesn't need
ROM communication).

**To capture boot messages specifically:** DTR-toggle reset first, then immediately
run monitor:
```bash
python3 -c "import serial,time; s=serial.Serial('/dev/ttyUSB0',115200); s.setDTR(False); s.setRTS(True); time.sleep(0.1); s.setDTR(True); s.setRTS(False); s.close()"
espflash monitor --before no-reset-no-sync --port /dev/ttyUSB0 --elf ~/foa_dswifi/target/.../PictoThing
```

Note: `--elf` is only on the `monitor` subcommand, not `flash`.

---

## PictoThing Firmware Behavior (from source analysis)

Based on reading `PictoThing/src/main.rs`:

1. **Boot:** Initializes display (SSD1306 OLED), WiFi hardware (foa + esp-hosted stack)
2. **Config check:** Reads stored WiFi credentials from flash (ekv key-value store)
3. **If no config:** Starts AP named `PictoThing-XXYYZZ` (last 3 bytes of MAC)
   - SSID visible, no password
   - IP: 10.82.50.1
   - HTTP server serves config page
4. **If config present:** Connects to WiFi (regular WPA2 STA via esp-hosted)
5. **PictoChat join:** Uses `foa_dswifi` to join PictoChat Room A on channel 1
   as a phantom second DS

**Our ESP32's AP SSID (when unconfigured):** `PictoThing-619FB0`
(last 3 bytes of MAC `a4:f0:0f:61:9f:b0` → `61 9F B0` → `619FB0`)

---

## Next Steps

### Immediate (next session)

1. **Read defmt boot output.** Run `espflash monitor --elf` immediately after
   flashing or after killing any competing process on ttyUSB0.

2. **Configure PictoThing WiFi.** Connect phone/laptop to AP `PictoThing-619FB0`,
   browse to `10.82.50.1`, configure WiFi credentials. (Note: not sure if WiFi
   config is even needed for PictoChat — re-read the config flow.)

3. **Verify PictoChat join.** With DS running PictoChat Room A:
   - Watch defmt log for "joining PictoChat", "associated", etc.
   - Run `picto_sniff.py` in parallel to see if a new client MAC appears in
     Roster type-4 frames.

4. **Understand the WiFi config requirement.** Looking at the source, PictoThing
   seems to use `embassy-net-esp-hosted` for standard WiFi AND `foa` for PictoChat.
   It's unclear if they operate on the same radio simultaneously (unlikely) or if
   the WiFi config is for something else (OTA update?). Needs investigation.

### Medium Priority

5. **Patch `picto_sniff.py` on vessel-01.** It may still have the old BSSID
   from a prior session. Re-confirm DS BSSID and update if needed.

6. **Test message send.** Once phantom DS is joined, try sending a message
   from the DS and verify PictoThing receives/relays it.

7. **Pi ↔ ESP32 UART protocol.** Understand how PictoThing communicates with
   the Pi (if at all in current form). Plan Phase 3: HF encapsulation bridge.

---

## Dependency Reference (Pinned Versions)

| Package | Version | Source |
|---|---|---|
| `foa` | `0.1.0` | git `36b47cdc` (FoA.git) |
| `embassy-net-esp-hosted` | `0.2.0` | local path `~/embassy/` (mjwells2002 fork) |
| `embassy-net-driver` | `0.2.0` | local path `~/embassy/` |
| `embassy-time-driver` | `0.2.0` | local path `~/embassy/` |
| `embassy-time-queue-utils` | `0.1.0` | local path `~/embassy/` |
| `embassy-time` | `0.4.0` | crates.io |
| `esp-hal` | `1.0.0-rc.0` | crates.io |
| `esp-hal-embassy` | `0.9.0` (resolves 0.9.1) | crates.io |
