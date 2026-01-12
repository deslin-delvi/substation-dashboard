"""
Delete specific violations by ID, last N violations, or by criteria
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Violation

def delete_by_ids(violation_ids, confirm=True):
    """Delete violations by specific IDs"""
    with app.app_context():
        violations = Violation.query.filter(Violation.id.in_(violation_ids)).all()
        
        if not violations:
            print(f"❌ No violations found with IDs: {violation_ids}")
            return
        
        print(f"\n📋 Found {len(violations)} violation(s) to delete:")
        for v in violations:
            print(f"  ID {v.id}: {v.timestamp} - {v.violation_type} - {v.image_path}")
        
        if confirm:
            response = input("\n⚠️  Delete these violations? (yes/no): ")
            if response.lower() != 'yes':
                print("❌ Cancelled")
                return
        
        # Delete images
        deleted_images = 0
        for v in violations:
            if v.image_path:
                image_path = os.path.join(app.root_path, 'static', 'violations', v.image_path)
                if os.path.exists(image_path):
                    os.remove(image_path)
                    deleted_images += 1
                    print(f"  🗑️  Deleted image: {v.image_path}")
            
            db.session.delete(v)
        
        db.session.commit()
        print(f"\n✅ Deleted {len(violations)} violation(s) and {deleted_images} image(s)")


def delete_last_n(n, confirm=True):
    """Delete the last N violations (most recent)"""
    with app.app_context():
        violations = Violation.query.order_by(Violation.timestamp.desc()).limit(n).all()
        
        if not violations:
            print(f"❌ No violations found")
            return
        
        print(f"\n📋 Last {len(violations)} violation(s) to delete:")
        for v in violations:
            print(f"  ID {v.id}: {v.timestamp} - {v.violation_type} - {v.image_path}")
        
        if confirm:
            response = input(f"\n⚠️  Delete these {len(violations)} violations? (yes/no): ")
            if response.lower() != 'yes':
                print("❌ Cancelled")
                return
        
        # Delete images
        deleted_images = 0
        for v in violations:
            if v.image_path:
                image_path = os.path.join(app.root_path, 'static', 'violations', v.image_path)
                if os.path.exists(image_path):
                    os.remove(image_path)
                    deleted_images += 1
                    print(f"  🗑️  Deleted image: {v.image_path}")
            
            db.session.delete(v)
        
        db.session.commit()
        print(f"\n✅ Deleted {len(violations)} violation(s) and {deleted_images} image(s)")


def delete_by_type(violation_type, confirm=True):
    """Delete violations by type (e.g., 'manual_override', 'gate_action')"""
    with app.app_context():
        violations = Violation.query.filter_by(violation_type=violation_type).all()
        
        if not violations:
            print(f"❌ No violations found with type: {violation_type}")
            return
        
        print(f"\n📋 Found {len(violations)} violation(s) with type '{violation_type}':")
        for v in violations:
            print(f"  ID {v.id}: {v.timestamp} - {v.image_path}")
        
        if confirm:
            response = input(f"\n⚠️  Delete all {len(violations)} violations? (yes/no): ")
            if response.lower() != 'yes':
                print("❌ Cancelled")
                return
        
        # Delete images
        deleted_images = 0
        for v in violations:
            if v.image_path:
                image_path = os.path.join(app.root_path, 'static', 'violations', v.image_path)
                if os.path.exists(image_path):
                    os.remove(image_path)
                    deleted_images += 1
            
            db.session.delete(v)
        
        db.session.commit()
        print(f"\n✅ Deleted {len(violations)} violation(s) and {deleted_images} image(s)")


def list_all_violations():
    """List all violations with IDs"""
    with app.app_context():
        violations = Violation.query.order_by(Violation.timestamp.desc()).all()
        
        if not violations:
            print("📋 No violations found")
            return
        
        print(f"\n📋 All Violations ({len(violations)} total):\n")
        print(f"{'ID':<5} {'Timestamp':<20} {'Type':<20} {'Gate Action':<15} {'Image'}")
        print("-" * 100)
        
        for v in violations:
            print(f"{v.id:<5} {v.timestamp.strftime('%Y-%m-%d %H:%M:%S'):<20} {v.violation_type or 'N/A':<20} {v.gate_action or 'N/A':<15} {v.image_path or 'N/A'}")


if __name__ == '__main__':
    print("🗑️  Violation Deletion Utility\n")
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python delete_violations.py list                    # List all violations")
        print("  python delete_violations.py last 2                  # Delete last 2 violations")
        print("  python delete_violations.py ids 5 7 9               # Delete violations with IDs 5, 7, 9")
        print("  python delete_violations.py type manual_override    # Delete all manual overrides")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'list':
        list_all_violations()
    
    elif command == 'last':
        if len(sys.argv) < 3:
            print("❌ Error: Specify number of violations to delete")
            print("Example: python delete_violations.py last 2")
            sys.exit(1)
        
        n = int(sys.argv[2])
        delete_last_n(n)
    
    elif command == 'ids':
        if len(sys.argv) < 3:
            print("❌ Error: Specify violation IDs to delete")
            print("Example: python delete_violations.py ids 5 7 9")
            sys.exit(1)
        
        ids = [int(x) for x in sys.argv[2:]]
        delete_by_ids(ids)
    
    elif command == 'type':
        if len(sys.argv) < 3:
            print("❌ Error: Specify violation type")
            print("Example: python delete_violations.py type manual_override")
            sys.exit(1)
        
        vtype = sys.argv[2]
        delete_by_type(vtype)
    
    else:
        print(f"❌ Unknown command: {command}")
        print("Valid commands: list, last, ids, type")