# PictoChat-HF: Inter-Provincial Ionospheric Interop

## 📡 Project Vision
**PictoChat-HF** is an experimental communication layer designed to extend the range of the Nintendo DS PictoChat protocol (originally limited to ~30-100 meters) to hundreds of kilometers. 

By leveraging **High Frequency (HF)** radio and **Ionospheric Skywave Propagation**, this project aims to facilitate a "Phantom DS" link between **Alberta (AB)** and **British Columbia (BC)**. The goal is to trick two physical Nintendo DS units into believing they are in the same room while their packets are actually bouncing off the Earth's atmosphere.

---

## 🏗️ Technical Architecture

The system operates by "sniffing" local 2.4 GHz packets and encapsulating them for transmission over the 3–30 MHz band.

### 1. The Local Interface (2.4 GHz)
* **Hardware:** Raspberry Pi + 2.4 GHz Transceiver (e.g., nRF24L01 or specialized SDR).
* **Mechanism:** The Pi acts as a "Man-in-the-Middle" (MitM) node. It listens for the proprietary Nintendo wireless frames.
* **The "Phantom DS":** The Pi presents itself to the local DS as a nearby user, acknowledging packets locally to prevent the DS from timing out due to the extreme latency of HF.

### 2. Frequency Conversion & Encapsulation
* **Down-conversion:** Captured 2.4 GHz digital data is stripped of its physical layer headers and re-encapsulated for HF.
* **Modulation:** Given the low bandwidth and high noise of the ionosphere, robust digital modes (e.g., JS8, FT8, or custom OFDM) will be used to ensure the drawings arrive intact.

### 3. The Long-Haul Link (HF)
* **Band:** 40m (7 MHz) or 20m (14 MHz) for optimal AB-to-BC propagation.
* **Transmission:** A "Skywave" bounce allows the signal to clear the Rockies without line-of-sight.
* **Latency:** Expect "Extreme Asynchronous" performance. Syncing a single canvas may take several minutes.

---

## 🗺️ Implementation Roadmap

### Phase 1: Packet Analysis (The "Sniff")
* Reverse-engineer the PictoChat beacon and data frames.
* Identify timing requirements; determine the maximum "handshake window" before the DS drops the connection.

### Phase 2: The Proxy Layer
* Develop a Python/C++ service on the Raspberry Pi to handle "Local Ack."
* Create a virtual buffer to hold incoming HF data until it can be "re-played" to the local DS.

### Phase 3: HF Integration
* Interface the Pi with an HF Transceiver (e.g., IC-7300 or a QRP DIY rig).
* Implement Forward Error Correction (FEC) to handle interference on the HF bands.

### Phase 4: Field Test (AB <=> BC)
* Station A (Alberta) vs Station B (British Columbia).
* Attempt the first "Slow-Scan PictoChat" across the mountains.

---

## 🛠️ Hardware Requirements (Proposed)

| Component | Purpose |
| :--- | :--- |
| **Nintendo DS / DS Lite** | The UI and original signal source. |
| **Raspberry Pi 4/5** | The central logic and packet processor. |
| **SDR (RTL-SDR / HackRF)** | For sniffing the 2.4 GHz environment. |
| **HF Transceiver** | For the ionospheric long-haul transmission. |
| **End-Fed Half-Wave Antenna** | For effective skywave propagation. |

---

## ⚠️ Constraints & Warnings
* **Latency:** This is not a real-time chat solution. It is "Slow-Scan PictoChat."
* **Legal:** Users must hold a valid Amateur Radio License to transmit on HF bands.
* **Philosophy:** This is a 10/10 difficulty project for a 1/10 utility payoff. **That is the point.**
