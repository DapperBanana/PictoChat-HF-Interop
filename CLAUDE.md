# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PictoChat-HF** is an experimental hardware/radio project to extend Nintendo DS PictoChat range from ~30-100m to hundreds of kilometers using HF radio and ionospheric skywave propagation. The goal is a cross-provincial (Alberta ↔ British Columbia) link where packets bounce off the ionosphere.

This is a pre-implementation planning-stage project. No source code exists yet. The full vision and architecture is in `start-here.md`.

## Planned Technology Stack

- **Language:** Python and/or C++
- **Platform:** Raspberry Pi 4/5
- **Hardware interfaces:** nRF24L01 or SDR (RTL-SDR / HackRF) for 2.4 GHz sniffing; IC-7300 or QRP rig for HF TX/RX
- **Digital modes:** JS8, FT8, or custom OFDM for HF link

## Architecture

The system is a packet relay pipeline with four layers:

1. **2.4 GHz Sniff Layer** — Raspberry Pi + SDR or nRF24L01 listens for proprietary Nintendo DS wireless frames on 2.4 GHz.

2. **Proxy / Local Ack Layer** — Pi acts as a "Phantom DS," locally acknowledging packets to prevent the Nintendo DS from timing out during the multi-minute HF round-trip. Holds incoming HF data in a virtual buffer until it can be replayed to the local DS.

3. **HF Encapsulation Layer** — Strips 2.4 GHz physical-layer headers, applies Forward Error Correction (FEC), and re-encapsulates for HF transmission. Targets 40m (7 MHz) or 20m (14 MHz) bands for AB-to-BC propagation.

4. **HF Transceiver Interface** — Interfaces Pi with HF rig (e.g., via CAT/USB) to transmit and receive skywave signals.

## Implementation Phases

- **Phase 1:** Reverse-engineer PictoChat beacon and data frames; identify handshake timing windows.
- **Phase 2:** Build Python/C++ proxy service with Local Ack and virtual replay buffer.
- **Phase 3:** HF transceiver integration and FEC implementation.
- **Phase 4:** Live field test between two stations (AB ↔ BC).

## Raspberry Pi (vessel-01)

The Raspberry Pi is already deployed and on the local network.

| Property | Value |
| :--- | :--- |
| Hostname | `vessel-01` (mDNS: `vessel-01.local`) |
| IPv4 | `192.168.0.254` |
| Username | `root-1` |
| Password | see `secrets.local` |
| SSH | Enabled (confirmed working 2026-03-17) |

Connect: `ssh root-1@vessel-01.local` or `ssh root-1@192.168.0.254`

Credentials are stored in `secrets.local` (gitignored). Copy `secrets.local.example` to `secrets.local` and fill in values.

> **Tailscale IP:** Not yet recorded — update `secrets.local` once tested remotely.

## Key Constraints

- **Latency:** Expect several minutes per canvas sync — this is "Slow-Scan PictoChat," not real-time.
- **Legal:** Valid Amateur Radio License required for any HF transmission.
