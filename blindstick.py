#!/usr/bin/env python3
"""
blindstick.py  —  AI Assistive Blind Stick (Raspberry Pi 4 main program)
=========================================================================

  Layer 1  : YOLOv8 fine-tuned on IDD  -> Indian road objects (best.pt)
  Layer 2  : YOLOv8 COCO               -> 80 everyday objects (yolov8n.pt)
  Layer 3  : MobileNetV2 + KNN         -> user-taught custom objects (optional)
  Layer 4  : NEO-6M GPS + Nominatim    -> Hindi street-name announcements
  Safety   : HC-SR04 (via Arduino)     -> obstacle buzzer + vibration

  Scene button (read from Arduino over serial):
    - short press (< 3 s)  -> describe the whole scene now
    - long  press (>= 3 s) -> learning mode: teach a new object by voice

  Output : Hindi text-to-speech through the Bluetooth earpiece
  Voice in: USB microphone (for naming objects during learning)

Run:        python3 blindstick.py
Auto-start: add 'python3 /home/pi/blindstick.py &' before 'exit 0' in /etc/rc.local

NOTE ON MEMORY:
  On a Raspberry Pi 4 (4GB) this runs comfortably — all layers, including
  custom learning, load with room to spare (~2.5GB used of 4GB). No swap needed.
  On a 2GB Pi, TensorFlow may fail to load; if it does, Layer 3 (custom learning)
  auto-disables and everything else keeps working. You can also set
  ENABLE_CUSTOM_LEARNING = False below to skip Layer 3 entirely.
"""

import os
import time
import json
import wave
import queue
import pickle
import shutil
import threading
import subprocess

import numpy as np
import cv2
import serial
import requests

# ──────────────────────────────────────────────────────────────────────────
# CONFIGURATION  — edit these if your setup differs
# ──────────────────────────────────────────────────────────────────────────
IDD_MODEL      = "/home/pi/best.pt"            # your trained Indian-roads model
COCO_MODEL     = "/home/pi/yolov8n.pt"         # stock COCO model
MEMORY_FILE    = "/home/pi/object_memory.pkl"  # custom object embeddings
LABELS_FILE    = "/home/pi/object_labels.json" # custom object names

ARDUINO_PORT   = "/dev/ttyUSB0"                # Arduino Nano (sensor hub)
GPS_PORT       = "/dev/ttyAMA3"                # NEO-6M on UART3 (GPIO4/5)
ARDUINO_BAUD   = 9600
GPS_BAUD       = 9600

CAM_SIZE       = (640, 480)
IDD_CONF       = 0.55          # half-trained road model: only trust confident hits (raise to mute, lower as it improves)
COCO_CONF      = 0.40          # everyday-object model: lower so real objects aren't discarded
CUSTOM_CONF    = 0.75
SPEAK_COOLDOWN = 5.0
GPS_INTERVAL   = 30.0
LONG_PRESS_SEC = 3.0
OBSTACLE_CM    = 70

LANGUAGE                = "hi"     # 'hi' = Hindi, 'en' = English
ENABLE_CUSTOM_LEARNING  = False    # TensorFlow fails on Python 3.13 ('imp' removed); keep off for now
CAMERA_FLIP_180         = False    # camera is mounted upright; set True only if it's physically upside down
USE_IDD_MODEL           = True     # off for indoor testing (half-trained model hallucinates road objects);
                                   # turn ON outdoors once IDD training is finished

# Text-to-speech: Piper neural TTS (natural Hindi voice, runs offline on the Pi)
PIPER_BIN     = "piper"            # if not found under systemd, use full path e.g. /home/pi/.local/bin/piper
PIPER_MODEL   = "/home/pi/piper_voices/hi_IN-pratham-medium.onnx"
PIPER_WAV     = "/tmp/blindstick_say.wav"
# Bluetooth earpieces sleep between clips and clip the first word on wake-up.
# Padding each clip with silence lets the earpiece wake during the silence.
TTS_LEAD_SILENCE  = 0.8    # seconds of silence before speech (raise if still clipped)
TTS_TRAIL_SILENCE = 0.3    # seconds of silence after speech

# ──────────────────────────────────────────────────────────────────────────
# HINDI TRANSLATION DICTIONARY  (offline)
# ──────────────────────────────────────────────────────────────────────────
HINDI = {
    "person": "व्यक्ति", "rider": "सवार", "car": "कार", "truck": "ट्रक",
    "bus": "बस", "motorcycle": "मोटरसाइकिल", "bicycle": "साइकिल",
    "autorickshaw": "ऑटो रिक्शा", "tempo": "टेम्पो", "animal": "जानवर",
    "traffic sign": "ट्रैफिक साइन", "billboard": "होर्डिंग",
    "vehicle fallback": "वाहन", "obstacle": "रुकावट", "traffic light": "ट्रैफिक लाइट",
    "dog": "कुत्ता", "cow": "गाय", "cat": "बिल्ली", "bottle": "बोतल",
    "chair": "कुर्सी", "bench": "बेंच", "backpack": "बैग", "handbag": "हैंडबैग",
    "umbrella": "छाता", "cell phone": "फोन", "book": "किताब", "cup": "कप",
    "stop sign": "स्टॉप साइन", "fire hydrant": "हाइड्रेंट", "bird": "पक्षी",
}
HINDI_POS = {"ahead": "आगे", "close": "पास में", "very close": "बहुत पास"}

def hindi_name(label):
    """Full Hindi name of a label (no position word)."""
    return HINDI.get(label, label) if LANGUAGE == "hi" else label

def to_hindi(label, position="ahead"):
    """Hindi label + position (falls back to English)."""
    if LANGUAGE == "en":
        return f"{label} {position}"
    return f"{HINDI.get(label, label)} {HINDI_POS.get(position, position)}"

# ──────────────────────────────────────────────────────────────────────────
# TEXT-TO-SPEECH  — one worker thread owns the engine (thread-safe).
# PriorityQueue: 0 = urgent (obstacle), 1 = normal (detection), 2 = low (GPS).
# The sequence counter breaks ties so tuples never compare the text strings.
# ──────────────────────────────────────────────────────────────────────────
speak_q   = queue.PriorityQueue()
_seq      = 0
_seq_lock = threading.Lock()

def speak(text, priority=1):
    global _seq
    with _seq_lock:
        _seq += 1
        seq = _seq
    speak_q.put((priority, seq, text))

def _pad_wav(path, lead=TTS_LEAD_SILENCE, trail=TTS_TRAIL_SILENCE):
    """Prepend/append silence to a WAV so a sleeping Bluetooth earpiece wakes
    during the silence instead of swallowing the first word."""
    try:
        with wave.open(path, "rb") as w:
            p = w.getparams()
            data = w.readframes(w.getnframes())
        frame = p.sampwidth * p.nchannels
        head = b"\x00" * (int(p.framerate * lead) * frame)
        tail = b"\x00" * (int(p.framerate * trail) * frame)
        with wave.open(path, "wb") as w:
            w.setparams(p)
            w.writeframes(head + data + tail)
    except Exception:
        pass

def _tts_worker():
    """Speak queued text with Piper (natural neural voice). Falls back to
    espeak-ng if Piper or its model isn't available, so the device always talks."""
    piper_path = shutil.which(PIPER_BIN) or PIPER_BIN
    use_piper  = os.path.exists(PIPER_MODEL) and shutil.which(PIPER_BIN) is not None
    if use_piper:
        print("TTS: using Piper voice", os.path.basename(PIPER_MODEL))
    else:
        print("TTS: Piper unavailable -> falling back to espeak-ng")

    while True:
        _, _, text = speak_q.get()
        try:
            if use_piper:
                # Piper reads text on stdin and writes a WAV; aplay sends it to
                # the default audio sink (your Bluetooth earpiece).
                subprocess.run(
                    [piper_path, "--model", PIPER_MODEL, "--output_file", PIPER_WAV],
                    input=text.encode("utf-8"),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                _pad_wav(PIPER_WAV)
                subprocess.run(
                    ["aplay", "-q", PIPER_WAV],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            else:
                voice = "hi" if LANGUAGE == "hi" else "en"
                subprocess.run(
                    ["espeak-ng", "-v", voice, "-s", "130", text],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except Exception as e:
            print("TTS error:", e)
        speak_q.task_done()

# ──────────────────────────────────────────────────────────────────────────
# COOLDOWN  — don't repeat the same label every frame
# ──────────────────────────────────────────────────────────────────────────
_last_spoken = {}
_cool_lock   = threading.Lock()

def speak_once(label, priority=1):
    now = time.time()
    with _cool_lock:
        if label in _last_spoken and now - _last_spoken[label] < SPEAK_COOLDOWN:
            return
        _last_spoken[label] = now
    speak(label, priority)

# ──────────────────────────────────────────────────────────────────────────
# CUSTOM OBJECT MEMORY  (Layer 3 storage)
# ──────────────────────────────────────────────────────────────────────────
stored_embeddings = []
stored_labels     = []

def load_memory():
    global stored_embeddings, stored_labels
    if os.path.exists(MEMORY_FILE) and os.path.exists(LABELS_FILE):
        try:
            with open(MEMORY_FILE, "rb") as f:
                stored_embeddings = pickle.load(f)
            with open(LABELS_FILE, "r") as f:
                stored_labels = json.load(f)
            print(f"Loaded {len(set(stored_labels))} custom objects from memory")
        except Exception as e:
            print("Could not load custom memory:", e)

def save_memory():
    try:
        with open(MEMORY_FILE, "wb") as f:
            pickle.dump(stored_embeddings, f)
        with open(LABELS_FILE, "w") as f:
            json.dump(stored_labels, f)
    except Exception as e:
        print("Could not save custom memory:", e)

# ──────────────────────────────────────────────────────────────────────────
# SHARED STATE
# ──────────────────────────────────────────────────────────────────────────
pending_action = None
action_lock    = threading.Lock()
running        = True

# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════
def main():
    global pending_action, running

    threading.Thread(target=_tts_worker, daemon=True).start()
    speak("ब्लाइंड स्टिक शुरू हो रहा है" if LANGUAGE == "hi" else "Blind stick starting")

    load_memory()

    # ── Camera ──
    from picamera2 import Picamera2
    try:
        picam2 = Picamera2()
        picam2.configure(picam2.create_preview_configuration(
            main={"size": CAM_SIZE, "format": "RGB888"}))
        picam2.start()
        time.sleep(3)
        print("Camera ready")
    except Exception as e:
        print("FATAL: camera failed to start (check the CSI ribbon):", e)
        speak("कैमरा शुरू नहीं हुआ" if LANGUAGE == "hi" else "Camera failed to start")
        time.sleep(3)          # let the message finish speaking before exit
        return

    def grab_frame():
        """Capture a frame and guarantee 3 channels.
        NOTE: picamera2 'RGB888' returns a BGR-ordered array (a documented
        quirk), which matches what Ultralytics YOLO expects for numpy input."""
        f = picam2.capture_array()
        if f.ndim == 3 and f.shape[2] == 4:
            f = f[:, :, :3]
        if CAMERA_FLIP_180:
            f = cv2.rotate(f, cv2.ROTATE_180)
        return f

    # ── YOLO models (graceful) ──
    from ultralytics import YOLO
    idd_model = None
    try:
        if USE_IDD_MODEL and os.path.exists(IDD_MODEL):
            idd_model = YOLO(IDD_MODEL)
    except Exception as e:
        print("IDD model load failed:", e)

    coco_model = None
    try:
        coco_model = YOLO(COCO_MODEL) if os.path.exists(COCO_MODEL) else YOLO("yolov8n.pt")
    except Exception as e:
        print("COCO model load failed:", e)

    if idd_model is None and coco_model is None:
        speak("कोई मॉडल नहीं मिला" if LANGUAGE == "hi" else "No detection model found")
        print("FATAL: no YOLO model available.")
    print(f"Models loaded — idd:{idd_model is not None} coco:{coco_model is not None}")

    # ── MobileNetV2 feature extractor (Layer 3) — OPTIONAL ──
    feat = None
    preprocess = None
    if ENABLE_CUSTOM_LEARNING:
        try:
            import tensorflow as tf
            feat = tf.keras.applications.MobileNetV2(
                include_top=False, pooling="avg",
                input_shape=(224, 224, 3), weights="imagenet")
            feat.trainable = False
            preprocess = tf.keras.applications.mobilenet_v2.preprocess_input
            print("MobileNetV2 loaded (custom learning enabled)")
        except Exception as e:
            print("Custom learning disabled (TensorFlow/MobileNet load failed):", e)
            feat = None
            preprocess = None

    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.preprocessing import normalize

    knn = [None]
    def rebuild_knn():
        if stored_embeddings and len(set(stored_labels)) >= 1:
            k = min(5, len(stored_embeddings))
            knn[0] = KNeighborsClassifier(n_neighbors=k, metric="cosine")
            knn[0].fit(stored_embeddings, stored_labels)
        else:
            knn[0] = None
    rebuild_knn()

    def embed(frame):
        # MobileNet expects RGB; our frame is BGR-ordered -> convert.
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(rgb, (224, 224)).astype(np.float32)
        img = preprocess(img)
        vec = feat.predict(np.expand_dims(img, 0), verbose=0)[0]
        return normalize([vec])[0]

    def recognise_custom(frame):
        if feat is None or knn[0] is None:
            return None
        v = embed(frame)
        dist, _ = knn[0].kneighbors([v])
        best = dist[0][0]                       # cosine distance (0 = identical)
        if best < (1 - CUSTOM_CONF):
            return knn[0].predict([v])[0], round((1 - best) * 100)
        return None

    # ── Speech recognition (USB mic) ──
    import speech_recognition as sr
    recogniser = sr.Recognizer()

    def listen_name():
        try:
            with sr.Microphone() as src:
                speak("वस्तु का नाम बोलिए" if LANGUAGE == "hi" else "Say the object name")
                recogniser.adjust_for_ambient_noise(src, duration=0.5)
                audio = recogniser.listen(src, timeout=6, phrase_time_limit=4)
            lang = "hi-IN" if LANGUAGE == "hi" else "en-IN"
            return recogniser.recognize_google(audio, language=lang).strip()
        except sr.WaitTimeoutError:
            speak("कोई आवाज़ नहीं सुनी" if LANGUAGE == "hi" else "No name heard")
        except sr.UnknownValueError:
            speak("समझ नहीं आया" if LANGUAGE == "hi" else "Could not understand")
        except sr.RequestError:
            speak("इंटरनेट नहीं है" if LANGUAGE == "hi" else "No internet")
        except Exception as e:
            print("STT error:", e)
        return None

    def learning_mode():
        if feat is None:
            speak("कस्टम सीखना उपलब्ध नहीं" if LANGUAGE == "hi"
                  else "Custom learning unavailable")
            return
        speak("सीखने का मोड। वस्तु को कैमरे के सामने रखिए" if LANGUAGE == "hi"
              else "Learning mode. Hold the object in front of the camera")
        time.sleep(2)
        embs = []
        for _ in range(10):                 # 10 frames, spaced so you can rotate the object
            embs.append(embed(grab_frame()))
            time.sleep(0.25)
        name = listen_name()
        if not name:
            return
        for e in embs:
            stored_embeddings.append(e)
            stored_labels.append(name)
        save_memory()
        rebuild_knn()
        speak(f"{name} याद कर लिया" if LANGUAGE == "hi" else f"Saved {name}")
        print("Learned:", name)

    def scene_description():
        frame = grab_frame()
        found = set()
        if idd_model:
            for b in idd_model(frame, conf=IDD_CONF, verbose=False)[0].boxes:
                found.add(idd_model.names[int(b.cls[0])])
        if coco_model:
            for b in coco_model(frame, conf=COCO_CONF, verbose=False)[0].boxes:
                found.add(coco_model.names[int(b.cls[0])])
        if found:
            words  = [hindi_name(o) for o in found]      # FULL name, no position word
            joiner = " , " if LANGUAGE == "hi" else ", "
            prefix = "मुझे दिख रहा है: " if LANGUAGE == "hi" else "I can see: "
            speak(prefix + joiner.join(words))
        else:
            c = recognise_custom(frame)
            if c:
                speak(c[0])
            else:
                speak("कुछ नहीं दिखा" if LANGUAGE == "hi" else "Nothing recognised")

    # ── Serial reader thread (Arduino) ──
    def serial_thread():
        global pending_action
        try:
            ard = serial.Serial(ARDUINO_PORT, ARDUINO_BAUD, timeout=1)
        except Exception as e:
            print("Arduino not connected:", e)
            return
        press_time = None
        while running:
            try:
                line = ard.readline().decode("utf-8", "ignore").strip()
            except Exception:
                continue
            if not line:
                continue
            if line == "BTN:DOWN":
                press_time = time.time()
            elif line == "BTN:UP" and press_time is not None:
                held = time.time() - press_time
                press_time = None
                with action_lock:
                    pending_action = "learn" if held >= LONG_PRESS_SEC else "scene"
            elif line.startswith("DIST:"):
                try:
                    d = int(line.split(":")[1])
                except (ValueError, IndexError):
                    continue
                if 0 < d < OBSTACLE_CM:
                    pos = "very close" if d < 30 else "close"
                    speak_once(to_hindi("obstacle", pos), priority=0)

    # ── GPS thread (Layer 4) ──
    def gps_thread():
        try:
            import pynmea2
            gps = serial.Serial(GPS_PORT, GPS_BAUD, timeout=1)
        except Exception as e:
            print("GPS not available:", e)
            return
        last_announce = 0
        while running:
            try:
                line = gps.readline().decode("ascii", "ignore").strip()
            except Exception:
                continue
            if not line.startswith("$"):
                continue
            try:
                msg = pynmea2.parse(line)
            except Exception:
                continue
            lat = getattr(msg, "latitude", 0)
            lon = getattr(msg, "longitude", 0)
            if not lat or not lon:
                continue
            now = time.time()
            if now - last_announce < GPS_INTERVAL:
                continue
            last_announce = now
            try:
                url = ("https://nominatim.openstreetmap.org/reverse"
                       f"?lat={lat}&lon={lon}&format=json&zoom=17")
                r = requests.get(url, headers={"User-Agent": "blindstick"}, timeout=8).json()
                addr = r.get("address", {})
                road = addr.get("road") or addr.get("suburb") or addr.get("neighbourhood")
                if road:
                    speak(f"आप {road} पर हैं" if LANGUAGE == "hi"
                          else f"You are on {road}", priority=2)
            except Exception:
                pass   # no internet -> skip; GPS fix still fine

    threading.Thread(target=serial_thread, daemon=True).start()
    threading.Thread(target=gps_thread,    daemon=True).start()

    speak("तैयार है" if LANGUAGE == "hi" else "Ready")
    print("Blind stick running. Long-press the button to teach an object.")

    # ── MAIN DETECTION LOOP ──
    frame_count = 0
    try:
        while running:
            try:
                frame = grab_frame()
                frame_count += 1

                with action_lock:
                    action = pending_action
                    pending_action = None
                if action == "scene":
                    scene_description()
                elif action == "learn":
                    learning_mode()

                detected = False
                if idd_model:
                    for b in idd_model(frame, conf=IDD_CONF, verbose=False)[0].boxes:
                        label = idd_model.names[int(b.cls[0])]
                        x1, y1, x2, y2 = b.xyxy[0].tolist()
                        pos = "close" if (y2 - y1) > 200 else "ahead"
                        speak_once(to_hindi(label, pos))
                        detected = True

                if not detected and coco_model:
                    for b in coco_model(frame, conf=COCO_CONF, verbose=False)[0].boxes:
                        label = coco_model.names[int(b.cls[0])]
                        x1, y1, x2, y2 = b.xyxy[0].tolist()
                        pos = "close" if (y2 - y1) > 200 else "ahead"
                        speak_once(to_hindi(label, pos))
                        detected = True

                if not detected and feat is not None and frame_count % 10 == 0:
                    c = recognise_custom(frame)
                    if c and c[1] > 80:
                        speak_once(c[0])

            except Exception as e:
                print("loop error:", e)
                time.sleep(0.1)

    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        running = False
        try:
            picam2.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
