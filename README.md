# Substation PPE Safety Dashboard

Real-time PPE detection system for substation safety using YOLOv11n and Raspberry Pi.

## Features
- Live video feed with PPE detection
- Real-time status monitoring (helmet, vest, gloves)
- Automated gate control based on PPE compliance
- Smart violation capture (event-based, not continuous)
- Supervisor override controls with audit trail
- Activity logging and violation history

## Violation Capture Logic
The system uses **intelligent event-based capture** to prevent storage overflow:

**Photos are captured ONLY when:**
- ✅ Gate closes to deny entry (PPE violation detected)
- ✅ Supervisor manually overrides gate control
- ✅ Supervisor restores automatic mode

**Photos are NOT captured when:**
- ❌ Worker has complete PPE (normal entry)
- ❌ Gate opens (entry approved)
- ❌ PPE status changes without gate action
- ❌ Continuous monitoring (every frame)

## Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Run: `python app.py`
3. Open: `http://localhost:5000`
