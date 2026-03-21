# PictoChat-HF Architecture

Full hardware and software architecture for the PictoChat-HF relay system. Covers current state, target single-node state, and multi-node mesh.

---

## Hardware Architecture

### Current State (Phase 2b complete — ESP32 hosting DS, bidirectional echo verified)

```mermaid
graph LR
    DS[Nintendo DS Lite\nPictoChat Room A\nChannel 1]
    AR[AR9271 USB Adapter\nwlan1 — monitor mode\nch1, 1+2 Mbps]
    PI[Raspberry Pi 4\nvessel-01\n192.168.0.254]

    DS <-->|2.4 GHz 802.11b\nbeacons + data frames| AR
    AR <-->|USB 2.0| PI

    style DS fill:#d4edda,stroke:#28a745
    style AR fill:#fff3cd,stroke:#ffc107
    style PI fill:#d4edda,stroke:#28a745
```

**Limitation:** AR9271 in monitor mode does not generate 802.11 ACKs — the DS cannot complete association, so injected frames are dropped.

---

### Phase 2a — Dual-Interface Experiment (AR9271, experimental)

```mermaid
graph LR
    DS[Nintendo DS Lite]
    AR_STA[wlan1 — station mode\nConnected to DS BSSID\nKernel handles ACKs]
    AR_MON[mon0 — monitor mode\nSame physical radio\nRaw frame injection]
    PI[Raspberry Pi 4\nvessel-01]

    DS <-->|Auth + Assoc\nACKs handled by kernel| AR_STA
    DS <-->|Custom PictoChat\ndata frames injected| AR_MON
    AR_STA --- PI
    AR_MON --- PI

    style DS fill:#d4edda,stroke:#28a745
    style AR_STA fill:#cce5ff,stroke:#004085
    style AR_MON fill:#fff3cd,stroke:#ffc107
    style PI fill:#d4edda,stroke:#28a745
```

---

### Phase 2b — Target Single-Node State (ESP32 primary path)

```mermaid
graph LR
    DS[Nintendo DS Lite\nPictoChat Room A]
    ESP[ESP32-WROOM-32\nfoa_dswifi firmware\nLow-MAC 802.11b\nHardware ACKs]
    PI[Raspberry Pi 4\nvessel-01]
    HRF[HackRF One\nSDR TX/RX]
    ANT[EFHW Antenna\n40m or 20m band]
    ION[Ionosphere\nSkywave bounce]

    DS <-->|2.4 GHz 802.11b\nDataCFPoll / DataCFAck\nFull association| ESP
    ESP <-->|USB serial\n/dev/ttyUSB0\nCP2102| PI
    PI <-->|USB| HRF
    HRF <-->|RF coax| ANT
    ANT <-->|HF skywave\n~7 MHz or 14 MHz| ION

    style DS fill:#d4edda,stroke:#28a745
    style ESP fill:#cce5ff,stroke:#004085
    style PI fill:#d4edda,stroke:#28a745
    style HRF fill:#f8d7da,stroke:#721c24
    style ANT fill:#e2e3e5,stroke:#383d41
    style ION fill:#fefefe,stroke:#adb5bd,stroke-dasharray:5 5
```

---

### Multi-Node Architecture (Phase 4 target)

```mermaid
graph TB
    subgraph NodeA ["Node A — Alberta"]
        DSA[DS Lite A]
        ESPA[ESP32]
        PIA[Raspberry Pi]
        HRFA[HackRF One]
        ANTA[EFHW Antenna]
        DSA <-->|2.4 GHz| ESPA
        ESPA <-->|USB serial| PIA
        PIA <-->|USB| HRFA
        HRFA --- ANTA
    end

    subgraph NodeB ["Node B — British Columbia"]
        DSB[DS Lite B]
        ESPB[ESP32]
        PIB[Raspberry Pi]
        HRFB[HackRF One]
        ANTB[EFHW Antenna]
        DSB <-->|2.4 GHz| ESPB
        ESPB <-->|USB serial| PIB
        PIB <-->|USB| HRFB
        HRFB --- ANTB
    end

    subgraph NodeN ["Node N — anywhere"]
        DSN[DS Lite N]
        ESPN[ESP32]
        PIN[Raspberry Pi]
        HRFN[HackRF One]
        ANTN[EFHW Antenna]
        DSN <-->|2.4 GHz| ESPN
        ESPN <-->|USB serial| PIN
        PIN <-->|USB| HRFN
        HRFN --- ANTN
    end

    ANTA <-->|HF skywave\n~2000 km| ANTB
    ANTA <-->|HF skywave| ANTN
    ANTB <-->|HF skywave| ANTN
```

Each node is identical hardware. Any node relays to any other node. The HF mesh is the only long-haul link.

---

## Software Architecture

### Layer Stack

```mermaid
graph TB
    subgraph L4 ["Layer 4 — Application"]
        PC[PictoChat Protocol\nJoin sequence, message frames\nCanvas bitmap encode/decode]
    end

    subgraph L3 ["Layer 3 — HF Link"]
        FEC[Forward Error Correction\nFEC encode/decode]
        ENC[HF Frame Encapsulation\nstrip 2.4 GHz PHY headers\nadd HF framing + metadata]
        SDR[HackRF One Interface\nGNU Radio / SoapySDR\nTX on 40m or 20m]
    end

    subgraph L2 ["Layer 2 — Relay / Bridge"]
        BUF[Replay Buffer\nholds HF-bound frames\nuntil DS is ready]
        SER[Serial Bridge\nPi ↔ ESP32 protocol\n/dev/ttyUSB0]
        ACK[Local ACK Logic\nrespond to DS immediately\nwhile HF round-trip is in flight]
    end

    subgraph L1 ["Layer 1 — 2.4 GHz MAC"]
        LMAC[ESP32 Low-MAC\nfoa_dswifi\n802.11b DataCFPoll/DataCFAck\nhardware ACKs]
    end

    L4 --> L2
    L2 --> L3
    L2 --> L1
    L3 --> L2
```

---

### PictoChat 802.11 Frame Types

```mermaid
graph LR
    subgraph Management
        BCN[Beacon\ntype=0 sub=8\nVendor IE: Nintendo OUI\nRoom + user count]
        AUTH[Auth Request/Response\nopen system\nseq 1 and 2]
        ASSOC[Assoc Request/Response\nSSID = GameID+StreamCode\nrates = 1+2 Mbps only]
        DISAS[Disassociation\nreason=3]
    end

    subgraph Data
        CFP[DataCFPoll\nsubtype=6 FromDS\nhost → clients\naddr1=03:09:bf:00:00:00]
        CFA[DataCFAck\nsubtype=7 ToDS\nclient → host\naddr3=03:09:bf:00:00:10]
        HACK[Host ACK\nsubtype=7\naddr1=03:09:bf:00:00:03\npayload=0x82000000]
    end

    BCN -->|DS emits continuously| AUTH
    AUTH -->|open system handshake| ASSOC
    ASSOC -->|association complete| CFP
    CFP -->|DS polls client| CFA
    CFA -->|client replies| HACK
```

---

### PictoChat Application Join Sequence

```mermaid
sequenceDiagram
    participant DS as DS Lite
    participant Ph as Phantom DS (ESP32)

    DS->>Ph: Beacon (Room A, 1 user)
    Ph->>DS: Auth Request (open system, seq=1)
    DS->>Ph: Auth Response (seq=2, status=0)
    Ph->>DS: Assoc Request (SSID=GameID+StreamCode, rates=1+2 Mbps)
    DS->>Ph: Assoc Response (status=0, AID assigned)

    Note over DS,Ph: Association complete — DS shows 2 users in Room A

    DS->>Ph: Type 6 — client presence announcement
    Ph->>DS: Type 4 — roster frame (flags=28)
    DS->>Ph: Type 0 — transfer start (size=84)
    Ph->>DS: Type 1 — transfer header echo
    DS->>Ph: Type 2 — ConsoleIdPayload (DS identity)
    Ph->>DS: Type 1 — host identity header
    Ph->>DS: Type 2 — host ConsoleIdPayload (magic=[03,00])
    Ph->>DS: Type 1 — request client ident
    DS->>Ph: Type 2 — final client identity

    Note over DS,Ph: Session established

    Ph->>DS: Type 1 — message header
    Ph->>DS: Type 2 — message fragment(s) (180 bytes each)
```

---

### HF Relay Flow (Single Message, One Direction)

```mermaid
sequenceDiagram
    participant DSA as DS Lite A
    participant PhA as Phantom DS (Node A)
    participant PiA as Pi (Node A)
    participant HF as HF Skywave
    participant PiB as Pi (Node B)
    participant PhB as Phantom DS (Node B)
    participant DSB as DS Lite B

    DSA->>PhA: PictoChat message frames
    PhA->>PhA: Local ACK to DS A immediately
    PhA->>PiA: Frame payload over serial
    PiA->>PiA: Strip 2.4 GHz headers\napply FEC\nencapsulate for HF
    PiA->>HF: TX on 40m/20m band
    HF->>PiB: RX at Node B\n(~2–15 min skywave latency)
    PiB->>PiB: Decode FEC\nrecover PictoChat payload
    PiB->>PhB: Frame payload over serial
    PhB->>DSB: Replay PictoChat frames to DS B
    DSB->>DSB: Displays received drawing
```

---

## Component Inventory

| Component | Node | Connection | Status |
| :--- | :--- | :--- | :--- |
| Raspberry Pi 4 | A | — | Deployed (vessel-01) |
| AR9271 USB WiFi | A | USB → wlan1 | Present |
| ESP32-WROOM-32 | A | USB → /dev/ttyUSB0 | Deployed (vessel-01) |
| HackRF One | A | USB | Not acquired |
| EFHW antenna | A | RF coax | Not acquired |
| DS Lite | A | 2.4 GHz to ESP32 | Present |
| All Node B hardware | B | — | Not acquired |

---

## Key Protocol Constants

| Constant | Value |
| :--- | :--- |
| DS Lite BSSID | `00:23:cc:f8:9e:3e` (captured — may change if DS reboots) |
| Nintendo vendor IE OUI | `00:09:BF` |
| Stream code (last capture) | `0xAB38` — **read from beacon at runtime** |
| Room A channel | 1 (2412 MHz) |
| Supported rates | 1 Mbps (0x82) + 2 Mbps (0x84) only |
| Beacon interval | 105 TU (~107 ms) |
| Max fragment size (DS Lite) | 180 bytes per type 2 message fragment |
| Nintendo multicast host→client | `03:09:bf:00:00:00` |
| Nintendo multicast client→host | `03:09:bf:00:00:10` |
| Nintendo multicast host ACK | `03:09:bf:00:00:03` |
| ESP32 host MAC (Node A) | `a4:f0:0f:61:9f:b0` |
| Text message canvas size | 2048 bytes (assembled from 13×172 + 1×16 byte type-2 fragments) |
| Drawing canvas size | 10240 bytes (5 pages × 2048) |
| Last fragment marker | `transfer_flags == 1` (byte 7 in raw type-2 frame) |
| End-of-burst flag | `HostToClientFlags` bit 7 (0x80) — must be set on last echoed/sent fragment |

---

## Message Relay Protocol

### Relay unit: `MessagePayload`

The assembled `MessagePayload` from `pictochat_application.rs` is the relay unit passed
between nodes. It is DS-agnostic — any DS that joins and sends a message produces the same
format:

| Field | Size | Notes |
| :--- | :--- | :--- |
| magic | 1 byte | fixed |
| subtype | 1 byte | 0 = text+drawing, 1 = identity |
| from | 6 bytes | set to **destination node's host MAC** before sending to DS |
| magic_1 | 14 bytes | fixed |
| safezone | 14 bytes | fixed |
| message | 2048 or 10240 bytes | PictoChat canvas bitmap |

The `from` field is overwritten with the local host MAC at each relay hop so the receiving
DS accepts the message as originating from its room host.

### Inter-node TCP framing (implemented in `server_connection_task`, `main.rs`)

```
┌──────────┬──────────────┬──────────────────────────┐
│ type (1B)│ length (2B BE)│ payload (length bytes)   │
└──────────┴──────────────┴──────────────────────────┘

type 0x00 = handshake (no payload)
type 0xFD = data (payload = serialized MessagePayload)
type 0xAD = error
```

### Phase 3 relay path

```
Node A DS → ESP32 inbound_queue → serialize → TCP 0xFD frame → relay server / HF bridge
                                                                        ↓
Node B DS ← ESP32 outbound_queue ← set from=hostMAC ← deserialize ← TCP 0xFD frame
```

For pre-HF testing: relay server is a simple TCP forwarding process on the internet.
For HF: Pi replaces TCP relay — reads serial from ESP32, encapsulates for HackRF TX.

### Main loop changes required (Phase 3)

1. Spawn `server_connection_task` in `main()`
2. Route `inbound_queue` messages to the TCP send channel instead of `outbound_queue`
3. Add a third `select` arm receiving from the TCP receive channel → `outbound_queue`
