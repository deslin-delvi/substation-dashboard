from flask import Flask, render_template, jsonify
from datetime import datetime

app = Flask(__name__)

# Mock data (will be replaced by YOLO in Phase 3)
mock_status = {
    'ppe_status': 'OK',
    'relay': 'OPEN',
    'helmet': True,
    'vest': True,
    'gloves': True,
    'last_updated': datetime.now().strftime('%H:%M:%S')
}

mock_events = [
    {'time': '10:30:15', 'type': 'success', 'message': 'Worker entered with full PPE'},
    {'time': '10:25:42', 'type': 'warning', 'message': 'Missing helmet detected'},
    {'time': '10:20:11', 'type': 'success', 'message': 'Gate opened - PPE verified'},
]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def status():
    mock_status['last_updated'] = datetime.now().strftime('%H:%M:%S')
    return jsonify(mock_status)

@app.route('/events')
def events():
    return jsonify(mock_events)

@app.route('/control/relay', methods=['POST'])
def control_relay():
    # Mock relay control (GPIO in Phase 3)
    mock_status['relay'] = 'CLOSED' if mock_status['relay'] == 'OPEN' else 'OPEN'
    return jsonify({'relay': mock_status['relay']})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
