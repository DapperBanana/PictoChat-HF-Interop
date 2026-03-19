#!/usr/bin/env python3
"""
Phase 2a — AR9271 dual-interface experiment.

Strategy:
  1. Migrate home WiFi from wlan1 (AR9271) → wlan0 (Pi built-in) so SSH stays up
  2. Sniff DS beacon to get current stream code
  3. Add mon0 monitor interface on phy#1 (AR9271)
  4. Connect wlan1 to DS BSSID — kernel handles auth/assoc + ACKs
  5. Inject PictoChat join frames via mon0
  6. Restore: disconnect from DS, reconnect wlan1 to home WiFi, remove mon0
"""
import sys, time, paramiko, socket

PI_MDNS  = "vessel-01.local"
PI_USER  = "root-1"
PI_PASS  = "SonyPlaystation1!"
DS_BSSID = "00:23:cc:f8:9e:3e"
OUR_MAC  = "00:23:cc:de:ad:01"
HOME_SSID = "NCC-1701D"

def resolve():
    return socket.gethostbyname(PI_MDNS)

def ssh(ip=None):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(ip or resolve(), username=PI_USER, password=PI_PASS, timeout=20)
    return c

def run(client, cmd, timeout=20):
    if cmd.lstrip().startswith("sudo"):
        inner = cmd.lstrip()[5:]
        cmd = f"echo '{PI_PASS}' | sudo -S {inner}"
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc  = stdout.channel.recv_exit_status()
    return out, err, rc

def upload(client, path, content):
    sftp = client.open_sftp()
    with sftp.open(path, 'w') as f:
        f.write(content)
    sftp.close()

def section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

# ─────────────────────────────────────────────────────────────────────────────

SNIFF_SCRIPT = r"""
import sys, subprocess
sys.path.insert(0, "/usr/local/lib/python3.13/dist-packages")
from scapy.all import sniff, conf
from scapy.layers.dot11 import Dot11, Dot11Beacon, Dot11Elt
conf.verb = 0

DS_BSSID = "00:23:cc:f8:9e:3e"
found = {}
IP = "/sbin/ip"; IW = "/usr/sbin/iw"

def check(pkt):
    if not pkt.haslayer(Dot11Beacon): return
    if pkt[Dot11].addr3.lower() != DS_BSSID.lower(): return
    elt = pkt.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 221 and len(elt.info) >= 30 and elt.info[:3] == b'\x00\x09\xbf':
            p = elt.info
            found['game_id']     = p[12:16].hex()
            found['stream_code'] = int.from_bytes(p[16:18], 'little')
            found['beacon_type'] = p[19] if len(p) > 19 else 0
            found['room']        = p[28] if len(p) > 28 else 0
            found['users']       = p[29] if len(p) > 29 else 0
        elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None

subprocess.run([IP,"link","set","wlan1","down"],  capture_output=True)
subprocess.run([IW,"dev","wlan1","set","type","monitor"], capture_output=True)
subprocess.run([IP,"link","set","wlan1","up"],    capture_output=True)
subprocess.run([IW,"dev","wlan1","set","channel","1"], capture_output=True)

sniff(iface="wlan1", timeout=8, lfilter=check, count=1, store=False)

subprocess.run([IP,"link","set","wlan1","down"],  capture_output=True)
subprocess.run([IW,"dev","wlan1","set","type","managed"], capture_output=True)
subprocess.run([IP,"link","set","wlan1","up"],    capture_output=True)

if found:
    sc = found['stream_code']
    print(f"STREAM_CODE=0x{sc:04X}")
    print(f"GAME_ID={found['game_id']}")
    print(f"BEACON_TYPE=0x{found['beacon_type']:02X}")
    print(f"ROOM={found['room']}")
    print(f"USERS={found['users']}")
else:
    print("STREAM_CODE=NOT_FOUND")
"""

def make_inject_script(stream_code, phy):
    ssid_hex = (b'\x00\x00\x00\x00' + stream_code.to_bytes(2,'little') + b'\x00'*26).hex()
    return f"""
import sys, time, subprocess
sys.path.insert(0, "/usr/local/lib/python3.13/dist-packages")
from scapy.all import sendp, sniff, RadioTap, Raw, conf
from scapy.layers.dot11 import Dot11, Dot11Elt, Dot11Auth, Dot11AssoReq, Dot11AssoResp, Dot11Disas
conf.verb = 0

DS_BSSID   = "{DS_BSSID}"
OUR_MAC    = "{OUR_MAC}"
ASSOC_SSID = bytes.fromhex("{ssid_hex}")
PHY        = "{phy}"
IP  = "/sbin/ip"
IW  = "/usr/sbin/iw"
NMC = "/usr/bin/nmcli"

def tx(iface, pkt, label, count=1):
    print(f"  -> {{label}}")
    sendp(RadioTap()/pkt, iface=iface, count=count, inter=0.05, verbose=False)

def wait_for(iface, filt, timeout=3, label="response"):
    print(f"  .. waiting {{timeout}}s for {{label}}")
    r = sniff(iface=iface, timeout=timeout, lfilter=filt, count=1, store=True)
    if r:
        print(f"  <- {{label}}: {{r[0].summary()}}")
        return r[0]
    print(f"  !! no {{label}} received")
    return None

# Step A: add mon0 on the AR9271 phy
print("[A] Adding mon0 monitor interface on", PHY)
r = subprocess.run([IW,"phy",PHY,"interface","add","mon0","type","monitor"],
                   capture_output=True, text=True)
if r.returncode != 0 and "already exists" not in r.stderr:
    print("  FAILED:", r.stderr.strip())
    sys.exit(1)
subprocess.run([IP,"link","set","mon0","up"], capture_output=True)
print("  mon0 up.")

# Step B: connect wlan1 to DS (kernel drives auth/assoc, hardware ACKs)
print("[B] Connecting wlan1 to DS BSSID (kernel station mode)")
r = subprocess.run([NMC,"device","wifi","connect",DS_BSSID,
                    "ifname","wlan1","bssid",DS_BSSID],
                   capture_output=True, text=True, timeout=15)
print("  nmcli rc:", r.returncode)
if r.stdout.strip(): print("  ", r.stdout.strip())
if r.stderr.strip(): print("  ", r.stderr.strip())

time.sleep(2)

# Check link
r = subprocess.run([IW,"dev","wlan1","link"], capture_output=True, text=True)
print("  wlan1 link:", r.stdout.strip()[:120])
connected_to_ds = DS_BSSID.lower() in r.stdout.lower()
print("  Connected to DS:", connected_to_ds)

# Step C: inject PictoChat frames via mon0 regardless
# (even if kernel assoc failed, mon0 inject is the experiment)
print("[C] Injecting auth + assoc frames via mon0")

tx("mon0",
   Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID) /
   Dot11Auth(algo=0, seqnum=1, status=0),
   "Auth Request")

wait_for("mon0",
    lambda p: p.haslayer(Dot11Auth) and
              p[Dot11].addr1.lower() == OUR_MAC.lower() and
              p[Dot11Auth].seqnum == 2,
    timeout=3, label="Auth Response")

tx("mon0",
   Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID) /
   Dot11AssoReq(cap=0x0021, listen_interval=10) /
   Dot11Elt(ID="SSID", len=32, info=ASSOC_SSID) /
   Dot11Elt(ID="Rates", info=b"\\x82\\x84"),
   "Assoc Request")

resp = wait_for("mon0",
    lambda p: p.haslayer(Dot11AssoResp) and
              p[Dot11].addr1.lower() == OUR_MAC.lower(),
    timeout=3, label="Assoc Response")
if resp:
    print(f"  Assoc status: {{resp[Dot11AssoResp].status}}")

time.sleep(0.5)

# Type-6: client presence announcement
print("[D] PictoChat type-6 presence announcement")
llc  = bytes([0x0b, 0x02, 0x03])
body = bytes([0x06, 0x00, 0x04, 0x00])
tx("mon0",
   Dot11(type=2, subtype=0, FCfield=0x01,
         addr1=DS_BSSID, addr2=OUR_MAC, addr3="03:09:bf:00:00:10") /
   Raw(load=llc+body),
   "Type-6 presence", count=3)

time.sleep(1)

print("[E] Disassociate")
tx("mon0",
   Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID) /
   Dot11Disas(reason=3),
   "Disassoc")

# Step F: cleanup — remove mon0, reconnect wlan1 to home WiFi
print("[F] Cleanup")
subprocess.run([IP,"link","set","mon0","down"], capture_output=True)
subprocess.run([IW,"dev","mon0","del"],         capture_output=True)
# Reconnect wlan1 to home WiFi
r = subprocess.run([NMC,"device","wifi","connect","{HOME_SSID}","ifname","wlan1"],
                   capture_output=True, text=True, timeout=20)
print("  Reconnect to {HOME_SSID}:", r.returncode, r.stdout.strip()[:80])
print()
print("=== Phase 2a complete — check DS screen ===")
"""

# ─── Main ─────────────────────────────────────────────────────────────────────

print("Connecting to vessel-01...")
current_ip = resolve()
print(f"  Resolved to {current_ip}")
client = ssh(current_ip)
print("  Connected.")

# ── Step 1: sniff beacon (wlan1 in monitor briefly, then back to managed) ─────
section("1. Sniff DS beacon")
upload(client, '/tmp/sniff_beacon.py', SNIFF_SCRIPT)
out, err, rc = run(client, "sudo python3 /tmp/sniff_beacon.py", timeout=20)
print(out.strip())
if err.strip() and 'password' not in err.lower():
    print("STDERR:", err.strip())

stream_code = None
for line in out.splitlines():
    if line.startswith("STREAM_CODE=0x"):
        stream_code = int(line.split("=")[1], 16)

if stream_code is None:
    print("ERROR: no stream code — is DS on and in PictoChat Room A?")
    client.close(); sys.exit(1)

print(f"\n  Stream code: 0x{stream_code:04X}")

# ── Step 2: detect current phy for wlan1 ─────────────────────────────────────
section("2. Detect wlan1 phy")
out, _, _ = run(client, "sudo /usr/sbin/iw dev wlan1 info")
phy = None
for line in out.splitlines():
    if "wiphy" in line:
        phy = f"phy{line.strip().split()[-1]}"
        break
if not phy:
    print("ERROR: could not determine phy"); client.close(); sys.exit(1)
print(f"  AR9271 is on {phy}")

# ── Step 3: connect wlan0 to home WiFi (backup SSH path) ─────────────────────
section(f"3. Connect wlan0 (Pi built-in) to {HOME_SSID}")
out, err, rc = run(client,
    f"sudo /usr/bin/nmcli device wifi connect '{HOME_SSID}' ifname wlan0",
    timeout=25)
print(f"  rc={rc}")
if out.strip(): print(f"  {out.strip()}")
if err.strip() and 'password' not in err.lower(): print(f"  {err.strip()}")

if rc != 0:
    print(f"  WARNING: wlan0 did not connect to {HOME_SSID}.")
    print("  Proceeding anyway — SSH will drop when wlan1 switches to DS.")
    print("  The inject script will reconnect wlan1 to home WiFi when done.")
    time.sleep(2)
else:
    time.sleep(3)
    out, _, _ = run(client, "sudo /usr/bin/nmcli device status")
    print("\n  Interface status:")
    for line in out.splitlines():
        if any(x in line for x in ("wlan","eth","DEVICE")):
            print(f"  {line}")

# ── Step 4: upload + run the inject script autonomously via nohup ─────────────
section("4. Upload and launch inject script (nohup)")
inject = make_inject_script(stream_code, phy)
upload(client, '/tmp/inject_picto.py', inject)

# Run autonomously — SSH may drop when wlan1 switches from home WiFi to DS
# Log goes to /tmp/phase2a.log
run(client,
    "sudo bash -c 'nohup python3 /tmp/inject_picto.py > /tmp/phase2a.log 2>&1 &'",
    timeout=5)
print("  Script launched. Waiting 20s for it to complete...")

client.close()

# ── Step 5: reconnect and read log ────────────────────────────────────────────
time.sleep(22)

print("\n  Reconnecting to vessel-01...")
for attempt in range(6):
    try:
        new_ip = resolve()
        client2 = ssh(new_ip)
        print(f"  Reconnected ({new_ip})")
        break
    except Exception as e:
        print(f"  Attempt {attempt+1}/6 failed: {e}")
        time.sleep(5)
else:
    print("  Could not reconnect. Check /tmp/phase2a.log manually.")
    sys.exit(1)

section("5. Results")
out, _, _ = run(client2, "cat /tmp/phase2a.log")
print(out.strip() if out.strip() else "  (log empty)")

out, _, _ = run(client2, "sudo /usr/sbin/iw dev wlan1 link")
print("\n  wlan1 final state:")
print(out.strip())

client2.close()
print("\nDone. Check the DS Lite screen.")
