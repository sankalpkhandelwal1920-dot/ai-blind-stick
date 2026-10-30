/*
 * blindstick.ino  —  Arduino Nano sensor hub for the AI Blind Stick
 * ==================================================================
 *
 * Responsibilities:
 *   - Read the HC-SR04 ultrasonic sensor (Segment E)
 *   - Drive the piezo buzzer (Segment E) and vibration motor (Segment B grip)
 *     AUTONOMOUSLY based on distance, for the fastest possible reaction
 *   - Read the scene button (Segment B grip) and report press/release to the Pi
 *   - Stream distance readings to the Raspberry Pi over USB serial
 *
 * Serial protocol (Arduino -> Pi, 9600 baud):
 *     "BTN:DOWN"   button pressed
 *     "BTN:UP"     button released
 *     "DIST:<cm>"  measured distance in centimetres ( -1 = no echo )
 *
 * Wiring (matches the circuit diagram):
 *     D2  -> scene button  (other leg to GND, INPUT_PULLUP)
 *     D5  -> vibration motor base of NPN transistor (via 1K resistor)
 *     D6  -> piezo buzzer  (via 1K resistor)
 *     D9  -> HC-SR04 TRIG
 *     D10 -> HC-SR04 ECHO
 *     5V / GND shared with HC-SR04
 *
 * Upload: Arduino IDE -> Board "Arduino Nano".
 * If upload fails, set Processor -> "ATmega328P (Old Bootloader)".
 */

const int BTN_PIN    = 2;    // scene button  (INPUT_PULLUP)
const int MOTOR_PIN  = 5;    // vibration motor (through NPN transistor)
const int BUZZER_PIN = 6;    // piezo buzzer (through 1K resistor)
const int TRIG_PIN   = 9;    // HC-SR04 trigger
const int ECHO_PIN   = 10;   // HC-SR04 echo

const int WARN_NEAR = 50;    // start pulsing warning below this (cm)
const int WARN_CRIT = 20;    // continuous warning below this (cm)

bool          lastBtn      = HIGH;
unsigned long lastDistSend = 0;
unsigned long beepCycle    = 0;

void setup() {
  Serial.begin(9600);
  pinMode(BTN_PIN,    INPUT_PULLUP);
  pinMode(MOTOR_PIN,  OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(TRIG_PIN,   OUTPUT);
  pinMode(ECHO_PIN,   INPUT);
  digitalWrite(MOTOR_PIN, LOW);
  noTone(BUZZER_PIN);

  // startup confirmation: short beep + buzz so you KNOW the Arduino booted
  tone(BUZZER_PIN, 1500, 120);
  digitalWrite(MOTOR_PIN, HIGH);
  delay(120);
  digitalWrite(MOTOR_PIN, LOW);
  Serial.println("READY");
}

// Returns distance in cm, or -1 if no echo within range.
long readDistanceCM() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long dur = pulseIn(ECHO_PIN, HIGH, 30000UL);  // 30 ms timeout (~5 m)
  if (dur == 0) return -1;
  return (long)(dur * 0.0343 / 2.0);
}

void loop() {
  unsigned long now = millis();

  // ---- scene button (report edges to the Pi) ----
  bool btn = digitalRead(BTN_PIN);
  if (btn != lastBtn) {
    if (btn == LOW) Serial.println("BTN:DOWN");   // pressed (pull-up -> LOW)
    else            Serial.println("BTN:UP");     // released
    lastBtn = btn;
    delay(40);                                    // debounce
  }

  // ---- distance ----
  long d = readDistanceCM();
  if (now - lastDistSend > 200) {                 // ~5 readings/sec to the Pi
    Serial.print("DIST:");
    Serial.println(d);
    lastDistSend = now;
  }

  // ---- autonomous obstacle alert (buzzer + vibration), non-blocking ----
  if (d > 0 && d < WARN_NEAR) {
    if (d < WARN_CRIT) {
      // critical: solid buzz + solid vibration
      digitalWrite(MOTOR_PIN, HIGH);
      tone(BUZZER_PIN, 2500);
    } else {
      // pulse faster the closer the obstacle is (interval 120-600 ms)
      int interval = map(d, WARN_CRIT, WARN_NEAR, 120, 600);
      unsigned long phase = now - beepCycle;
      if (phase < 70) {                           // "on" phase ~70 ms
        digitalWrite(MOTOR_PIN, HIGH);
        tone(BUZZER_PIN, 2000);
      } else if (phase < (unsigned long)interval) { // "off" phase
        digitalWrite(MOTOR_PIN, LOW);
        noTone(BUZZER_PIN);
      } else {
        beepCycle = now;                          // restart the pulse cycle
      }
    }
  } else {
    // clear path: everything off
    digitalWrite(MOTOR_PIN, LOW);
    noTone(BUZZER_PIN);
  }
}
