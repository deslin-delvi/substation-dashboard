# utils/yolo_detector.py
from ultralytics import YOLO
import cv2
import threading
import time


class YOLOProcessor:
    def __init__(self, model_path="models/best.pt", camera_index=0):
        # Load model
        self.model = YOLO(model_path)

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
        names = self.model.names
        classes = [names[int(b.cls)] for b in results.boxes]
        helmet = "helmet" in classes
        vest = "vest" in classes or "safety vest" in classes
        gloves = "gloves" in classes or "glove" in classes

        ok = helmet and vest and gloves
        self.latest_status.update({
            "ppe_status": "OK" if ok else "NOT_OK",
            "helmet": helmet,
            "vest": vest,
            "gloves": gloves
        })

    def _draw_boxes(self, frame, results):
        for b in results.boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cls_id = int(b.cls)
            conf = float(b.conf)
            label = f"{self.model.names[cls_id]} {conf:.2f}"
            color = (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame, label, (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2
            )

    def loop(self):
        self.running = True
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            """
            # YOLO inference
            results = self.model(frame, verbose=False)[0]
            self._process_results(results)
            self._draw_boxes(frame, results)
            """
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
