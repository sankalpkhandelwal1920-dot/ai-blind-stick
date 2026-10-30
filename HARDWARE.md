# Hardware & Wiring

## Components

| Part | Role |
|------|------|
| Raspberry Pi 4 (4GB) | Main compute — vision, TTS, orchestration |
| Arduino Nano | Sensor hub — ultrasonic, buzzer, motor, button |
| OV5647 CSI camera | Vision input (fisheye) |
| HC-SR04 | Ultrasonic distance sensor |
| NEO-6M | GPS module (optional, for street names) |
| USB audio headset | Speech output |
| USB microphone | Voice input for custom-object learning |
| Vibration motor + buzzer | Obstacle alerts |
| Push button | Scene description (short press) / learn (long press) |
| 5V / 3A supply | Power — a solid supply is required to avoid CPU throttling |

## Division of labour

- The **Raspberry Pi** runs the camera, the detection models, text-to-speech, and
  the overall program (`src/blindstick.py`).
- The **Arduino Nano** runs an independent loop (`arduino/blindstick.ino`) that
  reads the ultrasonic sensor and drives the buzzer/motor on its own, and reports
  button presses and distance to the Pi over USB serial. This keeps close-range
  obstacle warnings working even when the vision pipeline is busy.

## Arduino Nano pin assignments

| Pin | Connection |
|-----|------------|
| D2  | Push button → GND (internal pull-up) |
| D5  | → 1kΩ → NPN transistor base → vibration motor (flyback diode across motor) |
| D6  | → 1kΩ → piezo buzzer → GND |
| D9  | HC-SR04 TRIG |
| D10 | HC-SR04 ECHO |
| 5V / GND | HC-SR04 power |

The Arduino is powered from the Pi over USB and communicates at 9600 baud.
It sends `DIST:<cm>` readings continuously and `BTN:DOWN` / `BTN:UP` on button events.

## Raspberry Pi connections

| Interface | Connection |
|-----------|------------|
| CSI port | OV5647 camera ribbon |
| USB | Arduino Nano (serial, `/dev/ttyUSB0`) |
| USB | Audio headset |
| USB | Microphone |
| UART (GPIO) | NEO-6M GPS — VCC 3.3V, GND, TX→GPIO, RX→GPIO |
| USB-C | 5V/3A power |

> **Power note:** the Pi 4 needs a genuine 5V/3A supply. Running from an
> underpowered source (e.g. a weak power bank) causes under-voltage throttling,
> which dramatically slows neural text-to-speech. Check with
> `vcgencmd get_throttled` — a trailing digit other than `0` means under-voltage.

## Camera orientation

If the camera is mounted upside down, set `CAMERA_FLIP_180 = True` in
`src/blindstick.py` to rotate frames in software instead of remounting.
