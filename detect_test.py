#!/usr/bin/env python3
"""
detect_test.py — detection diagnostic for the blind stick.

Captures ONE frame, saves it as a JPG (so you can check focus/lighting),
then prints everything both YOLO models detect, with confidence scores,
at a low threshold so you see even weak detections.

Run:  python3 /home/pi/detect_test.py
Then copy /home/pi/camera_test.jpg to your laptop to view what the camera saw:
      (on laptop)  scp pi@blindstick.local:/home/pi/camera_test.jpg .
"""
import os
import time
import cv2
from picamera2 import Picamera2
from ultralytics import YOLO

IDD_MODEL  = "/home/pi/best.pt"
COCO_MODEL = "/home/pi/yolov8n.pt"
CONF = 0.25                       # low on purpose, to reveal weak detections

picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "RGB888"}))
picam2.start()
time.sleep(2)
frame = picam2.capture_array()
if frame.ndim == 3 and frame.shape[2] == 4:
    frame = frame[:, :, :3]
picam2.stop()

cv2.imwrite("/home/pi/camera_test.jpg", frame)
print(f"Saved camera view -> /home/pi/camera_test.jpg   shape={frame.shape}")
print("Copy it to your laptop to check the image is clear and well-lit.\n")

print("=== IDD model (best.pt — your trained road model) ===")
idd = YOLO(IDD_MODEL)
r = idd(frame, conf=CONF, verbose=False)[0]
if len(r.boxes) == 0:
    print("  (nothing detected)")
for b in r.boxes:
    print(f"  {idd.names[int(b.cls[0])]:22s} conf={float(b.conf[0]):.2f}")

print("\n=== COCO model (yolov8n.pt — 80 everyday objects) ===")
coco = YOLO(COCO_MODEL) if os.path.exists(COCO_MODEL) else YOLO("yolov8n.pt")
r = coco(frame, conf=CONF, verbose=False)[0]
if len(r.boxes) == 0:
    print("  (nothing detected)")
for b in r.boxes:
    print(f"  {coco.names[int(b.cls[0])]:22s} conf={float(b.conf[0]):.2f}")

print("\nDone. Tell Claude what each model listed, and check the saved image.")
