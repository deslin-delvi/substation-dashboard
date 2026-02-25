from flask import Flask, render_template, jsonify, Response, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import time
import os
import cv2
import numpy as np
import atexit
import threading

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

# Local imports
from utils.yolo_detector import YOLOProcessor
from utils.rtsp_processor import RTSPManager          # 📡 NEW
from models import db, User, Violation, RTSPCamera    # 📡 NEW: RTSPCamera model
from hardware_controller import GateController

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///substation.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Hardware controller (unchanged)
gate_controller = GateController(mode='direct', servo_pin=18, relay_pin=23, led_active_low=True)
gate_state_lock = threading.Lock()
relay_state = "CLOSED"
override = False

import time as time_module
COOLDOWN_SECONDS = 5          # seconds gate stays closed after a violation
gate_closed_at: float = 0.0  # timestamp of last auto-close

# Primary USB camera YOLO processor (unchanged)
yolo = YOLOProcessor(model_path="models/best.pt", camera_index=0, flask_app=app)
yolo.start()

# 📡 NEW: RTSP multi-camera manager
# Streams are loaded from the DB after db.create_all() in __main__
rtsp_manager = RTSPManager(model_path="models/best.pt", flask_app=app)

def cleanup_on_exit():
    print("\n🛑 Shutting down…")
    yolo.stop()
    rtsp_manager.cleanup()          # 📡 NEW: stop all RTSP streams
    gate_controller.cleanup()
    print("✅ Cleanup complete")

atexit.register(cleanup_on_exit)


# ─────────────────────────────────────────────────────────────
# Auth routes  (UNCHANGED)
# ─────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user, remember=True)
            return redirect(url_for('index'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ─────────────────────────────────────────────────────────────
# Main dashboard  (UNCHANGED)
# ─────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    return render_template('index.html', username=current_user.username)


# ─────────────────────────────────────────────────────────────
# Gate / USB-camera status routes  (UNCHANGED)
# ─────────────────────────────────────────────────────────────
@app.route('/status')
@login_required
def status():
    global relay_state, override, gate_closed_at
    with gate_state_lock:
        current = yolo.latest_status.copy()
        previous_relay_state = relay_state
    
        if not override:
            if current.get("ppe_status") == "OK":
                # Only open if cooldown has fully elapsed
                elapsed = time_module.time() - gate_closed_at
                if elapsed >= COOLDOWN_SECONDS:
                    relay_state = "OPEN"
                # else: leave relay_state as CLOSED, cooldown still running
            else:
                # PPE not OK — close and record the timestamp
                if relay_state != "CLOSED":
                    gate_closed_at = time_module.time()
                relay_state = "CLOSED"

        if previous_relay_state != relay_state:
            gate_controller.set_state(relay_state)
            yolo.update_gate_state(relay_state)

        elapsed   = time_module.time() - gate_closed_at
        remaining = max(0.0, COOLDOWN_SECONDS - elapsed)

        response_data = current.copy()
        response_data["relay"]              = relay_state
        response_data["override"]           = override
        response_data['last_updated']       = datetime.now().strftime('%H:%M:%S')
        response_data['cooldown_active']    = remaining > 0 and not override
        response_data['cooldown_remaining'] = round(remaining, 1)
    return jsonify(response_data)

@app.route('/events')
@login_required
def events():
    return jsonify(yolo.events[-10:])

@app.route('/control/relay', methods=['POST'])
@login_required
def control_relay():
    global relay_state, override
    with gate_state_lock:
        override = True
        violation_timestamp = datetime.now()
        timestamp_str = violation_timestamp.strftime("%Y%m%d_%H%M%S")
        current_frame  = yolo.latest_frame
        image_filename = None
        if current_frame and isinstance(current_frame, bytes):
            try:
                nparr    = np.frombuffer(current_frame, np.uint8)
                frame_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame_np is not None and frame_np.size > 0:
                    image_filename  = f"override_{timestamp_str}.jpg"
                    violations_dir  = os.path.join(app.root_path, "static", "violations")
                    os.makedirs(violations_dir, exist_ok=True)
                    success = cv2.imwrite(os.path.join(violations_dir, image_filename), frame_np)
                    if not success:
                        image_filename = None
            except Exception as e:
                print(f"❌ Error capturing override photo: {e}")
                image_filename = None

        if relay_state == "OPEN":
            relay_state = "CLOSED"
            msg         = "Manual override: gate CLOSED by supervisor"
            gate_action = "MANUAL_CLOSE"
        else:
            relay_state = "OPEN"
            msg         = "Manual override: gate OPENED by supervisor"
            gate_action = "MANUAL_OPEN"

        gate_controller.set_state(relay_state)
        ppe_status = yolo.latest_status.copy()

    violations_detected = []
    if ppe_status.get('no_helmet'): violations_detected.append('no-helmet')
    if ppe_status.get('no_gloves'): violations_detected.append('no-gloves')
    if ppe_status.get('no_boots'):  violations_detected.append('no-boots')

    missing_items = (
        [v.replace('no-', '') for v in violations_detected]
        if violations_detected
        else [x for x in ('helmet', 'gloves', 'boots') if not ppe_status.get(x)]
    )

    has_violation = ppe_status.get('has_violation', False)
    ppe_state     = ppe_status.get('ppe_status', 'UNKNOWN')

    if has_violation:
        ppe_description = f"VIOLATION DETECTED: {', '.join(violations_detected)}"
    elif ppe_state == "OK":
        ppe_description = "COMPLETE PPE"
    else:
        ppe_description = "NO PERSON DETECTED"

    violation = Violation(
        timestamp      = violation_timestamp,
        violation_type = 'manual_override',
        missing_items  = ', '.join(missing_items) if missing_items else 'N/A',
        image_path     = image_filename,
        gate_action    = gate_action,
        operator_id    = current_user.id,
        notes          = f'{msg} by {current_user.username}. PPE Status: {ppe_description}',
    )
    db.session.add(violation)
    db.session.commit()

    return jsonify({
        "relay":          relay_state,
        "override":       override,
        "message":        msg,
        "image_captured": image_filename is not None,
        "ppe_status":     ppe_status.get('ppe_status', 'UNKNOWN'),
        "violations":     violations_detected if has_violation else [],
    })

@app.route("/control/auto", methods=["POST"])
@login_required
def clear_override():
    global override
    with gate_state_lock:
        override  = False
        ppe_status = yolo.latest_status.copy()

    has_violation = ppe_status.get('has_violation', False)
    violations    = [x for x in ('helmet', 'gloves', 'boots')
                     if ppe_status.get(f'no_{x}')]
    image_filename    = None
    violation_timestamp = datetime.now()

    if has_violation and violations:
        image_filename = yolo.capture_gate_violation(
            gate_action='AUTO_MODE',
            reason=f'Auto control restored by {current_user.username} - Active violations: {", ".join(violations)}'
        )
        violation = Violation(
            timestamp      = violation_timestamp,
            violation_type = 'auto_mode_restored',
            missing_items  = ', '.join(violations),
            image_path     = image_filename,
            gate_action    = 'AUTO_MODE',
            operator_id    = current_user.id,
            notes          = f'Auto control restored by {current_user.username} - Person detected without: {", ".join(violations)}',
        )
    else:
        ppe_state = "complete PPE" if ppe_status.get('ppe_status') == 'OK' else "no person detected"
        violation = Violation(
            timestamp      = violation_timestamp,
            violation_type = 'auto_mode_restored',
            missing_items  = 'N/A',
            image_path     = None,
            gate_action    = 'AUTO_MODE',
            operator_id    = current_user.id,
            notes          = f'Auto control restored by {current_user.username} - {ppe_state}',
        )
    db.session.add(violation)
    db.session.commit()

    return jsonify({
        "override":           False,
        "message":            "Automatic PPE control restored",
        "violation_detected": has_violation,
        "violations":         violations if has_violation else [],
    })


# ─────────────────────────────────────────────────────────────
# Violations review  (UNCHANGED)
# ─────────────────────────────────────────────────────────────
@app.route('/violations')
@login_required
def violations():
    page       = request.args.get('page', 1, type=int)
    violations = Violation.query.order_by(Violation.timestamp.desc()).paginate(
        page=page, per_page=12, error_out=False
    )
    return render_template('violations.html', violations=violations)

@app.route('/violations/<int:id>/notes', methods=['POST'])
@login_required
def add_violation_notes(id):
    violation = Violation.query.get_or_404(id)
    violation.supervisor_notes = request.json.get('notes')
    db.session.commit()
    return jsonify({'status': 'success', 'violation_id': id, 'notes': violation.supervisor_notes})

@app.route('/violation-image/<path:filename>')
@login_required
def serve_violation_image(filename):
    return send_from_directory('static/violations', filename)

@app.route("/video_feed")
def video_feed():
    """Primary USB camera feed (unchanged)."""
    def generate():
        while True:
            frame = yolo.latest_frame
            if frame is None:
                time.sleep(0.05)
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ─────────────────────────────────────────────────────────────
# 📡 NEW: RTSP / CCTV camera management
# ─────────────────────────────────────────────────────────────

@app.route('/cameras')
@login_required
def cameras():
    """
    Dashboard page listing all registered RTSP cameras.
    Renders templates/cameras.html
    """
    all_cameras = RTSPCamera.query.order_by(RTSPCamera.added_at.desc()).all()
    return render_template('cameras.html', cameras=all_cameras)


@app.route('/cameras/add', methods=['POST'])
@login_required
def add_camera():
    """
    Register a new RTSP camera and start its stream immediately.

    Expected JSON body:
    {
        "name":     "Gate A Camera",
        "url":      "rtsp://admin:pass@192.168.1.100:554/stream1",
        "location": "North perimeter"   ← optional
    }
    """
    data     = request.get_json() or {}
    name     = (data.get('name') or '').strip()
    url      = (data.get('url')  or '').strip()
    location = (data.get('location') or '').strip()

    if not name or not url:
        return jsonify({'status': 'error', 'message': 'name and url are required'}), 400

    if not url.startswith(('rtsp://', 'rtmp://', 'http://', 'https://')):
        return jsonify({'status': 'error', 'message': 'URL must start with rtsp://, rtmp://, http://, or https://'}), 400

    cam = RTSPCamera(name=name, url=url, location=location, enabled=True)
    db.session.add(cam)
    db.session.commit()

    # Start the live stream immediately
    rtsp_manager.add_stream(cam.id, cam.name, cam.url)

    return jsonify({'status': 'success', 'camera': cam.to_dict()}), 201


@app.route('/cameras/<int:camera_id>', methods=['DELETE'])
@login_required
def delete_camera(camera_id):
    """Stop the stream and delete the DB record."""
    cam = RTSPCamera.query.get_or_404(camera_id)
    rtsp_manager.remove_stream(camera_id)
    db.session.delete(cam)
    db.session.commit()
    return jsonify({'status': 'success', 'message': f'Camera "{cam.name}" removed'})


@app.route('/cameras/<int:camera_id>/toggle', methods=['POST'])
@login_required
def toggle_camera(camera_id):
    """
    Enable or disable a camera stream without deleting it.
    Accepts optional JSON: {"enabled": true/false}
    If omitted, the current state is flipped.
    """
    cam  = RTSPCamera.query.get_or_404(camera_id)
    data = request.get_json() or {}

    if 'enabled' in data:
        cam.enabled = bool(data['enabled'])
    else:
        cam.enabled = not cam.enabled   # flip

    db.session.commit()

    if cam.enabled:
        rtsp_manager.enable_stream(cam.id, cam.name, cam.url)
        msg = f'Camera "{cam.name}" enabled'
    else:
        rtsp_manager.disable_stream(cam.id)
        msg = f'Camera "{cam.name}" disabled'

    return jsonify({'status': 'success', 'message': msg, 'camera': cam.to_dict()})


@app.route('/cameras/<int:camera_id>/status')
@login_required
def camera_status(camera_id):
    """Return live PPE detection status for one RTSP camera."""
    RTSPCamera.query.get_or_404(camera_id)   # 404 if unknown ID
    status = rtsp_manager.get_status(camera_id)
    status['last_updated'] = datetime.now().strftime('%H:%M:%S')
    return jsonify(status)


@app.route('/cameras/status/all')
@login_required
def all_cameras_status():
    """Return PPE status for every active RTSP stream in one call."""
    return jsonify(rtsp_manager.get_all_statuses())


@app.route('/cameras/<int:camera_id>/feed')
@login_required
def rtsp_video_feed(camera_id):
    """
    MJPEG stream for a specific RTSP camera.
    Embed in an <img> tag:  <img src="/cameras/3/feed">
    """
    RTSPCamera.query.get_or_404(camera_id)

    def generate():
        placeholder_sent = False
        while True:
            frame = rtsp_manager.get_frame(camera_id)
            if frame is None:
                # Stream not ready yet – send a plain placeholder every 0.5s
                if not placeholder_sent:
                    placeholder_sent = True
                time.sleep(0.1)
                continue
            placeholder_sent = False
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route('/cameras/<int:camera_id>/capture', methods=['POST'])
@login_required
def capture_cctv_violation(camera_id):
    """Supervisor manually captures a violation snapshot from a CCTV stream."""
    RTSPCamera.query.get_or_404(camera_id)
    data  = request.get_json() or {}
    notes = (data.get('notes') or '').strip()

    filename, error = rtsp_manager.capture_violation(
        camera_id    = camera_id,
        supervisor_id = current_user.id,
        notes        = notes,
    )

    if error:
        return jsonify({'status': 'error', 'message': error}), 400

    return jsonify({
        'status':   'success',
        'message':  'Violation captured and logged',
        'image':    filename,
    })

# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()   # creates RTSPCamera table on first run too

    # 📡 Load saved cameras from DB and start their streams
    rtsp_manager.load_from_db()

    print("\n" + "="*50)
    print("🚀 SUBSTATION PPE MONITORING SYSTEM")
    print("="*50)
    print(f"📹 Camera:    USB Webcam (index 0)")
    print(f"📡 RTSP:      {rtsp_manager.active_count()} stream(s) active")
    print(f"🤖 Model:     YOLOv11 (models/best.pt)")
    print(f"🔧 Hardware:  {'GPIO ENABLED' if gate_controller else 'SIMULATION MODE'}")
    print(f"🚪 Gate:      {gate_controller.get_state()}")
    print("="*50 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
