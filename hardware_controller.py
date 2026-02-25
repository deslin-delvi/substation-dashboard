# hardware_controller.py
"""
Hardware control for Raspberry Pi 4 + SG90 Servo Motor
Supports direct servo control (no relay needed for servo).

LED Indicator via single-channel relay module:
  - Relay OFF (NC) → RED  LED on  → Gate CLOSED
  - Relay ON  (NO) → GREEN LED on → Gate OPEN

Wiring:
  Pi GPIO 17  →  Relay IN
  Pi 5V       →  Relay VCC
  Pi GND      →  Relay GND
  Relay COM   →  GND
  Relay NC    →  220Ω → RED   LED (+) → 5V
  Relay NO    →  220Ω → GREEN LED (+) → 5V
"""

import time
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("⚠️ RPi.GPIO not available - running in simulation mode")


# ──────────────────────────────────────────────────────────────
# LED Indicator via relay (NC = red/closed, NO = green/open)
# ──────────────────────────────────────────────────────────────
class LEDIndicator:
    """
    Uses one single-channel relay module to switch between
    a RED LED (gate closed) and a GREEN LED (gate open).

    Relay OFF → NC terminal active → RED LED lights up
    Relay ON  → NO terminal active → GREEN LED lights up

    Most relay modules are ACTIVE LOW:
        GPIO LOW  (0V) → Relay energised (ON)  → GREEN
        GPIO HIGH (3V) → Relay de-energised (OFF) → RED

    If your relay module is active-high (less common), set
    active_low=False when creating the object.
    """

    def __init__(self, relay_pin: int = 17, active_low: bool = True):
        self.relay_pin  = relay_pin
        self.active_low = active_low   # Most cheap relay boards are active-low

        if not GPIO_AVAILABLE:
            print("⚠️ [LED] Simulation mode — no GPIO")
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.relay_pin, GPIO.OUT, initial=GPIO.HIGH)  # HIGH = relay OFF for active-low

        # Start with relay OFF → RED LED on (gate assumed closed)
        self._relay_off()
        print(f"✅ LEDIndicator ready on GPIO{relay_pin} "
              f"({'active-low' if active_low else 'active-high'} relay)")

    # ── public helpers ───────────────────────────────────────
    def set_open(self):
        """Energise relay → NO closes → GREEN LED on."""
        if not GPIO_AVAILABLE:
            print("[SIM] LED → GREEN (gate open)")
            return
        self._relay_on()
        print("🟢 LED: GREEN (gate open)")

    def set_closed(self):
        """De-energise relay → NC closes → RED LED on."""
        if not GPIO_AVAILABLE:
            print("[SIM] LED → RED (gate closed)")
            return
        self._relay_off()
        print("🔴 LED: RED (gate closed)")

    def set_state(self, gate_state: str):
        """Pass "OPEN" or "CLOSED" to update the LED."""
        if gate_state == "OPEN":
            self.set_open()
        else:
            self.set_closed()

    def both_off(self):
        """
        De-energise relay on shutdown.
        NC path stays connected → RED LED stays on,
        which is the safe/closed default.
        """
        if not GPIO_AVAILABLE:
            return
        self._relay_off()

    # ── internal relay helpers ────────────────────────────────
    def _relay_on(self):
        """Energise the relay coil."""
        signal = GPIO.LOW if self.active_low else GPIO.HIGH
        GPIO.output(self.relay_pin, signal)

    def _relay_off(self):
        """De-energise the relay coil."""
        signal = GPIO.HIGH if self.active_low else GPIO.LOW
        GPIO.output(self.relay_pin, signal)


# ──────────────────────────────────────────────────────────────
# Gate Controller  (direct servo + relay LED indicator)
# ──────────────────────────────────────────────────────────────
class GateController:
    def __init__(self,
                 mode='direct',
                 servo_pin=18,
                 relay_pin=23,
                 led_active_low=True):
        """
        Initialize gate controller.

        Args:
            mode          : 'direct' — servo is driven directly by PWM (no relay for servo)
            servo_pin     : GPIO BCM pin for servo PWM signal   (default 18)
            relay_pin     : GPIO BCM pin for LED relay IN pin   (default 17)
            led_active_low: True for most cheap relay modules (active-low trigger)
        """
        self.mode      = mode
        self.servo_pin = servo_pin
        self.relay_pin = relay_pin
        self.current_state = "CLOSED"

        if not GPIO_AVAILABLE:
            print("⚠️ Running in SIMULATION mode")
            self.led = LEDIndicator(relay_pin, led_active_low)
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Servo setup
        self._setup_direct_servo()

        # LED relay setup
        self.led = LEDIndicator(relay_pin, led_active_low)

        print(f"✅ GateController ready — servo GPIO{servo_pin}, LED relay GPIO{relay_pin}")

        # Directly set LED to closed at boot.
        # We can't call close_gate() here because current_state starts as "CLOSED"
        # which triggers the early-return guard and skips the LED update entirely.
        self.led.set_closed()

    # ── servo setup ──────────────────────────────────────────
    def _setup_direct_servo(self):
        GPIO.setup(self.servo_pin, GPIO.OUT)
        self.servo_pwm = GPIO.PWM(self.servo_pin, 50)  # 50 Hz for SG90
        self.servo_pwm.start(0)
        self._current_angle = 45  # Start assumption matches closed position
        print(f"✅ Direct servo on GPIO{self.servo_pin}")

    #for speed adjustment of servo
    def _angle_to_duty(self, angle):
        """Convert angle (0–180°) to SG90 duty cycle (2.5–12.5%)."""
        return 2.5 + (angle / 180.0) * 10.0

    def _set_servo_angle(self, target_angle, step=3, step_delay=0.02):
        """
        Move servo to target angle in small steps to prevent
        overshoot and undershoot caused by software PWM inconsistency.

        Args:
            target_angle: destination angle in degrees
            step        : degrees per step (smaller = smoother, slower)
            step_delay  : seconds between steps
        """
        if not GPIO_AVAILABLE:
            print(f"[SIM] Servo → {target_angle}°")
            return

        current_angle = self._current_angle

        # Determine direction
        if current_angle < target_angle:
            angles = range(int(current_angle), int(target_angle) + 1, step)
        else:
            angles = range(int(current_angle), int(target_angle) - 1, -step)

        for angle in angles:
            duty = self._angle_to_duty(angle)
            self.servo_pwm.ChangeDutyCycle(duty)
            time.sleep(step_delay)

        # Final correction — ensure we land exactly on target
        self.servo_pwm.ChangeDutyCycle(self._angle_to_duty(target_angle))
        time.sleep(0.3)
        self.servo_pwm.ChangeDutyCycle(0)  # Stop signal to prevent jitter

        self._current_angle = target_angle

    # ── gate control ─────────────────────────────────────────
    def open_gate(self):
        """Servo → 90° and switch LED to GREEN."""
        if self.current_state == "OPEN":
            print("ℹ️ Gate already OPEN")
            return

        print("🟢 Opening gate...")
        self._set_servo_angle(135)
        self.current_state = "OPEN"
        self.led.set_open()             # Relay ON → GREEN LED
        print("✅ Gate OPENED")

    def close_gate(self):
        """Servo → 0° and switch LED to RED."""
        if self.current_state == "CLOSED":
            print("ℹ️ Gate already CLOSED")
            return

        print("🔴 Closing gate...")
        self._set_servo_angle(45)
        self.current_state = "CLOSED"
        self.led.set_closed()           # Relay OFF → RED LED
        print("✅ Gate CLOSED")

    def set_state(self, state: str):
        """Set gate by string: "OPEN" or "CLOSED"."""
        if state == "OPEN":
            self.open_gate()
        elif state == "CLOSED":
            self.close_gate()
        else:
            print(f"⚠️ Unknown state: {state}")

    def get_state(self) -> str:
        return self.current_state

    def cleanup(self):
        """Release GPIO on shutdown."""
        if not GPIO_AVAILABLE:
            return
        print("🧹 Cleaning up GPIO...")
        self.led.both_off()
        self.servo_pwm.stop()
        GPIO.cleanup()
        print("✅ GPIO cleanup done")


# ──────────────────────────────────────────────────────────────
# Quick test  (python hardware_controller.py)
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Gate + LED Relay Test ===\n")

    gate = GateController(
        mode='direct',
        servo_pin=18,       # Servo PWM pin
        relay_pin=17,       # Relay IN pin (controls LEDs)
        led_active_low=True # Most cheap relay boards need this
    )

    try:
        print("\nTesting gate + LED cycling...")

        gate.open_gate()        # GREEN LED should light
        time.sleep(2)

        gate.close_gate()       # RED LED should light
        time.sleep(2)

        gate.open_gate()        # GREEN
        time.sleep(2)

        gate.close_gate()       # RED

        print("\n✅ Test complete!")

    except KeyboardInterrupt:
        print("\n⚠️ Interrupted")

    finally:
        gate.cleanup()