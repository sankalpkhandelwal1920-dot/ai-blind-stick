# AI-Powered Assistive Blind Stick

A wearable navigation aid for visually impaired users, built around a Raspberry Pi.
A camera watches the road ahead; a custom-trained YOLOv8 model detects vehicles,
people, and obstacles common to Indian streets; and the device announces what it
sees in **Hindi** through an earpiece. An ultrasonic sensor provides close-range
obstacle warnings, and the user can teach the device new objects by voice.

> Built as an independent engineering project. The object detector was fine-tuned
> from scratch on the India Driving Dataset (IDD), not an off-the-shelf model.

---

## What it does

- **Road object detection** — a YOLOv8 model fine-tuned on Indian roads calls out
  cars, buses, autorickshaws, motorcycles, trucks, riders, and pedestrians.
- **Hindi speech output** — detections are spoken aloud through an earpiece using
  a neural text-to-speech voice (Piper), with a fast fallback voice for low-power
  conditions.
- **Close-range obstacle warning** — an ultrasonic sensor on an Arduino triggers a
  buzzer/vibration independently of the camera, as a non-AI safety layer.
- **Voice-taught custom objects** — hold the button, show an object to the camera,
  and speak its name; the device learns it and recognises it later.
- **Scene description** — a short button press announces everything currently in view.
- **(Optional) GPS street names** — reverse-geocoded road names announced in Hindi.

## How it works

The software runs four cooperating layers:

| Layer | Role | Model / Hardware |
|-------|------|------------------|
| 1 | Primary detection (Indian roads) | YOLOv8 fine-tuned on IDD (15 classes) |
| 2 | Fallback detection (general) | YOLOv8 pretrained on COCO (80 classes) |
| 3 | Custom object learning | YOLOv8 backbone embeddings + nearest-neighbour match |
| 4 | Location → street name | NEO-6M GPS + reverse geocoding |

Plus a non-ML safety layer: the Arduino reads an HC-SR04 ultrasonic sensor and
drives a buzzer and vibration motor on its own, so close-obstacle warnings work
even if the vision pipeline is busy.

## The model

The detector was fine-tuned from `yolov8s` on the **India Driving Dataset (IDD)**
(~31k training images, 15 classes). Training ran for 60 epochs on an NVIDIA A100.

**Results (validation mAP@0.5):**

| Class | mAP@0.5 |
|-------|:-------:|
| bus | 0.72 |
| autorickshaw | 0.71 |
| car | 0.68 |
| motorcycle | 0.67 |
| truck | 0.64 |
| rider | 0.57 |
| person | 0.53 |
| bicycle | 0.46 |
| **overall** | **0.457** |

The safety-critical vehicle classes (car, bus, autorickshaw, motorcycle) all score
above 0.65, which is the range that matters for a navigation aid. Rare classes
(animal, tempo, traffic light) score lower, as expected with few training examples.

An earlier `yolov8n` (nano) model reached 0.388 overall; moving to `yolov8s`
lifted every safety-critical class by 5–13 points. See
[`docs/MODEL.md`](docs/MODEL.md) for the full nano-vs-small comparison and the
reasoning behind the architecture choice.

> **Trained weights are not stored in this repo** (they are large binaries).
> Download `best.pt` from the [Releases](../../releases) page.

## Hardware

- Raspberry Pi 4 (4GB) — main compute
- Arduino Nano — sensor hub (ultrasonic, buzzer, vibration motor, button)
- OV5647 CSI camera (fisheye)
- HC-SR04 ultrasonic sensor
- NEO-6M GPS module
- USB audio headset
- USB microphone (for voice-taught objects)
- 5V/3A power supply

Full wiring and pin assignments are in [`docs/HARDWARE.md`](docs/HARDWARE.md).

## Repository layout

```
.
├── src/              Raspberry Pi program (Python)
├── arduino/          Arduino Nano sketch (sensor hub)
├── diagnostics/      Standalone test scripts
├── docs/             Setup, hardware, model, and training notes
├── assets/           Demo images and screenshots
└── README.md
```

## Quick start

1. Flash Raspberry Pi OS and wire the hardware ([`docs/HARDWARE.md`](docs/HARDWARE.md)).
2. Install dependencies ([`docs/SETUP.md`](docs/SETUP.md)).
3. Download `best.pt` from [Releases](../../releases) to `/home/pi/`.
4. Upload `arduino/blindstick.ino` to the Arduino Nano.
5. Run:
   ```bash
   python3 src/blindstick.py
   ```

## Limitations (honest notes)

- `yolov8s` is more accurate than `nano` but heavier; on a Pi 4 it trades real-time
  speed for accuracy. The repo keeps both so the speed/accuracy choice is explicit.
- Neural TTS (Piper) is slow on an under-powered Pi; the device must run on a solid
  5V/3A supply to avoid CPU throttling, and falls back to a faster voice if needed.
- GPS needs a clear view of the sky and does not get a fix indoors.
- Custom-object learning uses detection-backbone embeddings, so it works best on
  visually distinct objects.

## License

MIT — see [LICENSE](LICENSE).

# Source

`blindstick.py` is the main Raspberry Pi program.

> ⚠️ **Replace this file with the current version from your Pi before publishing.**
> The copy committed here may be behind the live version running on the device.
> On the Pi:  `scp pi@blindstick.local:/home/pi/blindstick.py .`  then overwrite this file.

## Configuration

Key flags live in the `CONFIGURATION` block at the top of the file:

- `IDD_MODEL` / `COCO_MODEL` — paths to the detection weights
- `USE_IDD_MODEL` — use the fine-tuned Indian-roads model (True) vs COCO only
- `IDD_CONF` / `COCO_CONF` — per-model confidence thresholds
- `CAMERA_FLIP_180` — rotate frames if the camera is mounted upside down
- `ENABLE_CUSTOM_LEARNING` — voice-taught custom objects
- `LANGUAGE` — `"hi"` for Hindi, `"en"` for English
