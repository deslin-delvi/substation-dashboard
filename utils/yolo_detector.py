# utils/yolo_detector.py
from ultralytics import YOLO
import cv2
import threading
import time
import platform
from datetime import datetime

try:
    from flask_sqlalchemy import SQLAlchemy
    from models import db, Violation
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    print("⚠️ Database not available - running in mock mode")

class YOLOProcessor:
    def __init__(self, model_path="models/best.pt", camera_index=0, flask_app=None, socketio=None):
        # Load model
        self.model = YOLO(model_path)
        self.flask_app = flask_app
        self.socketio = socketio

        # Events + status tracking
        self.events = []
        self.prev_status = "UNKNOWN"

        # Track individual item states to detect changes within the same overall status
        self.prev_items = {
            "helmet": False, "gloves": False, "boots": False,
            "no_helmet": False, "no_gloves": False, "no_boots": False
        }
        # Rate-limit UI emits — max 5/sec so socketio.emit() never blocks the YOLO loop
        self.last_emit_time = 0.0
        self.EMIT_INTERVAL  = 0.2   # seconds (5 fps for UI updates is plenty)
        
        # 🔧 NEW: Track gate state to detect changes
        self.prev_gate_state = None
        self.current_gate_state = None
        
        # Prevent logging violations during startup
        self.startup_grace_period = 5.0
        self.start_time = time.time()

        # Open camera
        # Updated code with explicit V4L2 backend:
        if platform.system() == 'Windows':
            self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        else:
            # Linux/Raspberry Pi - use V4L2 backend explicitly
            self.cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

        self.latest_frame = None  # JPEG bytes
        self.latest_status = {
            "ppe_status": "UNKNOWN",
            "helmet": False,
            "gloves": False,
            "boots": False
        }
        self.running = False

    def capture_gate_violation(self, gate_action, reason=""):
        """
        Called only when gate state changes
        ONLY captures and saves image
        """
        import os
        import numpy as np

        elapsed = time.time() - self.start_time
        if elapsed < self.startup_grace_period:
            print("⏳ Still in grace period, skipping capture")
            return None

        timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        image_filename = f"gate_{gate_action.lower()}_{timestamp_str}.jpg"

        if not isinstance(self.latest_frame, bytes) or len(self.latest_frame) == 0:
            print("❌ No frame available")
            return None

        nparr = np.frombuffer(self.latest_frame, np.uint8)
        frame_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame_np is None or frame_np.size == 0:
            print("❌ Frame decode failed")
            return None

        if self.flask_app is None:
            print("⚠️ Flask app not available, cannot save image")
            return None
            
        violations_dir = os.path.join(self.flask_app.root_path, "static", "violations")
        os.makedirs(violations_dir, exist_ok=True)
        full_path = os.path.join(violations_dir, image_filename)

        if cv2.imwrite(full_path, frame_np):
            print(f"✅ Image saved: {image_filename}")
            return image_filename

        print("❌ Failed to save image")
        return None

    def update_gate_state(self, new_gate_state):
        """
        🔧 FIXED: Called from app.py when gate state changes
        Only captures when gate CLOSES (denial), NOT when it opens (approval)
        Now also saves to database!
        """
        if self.prev_gate_state != new_gate_state:
            print(f"🚪 Gate state changed: {self.prev_gate_state} → {new_gate_state}")
            
            # 🔧 FIXED: Only capture when gate CLOSES to deny entry
            if new_gate_state == "CLOSED":
                ppe_status = self.latest_status.get('ppe_status', 'UNKNOWN')
                has_violation = self.latest_status.get('has_violation', False)
                
                # Only if it closed due to PPE violation (not just staying closed)
                if ppe_status == "NOT_OK" and has_violation and self.prev_gate_state == "OPEN":
                    # Capture the image
                    image_filename = self.capture_gate_violation(
                        gate_action="AUTO_DENIED",
                        reason="Gate closed automatically due to incomplete PPE"
                    )
                    
                    # 🔧 NEW: Save to database
                    if image_filename:
                        
                        # Get missing items
                        missing_items = []
                        if self.latest_status.get('no_helmet'): missing_items.append('helmet')
                        if self.latest_status.get('no_gloves'): missing_items.append('gloves')
                        if self.latest_status.get('no_boots'): missing_items.append('boots')
                        
                        if self.flask_app:
                            try:
                                with self.flask_app.app_context():
                                    violation = Violation(
                                        timestamp=datetime.now(),
                                        violation_type='auto_denied',
                                        missing_items=', '.join(missing_items) if missing_items else 'N/A',
                                        image_path=image_filename,
                                        gate_action='AUTO_DENIED',
                                        operator_id=None,  # Automatic, no operator
                                        notes=f'Gate automatically closed - PPE violations detected: {", ".join(missing_items)}'
                                    )
                                    db.session.add(violation)
                                    db.session.commit()
                                    print(f"✅ AUTO_DENIED violation saved to database")
                            except Exception as e:
                                print(f"❌ Error saving violation to database: {e}")

                    
                    print(f"📸 Violation captured: Gate CLOSED due to missing PPE")
                elif self.prev_gate_state == "OPEN":
                    print(f"🚪 Gate closed (no violation capture needed)")
            
            elif new_gate_state == "OPEN":
                print(f"✅ Gate opened - PPE complete, no violation to capture")
            
            self.prev_gate_state = new_gate_state

            # 🔌 WebSocket: push gate state change instantly
            if self.socketio:
                self.socketio.emit('gate_update', {
                    "relay": new_gate_state,
                    "last_updated": datetime.now().strftime('%H:%M:%S')
                })

        self.current_gate_state = new_gate_state

    def _process_results(self, results):
        """
        🔧 UPDATED: Tracks both positive AND negative PPE detections
        Only marks as violation if negative classes are detected (no-helmet, no-gloves, no-boots)
        """
        names = self.model.names
        classes = [names[int(b.cls)] for b in results.boxes]
        
        # Positive detections (PPE present)
        helmet = "helmet" in classes
        gloves = "gloves" in classes or "glove" in classes
        boots = "boots" in classes
        
        # 🔧 NEW: Negative detections (PPE violations - person present WITHOUT PPE)
        no_helmet = "no-helmet" in classes
        no_gloves = "no-gloves" in classes or "no-glove" in classes
        no_boots = "no-boots" in classes
        
        # 🔧 CRITICAL: Only mark as NOT_OK if negative classes are detected
        # This means there's actually a person without proper PPE
        has_violation = no_helmet or no_boots#or no_gloves or no_boots
        
        # Determine status
        if has_violation:
            new_status = "NOT_OK"
        elif helmet and boots:               #NEED TO ADD GLOVES AND BOOTS
            new_status = "OK"
        else:
            # No positive OR negative detections = just background/empty frame
            new_status = "UNKNOWN"
        
        # Update status change events (for UI), but don't capture photos
        if new_status == "NOT_OK" and self.prev_status != "NOT_OK":
            elapsed = time.time() - self.start_time
            if elapsed >= self.startup_grace_period:
                missing = []
                if no_helmet: missing.append("helmet")
                if no_gloves: missing.append("gloves")
                if no_boots: missing.append("boots")
                
                ts = datetime.now().strftime("%H:%M:%S")
                msg = f"PPE VIOLATION detected: {', '.join(missing)}"
                event = {"time": ts, "type": "danger", "message": msg}
                self.events.append(event)
                print(f"⚠️ PPE Status: NOT_OK (violations: {missing})")

                # 🔌 WebSocket: push violation alert instantly
                if self.socketio:
                    self.socketio.emit('new_event', event)

        elif new_status == "OK" and self.prev_status == "NOT_OK":
            ts = datetime.now().strftime("%H:%M:%S")
            event = {"time": ts, "type": "success", "message": "All PPE detected"}
            self.events.append(event)
            print(f"✅ PPE Status: OK")

            # 🔌 WebSocket: push cleared status instantly
            if self.socketio:
                self.socketio.emit('new_event', event)

        elif new_status == "UNKNOWN" and self.prev_status == "NOT_OK":
            ts = datetime.now().strftime("%H:%M:%S")
            event = {"time": ts, "type": "info", "message": "No person detected"}
            self.events.append(event)
            print(f"ℹ️ PPE Status: UNKNOWN (no person in frame)")

            # 🔌 WebSocket: push unknown status instantly
            if self.socketio:
                self.socketio.emit('new_event', event)

        # 🔌 WebSocket: push full PPE status — rate-limited to EMIT_INTERVAL
        # Emitting every frame blocks the YOLO loop via threading lock acquisition
        current_items = {
            "helmet": helmet, "gloves": gloves, "boots": boots,
            "no_helmet": no_helmet, "no_gloves": no_gloves, "no_boots": no_boots
        }
        state_changed = new_status != self.prev_status or current_items != self.prev_items
        now = time.time()
        if state_changed and (now - self.last_emit_time) >= self.EMIT_INTERVAL:
            if self.socketio:
                self.socketio.emit('ppe_update', {
                    "ppe_status":    new_status,
                    "helmet":        helmet,
                    "gloves":        gloves,
                    "boots":         boots,
                    "no_helmet":     no_helmet,
                    "no_gloves":     no_gloves,
                    "no_boots":      no_boots,
                    "has_violation": has_violation,
                    "last_updated":  datetime.now().strftime('%H:%M:%S')
                })
            self.prev_items    = current_items
            self.last_emit_time = now

        self.prev_status = new_status
        
        # 🔧 NEW: Store negative detections for violation tracking
        self.latest_status.update({
            "ppe_status": new_status,
            "helmet": helmet,
            "gloves": gloves,
            "boots": boots,
            "no_helmet": no_helmet,
            "no_gloves": no_gloves,
            "no_boots": no_boots,
            "has_violation": has_violation  # Easy check for violations
        })

    def _draw_boxes(self, frame, results):
        for b in results.boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cls_id = int(b.cls)
            conf = float(b.conf)
            
            class_name = self.model.names[cls_id]
            label = f"{class_name} {conf:.2f}"
            
            # Color coding
            if class_name in ["helmet", "gloves", "glove", "boots"]:
                color = (0, 255, 0)    # GREEN ✅
                text_color = (0, 255, 0)
            elif class_name.startswith("no-"):
                color = (0, 0, 255)    # RED ❌
                text_color = (0, 0, 255)
            else:
                color = (0, 255, 255)  # YELLOW
                text_color = (0, 255, 255)
            
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 2)

    def loop(self):
        self.running = True
        print(f"⏳ YOLO processor starting with {self.startup_grace_period}s grace period...")
        print(f"📸 Violations ONLY captured on: Manual Override + Gate State Changes")

        self.raw_frame = None
        self.last_results = None
        self.stable_results = None
        self.stable_count = 0
        STABILITY_FRAMES = 3

        # Thread 1 — capture only, no YOLO
        def capture_loop():
            while self.running:
                ok, frame = self.cap.read()
                if ok:
                    self.raw_frame = frame
                else:
                    time.sleep(0.05)

        capture_thread = threading.Thread(target=capture_loop, daemon=True)
        capture_thread.start()

        # Thread 2 — inference loop
        prev_time = time.time()

        while self.running:
            if self.raw_frame is None:
                time.sleep(0.01)
                continue

            frame = self.raw_frame.copy()
            results = self.model(frame, verbose=False, imgsz=320, conf=0.5, iou=0.5)[0]

            # Temporal stability filter
            if len(results.boxes) > 0:
                self.stable_count += 1
                self.last_results = results
                if self.stable_count >= STABILITY_FRAMES:
                    self.stable_results = results
            else:
                self.stable_count = 0
                self.stable_results = None

            # Process and draw stable results only
            draw_frame = frame.copy()
            if self.stable_results is not None:
                self._process_results(self.stable_results)
                self._draw_boxes(draw_frame, self.stable_results)
            else:
                # Still need to update status when no detections
                self._process_results(results)

            # FPS overlay
            curr_time = time.time()
            self.fps = round(1 / (curr_time - prev_time), 1)
            prev_time = curr_time
            cv2.putText(draw_frame, f"FPS: {self.fps}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            ret, jpeg = cv2.imencode(".jpg", draw_frame)
            if ret:
                self.latest_frame = jpeg.tobytes()

        self.cap.release()

    def start(self):
        t = threading.Thread(target=self.loop, daemon=True)
        t.start()

    def stop(self):
        self.running = False