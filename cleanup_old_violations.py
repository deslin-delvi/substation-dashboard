"""
Storage cleanup utility - Delete old violation photos and database records
Run periodically to manage storage space
"""
from app import app, db
from models import Violation
from datetime import datetime, timedelta
import os

def cleanup_old_violations(days_to_keep=30, dry_run=True):
    """
    Delete violations older than specified days
    
    Args:
        days_to_keep: Keep violations from last N days (default: 30)
        dry_run: If True, only show what would be deleted (default: True)
    """
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    
    with app.app_context():
        # Find old violations
        old_violations = Violation.query.filter(
            Violation.timestamp < cutoff_date
        ).all()
        
        if not old_violations:
            print(f"✅ No violations older than {days_to_keep} days found")
            return
        
        print(f"{'[DRY RUN] ' if dry_run else ''}Found {len(old_violations)} violations older than {days_to_keep} days")
        
        deleted_images = 0
        deleted_records = 0
        
        for violation in old_violations:
            # Delete image file if exists
            if violation.image_path:
                image_path = os.path.join(
                    app.root_path, 
                    'static', 
                    'violations', 
                    violation.image_path
                )
                
                if os.path.exists(image_path):
                    if not dry_run:
                        os.remove(image_path)
                    print(f"  {'[WOULD DELETE]' if dry_run else '[DELETED]'} {violation.image_path}")
                    deleted_images += 1
            
            # Delete database record
            if not dry_run:
                db.session.delete(violation)
            deleted_records += 1
        
        if not dry_run:
            db.session.commit()
        
        print(f"\n{'[DRY RUN] Would delete:' if dry_run else 'Deleted:'}")
        print(f"  📷 Images: {deleted_images}")
        print(f"  📊 Database records: {deleted_records}")
        
        if dry_run:
            print(f"\n⚠️  This was a DRY RUN - no data was actually deleted")
            print(f"To actually delete, run: cleanup_old_violations(days_to_keep={days_to_keep}, dry_run=False)")


def get_storage_stats():
    """Show current storage usage"""
    violations_dir = os.path.join(app.root_path, 'static', 'violations')
    
    if not os.path.exists(violations_dir):
        print("📁 No violations directory found")
        return
    
    total_size = 0
    file_count = 0
    
    for filename in os.listdir(violations_dir):
        file_path = os.path.join(violations_dir, filename)
        if os.path.isfile(file_path):
            total_size += os.path.getsize(file_path)
            file_count += 1
    
    # Convert to MB
    size_mb = total_size / (1024 * 1024)
    
    print(f"📊 Storage Statistics:")
    print(f"  📷 Total images: {file_count}")
    print(f"  💾 Total size: {size_mb:.2f} MB")
    print(f"  📈 Average per image: {(total_size/file_count/1024):.2f} KB" if file_count > 0 else "  No images")
    
    with app.app_context():
        violation_count = Violation.query.count()
        print(f"  📊 Database records: {violation_count}")


if __name__ == '__main__':
    import sys
    
    print("🧹 Violation Storage Cleanup Utility\n")
    
    # Show current stats
    get_storage_stats()
    print()
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == '--delete':
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            print(f"⚠️  DELETING violations older than {days} days...")
            response = input("Are you sure? (yes/no): ")
            if response.lower() == 'yes':
                cleanup_old_violations(days_to_keep=days, dry_run=False)
            else:
                print("❌ Cancelled")
        else:
            print("Usage:")
            print("  python cleanup_old_violations.py              # Show stats + dry run")
            print("  python cleanup_old_violations.py --delete 30  # Delete violations older than 30 days")
    else:
        # Default: dry run showing what would be deleted
        print("Running DRY RUN (showing what would be deleted)...\n")
        cleanup_old_violations(days_to_keep=30, dry_run=True)
        print("\n💡 Tip: Run with --delete flag to actually delete files")