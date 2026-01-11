from flask import Flask, render_template, jsonify, Response, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import time
import os
import cv2
import numpy as np

# Local imports
from utils.yolo_detector import YOLOProcessor
from models import db, User, Violation

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

# Start YOLO processor (update path if your weights are elsewhere)
yolo = YOLOProcessor(model_path="models/best.pt", camera_index=0)
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
    """
    global relay_state, override
    current = yolo.latest_status.copy()

    if not override:
        if current.get("ppe_status") == "OK":
            relay_state = "OPEN"
        else:
            relay_state = "CLOSED"

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
    """Manual override - logs supervisor action + CAPTURES CURRENT FRAME"""
    global relay_state, override
    override = True

    # 🔧 FIX: Create timestamp ONCE at the start
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

    # Get current PPE status for context
    ppe_status = yolo.latest_status.copy()
    missing_items = []
    if not ppe_status.get('helmet'): missing_items.append('helmet')
    if not ppe_status.get('vest'): missing_items.append('vest')
    if not ppe_status.get('gloves'): missing_items.append('gloves')

    # 🔧 FIX: Use the SAME timestamp for database record
    violation = Violation(
        timestamp=violation_timestamp,  # Use the same datetime object
        violation_type='manual_override',
        missing_items=', '.join(missing_items) if missing_items else 'N/A',
        image_path=image_filename,
        gate_action=gate_action,
        operator_id=current_user.id,
        notes=f'{msg} by {current_user.username}. PPE Status: {"COMPLETE" if not missing_items else "INCOMPLETE"}'
    )
    db.session.add(violation)
    db.session.commit()

    return jsonify({
        "relay": relay_state,
        "override": override,
        "message": msg,
        "image_captured": image_filename is not None
    })

@app.route("/control/auto", methods=["POST"])
@login_required
def clear_override():
    global override
    override = False
    
    # 🔧 FIX: Create timestamp ONCE at the start
    violation_timestamp = datetime.now()
    timestamp_str = violation_timestamp.strftime("%Y%m%d_%H%M%S")
    
    # Capture photo when returning to auto mode
    current_frame = yolo.latest_frame
    image_filename = None
    
    if current_frame and isinstance(current_frame, bytes):
        try:
            nparr = np.frombuffer(current_frame, np.uint8)
            frame_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame_np is not None and frame_np.size > 0:
                image_filename = f"auto_restore_{timestamp_str}.jpg"
                violations_dir = os.path.join(app.root_path, "static", "violations")
                os.makedirs(violations_dir, exist_ok=True)
                full_path = os.path.join(violations_dir, image_filename)
                
                success = cv2.imwrite(full_path, frame_np)
                if success:
                    print(f"✅ Auto mode restore photo saved: {image_filename}")
                else:
                    image_filename = None
        except Exception as e:
            print(f"❌ Error capturing auto restore photo: {e}")
    
    # 🔧 FIX: Use the SAME timestamp for database record
    violation = Violation(
        timestamp=violation_timestamp,  # Use the same datetime object
        violation_type='auto_mode_restored',
        image_path=image_filename,
        gate_action='AUTO_MODE',
        operator_id=current_user.id,
        notes=f'Automatic PPE control restored by {current_user.username}'
    )
    db.session.add(violation)
    db.session.commit()
    
    return jsonify({
        "override": False,
        "message": "Automatic PPE control restored",
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
    """🔧 FIX: Save to supervisor_notes field, not notes"""
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
        db.create_all()  # ← Creates substation.db + tables automatically
    # IMPORTANT: disable reloader so the camera is not opened twice
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)