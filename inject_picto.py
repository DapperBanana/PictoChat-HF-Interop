#!/usr/bin/env python3
"""
Phase 2a inject script — runs ON the Pi.
Assumes wlan0 is connected to home WiFi (SSH stable).
wlan1 (AR9271, phy1) is free to use for DS association.
"""
import sys, time, subprocess
sys.path.insert(0, "/usr/local/lib/python3.13/dist-packages")
from scapy.all import sendp, sniff, RadioTap, Raw, conf
from scapy.layers.dot11 import (Dot11, Dot11Elt, Dot11Auth,
                                 Dot11AssoReq, Dot11AssoResp, Dot11Disas)
conf.verb = 0

IP  = "/sbin/ip"
IW  = "/usr/sbin/iw"
NMC = "/usr/bin/nmcli"

DS_BSSID   = "00:23:cc:f8:9e:3e"
OUR_MAC    = "00:23:cc:de:ad:01"
HOME_SSID  = "NCC-1701D"
PHY        = "phy1"

# Read stream code from /tmp/stream_code (written by sniff step)
try:
    with open("/tmp/stream_code") as f:
        stream_code = int(f.read().strip(), 16)
except Exception:
    stream_code = 0x6CD8   # fallback from last sniff

game_id    = b'\x00\x00\x00\x00'
sc_bytes   = stream_code.to_bytes(2, 'little')
ASSOC_SSID = game_id + sc_bytes + b'\x00' * 26
RATES      = bytes([0x82, 0x84])   # 1 Mbps basic + 2 Mbps basic

print(f"Stream code: 0x{stream_code:04X}")
print(f"ASSOC_SSID:  {ASSOC_SSID.hex()}")

def tx(iface, pkt, label, n=1):
    print(f"  -> {label}")
    sendp(RadioTap() / pkt, iface=iface, count=n, inter=0.05, verbose=False)

def wait_for(iface, filt, timeout=3, label="response"):
    print(f"  .. waiting {timeout}s for {label}")
    r = sniff(iface=iface, timeout=timeout, lfilter=filt, count=1, store=True)
    if r:
        print(f"  <- got: {r[0].summary()}")
        return r[0]
    print(f"  !! none received")
    return None

# ── A: add mon0 on phy1 ───────────────────────────────────────────────────────
print("\n[A] Add mon0 monitor interface on", PHY)
r = subprocess.run([IW, "phy", PHY, "interface", "add", "mon0", "type", "monitor"],
                   capture_output=True, text=True)
if r.returncode != 0 and "already exists" not in r.stderr:
    print("  FAILED:", r.stderr.strip())
    sys.exit(1)
subprocess.run([IP, "link", "set", "mon0", "up"], capture_output=True)
print("  mon0 up")

# ── B: connect wlan1 to DS via nmcli ─────────────────────────────────────────
print(f"\n[B] Connecting wlan1 to DS ({DS_BSSID})")
r = subprocess.run([NMC, "device", "wifi", "connect", DS_BSSID,
                    "ifname", "wlan1"], capture_output=True, text=True, timeout=15)
print(f"  nmcli rc={r.returncode}")
if r.stdout.strip(): print(" ", r.stdout.strip()[:120])
if r.stderr.strip(): print(" ", r.stderr.strip()[:120])
time.sleep(2)

r2 = subprocess.run([IW, "dev", "wlan1", "link"], capture_output=True, text=True)
link_out = r2.stdout.strip()
print(f"  link: {link_out[:100]}")
ds_connected = DS_BSSID.lower() in link_out.lower()
print(f"  Associated with DS: {ds_connected}")

# ── C: inject auth + assoc via mon0 ──────────────────────────────────────────
print("\n[C] Auth Request (via mon0)")
tx("mon0",
   Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID) /
   Dot11Auth(algo=0, seqnum=1, status=0),
   "Auth Request")

wait_for("mon0",
    lambda p: (p.haslayer(Dot11Auth) and
               p[Dot11].addr1.lower() == OUR_MAC.lower() and
               p[Dot11Auth].seqnum == 2),
    timeout=3, label="Auth Response")

print("\n[D] Assoc Request (via mon0)")
tx("mon0",
   Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID) /
   Dot11AssoReq(cap=0x0021, listen_interval=10) /
   Dot11Elt(ID="SSID", len=32, info=ASSOC_SSID) /
   Dot11Elt(ID="Rates", info=RATES),
   "Assoc Request")

resp = wait_for("mon0",
    lambda p: (p.haslayer(Dot11AssoResp) and
               p[Dot11].addr1.lower() == OUR_MAC.lower()),
    timeout=3, label="Assoc Response")
if resp:
    print(f"  Assoc status: {resp[Dot11AssoResp].status}")

time.sleep(0.3)

# ── D: PictoChat type-6 presence announcement ────────────────────────────────
print("\n[E] PictoChat type-6 client presence announcement")
llc  = bytes([0x0b, 0x02, 0x03])
# type_id=6 (u16 LE) + size_with_header=4 (u16 LE)
body = bytes([0x06, 0x00, 0x04, 0x00])
tx("mon0",
   Dot11(type=2, subtype=0, FCfield=0x01,
         addr1=DS_BSSID, addr2=OUR_MAC, addr3="03:09:bf:00:00:10") /
   Raw(load=llc + body),
   "Type-6 presence", n=3)

time.sleep(1)

# ── E: disassociate ──────────────────────────────────────────────────────────
print("\n[F] Disassociation")
tx("mon0",
   Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID) /
   Dot11Disas(reason=3),
   "Disassoc (reason=3)")

# ── F: cleanup ───────────────────────────────────────────────────────────────
print("\n[G] Cleanup")
subprocess.run([IP, "link", "set", "mon0", "down"], capture_output=True)
subprocess.run([IW, "dev", "mon0", "del"], capture_output=True)
print("  mon0 removed")

print("\n=== Phase 2a sequence complete ===")
print("Check DS Lite screen — did Room A show 2 users?")
