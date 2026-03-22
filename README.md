# SPARC - Substation Protection and Risk Control Dashboard

A real-time PPE (Personal Protective Equipment) detection and gate control system for electrical substations, built on a Raspberry Pi 4. Workers approaching the entry gate are monitored via live camera feeds — the gate opens automatically only when full PPE compliance is confirmed and violations are logged to database for supervisor audit.

---

## Features

- **Real-time PPE detection** using YOLOv11 — detects helmet, gloves, and boots (positive and negative classes)
- **Automatic gate control** via SG90 servo (pigpio DMA PWM) — opens on compliance, closes on violation
- **RED / GREEN LED indicator** via single-channel relay module
- **Multi-camera RTSP/CCTV support** — add, enable/disable, and monitor multiple IP cameras
- **Auto violation capture** — cooldown-guarded snapshots saved on PPE breach detection from RTSP streams
- **Manual supervisor override** — toggle gate open/closed independently of auto mode
- **Live web dashboard** — real-time PPE status, gate state, and activity log via WebSocket
- **Violations log** — paginated history with images, missing item labels, capture source badges, and supervisor notes
- **Secure access** — Flask-Login authentication with role-based user accounts

---

## System Architecture

```
USB Webcam ──────────────────────────────────────────► Raspberry Pi 4 (primary feed)
 
IP Camera ──► Windows Laptop (FFmpeg encode) ──► MediaMTX RTSP Server ──► Raspberry Pi 4
                                                                                │
                                                         ┌─────────────────────────────────┐
                                                         │  Flask + Flask-SocketIO (app.py) │
                                                         │  YOLOv11 Inference               │
                                                         │  Gate Control Loop               │
                                                         └──────────┬──────────────────────┘
                                                                    │
                                                       ┌────────────┴────────────┐
                                                    GPIO 18                   GPIO 23
                                                  SG90 Servo               Relay Module
                                                  (Gate arm)            (RED/GREEN LED)
```

---

## Hardware

| Component | Details |
|---|---|
| Main board | Raspberry Pi 4 |
| Servo | SG90 on GPIO 18 — pigpio DMA PWM |
| Relay | Single-channel (ADIY no-opto) on GPIO 23 — 3.3V logic |
| LEDs | RED (NC/closed) and GREEN (NO/open) via relay |
| Primary camera | USB webcam (V4L2, index 0) connected directly to Pi |
| CCTV cameras | Additional IP/RTSP cameras via MediaMTX + FFmpeg offload |

---

## Software Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask, Flask-SocketIO (threading mode) |
| ML Inference | YOLOv11 via Ultralytics |
| Database | SQLite + SQLAlchemy |
| Auth | Flask-Login, Flask-Bcrypt |
| Frontend | Bootstrap 5, Vanilla JS, Socket.IO client |
| GPIO | pigpio (DMA PWM), RPi.GPIO (fallback) |
| Streaming | MediaMTX, FFmpeg, OpenCV |

---

## Project Structure

```
substation-dashboard/
├── app.py                  # Flask app, gate control loop, all routes
├── hardware_controller.py  # GateController (servo + relay LED)
├── models.py               # SQLAlchemy models (User, Violation, RTSPCamera)
├── utils/
│   ├── yolo_detector.py    # USB camera YOLO processor
│   └── rtsp_processor.py   # RTSP multi-stream manager + auto-capture
├── models/
│   └── best.pt             # YOLOv11 trained weights
├── static/
│   ├── css/dashboard.css
│   ├── js/dashboard.js
│   └── violations/         # Captured violation images
└── templates/
    ├── base.html
    ├── index.html
    ├── cameras.html
    ├── violations.html
    └── login.html
```

---

## Setup

### 1. Pi dependencies

```bash
sudo apt install pigpio python3-pigpio
sudo systemctl enable pigpiod && sudo systemctl start pigpiod
pip install flask flask-socketio flask-login flask-bcrypt flask-sqlalchemy \
            ultralytics opencv-python-headless simple-websocket
```

### 2. Run the app

```bash
python app.py
```

Dashboard available at `http://<pi-ip>:5000`

---

## Gate Logic

```
PPE Status OK?
    └─ YES → Cooldown elapsed (5s)? → Open gate, start 3s entry grace
    └─ NO  → Entry grace elapsed (3s)? → Close gate, start 5s cooldown
                └─ NO → Hold gate open (worker still entering)

Manual Override → bypasses all of the above
```

---

## Dataset & Training

PPE detection model trained using a custom dataset prepared with [Roboflow](https://roboflow.com) augmentation. Classes: `helmet`, `no-helmet`, `gloves`, `no-gloves`, `boots`, `no-boots`.

---
