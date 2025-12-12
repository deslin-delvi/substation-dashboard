from flask import Flask, render_template, jsonify, Response
from datetime import datetime
import time

from utils.yolo_detector import YOLOProcessor  # NEW import


app = Flask(__name__)

# Start YOLO processor (update path if your weights are elsewhere)
yolo = YOLOProcessor(model_path="models/best.pt", camera_index=0)
yolo.start()

# You can later append real events from detections
mock_events = [
    {'time': '10:30:15', 'type': 'success', 'message': 'System started'},
    {'time': '10:25:42', 'type': 'warning', 'message': 'Waiting for camera frames'},
]


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/status')
def status():
    # Read latest YOLO status instead of fixed mock
    current = yolo.latest_status.copy()
    current['relay'] = 'OPEN'          # relay logic will come in Pi phase
    current['last_updated'] = datetime.now().strftime('%H:%M:%S')
    return jsonify(current)


@app.route('/events')
def events():
    return jsonify(mock_events)


@app.route('/control/relay', methods=['POST'])
def control_relay():
    # Still mock for now; real GPIO on Pi later
    # You can add relay state into a global or yolo.latest_status if needed
    return jsonify({'relay': 'TOGGLE_PENDING'})


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

