from flask import Flask, render_template, jsonify, Response
from datetime import datetime
import time

from utils.yolo_detector import YOLOProcessor


app = Flask(__name__)

# Start YOLO processor (update path if your weights are elsewhere)
yolo = YOLOProcessor(model_path="models/best.pt", camera_index=0)
yolo.start()

relay_state = "CLOSED"   # gate starts closed
override = False         # manual override flag

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/status')
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
def events():
    # Last 10 events from YOLO
    return jsonify(yolo.events[-10:])


@app.route('/control/relay', methods=['POST'])
def control_relay():
    """
    Manual override:
      - Sets override = True.
      - Toggles gate OPEN/CLOSED regardless of PPE.
      - Supervisor can both open and close the gate.
    """
    global relay_state, override
    override = True

    if relay_state == "OPEN":
        relay_state = "CLOSED"
        msg = "Manual override: gate CLOSED by supervisor"
    else:
        relay_state = "OPEN"
        msg = "Manual override: gate OPENED by supervisor"

    return jsonify({
        "relay": relay_state,
        "override": override,
        "message": msg,
    })

@app.route("/control/auto", methods=["POST"])
def clear_override():
    global override
    override = False
    return jsonify({
        "override": False,
        "message": "Automatic PPE control restored",
    })

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
    # IMPORTANT: disable reloader so the camera is not opened twice
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

