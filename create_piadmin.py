#!/usr/bin/env python3
"""
create_admin.py - Create admin user for the system
"""

from app import app, db, User, bcrypt
from getpass import getpass

def create_admin():
    """Create admin user interactively"""
    print("\n" + "="*50)
    print("  Create Admin User")
    print("="*50 + "\n")
    
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        
        # Get user input
        username = input("Enter username: ").strip()
        
        if not username:
            print("❌ Username cannot be empty")
            return
        
        # Check if user already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            print(f"❌ User '{username}' already exists!")
            return
        
        email = input("Enter email: ").strip()
        
        if not email:
            print("❌ Email cannot be empty")
            return
        
        password = getpass("Enter password: ")
        password_confirm = getpass("Confirm password: ")
        
        if password != password_confirm:
            print("❌ Passwords don't match!")
            return
        
        if len(password) < 6:
            print("❌ Password must be at least 6 characters")
            return
        
        # Hash password and create user
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        admin_user = User(
            username=username,
            email=email,
            password=hashed_password,
            role='supervisor'
        )
        
        db.session.add(admin_user)
        db.session.commit()
        
        print("\n✅ Admin user created successfully!")
        print(f"   Username: {username}")
        print(f"   Email: {email}")
        print(f"   Role: supervisor")
        print("\n🔐 You can now login at: http://localhost:5000/login")

if __name__ == "__main__":
    create_admin()