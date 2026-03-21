# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PictoChat-HF** is an experimental hardware/radio project to extend Nintendo DS PictoChat range from ~30-100m to hundreds of kilometers using HF radio and ionospheric skywave propagation. The goal is a multi-node network where each node (Raspberry Pi + ESP32 + HackRF One) relays PictoChat sessions over the ionosphere — initially targeting Alberta ↔ British Columbia, but designed to support N nodes.

See `architecture.md` for full hardware/software diagrams. Session notes are in `session-YYYY-MM-DD.md` files.

## Phase Status

| Phase | Description | Status |
| :--- | :--- | :--- |
| 1 | Reverse-engineer PictoChat beacon and data frames | **Complete** ✅ |
| 2a | Phantom DS via AR9271 dual-interface (station+monitor) | **In progress — experimental** |
| 2b | Phantom DS via ESP32 (foa_dswifi) — primary path | **Complete** ✅ |
| 3 | HF encapsulation + HackRF One integration | **In progress — relay framework designed** |
| 4 | Multi-node field test (AB ↔ BC) | Not started |

## Hardware Per Node

| Component | Role | Status |
| :--- | :--- | :--- |
| Raspberry Pi 4/5 | Central coordinator, HF bridge, serial bus | Deployed (vessel-01) |
| ESP32-WROOM-32 (ELEGOO 2-pack) | 2.4 GHz Phantom DS — 802.11b with hardware ACKs | Deployed (vessel-01) |
| AR9271 USB WiFi adapter (wlan1) | 2.4 GHz sniffing / dual-interface experiment | Present on vessel-01 |
| HackRF One | HF TX/RX (SDR, used with upconverter on 40m/20m) | Not yet acquired |
| Nintendo DS Lite | User interface — signal source and sink | Present |
| EFHW antenna | Skywave propagation | Not yet acquired |

## Raspberry Pi (vessel-01)

| Property | Value |
| :--- | :--- |
| Hostname | `vessel-01` (mDNS: `vessel-01.local`) |
| IPv4 | `192.168.0.254` |
| Username | `root-1` |
| Password | see `secrets.local` |
| OS | Debian 13 (Trixie), kernel 6.12.47 |
| SSH | Confirmed working |

Connect: `ssh root-1@vessel-01.local` or `ssh root-1@192.168.0.254`

Credentials in `secrets.local` (gitignored). Copy `secrets.local.example` to `secrets.local` and fill in.

**sudo via paramiko (non-interactive):**
```python
cmd = f"echo '{password}' | sudo -S {inner_command}"
stdin, stdout, stderr = client.exec_command(cmd)
```

**SFTP for large file transfers (heredoc via exec_command drops connection):**
```python
sftp = client.open_sftp()
with sftp.open('/path/on/pi', 'w') as f:
    f.write(content)
sftp.close()
```

## Wireless on vessel-01

- Adapter: AR9271 (ath9k_htc) on `wlan1`
- Current mode: monitor, channel 1
- Set monitor mode: `sudo ip link set wlan1 down && sudo iw dev wlan1 set type monitor && sudo ip link set wlan1 up`
- Set channel: `sudo iw dev wlan1 set channel 1`
- Scapy 2.7.0 at `/usr/local/lib/python3.13/dist-packages`

## Phase 1 Findings (Complete)

DS Lite beacon captured and fully decoded. Key values:

| Field | Value |
| :--- | :--- |
| BSSID | `00:23:cc:f8:9e:3e` |
| Channel | 1 (Room A) |
| Rates | 1 Mbps + 2 Mbps only — identification signature |
| Vendor IE OUI | `00:09:BF` (Nintendo — inside IE, NOT the outer BSSID OUI) |
| Game ID | `0x00000000` (PictoChat) |
| Stream code | `0xAB38` (changes each session — read from beacon at runtime) |
| Room | `0x00` = Room A |
| User count | 1 |

Association SSID (32 bytes): `Game ID (4B, 0x00000000) + Stream code (2B LE) + 0x00 × 26`

Nintendo multicast addresses:
- `03:09:bf:00:00:00` — host → all clients (DataCFPoll)
- `03:09:bf:00:00:03` — host ACK to clients
- `03:09:bf:00:00:10` — client → host (DataCFAck)

Why the beacon was missed in session 1: searched for `00:09:BF` as the outer BSSID OUI, but DS Lite uses `00:23:CC`. The `00:09:BF` OUI only appears inside the vendor IE payload.

## Phase 2a — AR9271 Dual-Interface Experiment

The AR9271 generates 802.11 ACKs in hardware when in station or AP mode — it only suppresses them in monitor mode. Hypothesis: run `wlan1` in station mode (kernel handles ACKs) and create a secondary `mon0` monitor interface on the same radio for raw frame injection.

Approach:
1. `iw dev wlan1 connect 00:23:cc:f8:9e:3e` — kernel completes standard open-system auth/assoc
2. `iw phy phy2 interface add mon0 type monitor` — secondary inject interface
3. Inject PictoChat frames via mon0 with scapy

Risk: the DS may reject standard kernel-driven auth/assoc because its proprietary stack expects specific capabilities.

## Phase 2b — ESP32 Primary Path

Reference implementation: `mjwells2002/foa_dswifi` (GitHub, Rust, Embassy + foa crate).

The ESP32 operates at the Low-MAC (LMac) layer — full hardware ACK generation. It connects to the DS as a second DS would:
- Standard open-system auth/assoc (DS accepts this per foa_dswifi)
- DataCFPoll (host→client, subtype 6) and DataCFAck (client→host, subtype 7)
- PictoChat join: type 6 → type 4 → type 0/1/2 identity exchange → type 4/5 roster
- Message: type 1 header frame + type 2 data fragments (180 bytes/fragment for DS Lite)

ESP32 → Pi: USB serial via `/dev/ttyUSB0` (CP2102, no driver needed). Pi sends relay commands; ESP32 handles the DS side.

Toolchain to set up before ESP32 arrives: `espup` (installs Rust ESP32 target) + `espflash`.

## Phase 3 — HF Layer

- **Hardware:** HackRF One (1 MHz–6 GHz, half-duplex, 20 MHz bandwidth)
- **Bands:** 40m (7.0–7.3 MHz) or 20m (14.0–14.35 MHz) for AB↔BC skywave
- **Software:** GNU Radio or Python via SoapySDR / hackrf bindings
- **Modulation:** TBD — JS8Call, FT8, or custom OFDM with FEC
- **Antenna:** End-Fed Half-Wave (EFHW), tuned for target band

Both ends use identical hardware. The system is symmetric and designed for N nodes.

## Key Constraints

- **Latency:** Expect several minutes per canvas sync — "Slow-Scan PictoChat," not real-time.
- **Legal:** Valid Amateur Radio License required for any HF transmission.
- **Multi-node:** Architecture supports N nodes. Any node relays to any other node over HF mesh.
