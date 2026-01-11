"""
Migration script to add supervisor_notes column to existing database
Run this ONCE after updating models.py
"""
from app import app, db
from models import Violation
import sqlite3

def add_supervisor_notes_column():
    """Add supervisor_notes column to Violation table if it doesn't exist"""
    
    db_path = 'instance/substation.db'
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("PRAGMA table_info(violation)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'supervisor_notes' not in columns:
            print("📝 Adding supervisor_notes column...")
            cursor.execute("ALTER TABLE violation ADD COLUMN supervisor_notes TEXT")
            conn.commit()
            print("✅ Column added successfully!")
        else:
            print("ℹ️  supervisor_notes column already exists")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False
    
    return True

if __name__ == '__main__':
    print("🔧 Starting database migration...")
    success = add_supervisor_notes_column()
    
    if success:
        print("\n✅ Migration completed successfully!")
        print("You can now restart your Flask app.")
    else:
        print("\n❌ Migration failed. Please check the error above.")