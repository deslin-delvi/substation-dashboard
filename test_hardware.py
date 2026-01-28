#!/usr/bin/env python3
"""
test_hardware.py - Hardware test script for Raspberry Pi setup
Tests camera, servo, and relay (if connected)
"""

import sys
import time

def test_camera():
    """Test USB webcam connection"""
    print("\n" + "="*50)
    print("TEST 1: USB Webcam")
    print("="*50)
    
    try:
        import cv2
        
        # Try to open camera
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("❌ FAILED: Cannot open camera at index 0")
            print("💡 Try: ls /dev/video* to see available cameras")
            return False
        
        # Read a frame
        ret, frame = cap.read()
        
        if not ret:
            print("❌ FAILED: Cannot read frame from camera")
            cap.release()
            return False
        
        height, width = frame.shape[:2]
        print(f"✅ PASSED: Camera opened successfully")
        print(f"   Resolution: {width}x{height}")
        print(f"   FPS: {cap.get(cv2.CAP_PROP_FPS)}")
        
        cap.release()
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

def test_gpio():
    """Test GPIO availability"""
    print("\n" + "="*50)
    print("TEST 2: GPIO Library")
    print("="*50)
    
    try:
        import RPi.GPIO as GPIO
        print("✅ PASSED: RPi.GPIO library available")
        return True
    except ImportError:
        print("❌ FAILED: RPi.GPIO not installed")
        print("💡 Install: sudo apt install python3-rpi.gpio")
        return False

def test_servo(interactive=True):
    """Test servo motor control"""
    print("\n" + "="*50)
    print("TEST 3: Servo Motor (GPIO 18)")
    print("="*50)
    
    try:
        from hardware_controller import GateController
        
        if not interactive:
            print("⏭️  SKIPPED: Run with --interactive for servo test")
            return None
        
        print("\n⚠️  WARNING: Servo will move!")
        response = input("Is servo connected to GPIO 18? (y/n): ").lower()
        
        if response != 'y':
            print("⏭️  SKIPPED: User chose not to test")
            return None
        
        print("\n🔧 Initializing gate controller...")
        gate = GateController(mode='direct', servo_pin=18)
        
        print("\n📍 Testing servo movements...")
        print("   Moving to CLOSED position (0°)...")
        gate.close_gate()
        time.sleep(2)
        
        print("   Moving to OPEN position (90°)...")
        gate.open_gate()
        time.sleep(2)
        
        print("   Moving back to CLOSED position...")
        gate.close_gate()
        time.sleep(1)
        
        gate.cleanup()
        print("\n✅ PASSED: Servo control working")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

def test_yolo():
    """Test YOLOv11 installation"""
    print("\n" + "="*50)
    print("TEST 4: YOLOv11 (Ultralytics)")
    print("="*50)
    
    try:
        from ultralytics import YOLO
        print("✅ PASSED: Ultralytics library available")
        
        # Check if model file exists
        import os
        if os.path.exists("models/best.pt"):
            print("✅ Model file found: models/best.pt")
        else:
            print("⚠️  WARNING: Model file not found at models/best.pt")
            print("💡 Copy your trained model to: models/best.pt")
        
        return True
        
    except ImportError:
        print("❌ FAILED: Ultralytics not installed")
        print("💡 Install: pip install ultralytics")
        return False

def test_flask():
    """Test Flask and dependencies"""
    print("\n" + "="*50)
    print("TEST 5: Flask Dependencies")
    print("="*50)
    
    results = []
    
    packages = [
        'flask',
        'flask_login',
        'flask_bcrypt',
        'flask_sqlalchemy'
    ]
    
    for package in packages:
        try:
            __import__(package)
            print(f"✅ {package}")
            results.append(True)
        except ImportError:
            print(f"❌ {package}")
            results.append(False)
    
    if all(results):
        print("\n✅ PASSED: All Flask dependencies installed")
        return True
    else:
        print("\n❌ FAILED: Some dependencies missing")
        print("💡 Install: pip install flask flask-login flask-bcrypt flask-sqlalchemy")
        return False

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("  RASPBERRY PI HARDWARE TEST SUITE")
    print("  Substation PPE Monitoring System")
    print("="*60)
    
    interactive = '--interactive' in sys.argv or '-i' in sys.argv
    
    if interactive:
        print("\n🔧 Running in INTERACTIVE mode (will test servo movement)")
    else:
        print("\n📋 Running in SAFE mode (no servo movement)")
        print("💡 Use --interactive flag to test servo motor")
    
    # Run tests
    results = {
        'Camera': test_camera(),
        'GPIO': test_gpio(),
        'Servo': test_servo(interactive),
        'YOLOv11': test_yolo(),
        'Flask': test_flask()
    }
    
    # Summary
    print("\n" + "="*60)
    print("  TEST SUMMARY")
    print("="*60)
    
    for test_name, result in results.items():
        if result is True:
            status = "✅ PASSED"
        elif result is False:
            status = "❌ FAILED"
        else:
            status = "⏭️  SKIPPED"
        
        print(f"{test_name:20} {status}")
    
    print("\n" + "="*60)
    
    # Check if all critical tests passed
    critical_tests = ['Camera', 'GPIO', 'YOLOv11', 'Flask']
    critical_passed = all(results[t] for t in critical_tests if results[t] is not None)
    
    if critical_passed:
        print("✅ System ready to run!")
        print("\n🚀 Next steps:")
        print("   1. Ensure model file at: models/best.pt")
        print("   2. Create database: python3 create_admin.py")
        print("   3. Start application: python3 app.py")
    else:
        print("❌ System not ready - fix failed tests above")
    
    print("="*60 + "\n")

if __name__ == "__main__":
    main()