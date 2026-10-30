# Raspberry Pi Setup Guide — AI Blind Stick

Complete setup for a **Raspberry Pi 4 (4GB)** running **Raspberry Pi OS Bookworm Lite (64-bit)**.
Work through these stages in order. Most commands run **on the Pi** (after you SSH in).
A few run **on your laptop** — those are clearly marked.

---

## ⚠️ Before you start — two things to check

**1. Your username.** Raspberry Pi OS Bookworm makes you choose a username when imaging.
This guide and the code assume your username is **`pi`** (so files live in `/home/pi/`).
If you chose a different username, either re-image with username `pi`, OR change every
`/home/pi/` path in `blindstick.py` (the CONFIG block at the top) to `/home/YOURNAME/`.

**2. The Pi and your laptop must be on the same network** — your phone hotspot (the WiFi
you set during imaging). The Pi gets internet through the hotspot too.

---

## Stage 1 — Connect to the Pi over SSH

Power the Pi from the power bank or a charger. Wait ~60 seconds for it to boot and join
your hotspot. Then, on your **laptop** (PowerShell on Windows):

```bash
ssh pi@blindstick.local
```

Enter the password you set during imaging (you won't see characters as you type — normal).

If `blindstick.local` doesn't resolve, find the Pi's IP in your phone's hotspot
"connected devices" list and use that instead:
```bash
ssh pi@192.168.x.x
```

Everything from here runs **on the Pi** unless marked "(laptop)".

---

## Stage 2 — Update the system

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

The Pi will disconnect when it reboots. Wait a minute, then SSH back in.

---

## Stage 3 — Enable the camera and the GPS UART

The NEO-6M GPS uses UART3 (GPIO 4/5). Enable it by editing the boot config.
On Bookworm the file is at **`/boot/firmware/config.txt`**:

```bash
sudo nano /boot/firmware/config.txt
```

Add these lines at the bottom:
```
# NEO-6M GPS on UART3 (GPIO4=TX, GPIO5=RX) -> /dev/ttyAMA3
dtoverlay=uart3

# Camera (auto-detect is usually on; uncomment if your camera isn't found)
#dtoverlay=ov5647
camera_auto_detect=1
```

Save with `Ctrl+O`, `Enter`, exit with `Ctrl+X`. Then reboot:
```bash
sudo reboot
```

SSH back in after it restarts.

---

## Stage 4 — Install system packages

These are needed for the camera, audio output, microphone input, and speech:

```bash
sudo apt install -y \
    python3-picamera2 \
    espeak-ng \
    python3-pyaudio portaudio19-dev \
    flac \
    libatlas-base-dev python3-dev \
    bluetooth bluez pulseaudio-module-bluetooth
```

Notes on a few of these:
- **python3-picamera2** — install via apt, NOT pip (it needs system libcamera libraries).
- **espeak-ng** — the offline Hindi text-to-speech engine.
- **flac** — required by the speech recognizer used for naming custom objects.
- **portaudio19-dev / python3-pyaudio** — microphone input.

---

## Stage 5 — Install the Python libraries

Bookworm protects the system Python, so use `--break-system-packages` (simplest for a
single-purpose device like this). This step is the longest — TensorFlow and PyTorch are
large and may take 15–30 minutes on the Pi.

```bash
pip install --break-system-packages \
    ultralytics \
    pyttsx3 \
    pyserial \
    pynmea2 \
    requests \
    SpeechRecognition \
    scikit-learn \
    tensorflow
```

If TensorFlow fails to install or is too slow, you can skip it — the program will run
without custom-object learning. Just install everything except `tensorflow`, and set
`ENABLE_CUSTOM_LEARNING = False` in `blindstick.py`.

---

## Stage 6 — Copy your files onto the Pi

Run these on your **laptop** (from the folder where `best.pt` and `blindstick.py` are saved):

```bash
# (laptop)
scp best.pt       pi@blindstick.local:/home/pi/
scp blindstick.py pi@blindstick.local:/home/pi/
```

Back **on the Pi**, confirm they arrived:
```bash
ls -lh /home/pi/best.pt /home/pi/blindstick.py
```

---

## Stage 7 — Pair the Bluetooth earpiece

Put the earpiece in pairing mode, then on the Pi:

```bash
bluetoothctl
```

Inside the `bluetoothctl` prompt, type these one at a time:
```
power on
agent on
default-agent
scan on
```

Wait for your earpiece to appear with its MAC address (like `AA:BB:CC:DD:EE:FF`), then:
```
scan off
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
exit
```

`trust` makes it auto-reconnect on every boot. Set it as the default audio output:
```bash
# list audio outputs, find your earpiece, set it as default sink
pactl list short sinks
pactl set-default-sink <bluez_sink_name_from_the_list>
```

---

## Stage 8 — Test each component (do this BEFORE running the full program)

**Camera:**
```bash
rpicam-hello --list-cameras
```
You should see your OV5647 listed. If it says "no cameras available", reseat the CSI
ribbon (check it's the right way round and fully clicked in on both ends).

**Audio + Hindi speech:**
```bash
espeak-ng -v hi "नमस्ते, मैं तैयार हूँ"
```
You should hear Hindi through the earpiece.

**Arduino (after you've uploaded the sketch — Stage 9):**
```bash
ls /dev/ttyUSB*
```
Should show `/dev/ttyUSB0`. To watch live data:
```bash
cat /dev/ttyUSB0
```
Wave your hand near the HC-SR04 — you'll see `DIST:` values change and `BTN:DOWN`/`BTN:UP`
when you press the button. Press `Ctrl+C` to stop.

**GPS:**
```bash
cat /dev/ttyAMA3
```
You'll see `$GPGGA`, `$GPRMC` lines streaming. (Latitude/longitude stay empty until the
module gets a satellite fix — that needs a clear view of the sky and can take a few minutes
the first time.) Press `Ctrl+C` to stop.

---

## Stage 9 — Upload the Arduino sketch (laptop)

This is done from the **Arduino IDE on your laptop**, not the Pi:

1. Open `blindstick.ino` in the Arduino IDE.
2. Connect the Arduino Nano to your laptop by USB.
3. Tools → Board → **Arduino Nano**.
4. Tools → Port → select the COM port that appeared.
5. Click **Upload**.
6. If upload fails with a sync error, set Tools → Processor → **ATmega328P (Old Bootloader)**
   and upload again (most clone Nanos need this).

When it flashes successfully you'll hear a short startup beep and feel a buzz — that's the
confirmation built into the sketch. Then move the Arduino's USB cable to the Pi.

---

## Stage 10 — Run the program

On the Pi:
```bash
python3 /home/pi/blindstick.py
```

You should hear "ब्लाइंड स्टिक शुरू हो रहा है" then "तैयार है" once everything loads.
Watch the SSH output for any warnings (model loaded, camera ready, etc.).
Press `Ctrl+C` to stop.

---

## Stage 11 — Auto-start on boot (do this LAST, after testing works)

Once the program runs correctly by hand, make it start automatically when the Pi powers on.
Create a service:

```bash
sudo nano /etc/systemd/system/blindstick.service
```

Paste this (change `pi` if your username is different):
```ini
[Unit]
Description=AI Blind Stick
After=multi-user.target sound.target bluetooth.target network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi
ExecStart=/usr/bin/python3 /home/pi/blindstick.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save and exit, then enable it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable blindstick.service
sudo systemctl start blindstick.service
```

Check it's running / see its output:
```bash
sudo systemctl status blindstick.service
journalctl -u blindstick.service -f
```

If Bluetooth audio doesn't work under the service (a common quirk because audio runs in the
user session), just keep running it manually with `python3 /home/pi/blindstick.py` for now —
auto-start is a convenience, not a requirement.

---

## Troubleshooting quick reference

| Problem | Fix |
|---|---|
| `blindstick.local` won't connect | Use the Pi's IP from your hotspot device list |
| "no cameras available" | Reseat the CSI ribbon, check `camera_auto_detect=1` |
| No `/dev/ttyAMA3` | Confirm `dtoverlay=uart3` is in `/boot/firmware/config.txt`, reboot |
| No `/dev/ttyUSB0` | Check the Arduino USB cable; try `dmesg | tail` after plugging in |
| No Hindi audio | Re-pair Bluetooth; check `pactl list short sinks` and set default |
| "Custom learning disabled" | TensorFlow didn't load — fine on 4GB, reinstall it or set ENABLE_CUSTOM_LEARNING=False |
| GPS lat/lon always empty | Needs clear sky view; first fix can take several minutes |
| Permission denied on serial | `sudo usermod -aG dialout pi` then reboot |

---

## The recommended testing order (don't skip this)

1. **Camera alone** — `rpicam-hello --list-cameras`
2. **Audio alone** — `espeak-ng -v hi "नमस्ते"`
3. **Arduino + sensors alone** — `cat /dev/ttyUSB0`, watch DIST/BTN
4. **GPS alone** — `cat /dev/ttyAMA3`, watch NMEA lines
5. **Everything together** — `python3 /home/pi/blindstick.py`

Testing each piece on its own means when something doesn't work, you know exactly which
part to check. Only wire/test the full system after each component passes on its own.
