# File: migration.py
# This script is to be run ONLY ONCE on your deployed Render application.
from sqlalchemy import text
from app import app, db, Bill, Setting
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_migration():
    with app.app_context():
        try:
            logging.info("Starting database migration...")

            # --- Step 1: Add new settings for product-specific bill numbers ---
            if not Setting.query.filter_by(key='last_bill_number_fertilizer').first():
                db.session.add(Setting(key='last_bill_number_fertilizer', value=0))
                logging.info("Setting 'last_bill_number_fertilizer' created.")
            else:
                logging.info("Setting 'last_bill_number_fertilizer' already exists.")

            if not Setting.query.filter_by(key='last_bill_number_pesticide').first():
                db.session.add(Setting(key='last_bill_number_pesticide', value=0))
                logging.info("Setting 'last_bill_number_pesticide' created.")
            else:
                logging.info("Setting 'last_bill_number_pesticide' already exists.")

            if not Setting.query.filter_by(key='last_bill_number_general').first():
                db.session.add(Setting(key='last_bill_number_general', value=0))
                logging.info("Setting 'last_bill_number_general' created.")
            else:
                logging.info("Setting 'last_bill_number_general' already exists.")

            db.session.commit()
            logging.info("Settings check/creation complete.")

            # --- Step 2: Alter the bill_number column type to TEXT ---
            # This requires raw SQL as SQLAlchemy doesn't have a simple alter_column for this.
            # The exact command can vary slightly between DBs, but this is standard.
            # On PostgreSQL (used by Render), this works.
            with db.engine.connect() as connection:
                  with connection.begin(): # Manages the transaction (commit/rollback)
                      connection.execute(text('ALTER TABLE bills ALTER COLUMN bill_number TYPE TEXT;'))
            logging.info("Altered 'bills.bill_number' column type to TEXT.")

            # --- Step 3: Update all existing bills to the new string format ---
            # We fetch bills that are still in integer format (don't contain '/')
            existing_bills = Bill.query.filter(Bill.bill_number.notlike('%/%')).all()
            
            if not existing_bills:
                logging.info("No existing integer-based bill numbers found to update.")
            else:
                logging.info(f"Found {len(existing_bills)} existing bills to update.")
                for bill in existing_bills:
                    old_number = bill.bill_number
                    # Prefix with BT/OLD/ to signify it's from the old system
                    new_formatted_number = f"BT/OLD/{str(old_number).zfill(3)}"
                    bill.bill_number = new_formatted_number
                    db.session.add(bill)
                    logging.info(f"Updating bill ID {bill.id} from '{old_number}' to '{new_formatted_number}'.")

            db.session.commit()
            logging.info("All existing bills have been updated to the new format.")
            
            logging.info("--- MIGRATION COMPLETED SUCCESSFULLY ---")

        except Exception as e:
            db.session.rollback()
            logging.error(f"An error occurred during migration: {e}", exc_info=True)
            logging.error("--- MIGRATION FAILED. DATABASE HAS BEEN ROLLED BACK. ---")

if __name__ == '__main__':
    run_migration()
