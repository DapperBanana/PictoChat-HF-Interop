# Session Notes — 2026-03-18 (Sniffing Deep-Dive)

Continuation of the 2026-03-18 morning session. Focus: passive sniffer development, frame decoding, full message assembly.

---

## Session Goals

- Get picto_sniff.py actually capturing and decoding data frames
- Reassemble complete PictoChat messages from DataFragment sequences
- Decode what "hi" text looks like in the canvas bitmap
- Find out which addresses the client DS uses when sending a message

---

## Critical Bug Fixed: Address Filter Was Broken

### Original broken filter
```python
if not any(DS_BSSID.lower() in a.lower() for a in addrs):
    return
```

**Problem:** `DS_BSSID = "00:23:cc:f8:9e:3e"` was hardcoded to the FIRST DS that opened PictoChat. But DS roles rotate on restart — the SECOND DS becomes the host/AP. When the second DS hosts, its frames use Nintendo multicast addresses (`03:09:bf:xx:xx:xx`), NOT the DS_BSSID. Zero data frames were being decoded.

### Discovery via pcap analysis
Downloading `capture.pcap` and parsing manually revealed:
- 15 frames with DS_BSSID in addresses → all subtype=1, body=6B (empty CF-Acks from original DS)
- **63 frames with payload=118B from `00:1d:bc:97:fc:1c` to `03:09:bf:00:00:00`** — these are the actual data frames, invisible to the sniffer

### Fixed filter
```python
has_nintendo = any("03:09:bf" in a.lower() for a in addrs)
has_known_ds = any(DS_BSSID.lower() in a.lower() for a in addrs)
if not (has_nintendo or has_known_ds):
    return
```

### Fixed `is_host` detection
```python
# WRONG: hardcoded BSSID comparison — breaks if roles rotate
is_host = src.lower() == DS_BSSID.lower()

# CORRECT: host is whoever sends TO CLIENT_MC or ACK_MC
is_host = dst.lower() in (CLIENT_MC.lower(), ACK_MC.lower())
```

---

## Nintendo DS PictoChat 802.11 Frame Types (Empirically Confirmed)

From pcap analysis of `client_test.pcap` (1513 frames, 30 seconds):

| 802.11 Type | Subtype | Src | Dst | Count | Max Size | Role |
|---|---|---|---|---|---|---|
| 2 (Data) | 2 (Data+CF-Poll) | HOST | `03:09:bf:00:00:00` (CLIENT_MC) | 538 | 210B | HOST broadcasts canvas to all clients |
| 2 (Data) | 1 (Data+CF-Ack) | HOST | `03:09:bf:00:00:03` (ACK_MC) | 624 | 210B | HOST acknowledges client, relays data |
| 2 (Data) | 1 (Data+CF-Ack) | CLIENT | HOST unicast | 287 | 30B | CLIENT empty ACK (2B MSDU = `00 80`) |
| 0 (Mgmt) | 8 (Beacon) | HOST | `ff:ff:ff:ff:ff:ff` | 55 | 210B | HOST beacons to world |
| 2 (Data) | 5 (CF-Ack) | CLIENT | HOST unicast | 9 | 28B | CLIENT pure CF-Ack (no data) |

**Key finding:** In a 2-minute unfiltered pcap (`allframes.pcap`, 57,845 frames), the client DS NEVER sent a frame larger than 30B. All client 802.11 MSDUs are 2 bytes (`00 80`) = empty CF-Ack. The client's PictoChat message data is NOT appearing in the data frames we can capture.

---

## HOST Frame Structure (Confirmed)

For HOST→CLIENT_MC frames (sub=2) with PictoChat application data:

```
802.11 frame (stripped by scapy):
  scapy Raw = MSDU bytes

MSDU (scapy Raw):
  byte 0:  0x00 (constant — always zero in HOST frames)
  byte 1:  ps_halfwords  (payload size in 16-bit words)
  byte 2:  flags         (bit7 = RETRY)
  bytes 3..3+ps_bytes-1: PictoChat application layer
  last 4 bytes: Nintendo footer (data_seq u16 LE + client_mask u16 LE)

  ps_bytes = ps_halfwords × 2
```

**Example:** 179B scapy Raw → `ps_halfwords=0x52=82` → `ps_bytes=164` → 3+164+4+misc=~179 ✓

### PictoChat Application Layer
```
offset 0-1: type_id u16 LE
  0 = TransferAnnounce
  1 = TransferHeader
  2 = DataFragment
  4 = Roster (new client event)
  5 = Roster (idle)
  6 = ClientPresence

offset 2-3: size_with_header u16 LE (total app bytes including this header)
offset 4+:  body (type-specific)
```

### DataFragment Body Structure (type_id=2)
```
body[0]:   ??? (always 0x00 in captures — possibly console_id or constant)
body[1]:   fragment flags
             0x00 = FIRST fragment (write_offset=0)
             0x04 = continuation
             0x9b = retry continuation
body[2:4]: payload_length u16 LE  (typically 160 bytes per fragment)
body[4:6]: write_offset u16 LE    (byte position in reassembly buffer: 0, 160, 320, ...)
body[6:8]: magic bytes
body[8:8+payload_length]: actual payload data
```

### TransferHeader Body Structure (type_id=1)
```
body[0:4]:  0x0000FFFF (constant magic)
body[4:6]:  data_total_size u16 LE  (always 0x0824 = 2084 in captures)
            Full message size = 2084 bytes for standard PictoChat messages
body[6:8]:  sequence counter (increments per message)
body[8:12]: session hash / message fingerprint (different per message)
```

---

## Message Reassembly — Working

Fragment reassembly algorithm:
1. **TransferHeader (type=1) received**: record `ann_size = data_total_size`, pre-allocate `bytearray(ann_size)`
2. **DataFragment (type=2) received**: write `payload[0:payload_len]` to `buf[write_offset:write_offset+payload_len]`
3. **FIRST fragment**: `write_offset == 0` — reinitialize buffer to ensure clean start
4. **LAST fragment**: `write_offset + payload_len >= ann_size` — pop and emit assembled message

**Successfully assembled multiple 2084-byte complete messages.**

### MessagePayload Structure (2084 bytes)
Confirmed from assembled buffers:
```
offset 0:     0x03  magic byte
offset 1:     0x02  subtype
offset 2-7:   sender MAC, byte-pair-swapped (Nintendo encoding)
              unswap: raw6[i^1] for i in 0..5
offset 8-35:  metadata (room ID, user slots, session info — not fully decoded)
offset 36+:   canvas bitmap data (2084 - 36 = 2048 bytes)
```

**Byte-pair-swap MAC decode:** `"1d 00 97 bc 1c fc"` → XOR each index with 1 → `"00 1d bc 97 fc 1c"` → `00:1d:bc:97:fc:1c` ✓

**Canvas data confirmed ALL ZEROS** in every assembled message across all sessions. See "Open Questions" below.

---

## DS Role Rotation (Important!)

The DS that **opens PictoChat first** becomes the **host/AP**. The one joining second becomes the client/STA. Roles rotate if PictoChat is restarted on either DS.

| Session start | HOST MAC | CLIENT MAC |
|---|---|---|
| Session 1 (Phase 1) | `00:23:cc:f8:9e:3e` | — (alone in room) |
| Current session | `00:1d:bc:97:fc:1c` (second DS) | `00:23:cc:f8:9e:3e` |

**If the DS setup changes, update `DS_BSSID` in `picto_sniff.py` or rely purely on the Nintendo OUI filter.**

---

## Open Questions / Unsolved

### 1. Canvas is always blank (critical)

All assembled 2084-byte messages from `00:1d:bc:97:fc:1c` have 2048 bytes of zeros at offset 36 (the canvas area). Possible explanations:

- **Most likely: HOST DS user hasn't sent any messages.** The HOST DS broadcasts its own current canvas state. If the HOST user hasn't drawn/typed anything, the canvas is blank. We are only capturing the HOST's outgoing broadcasts.
- **Client's message not relayed.** When the CLIENT user sends a message, the HOST should receive it and rebroadcast it (with non-blank canvas). But we haven't captured any such rebroadcast. Either the timing of our captures didn't overlap with a client-side message send, or the relay mechanism is different.
- **Typed text not in canvas bitmap.** PictoChat may store text-mode messages in a different field. The 2048-byte canvas might be ONLY for stylus drawing. Text may be stored as a separate structure (possibly at a different offset, or as a different type_id entirely).

### 2. Client never sends data frames

In 57,845 frames over 2 minutes of unfiltered pcap, the client DS (`00:23:cc:f8:9e:3e`) sent ZERO data-bearing frames. All client frames are 2B empty ACKs (`0080`).

Possible explanations:
- User never pressed SEND during any of our capture windows (timing coordination issue via SSH)
- Client sends message via a mechanism we haven't identified (different address, different frame type)
- The CF-Poll/CF-Ack exchange where the client embeds data happens faster than the monitor interface can capture (SIFS = 16µs)

### 3. `body[0]` field in DataFragment

We observe `body[0] == 0x00` in 100% of captured DataFragment frames. Originally interpreted as `console_id` but could also be a constant. The foa_dswifi source may clarify.

---

## Tools and Scripts

| Script | Purpose | Location |
|---|---|---|
| `picto_sniff.py` | Full passive sniffer with message assembly and canvas preview | repo root |
| `sniff_fulldump.py` | Verbose sniffer that dumps full 512B hex of each assembled message | repo root |
| `sniff_out5.txt` | First successful complete message assembly | repo root |
| `sniff_full2.txt` | Full hex dumps of assembled messages | repo root |
| `capture.pcap` | Raw pcap from Phase 1 (pre-fix, used for analysis) | repo root |
| `client_test.pcap` | 30s filtered pcap with both DS MACs | repo root |
| `allframes.pcap` | 2min unfiltered pcap — confirmed no client data frames | repo root |

---

## Coordination Notes for Next Session

1. **Need better timing coordination** for user pressing SEND during captures. Options:
   - Run a 10+ minute continuous sniffer on Pi and have user confirm via SSH when they pressed SEND
   - Add a timestamp log to the sniffer so we can correlate with user's reported send times
   - Have the sniffer write a "READY" flag file, poll for it, notify user when sniffer is active

2. **Try sending from HOST DS specifically.** The sniffer captures HOST→ALL broadcasts. If the HOST DS user sends a message, it should appear with non-blank canvas in the next broadcast cycle.

3. **Try stylus drawing.** Fill a large area of the screen with ink before sending. This would produce obvious non-zero bytes in the canvas bitmap, making it easy to confirm we decoded the right content.

4. **Check if text messages use a smaller data_size.** The `TransferHeader` always announces `data_size=2084`. If text-only messages use a different size (e.g., just a text header + message body without the full canvas), the TransferHeader would show a different value. Worth watching for.
