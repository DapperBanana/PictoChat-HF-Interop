#!/usr/bin/env python3
"""Deploy and run phantom_ds.py on vessel-01 via paramiko SFTP."""
import sys
import time
import paramiko

PI_HOST = "192.168.0.121"
PI_USER = "root-1"
PI_PASS = "SonyPlaystation1!"

SCRIPT_PATH = "/home/root-1/phantom_ds.py"

PHANTOM_SCRIPT = r"""#!/usr/bin/env python3
# phantom_ds.py -- Connect to PictoChat Room A as a fake DS and send a message
import sys, time
sys.path.insert(0, "/usr/local/lib/python3.13/dist-packages")

from scapy.all import sendp, sniff, RadioTap, Raw, conf
from scapy.layers.dot11 import (
    Dot11, Dot11Auth, Dot11AssoReq, Dot11AssoResp,
    Dot11Disas, Dot11Elt
)
conf.verb = 0

DS_BSSID   = "00:23:cc:f8:9e:3e"
OUR_MAC    = "00:23:cc:de:ad:01"
IFACE      = "wlan1"
# 32-byte SSID: Game ID 0x00000000 + stream code 0xAB38 + 26 zero bytes
ASSOC_SSID = b"\x00\x00\x00\x00\xab\x38" + b"\x00" * 26

def send_pkt(pkt, label, count=1, inter=0.05):
    print(f"  -> {label}")
    sendp(RadioTap() / pkt, iface=IFACE, count=count, inter=inter, verbose=False)

def await_response(filter_fn, timeout=3, label="response"):
    print(f"  .. waiting for {label} ({timeout}s timeout)")
    pkts = sniff(iface=IFACE, timeout=timeout,
                 lfilter=filter_fn, count=1, store=True)
    if pkts:
        print(f"  <- got {label}: {pkts[0].summary()}")
        return pkts[0]
    print(f"  !! no {label} received")
    return None

# ── Step 1: Authentication ────────────────────────────────────────────────────
print("[1] Sending Auth Request (open system, seq=1)")
auth_req = (
    Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID, FCfield=0) /
    Dot11Auth(algo=0, seqnum=1, status=0)
)
send_pkt(auth_req, "Auth Request")

auth_resp = await_response(
    lambda p: (p.haslayer(Dot11Auth) and
               p[Dot11].addr1 == OUR_MAC and
               p[Dot11Auth].seqnum == 2),
    timeout=3, label="Auth Response"
)
if auth_resp is None:
    # DS may not respond to auth in Nintendo proprietary mode; proceed anyway
    print("  (no auth response — proceeding anyway, DS may skip standard auth)")

# ── Step 2: Association ───────────────────────────────────────────────────────
print("[2] Sending Association Request")
assoc_req = (
    Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID, FCfield=0) /
    Dot11AssoReq(cap=0x0021, listen_interval=10) /
    Dot11Elt(ID="SSID", len=32, info=ASSOC_SSID) /
    Dot11Elt(ID="Rates", info=b"\x82\x84")  # 1 Mbps + 2 Mbps
)
send_pkt(assoc_req, "Association Request")

assoc_resp = await_response(
    lambda p: (p.haslayer(Dot11AssoResp) and
               p[Dot11].addr1 == OUR_MAC),
    timeout=3, label="Association Response"
)
if assoc_resp is not None:
    status = assoc_resp[Dot11AssoResp].status
    print(f"  Association status: {status} ({'OK' if status == 0 else 'FAILED'})")
else:
    print("  (no assoc response — continuing to send message anyway)")

time.sleep(0.5)

# ── Step 3: PictoChat LLC data frame (client → host) ─────────────────────────
# Nintendo DS PictoChat uses 802.11 data frames with a proprietary LLC header.
# LLC: DSAP=0x0b, SSAP=0x02, ctrl=0x03 (UI frame)
# Payload: type byte 0x01 = ClientToHost, state byte 0x97 = begin session
# addr1 = DS BSSID (AP), addr2 = our MAC (client), addr3 = Nintendo multicast
# FCfield to-DS bit set (0x01)
print("[3] Sending PictoChat client-join notification")
llc_header = bytes([0x0b, 0x02, 0x03])     # DSAP, SSAP, ctrl
# Minimal PictoChat client-to-host payload:
# byte 0: type = 0x01 (ClientToHost)
# byte 1: state = 0x97 (begin)
# bytes 2-3: our AID = 0x0001
# bytes 4-5: sequence = 0x0000
# rest: zeros for now (no drawing data)
picto_payload = bytes([0x01, 0x97, 0x00, 0x01, 0x00, 0x00]) + b"\x00" * 10
raw_data = llc_header + picto_payload

data_frame = (
    Dot11(
        type=2,          # Data
        subtype=0,
        FCfield=0x01,    # to-DS
        addr1=DS_BSSID,
        addr2=OUR_MAC,
        addr3="03:09:bf:00:00:10"  # client→host multicast
    ) /
    Raw(load=raw_data)
)
send_pkt(data_frame, "PictoChat data frame", count=3, inter=0.1)

time.sleep(1.0)

# ── Step 4: Disassociation ────────────────────────────────────────────────────
print("[4] Sending Disassociation")
disas = (
    Dot11(addr1=DS_BSSID, addr2=OUR_MAC, addr3=DS_BSSID, FCfield=0) /
    Dot11Disas(reason=3)
)
send_pkt(disas, "Disassociation (reason=3: STA leaving)")

print()
print("=== Phantom DS sequence complete ===")
print("Check the DS Lite screen — Room A should have briefly shown 2 users.")
"""


def run_cmd(client, cmd, password=None, timeout=30):
    """Run a command via exec_command, piping sudo password via stdin."""
    # Wrap sudo commands to accept password via -S flag
    if password and cmd.lstrip().startswith("sudo"):
        inner = cmd.lstrip()[5:]  # strip leading "sudo "
        cmd = f"echo '{password}' | sudo -S {inner}"
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    stdout.channel.settimeout(timeout)
    try:
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
    except Exception as e:
        out, err = "", str(e)
    rc = stdout.channel.recv_exit_status()
    combined = out + (("\nSTDERR: " + err) if err.strip() else "")
    return combined, rc


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {PI_HOST} as {PI_USER}...")
    client.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=15)
    print("Connected.")

    # ── Transfer script via SFTP ──────────────────────────────────────────────
    print(f"\nUploading {SCRIPT_PATH} via SFTP...")
    sftp = client.open_sftp()
    with sftp.open(SCRIPT_PATH, "w") as f:
        f.write(PHANTOM_SCRIPT)
    sftp.close()
    print("Upload complete.")

    # ── Confirm wlan1 is in monitor mode on ch1 ───────────────────────────────
    print("\nChecking wlan1 mode...")
    out, _ = run_cmd(client, "sudo /usr/sbin/iw dev wlan1 info", password=PI_PASS)
    sys.stdout.write(out)

    if "monitor" not in out.lower():
        print("wlan1 not in monitor mode — setting it up...")
        for cmd in [
            "sudo /sbin/ip link set wlan1 down",
            "sudo /usr/sbin/iw dev wlan1 set type monitor",
            "sudo /sbin/ip link set wlan1 up",
            "sudo /usr/sbin/iw dev wlan1 set channel 1",
        ]:
            out, rc = run_cmd(client, cmd, password=PI_PASS)
            print(f"  {cmd!r} -> rc={rc}")
            if out.strip():
                sys.stdout.write(out)
    else:
        # Ensure we're on ch1
        out2, _ = run_cmd(client, "sudo /usr/sbin/iw dev wlan1 set channel 1", password=PI_PASS)
        if out2.strip():
            sys.stdout.write(out2)
        print("wlan1 confirmed in monitor mode, channel set to 1.")

    # ── Execute phantom_ds.py ─────────────────────────────────────────────────
    print(f"\nRunning {SCRIPT_PATH}...")
    print("=" * 60)
    out, rc = run_cmd(client, f"sudo python3 {SCRIPT_PATH}", password=PI_PASS, timeout=30)
    sys.stdout.write(out)
    print("=" * 60)
    print(f"Exit code: {rc}")

    client.close()
    print("\nDone. Check the DS Lite screen.")


if __name__ == "__main__":
    main()
