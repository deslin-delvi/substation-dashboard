from ultralytics import YOLO

model = YOLO("models/best.pt")

# Run detection on all images in the folder and save annotated outputs
model.predict(source="test_images", save=True)
