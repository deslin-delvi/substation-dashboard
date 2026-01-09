from flask import Flask, render_template, jsonify, Response, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import time
import os
import cv2

# Local imports
from utils.yolo_detector import YOLOProcessor
from models import db, User, Violation  # You'll need to create models.py

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
    """Manual override - logs supervisor action to database"""
    global relay_state, override
    override = True

    if relay_state == "OPEN":
        relay_state = "CLOSED"
        msg = "Manual override: gate CLOSED by supervisor"
    else:
        relay_state = "OPEN"
        msg = "Manual override: gate OPENED by supervisor"

    # Log manual override to database
    violation = Violation(
        violation_type='manual_override',
        gate_action='MANUAL_OVERRIDE',
        operator_id=current_user.id,
        notes=f'{msg} by {current_user.username}'
    )
    db.session.add(violation)
    db.session.commit()

    return jsonify({
        "relay": relay_state,
        "override": override,
        "message": msg,
    })

@app.route("/control/auto", methods=["POST"])
@login_required
def clear_override():
    global override
    override = False
    
    # Log restoration of auto mode
    violation = Violation(
        violation_type='auto_mode_restored',
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
    violation = Violation.query.get_or_404(id)
    violation.notes = request.json.get('notes')
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/violations/<path:image_path>')
@login_required
def serve_violation_image(image_path):
    """Securely serve violation images"""
    if not image_path.startswith('violations/'):
        return "Unauthorized", 403
    try:
        return send_from_directory('static', image_path)
    except FileNotFoundError:
        return "Image not found", 404

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

