# WARNING: This script permanently deletes all NEW bills (Pesticide and Fertilizer).
# It will NOT touch your old/migrated bills.

import logging
from app import app, db, Bill, BillItem, Setting, AvailableBillNumber

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def reset_new_billing_data():
    """
    Deletes only new bills and resets their specific counters, keeping old bills safe.
    """
    with app.app_context():
        try:
            logging.info("--- STARTING NEW BILLING DATA RESET ---")

            # Get user confirmation before proceeding
            confirm = input("ARE YOU SURE you want to delete all PESTICIDE and FERTILIZER bills and reset their counters to 1? (yes/no): ")
            if confirm.lower() != 'yes':
                logging.warning("Reset cancelled by user.")
                return

            # Find all new bills (Pesticide and Fertilizer)
            bills_to_delete = Bill.query.filter(
                Bill.bill_number.startswith('BT/P/'),
                Bill.bill_number.startswith('BT/F/')
            ).all()
            
            bill_ids_to_delete = [bill.id for bill in bills_to_delete]

            if not bill_ids_to_delete:
                logging.info("No new bills found to delete.")
            else:
                logging.info(f"Found {len(bill_ids_to_delete)} new bills to delete.")

                # Step 1: Delete bill items associated with the new bills
                db.session.query(BillItem).filter(BillItem.bill_id.in_(bill_ids_to_delete)).delete(synchronize_session=False)
                logging.info("Deleted associated bill items.")

                # Step 2: Delete the new bills themselves
                db.session.query(Bill).filter(Bill.id.in_(bill_ids_to_delete)).delete(synchronize_session=False)
                logging.info("Deleted the new bills.")

            # Step 3: Clear the table of available (reusable) bill numbers
            db.session.query(AvailableBillNumber).delete()
            logging.info("Cleared the available bill number pool.")

            # Step 4: Reset ONLY the new bill counters to 0
            settings_to_reset = [
                'last_bill_number_pesticide',
                'last_bill_number_fertilizer'
            ]
            for key in settings_to_reset:
                setting = Setting.query.filter_by(key=key).first()
                if setting:
                    setting.value = 0
                    db.session.add(setting)
                    logging.info(f"  - Counter '{key}' has been reset to 0.")

            db.session.commit()
            logging.info("--- NEW BILLING RESET COMPLETED SUCCESSFULLY ---")
            logging.info("Your old bills are safe. Your next Pesticide/Fertilizer bill will start from number 1.")

        except Exception as e:
            db.session.rollback()
            logging.error(f"An error occurred during the reset: {e}", exc_info=True)
            logging.error("--- RESET FAILED. DATABASE HAS BEEN ROLLED BACK. ---")

if __name__ == '__main__':
    reset_new_billing_data()
