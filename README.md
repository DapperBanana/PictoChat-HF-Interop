# PictoChat-HF: Inter-Provincial Ionospheric Interop

An experimental system to extend Nintendo DS PictoChat range from ~100m to hundreds of kilometres using HF radio and ionospheric skywave propagation.

The goal: trick two (or more) Nintendo DS units into believing they are in the same room while their packets bounce off the Earth's ionosphere between Alberta and British Columbia — or anywhere else.

**This is a 10/10 difficulty project for a 1/10 utility payoff. That is the point.**

See `architecture.md` for full hardware and software diagrams.

---

## How It Works

Each node is a Raspberry Pi + ESP32 + HackRF One sitting next to a Nintendo DS.

```
DS Lite  <--2.4 GHz 802.11b-->  ESP32  <--USB serial-->  Pi  <--USB-->  HackRF One  <--HF skywave-->  [ ... ]  <--HF-->  HackRF One  <--USB-->  Pi  <--USB serial-->  ESP32  <--2.4 GHz-->  DS Lite
```

The ESP32 acts as a "Phantom DS" — it associates with the real DS as if it were a second Nintendo DS in the room, using the same proprietary 802.11b protocol. The Raspberry Pi relays messages between the ESP32 and the HackRF One, which transmits and receives on the 40m or 20m HF band. On the other end, an identical node reassembles the frames and replays them to the remote DS.

Latency will be several minutes per canvas sync. This is "Slow-Scan PictoChat," not real-time chat.

---

## Phase Status

| Phase | Description | Status |
| :--- | :--- | :--- |
| 1 | Reverse-engineer PictoChat beacon + data frames | **Complete** ✅ |
| 2a | Phantom DS via AR9271 dual-interface (experimental) | In progress |
| 2b | Phantom DS via ESP32 (foa_dswifi) — primary path | ESP32 on order |
| 3 | HF encapsulation + HackRF One integration | Not started |
| 4 | Multi-node field test (AB ↔ BC) | Not started |

---

## Hardware Per Node

| Component | Purpose |
| :--- | :--- |
| **Nintendo DS / DS Lite** | The UI — signal source and sink |
| **Raspberry Pi 4/5** | Central coordinator |
| **ESP32-WROOM-32** | 2.4 GHz Phantom DS (hardware 802.11b ACKs) |
| **HackRF One** | HF SDR transceiver (TX/RX on 40m or 20m) |
| **End-Fed Half-Wave antenna** | Skywave propagation |

The AR9271 USB WiFi adapter (ath9k_htc driver) is used for Phase 1 sniffing and Phase 2a experimentation.

---

## Phase 1 — What We Found

The DS Lite (Room A) emits 802.11b beacons on channel 1 at 105 TU intervals, with a Nintendo vendor IE (OUI `00:09:BF`) inside. Captured and fully decoded:

| Field | Value |
| :--- | :--- |
| BSSID | `00:23:cc:f8:9e:3e` |
| Channel | 1 |
| Rates | 1 Mbps + 2 Mbps **only** |
| Game ID | `0x00000000` (PictoChat) |
| Stream code | `0xAB38` (per-session, read at runtime) |
| Room | A |

The stream code changes every session — it must be read from the live beacon, not hardcoded.

---

## Why the ESP32

The Nintendo DS expects standard 802.11b ACK frames within microseconds of each transmitted frame. A Linux WiFi adapter in monitor mode does not generate these ACKs. The ESP32 (via the `foa` crate's Low-MAC interface) operates below the normal WiFi stack and generates ACKs in hardware, exactly as a real DS would.

Reference implementation: [`mjwells2002/foa_dswifi`](https://github.com/mjwells2002/foa_dswifi) (Rust, ESP32).

---

## Constraints

- **Latency:** Several minutes per canvas sync.
- **Legal:** Valid Amateur Radio Licence required for HF transmission.
- **Multi-node:** The architecture supports N nodes. Any node can relay to any other node over HF.
