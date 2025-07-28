# File: app.py

from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for, session, g, send_from_directory
import sqlite3 # Still needed for local init_db if running locally without DATABASE_URL set
import datetime
from weasyprint import HTML
import os
import uuid
from functools import wraps
from io import BytesIO # Corrected import for BytesIO
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash # For password hashing
import secrets # For generating a secure secret key
import logging # For improved logging

# New: SQLAlchemy imports
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func # For SQL functions like SUM, COUNT, etc.
from sqlalchemy import or_ # For OR conditions in queries

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize the Flask app
app = Flask(__name__)

# New: Database Configuration for SQLAlchemy
# Use DATABASE_URL from environment variable for PostgreSQL on Render, fallback to SQLite locally
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///billing_software.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Disable signal for database changes

# New: Generate a strong, random secret key. For production, load from environment variable.
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
logging.info(f"Flask app initialized with secret key (first 8 chars): {app.secret_key[:8]}...")

# Define upload folder
UPLOAD_FOLDER = 'invoices_uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
logging.info(f"Upload folder set to: {UPLOAD_FOLDER}")

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# --- SQLAlchemy Models (replacing raw SQL table creation) ---

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True) # Added unique constraint
    company_name = db.Column(db.Text)
    product_type = db.Column(db.Text, nullable=False)
    mfg_date = db.Column(db.Text)
    exp_date = db.Column(db.Text)
    batch_num = db.Column(db.Text)
    hsn_code = db.Column(db.Text)
    pack_size = db.Column(db.Text)
    rate = db.Column(db.Float, nullable=False)
    stock_qty = db.Column(db.Integer, nullable=False)
    gst_percentage = db.Column(db.Float)

    def __repr__(self):
        return f"<Product {self.name}>"

class Bill(db.Model):
    __tablename__ = 'bills'
    id = db.Column(db.Integer, primary_key=True)
    bill_number = db.Column(db.Integer, nullable=False, unique=True) # Bill number should be unique
    customer_name = db.Column(db.Text, nullable=False)
    customer_village = db.Column(db.Text) # New: Added to persist this info
    customer_mobile_num = db.Column(db.Text) # New: Added to persist this info
    bill_date = db.Column(db.Date, nullable=False)
    grand_total = db.Column(db.Float, nullable=False)

    # Relationship to BillItem (one-to-many)
    items = db.relationship('BillItem', backref='bill', lazy=True)

    def __repr__(self):
        return f"<Bill {self.bill_number}>"

class BillItem(db.Model):
    __tablename__ = 'bill_items'
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=False)
    product_name = db.Column(db.Text, nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    rate = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    gst_percentage = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f"<BillItem {self.product_name} on Bill {self.bill_id}>"

class Setting(db.Model):
    __tablename__ = 'settings'
    key = db.Column(db.Text, primary_key=True)
    value = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return f"<Setting {self.key}: {self.value}>"

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, nullable=False, unique=True)
    _password_hash = db.Column('password', db.Text, nullable=False) # Store hashed password

    role = db.Column(db.Text, nullable=False) # 'admin' or 'user'

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self._password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self._password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"

class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.Text, nullable=False)
    stored_filename = db.Column(db.Text, nullable=False)
    upload_date = db.Column(db.Text, nullable=False) # Stored as 'YYYY-MM-DD' string

    def __repr__(self):
        return f"<Invoice {self.original_filename}>"

# --- End SQLAlchemy Models ---

# Function to initialize the database: create tables and seed initial data
def init_db():
    with app.app_context():
        # Create all tables defined by the models
        db.create_all()
        logging.info("SQLAlchemy models converted to database tables.")

        # Seed initial users if they don't exist
        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin', role='admin')
            admin_user.password = 'admin123' # This will hash the password via the setter
            db.session.add(admin_user)
            logging.info("Default admin user added.")
            
        if not User.query.filter_by(username='user').first():
            regular_user = User(username='user', role='user')
            regular_user.password = 'user123' # This will hash the password via the setter
            db.session.add(regular_user)
            logging.info("Default regular user added.")

        # Initialize last_bill_number if it doesn't exist
        if not Setting.query.filter_by(key='last_bill_number').first():
            db.session.add(Setting(key='last_bill_number', value=0))
            logging.info("Last bill number setting initialized to 0.")

        db.session.commit()
        logging.info("Database initialization complete (models created and data seeded).")

        # Create temp directory for PDFs if it doesn't exist
        if not os.path.exists('temp'):
            os.makedirs('temp')
            logging.info("Temporary PDF directory 'temp' created.")


# Login required decorator to protect routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            logging.warning(f"Access denied: User not logged in for route {request.path}")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Admin-only decorator to restrict access to admin users
def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session.get('role') != 'admin':
            logging.warning(f"Access denied: User '{session.get('username', 'N/A')}' attempted to access admin-only route {request.path}")
            return "Access Denied. You must be an admin to view this page.", 403
        return f(*args, **kwargs)
    return decorated_function

# Before each request, make the user's role available to all templates via Flask's 'g' object
@app.before_request
def before_request():
    g.role = session.get('role', None)
    logging.debug(f"User role set to '{g.role}' for request to {request.path}")

# Login route: handles displaying the login form and processing login attempts
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # New: Use SQLAlchemy to query user
        user = User.query.filter_by(username=username).first()

        # New: Verify password using the model's method
        if user and user.verify_password(password):
            session['username'] = username
            session['role'] = user.role
            logging.info(f"User '{username}' logged in successfully with role '{session['role']}'.")
            if session['role'] == 'admin':
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('billing_selection'))
        else:
            logging.warning(f"Failed login attempt for username '{username}'.")
            return render_template('login.html', error="Invalid credentials. Please try again.")

    return render_template('login.html')

# Logout route: clears the user's session
@app.route('/logout')
def logout():
    username = session.pop('username', None)
    session.pop('role', None)
    logging.info(f"User '{username}' logged out.")
    return redirect(url_for('login'))

# Main route to render the dashboard
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

# Route for bills selection page
@app.route('/bills')
@login_required
def bills():
    return render_template('bills.html')

# API endpoint to get all bills for searching
@app.route('/get_bills')
@login_required
def get_bills():
    # New: Use SQLAlchemy to fetch all bills
    bills_data = Bill.query.order_by(Bill.bill_number.desc()).all()

    bills_list = []
    for bill in bills_data:
        bills_list.append({
            'bill_number': bill.bill_number,
            'customer_name': bill.customer_name,
            'bill_date': bill.bill_date.strftime('%Y-%m-%d'), # Format date for JSON
            'grand_total': bill.grand_total
        })
    logging.info(f"Fetched {len(bills_list)} bills for display.")
    return jsonify(bills_list)

# Route for inventory selection page
@app.route('/inventory')
@login_required
@admin_only
def inventory_selection():
    return render_template('inventory_selection.html')

# Route to show the product list for a specific type
@app.route('/inventory/<product_type>')
@login_required
@admin_only
def inventory(product_type):
    products = []
    try:
        # New: Use SQLAlchemy to query products
        products_data = Product.query.filter_by(product_type=product_type).order_by(Product.name.asc()).all()

        for product in products_data:
            products.append({
                'id': product.id,
                'name': product.name,
                'company_name': product.company_name,
                'product_type': product.product_type,
                'mfg_date': product.mfg_date,
                'exp_date': product.exp_date,
                'batch_num': product.batch_num,
                'hsn_code': product.hsn_code,
                'pack_size': product.pack_size,
                'rate': product.rate,
                'stock_qty': product.stock_qty,
                'gst_percentage': product.gst_percentage
            })
        logging.info(f"Fetched {len(products)} products for product type '{product_type}'.")
    except Exception as e:
        logging.error(f"Error fetching inventory for '{product_type}': {e}")

    return render_template('inventory.html', products=products, product_type=product_type)

# API endpoint to add a new product
@app.route('/add_product', methods=['POST'])
@login_required
@admin_only
def add_product_web():
    data = request.form
    # Input validation for numeric fields
    try:
        rate = float(data['rate'])
        stock_qty = int(data['stock_qty'])
        gst_percentage = float(data['gst_percentage'])
    except ValueError:
        logging.warning("Invalid numeric input for product addition.")
        return jsonify({'error': 'Rate, Stock Quantity, and GST Percentage must be valid numbers.'}), 400

    if rate < 0 or stock_qty < 0 or gst_percentage < 0:
        logging.warning("Negative numeric input detected for product addition.")
        return jsonify({'error': 'Rate, Stock Quantity, and GST Percentage cannot be negative.'}), 400

    try:
        # New: Create a new Product instance and add to session
        new_product = Product(
            name=data['name'],
            company_name=data.get('company_name'), # Use .get() for optional fields
            product_type=data['product_type'],
            mfg_date=data.get('mfg_date'),
            exp_date=data.get('exp_date'),
            batch_num=data.get('batch_num'),
            hsn_code=data.get('hsn_code'),
            pack_size=data.get('pack_size'),
            rate=rate,
            stock_qty=stock_qty,
            gst_percentage=gst_percentage
        )
        db.session.add(new_product)
        db.session.commit() # Commit changes to the database
        logging.info(f"Product '{data['name']}' added successfully.")
        return redirect(url_for('inventory', product_type=data['product_type']))
    except Exception as e:
        db.session.rollback() # Rollback on error
        logging.error(f"Error adding product: {e}")
        # Check for unique constraint violation (product name)
        if "UNIQUE constraint failed: products.name" in str(e):
             return jsonify({'error': 'Product name already exists.'}), 400
        return jsonify({'error': str(e)}), 400


# Route to render the edit product form
@app.route('/edit_product_form/<int:product_id>')
@login_required
@admin_only
def edit_product_form(product_id):
    # New: Query product by ID
    product = Product.query.get(product_id)

    if product:
        logging.info(f"Fetched product for editing: ID {product_id}")
        return render_template('edit_product_form.html', product=product)
    else:
        logging.warning(f"Product with ID {product_id} not found for editing.")
        return "Product not found.", 404

# Route to handle the product update
@app.route('/update_product', methods=['POST'])
@login_required
@admin_only
def update_product():
    data = request.form
    # Input validation for numeric fields
    try:
        rate = float(data['rate'])
        stock_qty = int(data['stock_qty'])
        gst_percentage = float(data['gst_percentage'])
    except ValueError:
        logging.warning("Invalid numeric input for product update.")
        return jsonify({'error': 'Rate, Stock Quantity, and GST Percentage must be valid numbers.'}), 400

    if rate < 0 or stock_qty < 0 or gst_percentage < 0:
        logging.warning("Negative numeric input detected for product update.")
        return jsonify({'error': 'Rate, Stock Quantity, and GST Percentage cannot be negative.'}), 400

    try:
        product_id = data['product_id']
        product_type = data['product_type']

        # New: Fetch the product to update
        product = Product.query.get(product_id)

        if not product:
            logging.warning(f"Product ID {product_id} not found for update.")
            return jsonify({'error': 'Product not found.'}), 404

        # Update product attributes
        product.name = data['name']
        product.company_name = data.get('company_name')
        product.product_type = data['product_type']
        product.mfg_date = data.get('mfg_date')
        product.exp_date = data.get('exp_date')
        product.batch_num = data.get('batch_num')
        product.hsn_code = data.get('hsn_code')
        product.pack_size = data.get('pack_size')
        product.rate = rate
        product.stock_qty = stock_qty
        product.gst_percentage = gst_percentage

        db.session.commit() # Commit changes to the database
        logging.info(f"Product ID {product_id} updated successfully.")
        return redirect(url_for('inventory', product_type=product_type))
    except Exception as e:
        db.session.rollback() # Rollback on error
        logging.error(f"Error updating product ID {product_id}: {e}")
        # Check for unique constraint violation (product name)
        if "UNIQUE constraint failed: products.name" in str(e):
             return jsonify({'error': 'Product name already exists.'}), 400
        return jsonify({'error': str(e)}), 400
        
# Route to render the add product form for a specific type
@app.route('/add_product_form/<product_type>')
@login_required
@admin_only
def add_product_form(product_type):
    return render_template('add_product_form.html', product_type=product_type)

# New route for billing selection
@app.route('/billing')
@login_required
def billing_selection():
    return render_template('billing_selection.html')

# Route for the billing page, now filtered by product type
@app.route('/billing/<product_type>')
@login_required
def billing(product_type):
    products = []
    try:
        # New: Fetch products using SQLAlchemy
        products_data = Product.query.filter_by(product_type=product_type).order_by(Product.name.asc()).all()
        
        products_list = []
        for product in products_data:
            products_list.append({
                'id': product.id,
                'name': product.name,
                'company_name': product.company_name
            })
        logging.info(f"Fetched {len(products_list)} products for billing of type '{product_type}'.")
    except Exception as e:
        logging.error(f"Error fetching products for billing '{product_type}': {e}")
    
    return render_template('billing.html', products=products_list, today_date=datetime.date.today(), product_type=product_type)

# New API endpoint to get a single product's details by ID
@app.route('/product/<int:product_id>')
@login_required
def get_product_details(product_id):
    try:
        # New: Query product by ID
        product = Product.query.get(product_id)
        if product:
            product_dict = {
                'id': product.id,
                'name': product.name,
                'company_name': product.company_name,
                'product_type': product.product_type,
                'mfg_date': product.mfg_date,
                'exp_date': product.exp_date,
                'batch_num': product.batch_num,
                'hsn_code': product.hsn_code,
                'pack_size': product.pack_size,
                'rate': product.rate,
                'stock_qty': product.stock_qty,
                'gst_percentage': product.gst_percentage
            }
            logging.info(f"Fetched details for product ID {product_id}.")
            return jsonify(product_dict), 200
        else:
            logging.warning(f"Product ID {product_id} not found.")
            return jsonify({'error': 'Product not found'}), 404
    except Exception as e:
        logging.error(f"Error fetching product details for ID {product_id}: {e}")
        return jsonify({'error': str(e)}), 500

# New API endpoint to generate the PDF bill with a simple, sequential number
@app.route('/generate_pdf', methods=['POST'])
@login_required
def generate_pdf():
    data = request.json
    
    try:
        # Start a transaction (implicit with SQLAlchemy session)
        
        # Get and increment the last bill number
        last_bill_number_setting = Setting.query.filter_by(key='last_bill_number').first()
        if not last_bill_number_setting:
            # This should ideally not happen if init_db runs correctly
            last_bill_number_setting = Setting(key='last_bill_number', value=0)
            db.session.add(last_bill_number_setting)
            db.session.commit() # Commit the creation of setting first
            
        new_bill_number = last_bill_number_setting.value + 1
        last_bill_number_setting.value = new_bill_number
        db.session.add(last_bill_number_setting) # Mark as modified
        logging.info(f"Generated new bill number: {new_bill_number}")

        # Save the bill to the database using the Bill model
        # New: Capturing village and mobileNum from frontend
        new_bill = Bill(
            bill_number=new_bill_number,
            customer_name=data['customerName'],
            customer_village=data.get('village', 'N/A'), # Get from data, default to N/A
            customer_mobile_num=data.get('mobileNum', 'N/A'), # Get from data, default to N/A
            bill_date=datetime.datetime.strptime(data['billDate'], '%Y-%m-%d').date(), # Convert to date object
            grand_total=data['grandTotal']
        )
        db.session.add(new_bill)
        db.session.flush() # Flush to get bill_id before committing (needed for bill_items)
        logging.info(f"Bill header saved with ID {new_bill.id}.")

        # Save bill items and update stock
        for item_data in data['products']:
            # Basic validation for quantities and rates during billing
            try:
                qty = int(item_data['qty'])
                rate = float(item_data['rate'])
                amount = float(item_data['amount'])
                gst = float(item_data['gst'])
                if qty <= 0 or rate < 0 or amount < 0 or gst < 0:
                    raise ValueError("Quantity must be positive. Rate, Amount, and GST must be non-negative.")
            except ValueError as ve:
                db.session.rollback() # Rollback transaction if any item data is invalid
                logging.error(f"Invalid product data during bill generation: {ve}")
                return jsonify({'error': f"Invalid product data: {ve}"}), 400

            # Update product stock
            product_to_update = Product.query.filter_by(name=item_data['name']).first()
            if product_to_update:
                if product_to_update.stock_qty < qty:
                    db.session.rollback()
                    logging.warning(f"Insufficient stock for {item_data['name']}. Available: {product_to_update.stock_qty}, Requested: {qty}")
                    return jsonify({'error': f"Insufficient stock for {item_data['name']}. Available: {product_to_update.stock_qty}, Requested: {qty}"}), 400
                product_to_update.stock_qty -= qty
                db.session.add(product_to_update) # Mark as modified
            else:
                db.session.rollback()
                logging.error(f"Product '{item_data['name']}' not found when updating stock.")
                return jsonify({'error': f"Product '{item_data['name']}' not found."}), 404

            # Create new BillItem instance
            new_bill_item = BillItem(
                bill_id=new_bill.id,
                product_name=item_data['name'],
                qty=qty,
                rate=rate,
                amount=amount,
                gst_percentage=gst
            )
            db.session.add(new_bill_item)
        
        db.session.commit() # Commit the entire transaction

        # --- LOGIC TO DETERMINE BILL TYPE ---
        product_names = [item_data['name'] for item_data in data['products']]
        bill_type = 'general' # Default to general bill
        if product_names:
            # Query for product types of items in the current bill
            product_types_in_bill = db.session.query(Product.product_type).filter(Product.name.in_(product_names)).distinct().all()
            product_types_in_bill_list = [pt[0] for pt in product_types_in_bill]

            if 'pesticide' in product_types_in_bill_list:
                bill_type = 'pesticide'
            elif 'fertilizer' in product_types_in_bill_list:
                bill_type = 'fertilizer'
        logging.info(f"Determined bill type for Bill {new_bill_number}: {bill_type}")
        # --- END BILL TYPE LOGIC ---

        # Prepare data for the PDF template
        pdf_template_data = {
            'billNumber': new_bill_number,
            'customerName': data['customerName'],
            'billDate': data['billDate'], # Keep as string for template
            'grandTotal': data['grandTotal'],
            'village': data.get('village', 'N/A'),
            'mobileNum': data.get('mobileNum', 'N/A'),
            'products': data['products'], # The original product data from JS
            'totalBeforeTax': data['totalBeforeTax'], # Pass calculated values from JS
            'totalGst': data['totalGst'], # Pass calculated values from JS
            'bill_type': bill_type
        }
        
        # Render the HTML template with the bill data
        html_string = render_template('bill_template.html', bill_data=pdf_template_data)
        
        # Convert the HTML string to a PDF
        pdf_bytes = HTML(string=html_string).write_pdf()
        
        # Create a unique filename and save the PDF temporarily
        filename = f"bill_{uuid.uuid4().hex}.pdf"
        filepath = os.path.join('temp', filename)
        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)
        logging.info(f"Generated PDF saved temporarily as '{filename}'.")

        return jsonify({'filename': filename}), 200

    except Exception as e:
        db.session.rollback() # Rollback transaction on any error
        logging.error(f"Error generating PDF for bill: {e}", exc_info=True) # exc_info for full traceback
        return jsonify({'error': str(e)}), 500

# New route to serve the temporary PDF file
@app.route('/serve_pdf/<filename>')
@login_required
def serve_pdf(filename):
    filepath = os.path.join('temp', filename)
    if os.path.exists(filepath):
        logging.info(f"Serving temporary PDF file: '{filename}'.")
        return send_from_directory('temp', filename, as_attachment=False)
    else:
        logging.warning(f"Attempted to serve non-existent PDF file: '{filename}'.")
        return jsonify({'error': 'File not found'}), 404

# New route to view a historical bill
@app.route('/view_bill/<int:bill_number>')
@login_required
def view_bill(bill_number):
    try:
        # Fetch bill header details using SQLAlchemy
        bill_header = Bill.query.filter_by(bill_number=bill_number).first()
        
        if not bill_header:
            logging.warning(f"Bill number {bill_number} not found for viewing.")
            return "Bill not found.", 404
            
        # Access attributes directly from the model instance
        customer_name = bill_header.customer_name
        bill_date = bill_header.bill_date.strftime('%Y-%m-%d') # Format for template
        grand_total = bill_header.grand_total
        village = bill_header.customer_village
        mobileNum = bill_header.customer_mobile_num

        # Fetch all bill items associated with this bill, and join with product details
        bill_items_data = db.session.query(
            BillItem, Product.company_name, Product.mfg_date, Product.exp_date,
            Product.batch_num, Product.pack_size, Product.product_type
        ).join(Product, BillItem.product_name == Product.name).filter(
            BillItem.bill_id == bill_header.id
        ).all()
        
        bill_items = []
        product_types_for_bill_type_determination = []
        for item_obj, company_name, mfg_date, exp_date, batch_num, pack_size, product_type in bill_items_data:
            bill_items.append({
                'name': item_obj.product_name,
                'qty': item_obj.qty,
                'rate': item_obj.rate,
                'amount': item_obj.amount,
                'gst': item_obj.gst_percentage,
                'company_name': company_name,
                'mfg_date': mfg_date,
                'exp_date': exp_date,
                'batch_num': batch_num,
                'pack_size': pack_size
            })
            product_types_for_bill_type_determination.append(product_type) # Collect product types

        # --- LOGIC TO DETERMINE BILL TYPE FOR HISTORICAL VIEW ---
        bill_type = 'general' # Default to general bill
        if 'pesticide' in product_types_for_bill_type_determination:
            bill_type = 'pesticide'
        elif 'fertilizer' in product_types_for_bill_type_determination:
            bill_type = 'fertilizer'
        logging.info(f"Viewing historical bill {bill_number}, determined type: {bill_type}")
        # --- END BILL TYPE LOGIC ---

        # Reconstruct the bill data dictionary for the template
        bill_data = {
            'billNumber': bill_number,
            'customerName': customer_name,
            'billDate': bill_date,
            'grandTotal': grand_total,
            'village': village, # Now retrieved from DB
            'mobileNum': mobileNum, # Now retrieved from DB
            'products': bill_items, # Full list with product details
            'totalBeforeTax': 0, # Will recalculate for consistency
            'totalGst': 0,       # Will recalculate for consistency
            'bill_type': bill_type
        }
        
        for item in bill_items:
            # Recalculate totals for display
            gst_percentage = item['gst']
            if gst_percentage > 0:
                base_price = item['rate'] / (1 + gst_percentage / 100)
                gst_amount_per_item = item['rate'] - base_price
            else:
                base_price = item['rate']
                gst_amount_per_item = 0
            
            bill_data['totalBeforeTax'] += base_price * item['qty']
            bill_data['totalGst'] += gst_amount_per_item * item['qty']
            
        # Render the HTML template with the reconstructed data
        html_string = render_template('bill_template.html', bill_data=bill_data)
        
        # Convert HTML to PDF
        pdf_bytes = HTML(string=html_string).write_pdf()
        
        logging.info(f"Generated PDF for historical bill {bill_number} and serving.")
        return send_file(
            BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f'bill_{bill_number}.pdf'
        )

    except Exception as e:
        logging.error(f"Error viewing historical bill {bill_number}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# Route for sales reports selection page
@app.route('/reports')
@login_required
@admin_only
def reports_selection():
    return render_template('reports_selection.html')
    
# New route to handle the actual reports page
@app.route('/reports/<product_type>')
@login_required
@admin_only
def reports(product_type):
    products = []
    try:
        # New: Query products using SQLAlchemy
        products_data = Product.query.filter_by(product_type=product_type).order_by(Product.name.asc()).all()
        products = [p.name for p in products_data]
        logging.info(f"Fetched {len(products)} products for reports of type '{product_type}'.")
    except Exception as e:
        logging.error(f"Error fetching products for reports '{product_type}': {e}")
    
    return render_template('reports.html', products=products, product_type=product_type)

# API endpoint for sales reports generation
@app.route('/sales_report', methods=['GET'])
@login_required
@admin_only
def sales_report():
    report_type = request.args.get('type')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    product_name = request.args.get('product')
    product_type_filter = request.args.get('product_type')

    try:
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        logging.warning(f"Invalid date format for sales report: start={start_date_str}, end={end_date_str}")
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD.'}), 400

    query = db.session.query(BillItem, Bill, Product).join(Bill, BillItem.bill_id == Bill.id).join(Product, BillItem.product_name == Product.name).filter(
        Bill.bill_date.between(start_date, end_date)
    )

    if product_name and product_name != 'all':
        query = query.filter(BillItem.product_name == product_name)

    if product_type_filter and product_type_filter != 'all':
        query = query.filter(Product.product_type == product_type_filter) # Filter by product type

    # Grouping and aggregation based on report type (partial code from original)
    # The original sales_report function was truncated, this is the continuation based on common patterns.
    # Assuming the goal is to show a summary report.

    report_data = []
    if report_type == 'sales_by_date':
        results = db.session.query(
            Bill.bill_date,
            func.sum(Bill.grand_total).label('total_sales')
        ).filter(Bill.bill_date.between(start_date, end_date)).group_by(Bill.bill_date).order_by(Bill.bill_date.asc()).all()
        
        for row_date, row_total_sales in results:
            report_data.append({
                'date': row_date.strftime('%Y-%m-%d'),
                'total_sales': row_total_sales
            })
        logging.info(f"Generated 'sales_by_date' report for {len(report_data)} entries.")

    elif report_type == 'sales_by_product':
        results = db.session.query(
            BillItem.product_name,
            func.sum(BillItem.qty).label('total_quantity_sold'),
            func.sum(BillItem.amount).label('total_revenue')
        ).join(Bill, BillItem.bill_id == Bill.id).join(Product, BillItem.product_name == Product.name).filter(
            Bill.bill_date.between(start_date, end_date)
        )
        if product_name and product_name != 'all':
            results = results.filter(BillItem.product_name == product_name)
        if product_type_filter and product_type_filter != 'all':
            results = results.filter(Product.product_type == product_type_filter)
        
        results = results.group_by(BillItem.product_name).order_by(func.sum(BillItem.amount).desc()).all()

        for row_name, row_qty, row_revenue in results:
            report_data.append({
                'product_name': row_name,
                'total_quantity_sold': row_qty,
                'total_revenue': row_revenue
            })
        logging.info(f"Generated 'sales_by_product' report for {len(report_data)} entries.")

    return jsonify(report_data), 200

# --- Run the app ---
if __name__ == '__main__':
    # Initialize the database and create tables
    init_db()
    # Use 0.0.0.0 for Render deployment
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 5000), debug=False) # Set debug=True for local development
