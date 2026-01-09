# create_admin.py
from app import app, db, bcrypt
from models import User

with app.app_context():
    # Check if admin exists
    admin = User.query.filter_by(username='admin2').first()
    if not admin:
        hashed_password = bcrypt.generate_password_hash('admin1234').decode('utf-8')
        admin = User(
            username='admin2',
            email='admin2@gmail.com',
            password=hashed_password,
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()
        print('Admin user created successfully!')
