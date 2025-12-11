import cv2

cap = cv2.VideoCapture(0)  # try 0 first
print("Opened:", cap.isOpened())

while True:
    ret, frame = cap.read()
    if not ret:
        print("No frame")
        break
    cv2.imshow("cam", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
