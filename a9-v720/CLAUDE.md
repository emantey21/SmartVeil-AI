# A9 V720 / Naxclow Camera — Full Protocol & Setup Guide

## Overview

These are cheap WiFi IP cameras (Anyka AK3918E SoC, ~$5-15) sold under many brand names:
A9, V720, V380, V380 Pro, Naxclow, etc. They use a **proprietary P2P protocol** on ports **6123 TCP/UDP** and **8800 TCP** by default. The v720 mobile app communicates with the camera via this protocol, relayed through cloud servers at `*.naxclow.com`.

**Key fact:** The camera has **zero open TCP ports** when stock (no RTSP, no HTTP, no ONVIF). It only initiates outbound connections to the cloud. To use it locally, you must either:
- **(A)** Connect to its AP mode hotspot (`Nax_...`) and talk to it directly
- **(B)** Enable RTSP/ONVIF via `ceshi.ini` on SD card or firmware patch
- **(C)** Run a fake server that intercepts `*.naxclow.com` DNS

## Directory Structure

```
a9-v720/
├── CLAUDE.md              This file
├── readme.md              Original project readme
├── fake_server.md         Detailed fake server setup guide
├── requirements.txt       Python deps (tqdm, numpy, opencv-python, paho-mqtt)
├── src/                   Main protocol implementation
│   ├── a9_naxclow.py      CLI entry point — all commands
│   ├── a9_live.py         Live video display (OpenCV)
│   ├── v720_ap.py         AP mode client — communicates with camera directly
│   ├── v720_sta.py        STA mode server — fake cloud server implementation
│   ├── v720_http.py        HTTP server for fake-server mode
│   ├── netcl.py            TCP client base class
│   ├── netcl_tcp.py        TCP client implementation
│   ├── netcl_udp.py        UDP client implementation
│   ├── netsrv.py           TCP/UDP server base class
│   ├── netsrv_tcp.py       TCP server implementation
│   ├── netsrv_udp.py       UDP server implementation
│   ├── cmd_udp.py          All UDP command codes (constants)
│   ├── cmd_tcp.py          All TCP command codes (constants)
│   ├── prot_udp.py         Binary UDP packet protocol (de/encode)
│   ├── prot_json_udp.py    JSON-over-UDP protocol handler
│   ├── prot_xml_udp.py     XML-over-UDP protocol handler
│   ├── prot_ap.py          AP mode protocol handler
│   ├── log.py              Logging utility
│   └── bat_img.py          Batch image processor
├── firmware/              Firmware patches for permanent RTSP/ONVIF
│   ├── AK V200 V380E2 C2 WF1 V2.6.5.9 2021-02-24/
│   ├── AK V200 V380E2 C2 WF3 2.5.10.6 20200106/
│   ├── AK V200 V380E2 C2 WF9 V2.6.8.7 2021-07-14/
│   └── README.md
├── orig-app/              Decompiled original v720 Android app sources
├── docs/
│   └── uart.log            UART boot log from camera
├── static/                Web assets for fake-server HTTP interface
└── img/                   Hardware photos
```

## Protocol Architecture

### AP Mode (direct connection)

The camera can act as a WiFi hotspot (SSID: `Nax_XXXXXX` or `MVXXXXXXXX`). Connect your device to this hotspot, then:

- **Camera IP:** `192.168.169.1` (AP mode)
- **TCP Port:** `6123`
- **UDP Port:** `6123`

**Handshake sequence:**
1. Client sends `P2P_UDP_CMD_LIVE_MOTION` (cmd 115) as a UDP packet
2. Client establishes TCP connection on port 6123
3. Client sends JSON `{"code": 501, "target": "00000000000000000000000000000000", "token": "55ABfb77", "unixTimer": <timestamp>}`
4. Camera responds with device ID and forward ID
5. Client sends `CODE_FORWARD_DEV_BASE_INFO` (code 4) to get version info
6. Client sends `CODE_FORWARD_OPEN_A_OPEN_V` (code 3) to start A/V stream
7. Video frames arrive as fragmented JPEG over UDP

### STA Mode (via fake server)

When the camera connects to your WiFi, it tries to reach `*.naxclow.com` servers. By running a fake server that intercepts these DNS queries, you can capture the stream locally without cloud involvement.

**Registration flow:**
1. Camera POSTs to `http://v720.naxclow.com/app/api/ApiSysDevicesBatch/registerDevices`
2. Camera POSTs to `http://v720.naxclow.com/app/api/ApiServer/getA9ConfCheck`
3. Camera connects to a dedicated TCP server on port 29940/29941
4. Camera sends registration: `{"code": 100, "uid": "...", "token": "...", "domain": "..."}`
5. Camera connects to MQTT broker at `v720.p2p.naxclow.com:1883`
6. Camera subscribes to `Naxclow/P2P/Users/Device/sub/<UID>`
7. Server sends NAT probe (`code 11`), camera responds (`code 12`)
8. Video channel established via UDP, streaming fragmented JPEG frames

### Binary Packet Format (prot_udp)

All TCP and UDP messages use this binary header:

```
Offset  Size  Field
0       4     Payload length (little-endian)
4       2     Command code (little-endian)
6       1     Message flag
7       1     Deal flag
8       8     Forward ID (bytes)
16      4     Package ID (little-endian)
20      N     Payload (varies by command)
```

### Key Command Codes (cmd_udp.py)

| Code | Name | Description |
|------|------|-------------|
| 0 | P2P_UDP_CMD_JSON | JSON payload |
| 1 | P2P_UDP_CMD_JPEG | JPEG video frame |
| 3 | CODE_FORWARD_OPEN_A_OPEN_V | Start A/V stream |
| 4 | CODE_FORWARD_DEV_BASE_INFO | Get device info |
| 10 | CODE_C2S_NAT_REQ | NAT probe request |
| 11 | CODE_S2D_NAT_REQ | NAT probe from server |
| 20 | CODE_C2S_UDP_REQ | UDP channel request |
| 50 | CODE_C2D_PROBE_REQ | Probe device |
| 100 | P2P_UDP_CMD_HEARTBEAT | Heartbeat |
| 114 | P2P_UDP_CMD_DIRECT_MOTION | AP mode init |
| 115 | P2P_UDP_CMD_LIVE_MOTION | Live stream init (AP) |
| 204 | CODE_FORWARD_DEV_SET_WIFI | Set WiFi credentials |
| 208 | CODE_FORWARD_DEV_AP_MODE | Switch to AP mode |
| 299 | CODE_FORWARD_DEV_REBOOT | Reboot camera |
| 301 | CODE_CMD_FORWARD | Forward command (STA) |
| 400-412 | CODE_SDCARD_* | SD card commands |

### Video Frame Fragmentation

JPEG frames are fragmented across UDP packets (MTU ~1500, JPEG frames ~15-25KB):

| MSG_FLAG | Value | Meaning |
|----------|-------|---------|
| PROTOCOL_MSG_FLAG_HEAD | 250 | Start of frame |
| PROTOCOL_MSG_FLAG_BODY | 251 | Continuation |
| PROTOCOL_MSG_FLAG_END | 252 | End of frame (last 4 bytes = total size) |
| PROTOCOL_MSG_FLAG_FINISH | 255 | Single-packet frame |

## Setup Options

### Option 1: Configure WiFi via AP Mode (no app needed)

1. Power on camera, press/hold reset button until blue LED flashes quickly (AP mode)
2. Connect your computer to the camera's `Nax_XXXX` or `MVXXXXXXXX` WiFi
3. Run:
   ```bash
   python3 src/a9_naxclow.py --set-wifi YourSSID YourPassword
   ```
4. Camera reboots and connects to your WiFi

### Option 2: Enable RTSP/ONVIF (temporary, needs SD card)

1. Create `ceshi.ini` on SD card root with:
   ```ini
   [CONST_PARAM]
   rtsp_enable=1
   rtsp=1
   rtsp_ctrl=1
   onvif_enable=1
   ```
2. Power off camera, insert SD card, power on
3. RTSP server starts on port 554. SD card must remain inserted.

### Option 3: Permanent RTSP via Firmware Flash

1. Choose the correct firmware from `firmware/` folder (match camera model)
2. Unzip firmware, copy contents to SD card root
3. Insert SD card into powered-off camera, power on
4. Camera speaks "firmware update begin" (or wait ~3 minutes)
5. After reboot, remove SD card — RTSP/ONVIF is **permanently** enabled

### Option 4: Fake Server (full local control, no cloud)

1. Set up DNS to redirect `*.naxclow.com` to your server IP
2. Run:
   ```bash
   python3 src/a9_naxclow.py -s --proxy-port 80
   ```
3. Access streams at:
   - `http://<server>/dev/list` — device list
   - `http://<server>/dev/<CAM_ID>/live` — MJPEG stream
   - `http://<server>/dev/<CAM_ID>/snapshot` — snapshot

## Common RTSP URLs (after RTSP enabled)

These vary by model/firmware. Try in order:

```
rtsp://admin:admin@<IP>:554/live/ch00_0
rtsp://admin:admin@<IP>:554/live/ch00_1
rtsp://<IP>:554/live/ch00_0
rtsp://<IP>:554/11
rtsp://<IP>:554/onvif1
rtsp://<IP>:554/mpeg4
rtsp://<IP>:554/cam/realmonitor?channel=1&subtype=0
```

Default credentials: `admin`/`admin` or `admin`/`12345` or no password.

## Hardware Info

- **SoC:** Anyka AK3918E (ARM926EJ-S, ARMv5TEJ)
- **RAM:** 64MB DDR2
- **Flash:** 8MB SPI flash (Winbond 25Q64)
- **WiFi:** RDA 5995 (USB)
- **Sensor:** Various (H42, SC1035, SC1135, etc.)
- **UART:** 115200 baud, 3.3V (GND, TX, RX pads on PCB)
- **Root password:** Found in UART logs (may vary by firmware version)

## Integration with SmartVeil (SmartHome App)

Once RTSP is enabled (via ceshi.ini or firmware flash), add to `config.ini`:

```ini
[channels]
v720_cam = rtsp://admin:admin@192.168.100.175:554/live/ch00_0
```

If RTSP is not available, you can modify CameraWorker to use the native protocol or use the fake server's HTTP MJPEG stream.

## Building a Mobile App

To build a v720 replacement app (iOS/Android), port the following:

1. **AP Mode init:** Send `P2P_UDP_CMD_LIVE_MOTION` (115) via UDP, then TCP handshake with JSON code 501
2. **WiFi config:** Send `CODE_FORWARD_DEV_SET_WIFI` (204) via TCP with `{"s": "SSID", "p": "password"}`
3. **Live stream:** Request `CODE_FORWARD_OPEN_A_OPEN_V` (3), receive fragmented JPEG over UDP
4. **Heartbeat:** Send `P2P_UDP_CMD_HEARTBEAT` (100) every ~5 seconds
5. **Audio:** G.711 A-law format in UDP packets (CMD 4)

The protocol is fully documented in `src/` — `cmd_udp.py` has all command constants, `prot_udp.py` has the binary packet format, and `v720_ap.py` shows the complete AP mode flow.
