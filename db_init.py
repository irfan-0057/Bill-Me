# db_init.py
from app import app, db, User, Setting, Product, Bill, BillItem, Invoice, generate_password_hash
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_and_seed_db():
    with app.app_context():
        logging.info("Attempting to create all database tables via db_init.py...")
        db.create_all()
        logging.info("db.create_all() executed.")

        # Seed initial users if they don't exist
        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin', role='admin')
            admin_user.password = 'admin123'
            db.session.add(admin_user)
            logging.info("Default admin user added.")

        if not User.query.filter_by(username='user').first():
            regular_user = User(username='user', role='user')
            regular_user.password = 'user123'
            db.session.add(regular_user)
            logging.info("Default regular user added.")

        # NEW: Initialize last bill numbers for each product type
        if not Setting.query.filter_by(key='last_bill_number_fertilizer').first():
            db.session.add(Setting(key='last_bill_number_fertilizer', value=0))
            logging.info("Last bill number for fertilizer initialized to 0.")
            
        if not Setting.query.filter_by(key='last_bill_number_pesticide').first():
            db.session.add(Setting(key='last_bill_number_pesticide', value=0))
            logging.info("Last bill number for pesticide initialized to 0.")
            
        if not Setting.query.filter_by(key='last_bill_number_general').first():
            db.session.add(Setting(key='last_bill_number_general', value=0))
            logging.info("Last bill number for general initialized to 0.")


        db.session.commit()
        logging.info("Database initialization and seeding complete from db_init.py.")

        # Create temp directory for PDFs if it doesn't exist (can also be done in render.yaml if using)
        if not os.path.exists('temp'):
            os.makedirs('temp')
            logging.info("Temporary PDF directory 'temp' created.")
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
            logging.info("Uploads directory 'invoices_uploads' created.")

if __name__ == '__main__':
    # This allows you to run `python db_init.py` locally to set up your DB
    # Make sure DATABASE_URL is set locally if you're using PostgreSQL locally
    create_and_seed_db()
