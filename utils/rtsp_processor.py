# utils/rtsp_processor.py
"""
RTSP / CCTV Multi-Camera Processor
------------------------------------
• Each RTSPStream runs its own capture + YOLO thread
• Automatic reconnection on stream drop (configurable interval)
• Violations are logged to the same Violation table as the USB camera
• RTSPManager is the single object app.py imports – it owns all streams
"""

import cv2
import threading
import time
import os
import numpy as np
from datetime import datetime
from ultralytics import YOLO

try:
    from models import db, Violation, RTSPCamera
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    print("⚠️ Database not available for RTSP processor")


# ─────────────────────────────────────────────────────────────
# Single stream – one instance per RTSP camera
# ─────────────────────────────────────────────────────────────
class RTSPStream:
    """
    Captures frames from one RTSP URL, runs YOLO inference,
    logs violations, and exposes the annotated JPEG frame.
    """

    RECONNECT_INTERVAL = 7   # seconds between reconnection attempts
    STARTUP_GRACE      = 5.0  # seconds to suppress logging after (re)connect

    def __init__(self, camera_id: int, name: str, url: str,
                 model: YOLO, flask_app, violations_dir: str, socketio=None):
        self.camera_id      = camera_id
        self.name           = name
        self.url            = url
        self.model          = model
        self.flask_app      = flask_app
        self.violations_dir = violations_dir
        self.socketio       = socketio

        self.latest_frame: bytes | None = None
        self._frame_lock = threading.Lock()  # protects latest_frame access
        self.latest_status = {
            "ppe_status": "UNKNOWN",
            "helmet": False, "gloves": False, "boots": False,
            "no_helmet": False, "no_gloves": False, "no_boots": False,
            "has_violation": False,
        }

        self._running    = False
        self._thread     = None
        self._start_time = 0.0
        self._connected  = False
        self.fps         = 0.0
        self.prev_status = "UNKNOWN"

        # Auto-capture: cooldown prevents flooding disk/DB
        self.AUTO_CAPTURE_COOLDOWN = 30   # seconds between auto-saves per stream
        self._last_auto_capture    = 0.0

    # ── public API ──────────────────────────────────────────
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"▶️  RTSP stream started: [{self.camera_id}] {self.name}")

    def stop(self):
        self._running = False
        print(f"⏹️  RTSP stream stopped: [{self.camera_id}] {self.name}")

    def is_connected(self) -> bool:
        return self._connected

    def get_snapshot(self) -> bytes | None:
        """Return the latest annotated JPEG bytes (None if not yet available)."""
        with self._frame_lock:
            return self.latest_frame

    # ── internal loop ────────────────────────────────────────
    def _loop(self):
        while self._running:
            cap = self._open_capture()
            if cap is None:
                # 🔌 Notify frontend stream is offline
                if self.socketio:
                    self.socketio.emit('rtsp_status_update', {
                        "camera_id":   self.camera_id,
                        "camera_name": self.name,
                        "ppe_status":  "OFFLINE",
                        "fps":         0,
                    })
                time.sleep(self.RECONNECT_INTERVAL)
                continue

            self._connected  = True
            self._start_time = time.time()
            prev_time        = time.time()
            frame_count      = 0
            print(f"✅ Connected to RTSP stream: {self.name} ({self.url})")

            while self._running:
                ok, frame = cap.read()
                if not ok:
                    print(f"⚠️ Lost connection to {self.name}, reconnecting…")
                    self._connected = False
                    # 🔌 Notify frontend stream dropped
                    if self.socketio:
                        self.socketio.emit('rtsp_status_update', {
                            "camera_id":   self.camera_id,
                            "camera_name": self.name,
                            "ppe_status":  "OFFLINE",
                            "fps":         0,
                        })
                    break
                
                frame_count += 1
                if frame_count % 3 != 0:      # process every other frame
                    continue
                
                results = self.model(frame, verbose=False, imgsz=320, conf=0.6, iou=0.6)[0]
                self._process_results(results)
                self._draw_boxes(frame, results)

		
                #curr_time  = time.time()
                #self.fps   = round(1 / max(curr_time - prev_time, 1e-6), 1)
                #prev_time  = curr_time

                # Overlay: camera name + fps (disabled)
                #cv2.putText(frame, f"{self.name} | FPS:{self.fps}",
                #             (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                #             0.8, (0, 255, 0), 2)
                ret, jpeg = cv2.imencode(".jpg", frame)
                if ret:
                    with self._frame_lock:
                        self.latest_frame = jpeg.tobytes()

            cap.release()
            if self._running:
                time.sleep(self.RECONNECT_INTERVAL)

        self._connected = False

    def _open_capture(self):
        """Try to open the RTSP stream; return cap object or None."""
        try:
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;60000000"
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            if not cap.isOpened():
                print(f"❌ Cannot open RTSP URL: {self.url}")
                return None
            return cap
        except Exception as e:
            print(f"❌ Error opening {self.url}: {e}")
            return None

    # ── YOLO processing (mirrors yolo_detector.py logic) ────
    def _process_results(self, results):
        names   = self.model.names
        classes = [names[int(b.cls)] for b in results.boxes]

        helmet    = "helmet"    in classes
        gloves    = ("gloves"   in classes) or ("glove" in classes)
        boots     = "boots"     in classes
        no_helmet = "no-helmet" in classes
        no_gloves = ("no-gloves" in classes) or ("no-glove" in classes)
        no_boots  = "no-boots"  in classes

        has_violation = no_helmet or no_boots  # no_gloves excluded (intentional, matches USB camera)

        if has_violation:
            new_status = "NOT_OK"
        elif helmet and gloves and boots:
            new_status = "OK"
        else:
            new_status = "UNKNOWN"

        # 🔌 WebSocket: push RTSP camera status when it changes
        if new_status != self.prev_status:
            if self.socketio:
                self.socketio.emit('rtsp_status_update', {
                    "camera_id":    self.camera_id,
                    "camera_name":  self.name,
                    "ppe_status":   new_status,
                    "helmet":       helmet,
                    "gloves":       gloves,
                    "boots":        boots,
                    "no_helmet":    no_helmet,
                    "no_gloves":    no_gloves,
                    "no_boots":     no_boots,
                    "has_violation": has_violation,
                    "last_updated": datetime.now().strftime('%H:%M:%S')
                })

        self.prev_status = new_status
        self.latest_status.update({
            "ppe_status":   new_status,
            "helmet":       helmet,
            "gloves":       gloves,
            "boots":        boots,
            "no_helmet":    no_helmet,
            "no_gloves":    no_gloves,
            "no_boots":     no_boots,
            "has_violation": has_violation,
        })

        # Auto-capture when a violation is active (cooldown-guarded)
        if has_violation:
            missing = []
            if no_helmet: missing.append("helmet")
            if no_gloves: missing.append("gloves")
            if no_boots:  missing.append("boots")
            self._auto_capture_violation(missing)

    def _draw_boxes(self, frame, results):
        for b in results.boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cls_id     = int(b.cls)
            conf       = float(b.conf)
            class_name = self.model.names[cls_id]
            label      = f"{class_name} {conf:.2f}"

            if class_name in ("helmet", "gloves", "glove", "boots"):
                color = (0, 255, 0)
            elif class_name.startswith("no-"):
                color = (0, 0, 255)
            else:
                color = (0, 255, 255)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    def _auto_capture_violation(self, missing_items: list):
        """
        Auto-saves a violation frame + DB record when YOLO detects a PPE breach.
        Cooldown (AUTO_CAPTURE_COOLDOWN) prevents flooding disk and DB.
        Respects the startup grace period used by the stream.
        Image saved at 60% JPEG quality (~30-50 KB each).
        """
        now = time.time()

        # Respect startup grace — _start_time is set on each (re)connect
        if self._start_time and (now - self._start_time) < self.STARTUP_GRACE:
            return

        # Cooldown guard — one capture per camera per COOLDOWN window
        if (now - self._last_auto_capture) < self.AUTO_CAPTURE_COOLDOWN:
            return

        with self._frame_lock:
            frame_data = self.latest_frame
        if not isinstance(frame_data, bytes) or len(frame_data) == 0:
            return

        timestamp  = datetime.now()
        ts_str     = timestamp.strftime("%Y%m%d_%H%M%S")
        filename   = f"rtsp_auto_{self.camera_id}_{ts_str}.jpg"
        saved      = False

        try:
            os.makedirs(self.violations_dir, exist_ok=True)
            nparr    = np.frombuffer(frame_data, np.uint8)
            frame_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame_np is not None:
                path  = os.path.join(self.violations_dir, filename)
                saved = cv2.imwrite(path, frame_np, [cv2.IMWRITE_JPEG_QUALITY, 60])
        except Exception as e:
            print(f"❌ Auto-capture save error [{self.name}]: {e}")
            return

        if not saved:
            return

        self._last_auto_capture = now   # update only after a successful save

        try:
            with self.flask_app.app_context():
                record = Violation(
                    timestamp      = timestamp,
                    violation_type = "rtsp_auto_capture",
                    missing_items  = ", ".join(missing_items) if missing_items else "N/A",
                    image_path     = filename,
                    gate_action    = "RTSP_AUTO",
                    operator_id    = None,
                    notes          = (
                        f"[CCTV:{self.name}] Auto-detected PPE violation. "
                        f"Missing: {', '.join(missing_items)}"
                    ),
                )
                db.session.add(record)
                db.session.commit()
                print(f"📸 Auto-capture logged [{self.name}]: {filename}")

                if self.socketio:
                    self.socketio.emit('rtsp_violation', {
                        "camera_id":   self.camera_id,
                        "camera_name": self.name,
                        "ppe_status":  "NOT_OK",
                        "missing":     missing_items,
                        "image":       filename,
                        "time":        timestamp.strftime('%H:%M:%S'),
                        "auto":        True,
                    })
        except Exception as e:
            print(f"❌ Auto-capture DB error [{self.name}]: {e}")

    def capture_violation(self, supervisor_id, notes=""):
        """
        Called manually by supervisor via the dashboard button.
        Reads current frame + PPE status at time of click.
        """
        missing_items = []
        if self.latest_status.get('no_helmet'): missing_items.append('helmet')
        if self.latest_status.get('no_gloves'): missing_items.append('gloves')
        if self.latest_status.get('no_boots'):  missing_items.append('boots')

        ppe_status = self.latest_status.get('ppe_status', 'UNKNOWN')

        import os, numpy as np
        timestamp  = datetime.now()
        ts_str     = timestamp.strftime("%Y%m%d_%H%M%S")
        image_filename = f"rtsp_{self.camera_id}_{ts_str}.jpg"
        saved = False

        with self._frame_lock:
            frame_data = self.latest_frame
        if isinstance(frame_data, bytes) and len(frame_data) > 0:
            try:
                os.makedirs(self.violations_dir, exist_ok=True)
                nparr    = np.frombuffer(frame_data, np.uint8)
                frame_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame_np is not None:
                    saved = cv2.imwrite(
                        os.path.join(self.violations_dir, image_filename), frame_np
                    )
            except Exception as e:
                print(f"❌ Error saving snapshot: {e}")

        if not saved:
            image_filename = None

        # Save to DB
        try:
            with self.flask_app.app_context():
                record = Violation(
                    timestamp      = timestamp,
                    violation_type = "rtsp_manual_capture",
                    missing_items  = ", ".join(missing_items) if missing_items else "N/A",
                    image_path     = image_filename,
                    gate_action    = "RTSP_MANUAL",
                    operator_id    = supervisor_id,
                    notes          = (
                        notes or
                        f"[CCTV:{self.name}] Manual capture by supervisor. "
                        f"PPE status: {ppe_status}"
                        + (f" – missing: {', '.join(missing_items)}" if missing_items else "")
                    ),
                )
                db.session.add(record)
                db.session.commit()
                print(f"📸 Manual CCTV capture logged: {self.name}")

                # 🔌 WebSocket: notify dashboard of new RTSP violation
                if self.socketio:
                    self.socketio.emit('rtsp_violation', {
                        "camera_id":   self.camera_id,
                        "camera_name": self.name,
                        "ppe_status":  ppe_status,
                        "missing":     missing_items,
                        "image":       image_filename,
                        "time":        datetime.now().strftime('%H:%M:%S')
                    })

                return image_filename
        except Exception as e:
            print(f"❌ DB error: {e}")
            return None


# ─────────────────────────────────────────────────────────────
# Manager – owns all streams, imported by app.py
# ─────────────────────────────────────────────────────────────
class RTSPManager:
    """
    Manages the lifecycle of all RTSP camera streams.
    Call `load_from_db(app)` once at startup, then use the
    per-camera helpers from routes.
    """

    def __init__(self, model_path: str, flask_app, socketio=None):
        self.flask_app      = flask_app
        self.socketio       = socketio
        self.violations_dir = os.path.join(flask_app.root_path, "static", "violations")
        self._streams: dict[int, RTSPStream] = {}

        # Share one YOLO model across all RTSP streams (memory-efficient)
        print("🔄 Loading YOLO model for RTSP manager…")
        self.model = YOLO(model_path)
        print("✅ RTSP YOLO model loaded")

        """✅ Warm-up: force model fuse ONCE before any threads start
        This prevents the race condition where multiple threads
        all try to fuse the model simultaneously on first inference"""
        dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        self.model(dummy, verbose=False, imgsz=320)
        print("✅ RTSP YOLO model loaded and warmed up")

    # ── lifecycle ────────────────────────────────────────────
    def load_from_db(self):
        """Start streams for every enabled RTSPCamera row in the database."""
        with self.flask_app.app_context():
            cameras = RTSPCamera.query.filter_by(enabled=True).all()
            for cam in cameras:
                self._start_stream(cam.id, cam.name, cam.url)
        print(f"📡 RTSPManager: {len(self._streams)} stream(s) started from DB")

    def cleanup(self):
        for stream in self._streams.values():
            stream.stop()
        self._streams.clear()

    # ── stream control (called from routes) ─────────────────
    def add_stream(self, camera_id: int, name: str, url: str):
        if camera_id in self._streams:
            return
        self._start_stream(camera_id, name, url)
        if self.socketio:
            self.socketio.emit('rtsp_camera_enabled', {
                "camera_id": camera_id,
                "name":      name,
            })

    def remove_stream(self, camera_id: int):
        """Stop and remove a stream."""
        stream = self._streams.pop(camera_id, None)
        if stream:
            stream.stop()

    def enable_stream(self, camera_id: int, name: str, url: str):
        self.add_stream(camera_id, name, url)

    def disable_stream(self, camera_id: int):
        self.remove_stream(camera_id)

    # ── data access (called from routes) ────────────────────
    def get_frame(self, camera_id: int) -> bytes | None:
        stream = self._streams.get(camera_id)
        return stream.get_snapshot() if stream else None

    def get_status(self, camera_id: int) -> dict:
        stream = self._streams.get(camera_id)
        if not stream:
            return {"connected": False, "ppe_status": "OFFLINE"}
        return {
            **stream.latest_status,
            "connected": stream.is_connected(),
            "fps": stream.fps,
            "name": stream.name,
        }

    def get_all_statuses(self) -> dict:
        return {cid: self.get_status(cid) for cid in self._streams}

    def active_count(self) -> int:
        return len(self._streams)

    # ── internal ─────────────────────────────────────────────
    def _start_stream(self, camera_id: int, name: str, url: str):
        stream = RTSPStream(
            camera_id      = camera_id,
            name           = name,
            url            = url,
            model          = self.model,
            flask_app      = self.flask_app,
            violations_dir = self.violations_dir,
            socketio       = self.socketio,
        )
        stream.start()
        self._streams[camera_id] = stream

    # Add to RTSPManager class
    def capture_violation(self, camera_id: int, supervisor_id: int, notes: str = ""):
        """Called from the route when supervisor clicks Capture."""
        stream = self._streams.get(camera_id)
        if not stream:
            return None, "Stream not active"
        filename = stream.capture_violation(supervisor_id, notes)
        return filename, None