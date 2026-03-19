#!/usr/bin/env python3
"""Sniffer that prints full 512B hex of each assembled message."""
import sys, struct, time
sys.path.insert(0, "/usr/local/lib/python3.13/dist-packages")
from scapy.all import sniff, conf
from scapy.layers.dot11 import Dot11
from scapy.packet import Raw
conf.verb = 0

DS_BSSID  = "00:23:cc:f8:9e:3e"
CLIENT_MC = "03:09:bf:00:00:00"
ACK_MC    = "03:09:bf:00:00:03"
IFACE     = "wlan1"

seen = 0
fragments = {}
pending_header = {}

def unswap_mac(raw6):
    return ":".join(f"{raw6[i^1]:02x}" for i in range(6))

def hexd(data, max_bytes=512):
    out = []
    limit = min(len(data), max_bytes)
    for i in range(0, limit, 16):
        chunk = data[i:i+16]
        h = " ".join(f"{b:02x}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"  {i:04x}  {h:<47}  {a}")
    if len(data) > limit:
        out.append(f"  ...({len(data)} total bytes)")
    return "\n".join(out)

def decode_picto(app_bytes, src):
    if len(app_bytes) < 4:
        return
    type_id = struct.unpack_from("<H", app_bytes, 0)[0]
    body    = app_bytes[4:]

    if type_id == 5:
        return  # idle roster, skip

    if type_id == 1:
        data_size = struct.unpack_from("<H", body, 4)[0] if len(body) >= 6 else 0
        print(f"    TransferHeader: data_size={data_size}")
        pending_header[src] = data_size
        fragments[src] = bytearray(data_size) if data_size > 0 else bytearray()

    elif type_id == 2:
        if len(body) < 9:
            return
        payload_len  = struct.unpack_from("<H", body, 2)[0]
        write_offset = struct.unpack_from("<H", body, 4)[0]
        payload      = body[8:8 + payload_len]
        ann_size     = pending_header.get(src, 0)
        is_first     = (write_offset == 0)
        is_last      = (ann_size > 0 and write_offset + payload_len >= ann_size)

        if is_first and ann_size > 0:
            fragments[src] = bytearray(ann_size)
        if src in fragments and ann_size > 0:
            end = min(write_offset + payload_len, ann_size)
            fragments[src][write_offset:end] = payload[:end - write_offset]

        if is_last and src in fragments:
            buf  = fragments.pop(src)
            full = bytes(buf[:ann_size] if ann_size > 0 else buf)
            sender = "?"
            if len(full) >= 8 and full[0] == 0x03:
                sender = unswap_mac(full[2:8])
            print(f"\n*** COMPLETE MESSAGE {len(full)}B from src={src} sender={sender} ***")
            print(hexd(full, max_bytes=512))
            fname = f"/tmp/msg_{int(time.time()*1000)}.bin"
            with open(fname, "wb") as f:
                f.write(full)
            print(f"[saved {fname}]")

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
    is_host = dst.lower() in (CLIENT_MC.lower(), ACK_MC.lower())
    if not is_host:
        return
    if len(payload) < 3:
        return
    ps_bytes = payload[1] * 2
    if ps_bytes == 0:
        return
    app = payload[3 : 3 + ps_bytes]
    if len(app) < 4:
        return
    type_id = struct.unpack_from("<H", app, 0)[0]
    if type_id not in (1, 2):
        return
    print(f"[{seen}] HOST type={type_id} off={struct.unpack_from('<H', app[4:], 4)[0] if type_id==2 and len(app)>=12 else '?'}")
    decode_picto(app, src)

print("Sniffing — SEND A MESSAGE NOW")
sys.stdout.flush()
try:
    sniff(iface=IFACE, prn=handle, store=False, timeout=90)
except Exception as e:
    print(f"Error: {e}")
print(f"Done. {seen} data frames seen.")
