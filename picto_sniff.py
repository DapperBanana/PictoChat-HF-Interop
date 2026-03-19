#!/usr/bin/env python3
"""
PictoChat passive sniffer — runs ON the Pi.

Frame structure (from empirical analysis of captures):
  HOST->ALL (DataCFPoll):
    byte 0:       0x00 (constant)
    byte 1:       payload_size in halfwords (payload_bytes = byte1 * 2)
    byte 2:       flags (bit7 = retransmit)
    bytes 3..3+payload_bytes-1:  PictoChat app layer
    last 4 bytes: Nintendo footer (data_seq u16 + client_mask u16)

  PictoChat app layer:
    u16 LE:  type_id  (0=TransferAnnounce 1=TransferHeader 2=DataFragment
                       4=Roster/new 5=Roster/idle 6=ClientPresence)
    u16 LE:  size_with_header
    bytes:   body

  CLIENT->HOST (DataCFAck):
    byte 0:  payload_size (0 = empty ACK)
    byte 1:  flags
    bytes 2+: PictoChat app layer (if payload_size > 0)
"""
import sys, struct, time
sys.path.insert(0, "/usr/local/lib/python3.13/dist-packages")
from scapy.all import sniff, conf
from scapy.layers.dot11 import Dot11
from scapy.packet import Raw
conf.verb = 0

DS_BSSID  = "00:23:cc:f8:9e:3e"
CLIENT_MC = "03:09:bf:00:00:00"
ACK_MC    = "03:09:bf:00:00:03"
CLT_MC    = "03:09:bf:00:00:10"
IFACE     = "wlan1"

PTYPE = {0:"TransferAnnounce", 1:"TransferHeader", 2:"DataFragment",
         4:"Roster(new)", 5:"Roster(idle)", 6:"ClientPresence"}

seen = 0
fragments = {}        # src_mac -> accumulated bytes
pending_header = {}   # src_mac -> announced data_size (set when TransferHeader seen)

def unswap_mac(raw6):
    """Nintendo byte-pair-swap → normal MAC string."""
    return ":".join(f"{raw6[i^1]:02x}" for i in range(6))

def hexd(data, indent="    "):
    out = []
    for i in range(0, min(len(data), 64), 16):
        chunk = data[i:i+16]
        h = " ".join(f"{b:02x}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{indent}{i:04x}  {h:<47}  {a}")
    if len(data) > 64:
        out.append(f"{indent}... ({len(data)} bytes total)")
    return "\n".join(out)

def try_canvas(data):
    if len(data) < 200:
        return
    W, H = 256, 192
    print("    Canvas preview:")
    for row in range(0, H, 16):
        line = "    |"
        for col in range(0, W, 8):
            idx = row * W + col
            b = data[idx // 2] if idx // 2 < len(data) else 0
            n = (b >> 4) if idx % 2 == 0 else (b & 0x0f)
            line += " .:-=+*#%@"[min(n, 9)]
        line += "|"
        if line.strip("|").strip():  # only print non-blank rows
            print(line)

def decode_picto(app_bytes, src):
    if len(app_bytes) < 4:
        return
    type_id = struct.unpack_from("<H", app_bytes, 0)[0]
    size    = struct.unpack_from("<H", app_bytes, 2)[0]
    body    = app_bytes[4:]
    tname   = PTYPE.get(type_id, f"Unknown({type_id})")

    print(f"    PictoChat type={type_id} ({tname})  size={size}  body={len(body)}B")

    if type_id == 6:
        print("    *** CLIENT JOINED Room A ***")

    elif type_id == 5:   # idle roster
        if len(body) >= 4:
            # magic(4) + 16 × 6-byte MACs (byte-pair-swapped)
            macs = []
            for i in range(16):
                off = 4 + i * 6
                if off + 6 > len(body): break
                raw = body[off:off+6]
                if raw == b'\x00' * 6: continue
                macs.append(unswap_mac(raw))
            if macs:
                print(f"    Room members: {', '.join(macs)}")

    elif type_id == 4:   # roster with new client
        print("    Roster (new client event)")
        if len(body) >= 4:
            for i in range(16):
                off = 4 + i * 6
                if off + 6 > len(body): break
                raw = body[off:off+6]
                if raw == b'\x00' * 6: continue
                print(f"    Slot {i}: {unswap_mac(raw)}")

    elif type_id == 1:   # transfer header
        print(f"    Transfer header: {body[:20].hex()}")
        if len(body) >= 6:
            data_size = struct.unpack_from("<H", body, 4)[0]
            print(f"    Announced data size: {data_size}B")
        # Reset fragment buffer — pre-allocate full size so partial captures still decode correctly
        pending_header[src] = data_size if len(body) >= 6 else 0
        ann = pending_header[src]
        fragments[src] = bytearray(ann) if ann > 0 else bytearray()

    elif type_id == 2:   # data fragment — this is where the message lives
        # Per-fragment layout (body after 4B PictoChat header):
        #   body[0]   = console_id (which DS slot sent this)
        #   body[1]   = flags (0x69=first-of-cycle, 0x04=continuation)
        #   body[2:4] = payload_length u16 LE (actual data bytes, typ. 160)
        #   body[4:6] = write_offset u16 LE (byte position in reassembly buffer)
        #   body[6:8] = magic (2 bytes)
        #   body[8:]  = actual payload (payload_length bytes)
        if len(body) < 9: return
        console_id   = body[0]
        flags        = body[1]
        payload_len  = struct.unpack_from("<H", body, 2)[0]
        write_offset = struct.unpack_from("<H", body, 4)[0]
        payload      = body[8:8 + payload_len]

        is_first = (write_offset == 0)
        ann_size = pending_header.get(src, 0)
        is_last  = (ann_size > 0 and write_offset + payload_len >= ann_size)

        flag_str = ("FIRST " if is_first else "") + ("LAST" if is_last else "")
        print(f"    Fragment cid=0x{console_id:02x} flags=0x{flags:02x} "
              f"offset={write_offset} plen={payload_len} {flag_str}")

        key = src
        if is_first:
            if ann_size > 0:
                fragments[key] = bytearray(ann_size)
            else:
                fragments[key] = bytearray()

        if key in fragments:
            if ann_size > 0:
                end = min(write_offset + payload_len, ann_size)
                fragments[key][write_offset:end] = payload[:end - write_offset]
            else:
                fragments[key].extend(payload)

        if is_last and key in fragments:
            buf  = fragments.pop(key)
            full = bytes(buf[:ann_size] if ann_size > 0 else buf)
            print(f"\n    *** COMPLETE MESSAGE from {src} ({len(full)}B) ***")
            # MessagePayload structure:
            # byte 0:    magic 0x03
            # byte 1:    subtype 0x02
            # bytes 2-7: sender MAC (byte-pair-swapped)
            # bytes 8-21: magic_1 (14 bytes)
            # bytes 22-35: safezone (14 bytes)
            # bytes 36+:  message content (4bpp canvas bitmap)
            if len(full) >= 8 and full[0] == 0x03:
                sender = unswap_mac(full[2:8])
                print(f"    From: {sender}")
            print(f"    Raw (first 64B):\n{hexd(full)}")
            if len(full) > 36:
                try_canvas(full[36:])

    elif type_id == 0:   # transfer announce
        print(f"    Transfer announce: {body[:16].hex()}")


def handle(pkt):
    global seen
    if not pkt.haslayer(Dot11) or not pkt.haslayer(Raw):
        return
    d = pkt[Dot11]
    if d.type != 2:
        return

    addrs = [d.addr1 or "", d.addr2 or "", d.addr3 or ""]
    has_nintendo = any("03:09:bf" in a.lower() for a in addrs)
    has_known_ds = any(DS_BSSID.lower() in a.lower() for a in addrs)
    if not (has_nintendo or has_known_ds):
        return

    payload = bytes(pkt[Raw])
    src = d.addr2 or "?"
    dst = d.addr1 or "?"
    seen += 1

    # HOST sends to CLIENT_MC (03:09:bf:00:00:00) or ACK_MC (03:09:bf:00:00:03)
    # CLIENT sends to CLT_MC (03:09:bf:00:00:10) or host unicast
    is_host = dst.lower() in (CLIENT_MC.lower(), ACK_MC.lower())

    if is_host:
        # HOST frame: byte0=const, byte1=payload_size in halfwords, byte2=flags
        if len(payload) < 3:
            return
        ps_halfwords = payload[1]
        flags        = payload[2]
        ps_bytes     = ps_halfwords * 2
        retry        = bool(flags & 0x80)

        if ps_bytes == 0:
            return   # empty host poll — skip

        app = payload[3 : 3 + ps_bytes]
        if len(app) < 4:
            return

        type_id = struct.unpack_from("<H", app, 0)[0]

        # Skip noisy idle roster frames unless verbose
        if type_id == 5:
            return  # comment this out to see all roster frames

        if dst.lower() == CLIENT_MC.lower():
            direction = "HOST->ALL"
        elif dst.lower() == ACK_MC.lower():
            direction = "HOST->ACK"
        else:
            direction = f"HOST->{dst}"
        r = " [RETRY]" if retry else ""
        print(f"\n[{seen}] {direction}  {len(payload)}B{r}")
        decode_picto(app, src)

    else:
        # CLIENT frame: byte0=payload_size, byte1=flags
        if len(payload) < 2:
            return
        ps = payload[0]
        flags_b = payload[1] if len(payload) > 1 else 0

        if ps == 0:
            # Show all client ACKs so we can see if client ever sends data
            print(f"\n[{seen}] CLIENT(empty-ack) src={src} dst={dst}  {len(payload)}B  raw={payload[:8].hex()}")
            return

        print(f"\n[{seen}] CLIENT(data) src={src} dst={dst}  {len(payload)}B  ps={ps} flags=0x{flags_b:02x}")
        print(f"    raw(first 16B): {payload[:16].hex()}")

        app = payload[2 : 2 + ps]
        if len(app) < 4:
            print(f"    app too short ({len(app)}B), raw: {app.hex()}")
            return

        decode_picto(app, src)


print(f"Sniffing PictoChat on {IFACE} (channel 1)")
print(f"Known DS BSSID: {DS_BSSID} (filter also accepts any 03:09:bf Nintendo OUI)")
print("Idle roster frames hidden. SEND A MESSAGE NOW then watch here.")
print("Ctrl+C to stop.\n")

try:
    sniff(iface=IFACE, prn=handle, store=False)
except KeyboardInterrupt:
    print(f"\nDone. {seen} data frames seen.")
