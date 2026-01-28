# hardware_controller.py
"""
Hardware control for Raspberry Pi 4 + SG90 Servo Motor
Supports both direct servo control and relay-based control
"""

import time
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("⚠️ RPi.GPIO not available - running in simulation mode")

class GateController:
    def __init__(self, mode='direct', servo_pin=18, relay_pin=17):
        """
        Initialize gate controller
        
        Args:
            mode: 'direct' for direct servo control, 'relay' for relay+servo
            servo_pin: GPIO pin for servo signal (BCM numbering)
            relay_pin: GPIO pin for relay control (BCM numbering)
        """
        self.mode = mode
        self.servo_pin = servo_pin
        self.relay_pin = relay_pin
        self.current_state = "CLOSED"
        
        if not GPIO_AVAILABLE:
            print("⚠️ Running in SIMULATION mode (no actual GPIO control)")
            return
        
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        if mode == 'direct':
            self._setup_direct_servo()
        elif mode == 'relay':
            self._setup_relay_servo()
        else:
            raise ValueError("Mode must be 'direct' or 'relay'")
        
        print(f"✅ Gate controller initialized in {mode.upper()} mode")
        self.close_gate()  # Start with gate closed
    
    def _setup_direct_servo(self):
        """Setup for direct servo control (RECOMMENDED)"""
        GPIO.setup(self.servo_pin, GPIO.OUT)
        
        # Create PWM instance: 50Hz for SG90 servo
        self.servo_pwm = GPIO.PWM(self.servo_pin, 50)
        self.servo_pwm.start(0)  # Start with 0% duty cycle
        print(f"✅ Direct servo control on GPIO {self.servo_pin}")
    
    def _setup_relay_servo(self):
        """Setup for relay + servo control"""
        # Relay control
        GPIO.setup(self.relay_pin, GPIO.OUT)
        GPIO.output(self.relay_pin, GPIO.LOW)  # Relay OFF initially
        
        # Servo signal control
        GPIO.setup(self.servo_pin, GPIO.OUT)
        self.servo_pwm = GPIO.PWM(self.servo_pin, 50)
        self.servo_pwm.start(0)
        print(f"✅ Relay+Servo control on GPIO {self.relay_pin} (relay) & {self.servo_pin} (servo)")
    
    def _set_servo_angle(self, angle):
        """
        Set servo to specific angle (0-180 degrees)
        
        SG90 Servo specs:
        - 0° = 2.5% duty cycle (0.5ms pulse)
        - 90° = 7.5% duty cycle (1.5ms pulse)
        - 180° = 12.5% duty cycle (2.5ms pulse)
        """
        if not GPIO_AVAILABLE:
            print(f"[SIM] Servo angle: {angle}°")
            return
        
        # Convert angle to duty cycle
        duty_cycle = 2.5 + (angle / 180.0) * 10.0
        
        self.servo_pwm.ChangeDutyCycle(duty_cycle)
        time.sleep(0.5)  # Wait for servo to reach position
        self.servo_pwm.ChangeDutyCycle(0)  # Stop sending signal to prevent jitter
    
    def open_gate(self):
        """Open the gate (servo to 90°)"""
        if self.current_state == "OPEN":
            print("ℹ️ Gate already OPEN")
            return
        
        print("🟢 Opening gate...")
        
        if self.mode == 'relay' and GPIO_AVAILABLE:
            GPIO.output(self.relay_pin, GPIO.HIGH)  # Turn relay ON
            time.sleep(0.1)  # Small delay for relay to activate
        
        self._set_servo_angle(90)  # Open position (adjust angle as needed)
        self.current_state = "OPEN"
        print("✅ Gate OPENED")
    
    def close_gate(self):
        """Close the gate (servo to 0°)"""
        if self.current_state == "CLOSED":
            print("ℹ️ Gate already CLOSED")
            return
        
        print("🔴 Closing gate...")
        
        self._set_servo_angle(0)  # Closed position (adjust angle as needed)
        
        if self.mode == 'relay' and GPIO_AVAILABLE:
            time.sleep(0.1)
            GPIO.output(self.relay_pin, GPIO.LOW)  # Turn relay OFF
        
        self.current_state = "CLOSED"
        print("✅ Gate CLOSED")
    
    def set_state(self, state):
        """Set gate state by string ("OPEN" or "CLOSED")"""
        if state == "OPEN":
            self.open_gate()
        elif state == "CLOSED":
            self.close_gate()
        else:
            print(f"⚠️ Invalid state: {state}")
    
    def get_state(self):
        """Get current gate state"""
        return self.current_state
    
    def cleanup(self):
        """Cleanup GPIO resources"""
        if not GPIO_AVAILABLE:
            return
        
        print("🧹 Cleaning up GPIO...")
        self.servo_pwm.stop()
        GPIO.cleanup()
        print("✅ GPIO cleanup complete")


# Test function
if __name__ == "__main__":
    print("=== Gate Controller Test ===\n")
    
    # Create controller (change mode to 'relay' if using relay)
    gate = GateController(mode='direct', servo_pin=18, relay_pin=17)
    
    try:
        print("\n1. Testing gate movements...")
        
        # Open gate
        gate.open_gate()
        time.sleep(2)
        
        # Close gate
        gate.close_gate()
        time.sleep(2)
        
        # Open again
        gate.open_gate()
        time.sleep(2)
        
        # Close again
        gate.close_gate()
        
        print("\n✅ Test complete!")
        
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted by user")
    
    finally:
        gate.cleanup()