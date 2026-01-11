# utils/yolo_detector.py
from ultralytics import YOLO
import cv2
import threading
import time
from datetime import datetime

try:
    from flask_sqlalchemy import SQLAlchemy
    from models import db, Violation
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    print("⚠️ Database not available - running in mock mode")

class YOLOProcessor:
    def __init__(self, model_path="models/best.pt", camera_index=0):
        # Load model
        self.model = YOLO(model_path)

        # Events + status tracking
        self.events = []
        self.prev_status = "UNKNOWN"
        
        # 🔧 NEW: Prevent logging violations during startup
        self.startup_grace_period = 5.0  # seconds
        self.start_time = time.time()

        # Open camera EXACTLY like bare_cam_test
        self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        print("Opened:", self.cap.isOpened())

        # Optional: force same resolution as test script
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self.latest_frame = None  # JPEG bytes
        self.latest_status = {
            "ppe_status": "UNKNOWN",
            "helmet": False,
            "vest": False,
            "gloves": False
        }
        self.running = False

    def _process_results(self, results):
        import os
        import numpy as np
        from app import app
        names = self.model.names
        classes = [names[int(b.cls)] for b in results.boxes]
        helmet = "helmet" in classes
        vest = "vest" in classes or "safety vest" in classes
        gloves = "gloves" in classes or "glove" in classes

        ok = helmet and vest and gloves
        new_status = "OK" if ok else "NOT_OK"

        # 🔧 NEW: Check if we're still in startup grace period
        elapsed = time.time() - self.start_time
        in_grace_period = elapsed < self.startup_grace_period
        
        if in_grace_period:
            # Update status but don't log violations during startup
            self.prev_status = new_status
            self.latest_status.update({
                "ppe_status": new_status,
                "helmet": helmet,
                "vest": vest,
                "gloves": gloves
            })
            return  # Skip violation logging during startup

        # SAVE VIOLATION IMAGE + LOG TO DATABASE WHEN PPE MISSING (AFTER GRACE PERIOD)
        if new_status == "NOT_OK" and new_status != self.prev_status:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_filename = f"violation_{timestamp}.jpg"
            
            # Use os.path.join for full save path
            violations_dir = os.path.join(app.root_path, "static", "violations")
            os.makedirs(violations_dir, exist_ok=True)
            full_image_path = os.path.join(violations_dir, image_filename)
            
            print(f"🎯 TARGET: {full_image_path}")
            
            # CONVERT BYTES TO OPENCV FRAME
            if isinstance(self.latest_frame, bytes) and len(self.latest_frame) > 0:
                nparr = np.frombuffer(self.latest_frame, np.uint8)
                frame_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame_np is None or frame_np.size == 0:
                    print("❌ DECODE FAILED - No valid image data")
                    return
                
                print(f"✅ DECODED: {frame_np.shape}")
            else:
                print("❌ NO FRAME BYTES")
                return
            
            # SAVE IMAGE
            success = cv2.imwrite(full_image_path, frame_np)
            print(f"✅ SAVED: {success} → {full_image_path}")
            
            if success:
                # Database logging
                missing = []
                if not helmet: missing.append("helmet")
                if not vest: missing.append("vest")
                if not gloves: missing.append("gloves")
                
                try:
                    from models import db, Violation
                    with app.app_context():
                        violation = Violation(
                            timestamp=datetime.now(),
                            violation_type='ppe_incomplete',  # 🔧 NEW: Add violation type
                            missing_items=', '.join(missing),
                            image_path=image_filename,  # Store ONLY filename, not full path
                            gate_action="DENIED"
                        )
                        db.session.add(violation)
                        db.session.commit()
                        print(f"✅ DATABASE LOGGED: {missing} | Filename: {image_filename}")
                except Exception as e:
                    print(f"❌ DB Error: {e}")

            # Status change event
            ts = datetime.now().strftime("%H:%M:%S")
            msg = f"PPE missing: {', '.join(missing)}"
            self.events.append({"time": ts, "type": "danger", "message": msg})
        
        elif new_status != self.prev_status:
            # OK status change
            ts = datetime.now().strftime("%H:%M:%S")
            self.events.append({"time": ts, "type": "success", "message": "All PPE detected"})
        
        self.prev_status = new_status
        
        self.latest_status.update({
            "ppe_status": new_status,
            "helmet": helmet,
            "vest": vest,
            "gloves": gloves
        })


    def log_violation(self, frame, detection_results):
        """Capture violation image and log to database"""
        if not DATABASE_AVAILABLE or detection_results['ppe_status'] != "NOT_OK":
            return
            
        try:
            import os
            os.makedirs('static/violations', exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"static/violations/violation_{timestamp}.jpg"
            
            # Save annotated frame
            cv2.imwrite(filename, frame)
            
            # Log to database
            missing_items = [k for k, v in detection_results.items() 
                           if k != 'ppe_status' and not v]
            
            violation = Violation(
                violation_type='ppe_incomplete',
                missing_items=', '.join(missing_items),
                image_path=filename,
                gate_action='DENIED'
            )
            db.session.add(violation)
            db.session.commit()
            
            print(f"📸 Violation logged: {filename}")
            
        except Exception as e:
            print(f"❌ Violation logging failed: {e}")

    def _draw_boxes(self, frame, results):
        for b in results.boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cls_id = int(b.cls)
            conf = float(b.conf)
            
            class_name = self.model.names[cls_id]
            label = f"{class_name} {conf:.2f}"
            
            # GREEN for POSITIVE PPE classes, RED for NEGATIVE "no_" classes
            if class_name in ["helmet", "vest", "safety vest", "gloves", "glove"]:
                color = (0, 255, 0)    # GREEN ✅ PPE DETECTED
                text_color = (0, 255, 0)
            elif class_name.startswith("no-"): # RED ❌ PPE MISSING
                color = (0, 0, 255)    
                text_color = (0, 0, 255)
            else:
                color = (0, 255, 255) # YELLOW for other objects
                text_color = (0, 255, 255)  
            
            # Draw bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            cv2.putText(
                frame, label, (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 2
            )


    def loop(self):
        self.running = True
        print(f"⏳ YOLO processor starting with {self.startup_grace_period}s grace period...")
        
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            
            # YOLO inference
            results = self.model(frame, verbose=False)[0]
            self._process_results(results)
            self._draw_boxes(frame, results)
            
            # Encode exactly like bare_cam_test would
            ret, jpeg = cv2.imencode(".jpg", frame)
            if ret:
                self.latest_frame = jpeg.tobytes()

        self.cap.release()

    def start(self):
        t = threading.Thread(target=self.loop, daemon=True)
        t.start()

    def stop(self):
        self.running = False