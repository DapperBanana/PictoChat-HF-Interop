# PictoChat Protocol Findings

Comprehensive reference compiled from empirical captures (vessel-01 / wlan1 monitor mode) and comparison with published GitHub research. Last updated: 2026-03-18.

---

## Overview

Nintendo DS PictoChat uses a custom 802.11b application running in CF-Poll (Contention-Free) mode. The protocol is asymmetric: one DS acts as host/AP and polls clients for data; clients respond in the SIFS window between polls.

---

## Our Empirical Findings vs Published Research

### foa_dswifi (mjwells2002, GitHub — primary reference)

**Source:** `mjwells2002/foa_dswifi` — ESP32 Rust implementation that successfully joins PictoChat.

| Aspect | foa_dswifi says | Our empirical captures |
|---|---|---|
| Association SSID | `GameID (4B) + StreamCode (2B LE) + 0x00×26` | ✓ Confirmed |
| Auth type | Open system (seq 1/2) | ✓ Confirmed |
| Supported rates | 1 Mbps + 2 Mbps only | ✓ Confirmed |
| HOST→client frame | DataCFPoll, described as "subtype 6" | Sub=2 in pcap (Data+CF-Poll) |
| CLIENT→host frame | DataCFAck, described as "subtype 7" | Sub=1 in pcap (Data+CF-Ack) |
| PictoChat join sequence | type 6 → type 4 → type 0/1/2 identity exchange → type 4/5 roster | type 6 ClientPresence seen in captures ✓ |
| Message transfer | TransferHeader (type=1) + DataFragment (type=2) | ✓ Confirmed |
| Fragment size | 180 bytes per fragment (DS Lite) | 160 bytes observed in captures |
| Total message size | Not specified | 2084 bytes observed |
| Nintendo multicast addrs | Mentioned | ✓ Confirmed (see table below) |

**Note on subtype discrepancy:** foa_dswifi describes "subtype 6/7" but our pcap shows sub=2/1. IEEE 802.11 subtype 2 = "Data+CF-Poll" and subtype 1 = "Data+CF-Ack". Subtype 6 = "Data+CF-Ack+CF-Poll" (combined). The foa_dswifi numbers may refer to a higher-level Nintendo DS MAC layer abstraction, or there may be a protocol version difference. Both are valid CF-Period subtypes.

### Thesola10/PictoChat (GitHub)

General PictoChat documentation and protocol analysis. Key confirmations:
- Channel assignments: Room A=1, B=7, C=13
- Vendor IE structure (OUI `00:09:BF` inside IE, not as outer BSSID)
- Beacon interval ~107ms
- Stream code in vendor IE identifies the session

### ricbit.com / matthil.de PictoChat documentation

Same vendor IE structure confirmation. Adds:
- Beacon type values: 0x01=PictoChat, 0x09=Empty, 0x0B=Multiboot
- Fixed marker 0x2348 in vendor IE
- Room ID at offset 26, user count at offset 27

---

## Nintendo Multicast Addresses

| Address | Direction | 802.11 Frame Used |
|---|---|---|
| `03:09:bf:00:00:00` | HOST → all clients (CLIENT_MC) | Data+CF-Poll (sub=2) |
| `03:09:bf:00:00:03` | HOST → clients (ACK_MC), relay/ack | Data+CF-Ack (sub=1) |
| `03:09:bf:00:00:10` | CLIENT → host (CLT_MC) | Expected in client data frames (not yet captured) |

All three addresses have the `03:09:bf` Nintendo OUI (multicast bit set = `03` = locally administered multicast). The last 3 bytes encode slot/direction information.

---

## PictoChat Application Layer Types

| type_id | Name | Description |
|---|---|---|
| 0 | TransferAnnounce | Announces an upcoming data transfer |
| 1 | TransferHeader | Transfer metadata: total size, sequence, session hash |
| 2 | DataFragment | Actual canvas/message data in 160-byte chunks |
| 4 | Roster (new) | Room member list after new client joins |
| 5 | Roster (idle) | Periodic room member list broadcast |
| 6 | ClientPresence | New client announcing its presence |

---

## PictoChat HOST Frame Wire Format

```
802.11 MSDU (what scapy presents as Raw layer):

byte 0:    0x00 (constant — purpose unknown, possibly CF frame marker)
byte 1:    ps_halfwords (payload size / 2 = number of 16-bit words)
byte 2:    flags
             bit 7: RETRY (frame is a retransmission)
byte 3..3+ps_bytes-1: PictoChat application layer
last 4 bytes: Nintendo footer
  bytes -4..-3: data_seq u16 LE  (sequence number)
  bytes -2..-1: client_mask u16 LE

ps_bytes = ps_halfwords × 2

PictoChat application layer:
  [0:2]  type_id u16 LE
  [2:4]  size_with_header u16 LE  (total app layer bytes including these 4)
  [4:]   body (type-specific, see below)
```

### TransferHeader Body (type_id = 1)
```
body[0:4]:  0x0000FFFF       (constant magic)
body[4:6]:  data_total_size  u16 LE  (full reassembled message size, typically 2084)
body[6:8]:  sequence_counter u16 LE  (increments per message sent)
body[8:12]: session_hash     u32     (different per message; identifies this specific transfer)
            — remaining bytes if present: padding/unknown
```

### DataFragment Body (type_id = 2)
```
body[0]:   0x00              (constant or console_id — always 0x00 in all captures)
body[1]:   fragment_flags
             0x00 = first fragment (write_offset == 0)
             0x04 = continuation
             0x9b = retry continuation (bit7 = retransmit, other bits = cycle marker)
body[2:4]: payload_length    u16 LE  (bytes of actual data in this fragment, typ. 160)
body[4:6]: write_offset      u16 LE  (offset in reassembly buffer: 0, 160, 320, ...)
body[6:8]: magic              u16    (purpose unknown)
body[8:8+payload_length]: payload data
```

**Fragment detection:**
- FIRST: `write_offset == 0`
- LAST: `write_offset + payload_length >= ann_size` (where `ann_size` is from TransferHeader)

---

## Assembled MessagePayload Structure (2084 bytes)

```
offset 0:     0x03         magic byte (marks valid assembled message)
offset 1:     0x02         subtype
offset 2:7:   sender_mac  6 bytes, Nintendo byte-pair-swapped encoding
              decode: mac_bytes[i] = raw[i^1] for i in 0..5
              e.g., "1d 00 97 bc 1c fc" → "00 1d bc 97 fc 1c" → 00:1d:bc:97:fc:1c
offset 8:35:  metadata    28 bytes (room ID, user slots, session info — partially decoded)
              byte 8:  room ID? (0x00 = Room A)
              byte 14: 0x01 (user count or slot?)
              bytes 16-19: "09 0b 10 1b" — version or session marker?
offset 36+:   canvas_data  (2084 - 36 = 2048 bytes)
```

**Canvas data format:** 2048 bytes. Likely 4bpp or 1bpp bitmap. Currently all-zero in every captured message. See "Open Questions" below.

---

## Fragment Reassembly — Recommended Algorithm

```python
fragments = {}        # src_mac -> bytearray(ann_size)
pending_header = {}   # src_mac -> announced data_size

# On TransferHeader (type_id == 1):
data_size = struct.unpack_from("<H", body, 4)[0]
pending_header[src] = data_size
fragments[src] = bytearray(data_size)   # pre-allocate full buffer

# On DataFragment (type_id == 2):
payload_len  = struct.unpack_from("<H", body, 2)[0]
write_offset = struct.unpack_from("<H", body, 4)[0]
payload      = body[8 : 8 + payload_len]
ann_size     = pending_header.get(src, 0)
is_first = (write_offset == 0)
is_last  = (ann_size > 0 and write_offset + payload_len >= ann_size)

if is_first and ann_size > 0:
    fragments[src] = bytearray(ann_size)  # reinit on new FIRST fragment
if src in fragments and ann_size > 0:
    end = min(write_offset + payload_len, ann_size)
    fragments[src][write_offset:end] = payload[:end - write_offset]
if is_last and src in fragments:
    buf  = fragments.pop(src)
    full = bytes(buf[:ann_size])
    # full is the complete 2084-byte MessagePayload
```

**Important:** Pre-allocate `bytearray(data_size)` in the TransferHeader handler, not as an empty `bytearray()`. This ensures fragments can be written at the correct offsets even if the FIRST fragment (offset=0) is not received.

---

## CLIENT Frame Behavior (Observations)

In all captures (`client_test.pcap`, `allframes.pcap`):

| Frame type | Count | Size | Payload |
|---|---|---|---|
| sub=1 (Data+CF-Ack) to HOST unicast | 287 / 1156 | 30B | 2B MSDU = `00 80` (empty ACK) |
| sub=5 (CF-Ack) to HOST unicast | 9 / 24 | 28B | 0B MSDU (pure ACK) |

The client DS **never transmitted a data-bearing frame** in any of our captures. All client frames are empty CF-Acks. The mechanism by which the client sends PictoChat messages has not yet been captured.

**Hypothesis 1:** User never pressed SEND during a capture window (timing issue).
**Hypothesis 2:** Client messages are embedded in sub=1 frames that occur in the SIFS window immediately after CF-Poll reception — too brief for the monitor interface to capture separately from the CF-Poll.
**Hypothesis 3:** Client uses a different addressing scheme (e.g., CLT_MC `03:09:bf:00:00:10`) that we haven't successfully captured.

---

## Comparison with foa_dswifi: What We Still Need to Confirm

| Protocol step | foa_dswifi reference | Our status |
|---|---|---|
| Client joins via auth/assoc | ✓ (code exists) | Not tested via sniffer |
| Client sends type-6 presence | ✓ (code shows this) | Seen in captures ✓ |
| Host sends roster type-4 | ✓ | type-4 seen briefly |
| Identity exchange (type 0/1/2) | ✓ detailed in foa_dswifi | Not yet captured cleanly |
| Canvas message type-1 + type-2 | ✓ | TransferHeader + DataFragment confirmed ✓ |
| Fragment size 180B | ✓ | **Discrepancy: we see 160B, not 180B** |
| Full message content decoded | ✓ (foa_dswifi shows sender MAC etc.) | Canvas always blank — text not decoded |

**Fragment size discrepancy:** foa_dswifi mentions 180 bytes per fragment. We consistently observe 160-byte payloads. This may be a DS Lite vs DSi difference, or a different firmware version.

---

## What foa_dswifi Does That We Should Study

For Phase 2b (ESP32 integration), the foa_dswifi codebase shows:

1. **Full association flow** — exact frame sequence for an ESP32 to join an existing PictoChat room
2. **CF-Poll/CF-Ack participation** — how the ESP32 responds to the host's polls correctly
3. **Identity exchange** — the type 0/1/2 frames that establish who a player is
4. **Message sending** — how a client queues and sends its canvas drawing to the host
5. **Roster management** — type 4/5 frame handling

Study targets in foa_dswifi source:
- How `payload_length` and `write_offset` are set when constructing outgoing DataFragment frames
- What `body[0]` (the mysterious always-0x00 field) represents
- The full identity exchange sequence before messages can be sent

---

## Capture Infrastructure on vessel-01

```bash
# Monitor mode setup (needed after each reboot)
sudo ip link set wlan1 down
sudo iw dev wlan1 set type monitor
sudo ip link set wlan1 up
sudo iw dev wlan1 set channel 1

# Run sniffer
sudo python3 -u /home/root-1/picto_sniff.py

# Raw pcap capture
sudo tcpdump -i wlan1 -w /tmp/cap.pcap

# Filter after the fact (finds non-broadcast non-management frames)
# — look for frames with 03:09:bf or DS MAC
```

---

## Next Steps for Sniffing

### High priority
1. **Coordinate SEND timing.** Run a 10-minute sniffer and have the user send messages while confirming via SSH when they've sent. Watch for TransferHeader with non-blank canvas.
2. **Send from HOST DS.** Have the HOST DS user (`00:1d:bc:97:fc:1c`) type/draw a message and send it. This guarantees we see the message in the HOST→CLIENT_MC broadcasts.
3. **Try a stylus drawing.** Fill a large area with ink — the canvas bytes would be obviously non-zero and unmistakeable in the hex dump.

### Medium priority
4. **Capture the identity exchange.** Run the sniffer when both DSes first connect (power one off and on). This should produce type-0, type-1, type-4 frames in sequence.
5. **Decode CLIENT→host frames properly.** When the client sends, what exact subtype and address does it use? Run a capture immediately after pressing SEND on the client DS.
6. **Watch TransferHeader for size variation.** Do text-only messages still use 2084 bytes? Or is there a smaller payload for typed text?

### Low priority (for Phase 2b planning)
7. **Read foa_dswifi body[0] field.** Look at the Rust source to determine if this is a console_id, a constant, or something else.
8. **Decode offset 8-35 of MessagePayload.** Reverse-engineer what the metadata fields mean (room ID, user slot assignments, etc.).
