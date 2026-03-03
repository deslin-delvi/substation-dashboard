# hardware_controller.py
"""
Hardware control for Raspberry Pi 4 + SG90 Servo Motor
Supports direct servo control using pigpio DMA-based PWM.

Why pigpio instead of RPi.GPIO PWM:
  RPi.GPIO uses software PWM which is vulnerable to CPU scheduling.
  Under heavy load (YOLO inference + Flask + camera threads), the PWM
  signal loses timing accuracy → servo moves to wrong angles, jitters,
  or ignores commands entirely.
  pigpio uses DMA hardware timing — completely independent of CPU load,
  giving rock-solid 50Hz PWM even while YOLO is running.

LED Indicator via single-channel relay module (ADIY no-opto):
  - Relay OFF (NC) → RED  LED on  → Gate CLOSED
  - Relay ON  (NO) → GREEN LED on → Gate OPEN

Wiring:
  Pi GPIO 18  →  Servo Signal (orange wire)
  Pi GPIO 23  →  Relay IN
  Pi 3.3V     →  Relay VCC  ← MUST be 3.3V, not 5V (logic level match)
  Pi GND      →  Relay GND + Servo GND (shared via breadboard rail)
  Relay COM   →  GND
  Relay NC    →  220Ω → RED   LED (+) → 5V
  Relay NO    →  220Ω → GREEN LED (+) → 5V

Setup (run once on Pi):
  sudo apt install pigpio python3-pigpio
  sudo systemctl enable pigpiod
  sudo systemctl start pigpiod
"""

import time

# ── pigpio (DMA PWM — preferred) ─────────────────────────────────────────────
try:
    import pigpio
    PIGPIO_AVAILABLE = True
except ImportError:
    PIGPIO_AVAILABLE = False
    print("⚠️  pigpio not available — falling back to RPi.GPIO software PWM")
    print("    Fix: sudo apt install pigpio python3-pigpio && sudo systemctl start pigpiod")

# ── RPi.GPIO (fallback software PWM) ─────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("⚠️  RPi.GPIO not available — running in simulation mode")


# ─────────────────────────────────────────────────────────────────────────────
# LED Indicator via relay (NC = red/closed, NO = green/open)
# ─────────────────────────────────────────────────────────────────────────────
class LEDIndicator:
    """
    Controls RED/GREEN LEDs via a single relay module.
    Uses RPi.GPIO for the relay signal (no PWM needed, just digital out).

    ADIY no-opto relay (VCC on Pi 3.3V):
        GPIO LOW  → relay energised  (ON)  → NO contact → GREEN
        GPIO HIGH → relay de-energised(OFF) → NC contact → RED
        active_low = True
    """

    def __init__(self, relay_pin: int = 23, active_low: bool = True):
        self.relay_pin  = relay_pin
        self.active_low = active_low

        if not GPIO_AVAILABLE:
            print("⚠️  [LED] Simulation mode — no GPIO")
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        # initial=HIGH → relay OFF → NC → RED (safe closed default)
        GPIO.setup(self.relay_pin, GPIO.OUT, initial=GPIO.HIGH)
        self._relay_off()
        print(f"✅ LEDIndicator ready on GPIO{relay_pin} "
              f"({'active-low' if active_low else 'active-high'} relay)")

    def set_open(self):
        """Energise relay → NO closes → GREEN LED."""
        if not GPIO_AVAILABLE:
            print("[SIM] LED → GREEN (gate open)")
            return
        self._relay_on()
        print("🟢 LED: GREEN (gate open)")

    def set_closed(self):
        """De-energise relay → NC closes → RED LED."""
        if not GPIO_AVAILABLE:
            print("[SIM] LED → RED (gate closed)")
            return
        self._relay_off()
        print("🔴 LED: RED (gate closed)")

    def set_state(self, gate_state: str):
        if gate_state == "OPEN":
            self.set_open()
        else:
            self.set_closed()

    def both_off(self):
        if not GPIO_AVAILABLE:
            return
        self._relay_off()

    def _relay_on(self):
        signal = GPIO.LOW if self.active_low else GPIO.HIGH
        GPIO.output(self.relay_pin, signal)

    def _relay_off(self):
        signal = GPIO.HIGH if self.active_low else GPIO.LOW
        GPIO.output(self.relay_pin, signal)


# ─────────────────────────────────────────────────────────────────────────────
# Gate Controller — pigpio DMA PWM for servo
# ─────────────────────────────────────────────────────────────────────────────
class GateController:
    """
    Controls the servo gate using pigpio DMA PWM (CPU-load independent)
    and the relay LED indicator.
    """

    # SG90 pulse widths in microseconds (pigpio uses µs, not duty %)
    # Tune CLOSED_PW / OPEN_PW if your servo needs slight adjustment
    CLOSED_PW = 1150   # µs → ~45°  (gate closed)
    OPEN_PW   = 2150   # µs → ~135° (gate open)
    PWM_FREQ  = 50     # Hz — SG90 standard

    def __init__(self,
                 mode           = 'direct',
                 servo_pin      = 18,
                 relay_pin      = 23,
                 led_active_low = True):

        self.mode          = mode
        self.servo_pin     = servo_pin
        self.relay_pin     = relay_pin
        self.current_state = "CLOSED"
        self._pi           = None   # pigpio instance

        # LED relay (always uses RPi.GPIO digital out — no PWM needed)
        self.led = LEDIndicator(relay_pin, led_active_low)

        if PIGPIO_AVAILABLE:
            self._init_pigpio()
        elif GPIO_AVAILABLE:
            self._init_gpio_pwm()
        else:
            print("⚠️  Running in full SIMULATION mode")

        # Ensure LED matches boot state
        self.led.set_closed()
        print(f"✅ GateController ready — servo GPIO{servo_pin}, "
              f"relay GPIO{relay_pin}, "
              f"PWM={'pigpio DMA' if self._pi else 'RPi.GPIO software'}")

    # ── pigpio init ──────────────────────────────────────────────────────────
    def _init_pigpio(self):
        """Connect to pigpiod daemon and configure servo pin."""
        try:
            self._pi = pigpio.pi()
            if not self._pi.connected:
                print("❌ pigpiod daemon not running!")
                print("   Fix: sudo systemctl start pigpiod")
                self._pi = None
                if GPIO_AVAILABLE:
                    print("   Falling back to RPi.GPIO software PWM")
                    self._init_gpio_pwm()
                return

            self._pi.set_mode(self.servo_pin, pigpio.OUTPUT)
            # Set servo frequency
            self._pi.set_PWM_frequency(self.servo_pin, self.PWM_FREQ)
            # Start with pulse width 0 (no signal = no jitter at rest)
            self._pi.set_servo_pulsewidth(self.servo_pin, 0)
            self._current_pw = self.CLOSED_PW
            print(f"✅ pigpio DMA PWM initialised on GPIO{self.servo_pin}")

        except Exception as e:
            print(f"❌ pigpio init failed: {e}")
            self._pi = None
            if GPIO_AVAILABLE:
                self._init_gpio_pwm()

    # ── RPi.GPIO fallback ────────────────────────────────────────────────────
    def _init_gpio_pwm(self):
        """Fallback to RPi.GPIO software PWM if pigpio unavailable."""
        print("⚠️  Using RPi.GPIO software PWM — servo may jitter under load")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.servo_pin, GPIO.OUT)
        self.servo_pwm = GPIO.PWM(self.servo_pin, self.PWM_FREQ)
        self.servo_pwm.start(0)
        self._current_angle = 45

    # ── pulse width helpers (pigpio) ─────────────────────────────────────────
    def _set_pulsewidth(self, target_pw, step=35, step_delay=0.014):
        """
        Smoothly move servo to target pulse width (µs).
        step      : µs per step — smaller = smoother, slower
        step_delay: seconds between steps
        """
        if self._pi is None:
            return

        current_pw = self._current_pw
        if current_pw == target_pw:
            return

        direction = 1 if target_pw > current_pw else -1
        pw = current_pw

        while (direction == 1 and pw < target_pw) or \
              (direction == -1 and pw > target_pw):
            pw += direction * step
            pw  = max(500, min(2500, pw))  # clamp to safe SG90 range
            self._pi.set_servo_pulsewidth(self.servo_pin, pw)
            time.sleep(step_delay)

        # Final correction to exact target
        self._pi.set_servo_pulsewidth(self.servo_pin, target_pw)
        time.sleep(0.3)

        # Stop signal after move — eliminates resting jitter
        self._pi.set_servo_pulsewidth(self.servo_pin, 0)
        self._current_pw = target_pw

    # ── angle helpers (RPi.GPIO fallback) ────────────────────────────────────
    def _angle_to_duty(self, angle):
        return 2.5 + (angle / 180.0) * 10.0

    def _set_servo_angle(self, target_angle, step=3, step_delay=0.02):
        if not GPIO_AVAILABLE:
            print(f"[SIM] Servo → {target_angle}°")
            return

        current_angle = self._current_angle
        if current_angle < target_angle:
            angles = range(int(current_angle), int(target_angle) + 1, step)
        else:
            angles = range(int(current_angle), int(target_angle) - 1, -step)

        for angle in angles:
            self.servo_pwm.ChangeDutyCycle(self._angle_to_duty(angle))
            time.sleep(step_delay)

        self.servo_pwm.ChangeDutyCycle(self._angle_to_duty(target_angle))
        time.sleep(0.3)
        self.servo_pwm.ChangeDutyCycle(0)  # stop jitter
        self._current_angle = target_angle

    # ── gate control (public API) ─────────────────────────────────────────────
    def open_gate(self):
        """Move servo to open position and switch LED to GREEN."""
        if self.current_state == "OPEN":
            print("ℹ️  Gate already OPEN")
            return

        print("🟢 Opening gate...")
        if self._pi:
            self._set_pulsewidth(self.OPEN_PW)
        elif GPIO_AVAILABLE:
            self._set_servo_angle(135)

        self.current_state = "OPEN"
        self.led.set_open()
        print("✅ Gate OPENED")

    def close_gate(self):
        """Move servo to closed position and switch LED to RED."""
        if self.current_state == "CLOSED":
            print("ℹ️  Gate already CLOSED")
            return

        print("🔴 Closing gate...")
        if self._pi:
            self._set_pulsewidth(self.CLOSED_PW)
        elif GPIO_AVAILABLE:
            self._set_servo_angle(45)

        self.current_state = "CLOSED"
        self.led.set_closed()
        print("✅ Gate CLOSED")

    def set_state(self, state: str):
        if state == "OPEN":
            self.open_gate()
        elif state == "CLOSED":
            self.close_gate()
        else:
            print(f"⚠️  Unknown state: {state}")

    def get_state(self) -> str:
        return self.current_state

    def cleanup(self):
        """Release all hardware resources on shutdown."""
        print("🧹 Cleaning up hardware...")
        self.led.both_off()

        if self._pi:
            self._pi.set_servo_pulsewidth(self.servo_pin, 0)
            self._pi.stop()
            print("✅ pigpio released")
        elif GPIO_AVAILABLE:
            try:
                self.servo_pwm.stop()
            except Exception:
                pass
            GPIO.cleanup()
            print("✅ GPIO cleanup done")