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

# Local imports
from utils.yolo_detector import YOLOProcessor
from models import db, User, Violation
from hardware_controller import GateController  # 🔧 NEW: Import hardware controller

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

# 🔧 NEW: Initialize hardware controller
# Change mode to 'relay' if using relay module
gate_controller = GateController(mode='direct', servo_pin=18, relay_pin=17)

# Cleanup GPIO on exit
def cleanup_on_exit():
    print("\n🛑 Shutting down...")
    yolo.stop()
    gate_controller.cleanup()
    print("✅ Cleanup complete")

atexit.register(cleanup_on_exit)

# Start YOLO processor (update camera_index if needed, usually 0 for USB webcam)
yolo = YOLOProcessor(model_path="models/best.pt", camera_index=0, flask_app=app)
yolo.start()

relay_state = "CLOSED"   # gate starts closed
override = False         # manual override flag

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


@app.route('/')
@login_required
def index():
    return render_template('index.html', username=current_user.username)


@app.route('/status')
@login_required
def status():
    """
    Automatic logic when override is OFF:
      - ppe_status == "OK"     -> relay_state = "OPEN"
      - ppe_status == "NOT_OK" -> relay_state = "CLOSED"
    When override is ON:
      - relay_state is left as last set by supervisor.
    
    🔧 NEW: Now controls actual hardware gate!
    """
    global relay_state, override
    current = yolo.latest_status.copy()
    
    # Store previous state to detect changes
    previous_relay_state = relay_state

    if not override:
        if current.get("ppe_status") == "OK":
            relay_state = "OPEN"
        else:
            relay_state = "CLOSED"
    
    # 🔧 NEW: Control actual hardware gate when state changes
    if previous_relay_state != relay_state:
        gate_controller.set_state(relay_state)
        yolo.update_gate_state(relay_state)

    current["relay"] = relay_state
    current["override"] = override
    current['last_updated'] = datetime.now().strftime('%H:%M:%S')
    return jsonify(current)


@app.route('/events')
@login_required
def events():
    # Last 10 events from YOLO
    return jsonify(yolo.events[-10:])

@app.route('/control/relay', methods=['POST'])
@login_required
def control_relay():
    """Manual override - logs supervisor action + CAPTURES CURRENT FRAME + CONTROLS HARDWARE"""
    global relay_state, override
    override = True

    # Create timestamp ONCE at the start
    violation_timestamp = datetime.now()
    timestamp_str = violation_timestamp.strftime("%Y%m%d_%H%M%S")

    # Capture current frame from camera
    current_frame = yolo.latest_frame
    image_filename = None
    
    if current_frame and isinstance(current_frame, bytes):
        try:
            # Decode JPEG bytes to OpenCV frame
            nparr = np.frombuffer(current_frame, np.uint8)
            frame_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame_np is not None and frame_np.size > 0:
                # Save the image
                image_filename = f"override_{timestamp_str}.jpg"
                violations_dir = os.path.join(app.root_path, "static", "violations")
                os.makedirs(violations_dir, exist_ok=True)
                full_path = os.path.join(violations_dir, image_filename)
                
                success = cv2.imwrite(full_path, frame_np)
                if success:
                    print(f"✅ Manual override photo saved: {image_filename}")
                else:
                    print(f"❌ Failed to save override photo")
                    image_filename = None
            else:
                print("❌ Frame decode failed")
        except Exception as e:
            print(f"❌ Error capturing override photo: {e}")
            image_filename = None

    # Toggle relay state
    if relay_state == "OPEN":
        relay_state = "CLOSED"
        msg = "Manual override: gate CLOSED by supervisor"
        gate_action = "MANUAL_CLOSE"
    else:
        relay_state = "OPEN"
        msg = "Manual override: gate OPENED by supervisor"
        gate_action = "MANUAL_OPEN"

    # 🔧 NEW: Control actual hardware gate
    gate_controller.set_state(relay_state)

    # Get current PPE status for context
    ppe_status = yolo.latest_status.copy()
    
    # Use negative detections for more accurate violation tracking
    violations_detected = []
    if ppe_status.get('no_helmet'): violations_detected.append('no-helmet')
    if ppe_status.get('no_gloves'): violations_detected.append('no-gloves')
    if ppe_status.get('no_boots'): violations_detected.append('no-boots')
    
    # Fallback to missing items if no negative detections
    if not violations_detected:
        missing_items = []
        if not ppe_status.get('helmet'): missing_items.append('helmet')
        if not ppe_status.get('gloves'): missing_items.append('gloves')
        if not ppe_status.get('boots'): missing_items.append('boots')
    else:
        missing_items = [v.replace('no-', '') for v in violations_detected]
    
    # Determine PPE state for logging
    has_violation = ppe_status.get('has_violation', False)
    ppe_state = ppe_status.get('ppe_status', 'UNKNOWN')
    
    if has_violation:
        ppe_description = f"VIOLATION DETECTED: {', '.join(violations_detected)}"
    elif ppe_state == "OK":
        ppe_description = "COMPLETE PPE"
    else:
        ppe_description = "NO PERSON DETECTED"

    # Save to database
    violation = Violation(
        timestamp=violation_timestamp,
        violation_type='manual_override',
        missing_items=', '.join(missing_items) if missing_items else 'N/A',
        image_path=image_filename,
        gate_action=gate_action,
        operator_id=current_user.id,
        notes=f'{msg} by {current_user.username}. PPE Status: {ppe_description}'
    )
    db.session.add(violation)
    db.session.commit()

    return jsonify({
        "relay": relay_state,
        "override": override,
        "message": msg,
        "image_captured": image_filename is not None,
        "ppe_status": ppe_state,
        "violations": violations_detected if has_violation else []
    })

@app.route("/control/auto", methods=["POST"])
@login_required
def clear_override():
    """Resume automatic control + CONTROLS HARDWARE"""
    global override
    override = False
    
    # Get current PPE status
    ppe_status = yolo.latest_status.copy()
    
    # Check if there's an ACTUAL violation (negative classes detected)
    has_violation = ppe_status.get('has_violation', False)
    no_helmet = ppe_status.get('no_helmet', False)
    no_gloves = ppe_status.get('no_gloves', False)
    no_boots = ppe_status.get('no_boots', False)
    
    # Build list of actual violations
    violations = []
    if no_helmet: violations.append('helmet')
    if no_gloves: violations.append('gloves')
    if no_boots: violations.append('boots')
    
    image_filename = None
    violation_timestamp = datetime.now()
    
    # Only capture if there are ACTUAL violations detected
    if has_violation and violations:
        print(f"⚠️ Auto mode restored WITH active PPE violations: {violations}")
        image_filename = yolo.capture_gate_violation(
            gate_action='AUTO_MODE',
            reason=f'Auto control restored by {current_user.username} - Active violations: {", ".join(violations)}'
        )
        
        # Log the violation
        violation = Violation(
            timestamp=violation_timestamp,
            violation_type='auto_mode_restored',
            missing_items=', '.join(violations),
            image_path=image_filename,
            gate_action='AUTO_MODE',
            operator_id=current_user.id,
            notes=f'Auto control restored by {current_user.username} - Person detected without: {", ".join(violations)}'
        )
        db.session.add(violation)
        db.session.commit()
        print(f"📸 Violation captured and logged")
        
    else:
        # No actual violation (just background or complete PPE)
        ppe_state = "complete PPE" if ppe_status.get('ppe_status') == 'OK' else "no person detected"
        print(f"✅ Auto mode restored - {ppe_state} - NO violation logged")
        
        # Optional: Log the mode change without creating a violation record
        violation = Violation(
            timestamp=violation_timestamp,
            violation_type='auto_mode_restored',
            missing_items='N/A',
            image_path=None,
            gate_action='AUTO_MODE',
            operator_id=current_user.id,
            notes=f'Auto control restored by {current_user.username} - {ppe_state}'
        )
        db.session.add(violation)
        db.session.commit()
    
    return jsonify({
        "override": False,
        "message": "Automatic PPE control restored",
        "violation_detected": has_violation,
        "violations": violations if has_violation else []
    })

@app.route('/violations')
@login_required
def violations():
    """Supervisor violation review dashboard"""
    page = request.args.get('page', 1, type=int)
    violations = Violation.query.order_by(Violation.timestamp.desc()).paginate(
        page=page, per_page=12, error_out=False
    )
    return render_template('violations.html', violations=violations)

@app.route('/violations/<int:id>/notes', methods=['POST'])
@login_required
def add_violation_notes(id):
    """Save to supervisor_notes field"""
    violation = Violation.query.get_or_404(id)
    supervisor_notes = request.json.get('notes')
    
    print(f"📝 Saving supervisor notes for violation {id}: '{supervisor_notes}'")
    
    violation.supervisor_notes = supervisor_notes
    db.session.commit()
    
    print(f"✅ Supervisor notes saved successfully")
    
    return jsonify({
        'status': 'success',
        'violation_id': id,
        'notes': supervisor_notes
    })

@app.route('/violation-image/<path:filename>')
@login_required
def serve_violation_image(filename):
    """Serve violation photos from static/violations"""
    return send_from_directory('static/violations', filename)

@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            frame = yolo.latest_frame
            if frame is None:
                time.sleep(0.05)
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" +
                   frame +
                   b"\r\n")
    return Response(generate(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # Creates substation.db + tables automatically
    
    print("\n" + "="*50)
    print("🚀 SUBSTATION PPE MONITORING SYSTEM")
    print("="*50)
    print(f"📹 Camera: USB Webcam (index 0)")
    print(f"🤖 Model: YOLOv11 (models/best.pt)")
    print(f"🔧 Hardware: {'GPIO ENABLED' if gate_controller else 'SIMULATION MODE'}")
    print(f"🚪 Gate: {gate_controller.get_state()}")
    print("="*50 + "\n")
    
    # IMPORTANT: disable reloader so the camera is not opened twice
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)