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
    # MODIFIED: Changed bill_number to Text to store formatted string like 'BT/F/001'
    bill_number = db.Column(db.Text, nullable=False, unique=True)
    customer_name = db.Column(db.Text, nullable=False)
    customer_village = db.Column(db.Text)
    customer_mobile_num = db.Column(db.Text)
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

        user = User.query.filter_by(username=username).first()

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
def bills_selection():
    return render_template('bills_selection.html')

# NEW: Route to display a filtered list of bills
@app.route('/bills/<bill_type>')
@login_required
def bills_list(bill_type):
    # This dictionary helps create a nice title for the page
    titles = {
        'pesticide': 'Pesticide Bills',
        'fertilizer': 'Fertilizer Bills',
        'old': 'Old / Migrated Bills'
    }
    # Get the title, with a default fallback
    bill_type_title = titles.get(bill_type, 'All Bills')
    return render_template('bill_list.html', bill_type=bill_type, bill_type_title=bill_type_title)

# API endpoint to get all bills for searching
# MODIFIED: API endpoint now filters bills based on the 'type' query parameter
@app.route('/get_bills')
@login_required
def get_bills():
    bill_type = request.args.get('type', 'all') # Get 'type' from URL, e.g., /get_bills?type=pesticide

    query = Bill.query

    # Apply filter based on the bill number prefix
    if bill_type == 'pesticide':
        query = query.filter(Bill.bill_number.startswith('BT/P/'))
    elif bill_type == 'fertilizer':
        query = query.filter(Bill.bill_number.startswith('BT/F/'))
    elif bill_type == 'old':
        query = query.filter(Bill.bill_number.startswith('BT/OLD/'))
    
    # Order by ID descending to get the newest bills first
    bills_data = query.order_by(Bill.id.desc()).all()

    bills_list = []
    for bill in bills_data:
        bills_list.append({
            'bill_number': bill.bill_number,
            'customer_name': bill.customer_name,
            'bill_date': bill.bill_date.strftime('%Y-%m-%d'),
            'grand_total': bill.grand_total
        })
    logging.info(f"Fetched {len(bills_list)} bills for type '{bill_type}'.")
    return jsonify(bills_list)


# MODIFIED: Route now takes a string bill_number
@app.route('/cancel_bill/<path:bill_number>', methods=['POST'])
@login_required
@admin_only
def cancel_bill(bill_number):
    """
    Cancels a bill and reverts stock quantities.
    NOTE: This version does NOT revert the bill number to avoid sequence gaps.
    """
    try:
        bill = Bill.query.filter_by(bill_number=bill_number).first()
        if not bill:
            logging.warning(f"Attempted to cancel non-existent bill number: {bill_number}")
            return jsonify({'error': 'Bill not found.'}), 404
        
        # Revert stock quantities
        bill_items = BillItem.query.filter_by(bill_id=bill.id).all()
        for item in bill_items:
            product = Product.query.filter_by(name=item.product_name).first()
            if product:
                product.stock_qty += item.qty
                db.session.add(product)
                logging.info(f"Reverted stock for product '{product.name}': +{item.qty}")
            else:
                # This case is unlikely but handled for safety
                logging.error(f"Product '{item.product_name}' not found during cancellation of bill {bill_number}.")
                raise ValueError(f"Product '{item.product_name}' not found in inventory.")
        
        # Delete bill items and the bill itself
        for item in bill_items:
            db.session.delete(item)
        db.session.delete(bill)
        
        db.session.commit()
        
        logging.info(f"Bill {bill_number} and associated items successfully cancelled. Stock quantities reverted.")
        return jsonify({'success': 'Bill cancelled successfully. Stock has been reverted.'}), 200
    except ValueError as ve:
        db.session.rollback()
        logging.error(f"Error during bill cancellation for {bill_number}: {ve}")
        return jsonify({'error': str(ve)}), 500
    except Exception as e:
        db.session.rollback()
        logging.error(f"Unexpected error cancelling bill {bill_number}: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred.'}), 500

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
    try:
        rate = float(data['rate'])
        stock_qty = int(data['stock_qty'])
        gst_percentage = float(data['gst_percentage'])
    except ValueError:
        return jsonify({'error': 'Rate, Stock Quantity, and GST must be valid numbers.'}), 400
    if rate < 0 or stock_qty < 0 or gst_percentage < 0:
        return jsonify({'error': 'Rate, Stock Quantity, and GST cannot be negative.'}), 400
    try:
        new_product = Product(
            name=data['name'],
            company_name=data.get('company_name'),
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
        db.session.commit()
        logging.info(f"Product '{data['name']}' added successfully.")
        return redirect(url_for('inventory', product_type=data['product_type']))
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error adding product: {e}")
        if "UNIQUE constraint failed: products.name" in str(e):
             return jsonify({'error': 'Product name already exists.'}), 400
        return jsonify({'error': str(e)}), 400

# Route to render the edit product form
@app.route('/edit_product_form/<int:product_id>')
@login_required
@admin_only
def edit_product_form(product_id):
    product = Product.query.get(product_id)
    if product:
        return render_template('edit_product_form.html', product=product)
    else:
        return "Product not found.", 404

# Route to handle the product update
@app.route('/update_product', methods=['POST'])
@login_required
@admin_only
def update_product():
    data = request.form
    try:
        rate = float(data['rate'])
        stock_qty = int(data['stock_qty'])
        gst_percentage = float(data['gst_percentage'])
    except ValueError:
        return jsonify({'error': 'Rate, Stock Quantity, and GST must be valid numbers.'}), 400
    if rate < 0 or stock_qty < 0 or gst_percentage < 0:
        return jsonify({'error': 'Rate, Stock Quantity, and GST cannot be negative.'}), 400
    try:
        product_id = data['product_id']
        product_type = data['product_type']
        product = Product.query.get(product_id)
        if not product:
            return jsonify({'error': 'Product not found.'}), 404
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
        db.session.commit()
        logging.info(f"Product ID {product_id} updated successfully.")
        return redirect(url_for('inventory', product_type=product_type))
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating product ID {product_id}: {e}")
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
    products_data = Product.query.filter_by(product_type=product_type).order_by(Product.name.asc()).all()
    products_list = [{'id': p.id, 'name': p.name, 'company_name': p.company_name} for p in products_data]
    return render_template('billing.html', products=products_list, today_date=datetime.date.today(), product_type=product_type)

# New API endpoint to get a single product's details by ID
@app.route('/product/<int:product_id>')
@login_required
def get_product_details(product_id):
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
        return jsonify(product_dict), 200
    else:
        return jsonify({'error': 'Product not found'}), 404

# MODIFIED: Major overhaul of this route for new bill number generation
@app.route('/generate_pdf', methods=['POST'])
@login_required
def generate_pdf():
    data = request.json
    try:
        # --- Step 1: Determine Bill Type and Prefix ---
        product_names = [item['name'] for item in data['products']]
        if not product_names:
            return jsonify({'error': 'Cannot generate a bill with no products.'}), 400

        product_types_in_bill = db.session.query(Product.product_type).filter(Product.name.in_(product_names)).distinct().all()
        product_types_list = [pt[0] for pt in product_types_in_bill]

        # Determine the primary type for this bill to select the correct counter
        if 'pesticide' in product_types_list:
            bill_type_key = 'pesticide'
            prefix = 'BT/P/'
        elif 'fertilizer' in product_types_list:
            bill_type_key = 'fertilizer'
            prefix = 'BT/F/'
        else:
            bill_type_key = 'general' # Fallback for other product types
            prefix = 'BT/G/'
            
        setting_key = f"last_bill_number_{bill_type_key}"
        logging.info(f"Determined bill type key: {bill_type_key}")

        # --- Step 2: Get and Increment the Correct Bill Counter ---
        last_bill_setting = Setting.query.filter_by(key=setting_key).first()
        if not last_bill_setting:
            # This is a fallback, should be created by db_init.py
            last_bill_setting = Setting(key=setting_key, value=0)
            db.session.add(last_bill_setting)
            db.session.commit()

        new_number = last_bill_setting.value + 1
        last_bill_setting.value = new_number
        db.session.add(last_bill_setting)
        
        # Format the new bill number string (e.g., 'BT/F/001')
        formatted_bill_number = f"{prefix}{str(new_number).zfill(3)}"
        logging.info(f"Generated new formatted bill number: {formatted_bill_number}")

        # --- Step 3: Save Bill and Items (as before) ---
        new_bill = Bill(
            bill_number=formatted_bill_number,
            customer_name=data['customerName'],
            customer_village=data.get('village', 'N/A'),
            customer_mobile_num=data.get('mobileNum', 'N/A'),
            bill_date=datetime.datetime.strptime(data['billDate'], '%Y-%m-%d').date(),
            grand_total=data['grandTotal']
        )
        db.session.add(new_bill)
        db.session.flush()

        for item_data in data['products']:
            qty = int(item_data['qty'])
            product_to_update = Product.query.filter_by(name=item_data['name']).first()
            if not product_to_update or product_to_update.stock_qty < qty:
                db.session.rollback()
                error_msg = f"Insufficient stock for {item_data['name']}" if product_to_update else f"Product '{item_data['name']}' not found."
                return jsonify({'error': error_msg}), 400
            
            product_to_update.stock_qty -= qty
            db.session.add(product_to_update)

            new_bill_item = BillItem(
                bill_id=new_bill.id,
                product_name=item_data['name'],
                qty=qty,
                rate=float(item_data['rate']),
                amount=float(item_data['amount']),
                gst_percentage=float(item_data['gst'])
            )
            db.session.add(new_bill_item)
        
        db.session.commit()

        # --- Step 4: Generate and Serve PDF ---
        pdf_template_data = {
            'billNumber': formatted_bill_number,
            'customerName': data['customerName'],
            'billDate': data['billDate'],
            'grandTotal': data['grandTotal'],
            'village': data.get('village', 'N/A'),
            'mobileNum': data.get('mobileNum', 'N/A'),
            'products': data['products'],
            'totalBeforeTax': data['totalBeforeTax'],
            'totalGst': data['totalGst'],
            'bill_type': bill_type_key 
        }
        
        html_string = render_template('bill_template.html', bill_data=pdf_template_data)
        pdf_bytes = HTML(string=html_string).write_pdf()
        
        filename = f"bill_{uuid.uuid4().hex}.pdf"
        filepath = os.path.join('temp', filename)
        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)

        return jsonify({'filename': filename}), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error generating PDF for bill: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# New route to serve the temporary PDF file
@app.route('/serve_pdf/<filename>')
@login_required
def serve_pdf(filename):
    filepath = os.path.join('temp', filename)
    if os.path.exists(filepath):
        return send_from_directory('temp', filename, as_attachment=False)
    else:
        return jsonify({'error': 'File not found'}), 404

# MODIFIED: Route now takes a string bill_number
@app.route('/view_bill/<path:bill_number>')
@login_required
def view_bill(bill_number):
    try:
        bill_header = Bill.query.filter_by(bill_number=bill_number).first()
        if not bill_header:
            return "Bill not found.", 404
            
        bill_items_data = db.session.query(
            BillItem, Product.company_name, Product.mfg_date, Product.exp_date,
            Product.batch_num, Product.pack_size, Product.product_type
        ).join(Product, BillItem.product_name == Product.name).filter(
            BillItem.bill_id == bill_header.id
        ).all()
        
        bill_items, product_types = [], []
        for item_obj, company_name, mfg_date, exp_date, batch_num, pack_size, p_type in bill_items_data:
            bill_items.append({
                'name': item_obj.product_name, 'qty': item_obj.qty, 'rate': item_obj.rate,
                'amount': item_obj.amount, 'gst': item_obj.gst_percentage, 'company_name': company_name,
                'mfg_date': mfg_date, 'exp_date': exp_date, 'batch_num': batch_num, 'pack_size': pack_size
            })
            product_types.append(p_type)

        bill_type = 'general'
        if 'pesticide' in product_types: bill_type = 'pesticide'
        elif 'fertilizer' in product_types: bill_type = 'fertilizer'

        bill_data = {
            'billNumber': bill_header.bill_number,
            'customerName': bill_header.customer_name,
            'billDate': bill_header.bill_date.strftime('%Y-%m-%d'),
            'grandTotal': bill_header.grand_total,
            'village': bill_header.customer_village,
            'mobileNum': bill_header.customer_mobile_num,
            'products': bill_items,
            'totalBeforeTax': 0, 'totalGst': 0, 'bill_type': bill_type
        }
        
        for item in bill_items:
            base_price = item['rate'] / (1 + item['gst'] / 100) if item['gst'] > 0 else item['rate']
            gst_amount_per_item = item['rate'] - base_price
            bill_data['totalBeforeTax'] += base_price * item['qty']
            bill_data['totalGst'] += gst_amount_per_item * item['qty']
            
        html_string = render_template('bill_template.html', bill_data=bill_data)
        pdf_bytes = HTML(string=html_string).write_pdf()
        
        return send_file(
            BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f'bill_{bill_number.replace("/", "_")}.pdf'
        )

    except Exception as e:
        logging.error(f"Error viewing historical bill {bill_number}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ... (The rest of the file from reports_selection onwards remains unchanged) ...
# --- PASTE THE REST OF YOUR ORIGINAL app.py FILE HERE ---
# (from @app.route('/reports') to the end)

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
        query = query.filter(Product.product_type == product_type_filter)

    results = []
    if report_type == 'daily':
        results = query.group_by(Bill.bill_date).order_by(Bill.bill_date).with_entities(
            Bill.bill_date.label('period'), func.sum(BillItem.amount).label('total_sales')
        ).all()
        report_data = [{'period': r.period.strftime('%Y-%m-%d'), 'total_sales': r.total_sales} for r in results]

    elif report_type == 'monthly':
        results = query.group_by(func.strftime('%Y-%m', Bill.bill_date)).order_by(func.strftime('%Y-%m', Bill.bill_date)).with_entities(
            func.strftime('%Y-%m', Bill.bill_date).label('period'), func.sum(BillItem.amount).label('total_sales')
        ).all()
        report_data = [{'period': r.period, 'total_sales': r.total_sales} for r in results]

    elif report_type == 'yearly':
        results = query.group_by(func.strftime('%Y', Bill.bill_date)).order_by(func.strftime('%Y', Bill.bill_date)).with_entities(
            func.strftime('%Y', Bill.bill_date).label('period'), func.sum(BillItem.amount).label('total_sales')
        ).all()
        report_data = [{'period': r.period, 'total_sales': r.total_sales} for r in results]

    elif report_type == 'total_sales_productwise':
        results = query.group_by(BillItem.product_name).order_by(BillItem.product_name).with_entities(
            BillItem.product_name, func.sum(BillItem.qty).label('total_qty'), func.sum(BillItem.amount).label('total_sales')
        ).all()
        report_data = [{'product_name': r.product_name, 'total_qty': r.total_qty, 'total_sales': r.total_sales} for r in results]

    elif report_type == 'num_products_sold':
        results = query.group_by(BillItem.product_name).order_by(BillItem.product_name).with_entities(
            BillItem.product_name, func.sum(BillItem.qty).label('total_qty')
        ).all()
        report_data = [{'product_name': r.product_name, 'total_qty': r.total_qty} for r in results]

    else:
        logging.warning(f"Invalid report type requested: {report_type}")
        return jsonify({'error': 'Invalid report type'}), 400

    logging.info(f"Generated sales report '{report_type}' with {len(report_data)} rows.")
    return jsonify(report_data), 200

# New routes for invoice management
@app.route('/upload_invoice_form')
@login_required
@admin_only
def upload_invoice_form():
    return render_template('upload_invoice_form.html')

@app.route('/upload_invoice', methods=['POST'])
@login_required
@admin_only
def upload_invoice():
    if 'invoice' not in request.files:
        logging.warning("No file part in upload_invoice request.")
        return "No file part", 400
    file = request.files['invoice']
    if file.filename == '':
        logging.warning("No selected file in upload_invoice request.")
        return "No selected file", 400
    if file and file.filename.endswith('.pdf'):
        original_filename = secure_filename(file.filename)
        stored_filename = f"{uuid.uuid4().hex}.pdf" # Generate unique filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
        file.save(filepath)
        logging.info(f"Uploaded file '{original_filename}' saved as '{stored_filename}'.")

        try:
            # New: Create Invoice instance and add to session
            new_invoice = Invoice(
                original_filename=original_filename,
                stored_filename=stored_filename,
                upload_date=datetime.date.today().strftime('%Y-%m-%d')
            )
            db.session.add(new_invoice)
            db.session.commit()
            logging.info(f"Invoice record for '{original_filename}' added to database.")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error saving invoice record to DB: {e}")
            # Consider deleting the uploaded file if DB commit fails
            if os.path.exists(filepath):
                os.remove(filepath)
                logging.info(f"Rolled back file upload due to DB error: {filepath}")
            return jsonify({'error': str(e)}), 500

        return redirect(url_for('uploaded_invoices'))
    logging.warning(f"Invalid file type uploaded: {file.filename}")
    return "Invalid file type. Only PDF files are allowed.", 400

@app.route('/uploaded_invoices')
@login_required
@admin_only
def uploaded_invoices():
    invoices = []
    try:
        # New: Query invoices using SQLAlchemy
        invoices_data = Invoice.query.order_by(Invoice.upload_date.desc()).all()
        for invoice in invoices_data:
            invoices.append({
                'original_filename': invoice.original_filename,
                'stored_filename': invoice.stored_filename,
                'upload_date': invoice.upload_date
            })
        logging.info(f"Fetched {len(invoices)} uploaded invoices.")
    except Exception as e:
        logging.error(f"Error fetching uploaded invoices: {e}")
    return render_template('uploaded_invoices.html', invoices=invoices)

@app.route('/view_uploaded_invoice/<stored_filename>')
@login_required
@admin_only
def view_uploaded_invoice(stored_filename):
    logging.info(f"Serving uploaded invoice: '{stored_filename}'.")
    return send_from_directory(app.config['UPLOAD_FOLDER'], stored_filename)


# New routes for user management
@app.route('/user_management')
@login_required
@admin_only
def user_management():
    users = []
    try:
        # New: Query users using SQLAlchemy
        users_data = User.query.all()
        for user in users_data:
            users.append({'id': user.id, 'username': user.username, 'role': user.role})
        logging.info(f"Fetched {len(users)} users for management.")
    except Exception as e:
        logging.error(f"Error fetching users for management: {e}")
    return render_template('user_management.html', users=users)

@app.route('/add_user_form')
@login_required
@admin_only
def add_user_form():
    return render_template('add_user_form.html')
    
@app.route('/add_user', methods=['POST'])
@login_required
@admin_only
def add_user():
    username = request.form['username']
    password = request.form['password']
    role = request.form['role']

    if not username or not password or not role:
        logging.warning("Attempted to add user with empty fields.")
        return "Username, password, and role cannot be empty.", 400

    try:
        # New: Check if username already exists using SQLAlchemy
        if User.query.filter_by(username=username).first():
            logging.warning(f"Attempted to add existing username: '{username}'.")
            return "Username already exists. Please choose a different username.", 400

        # New: Create new User instance and hash password
        new_user = User(username=username, role=role)
        new_user.password = password # This calls the setter to hash the password
        
        db.session.add(new_user)
        db.session.commit()
        logging.info(f"User '{username}' with role '{role}' added successfully.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error adding user '{username}': {e}")
        return jsonify({'error': str(e)}), 500
    return redirect(url_for('user_management'))

@app.route('/edit_user_form/<int:user_id>')
@login_required
@admin_only
def edit_user_form(user_id):
    # New: Query user by ID
    user = User.query.get(user_id)

    if user:
        logging.info(f"Fetched user ID {user_id} for editing.")
        return render_template('edit_user_form.html', user=user)
    else:
        logging.warning(f"User with ID {user_id} not found for editing.")
        return "User not found.", 404
    
@app.route('/update_user', methods=['POST'])
@login_required
@admin_only
def update_user():
    user_id = request.form['user_id']
    new_username = request.form['username']
    new_role = request.form['role']
    new_password = request.form['password'] # This will be the plain text password if provided

    if not new_username or not new_role:
        logging.warning(f"Attempted to update user ID {user_id} with empty username or role.")
        return "Username and role cannot be empty.", 400

    try:
        # New: Fetch user to update
        user = User.query.get(user_id)
        if not user:
            logging.warning(f"User ID {user_id} not found for update.")
            return jsonify({'error': 'User not found.'}), 404

        # Check if the username is being changed to an existing one (excluding the current user)
        existing_user_with_new_username = User.query.filter(
            User.username == new_username,
            User.id != user_id
        ).first()
        if existing_user_with_new_username:
            logging.warning(f"Attempted to change username to existing one: '{new_username}' for user ID {user_id}.")
            return "Username already exists. Please choose a different username.", 400

        user.username = new_username
        user.role = new_role

        if new_password:
            user.password = new_password # This calls the setter to hash the new password
            logging.info(f"User ID {user_id} updated (username, role, and password changed).")
        else:
            logging.info(f"User ID {user_id} updated (username and role changed, password unchanged).")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating user ID {user_id}: {e}")
        return jsonify({'error': str(e)}), 500
    return redirect(url_for('user_management'))
