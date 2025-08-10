# File: app.py

from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for, session, g, send_from_directory
import datetime
from weasyprint import HTML
import os
import uuid
from functools import wraps
from io import BytesIO
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import logging

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# DB config: use DATABASE_URL env var if set, otherwise local sqlite
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///billing_software.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
logging.info(f"Flask app initialized with secret key (first 8 chars): {app.secret_key[:8]}...")

# Upload folders
UPLOAD_FOLDER = 'invoices_uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists('temp'):
    os.makedirs('temp')

db = SQLAlchemy(app)

# -------------------------
# Models
# -------------------------
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    company_name = db.Column(db.Text)
    product_type = db.Column(db.Text, nullable=False)  # 'fertilizer' or 'pesticide' (or other)
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
    bill_number = db.Column(db.Integer, nullable=False, unique=True)
    customer_name = db.Column(db.Text, nullable=False)
    customer_village = db.Column(db.Text)
    customer_mobile_num = db.Column(db.Text)
    bill_date = db.Column(db.Date, nullable=False)
    grand_total = db.Column(db.Float, nullable=False)

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
    _password_hash = db.Column('password', db.Text, nullable=False)
    role = db.Column(db.Text, nullable=False)  # 'admin' or 'user'

    @property
    def password(self):
        raise AttributeError("Password is write-only")

    @password.setter
    def password(self, pwd):
        self._password_hash = generate_password_hash(pwd)

    def verify_password(self, pwd):
        return check_password_hash(self._password_hash, pwd)

    def __repr__(self):
        return f"<User {self.username}>"

class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.Text, nullable=False)
    stored_filename = db.Column(db.Text, nullable=False)
    upload_date = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f"<Invoice {self.original_filename}>"

# -------------------------
# Helper: renumber bills permanently
# -------------------------
def renumber_bills():
    """
    Permanently renumbers bills starting from 1 ordered by bill_date asc then id asc.
    Updates Setting 'last_bill_number' to highest new number.
    """
    try:
        bills = Bill.query.order_by(Bill.bill_date.asc(), Bill.id.asc()).all()
        n = 1
        for b in bills:
            b.bill_number = n
            n += 1
        db.session.commit()
        # Update setting
        setting = Setting.query.filter_by(key='last_bill_number').first()
        if setting:
            setting.value = n - 1
            db.session.add(setting)
            db.session.commit()
        else:
            db.session.add(Setting(key='last_bill_number', value=n - 1))
            db.session.commit()
        logging.info(f"Renumbered bills 1..{n-1}")
    except Exception as e:
        db.session.rollback()
        logging.exception("Failed to renumber bills")

# -------------------------
# DB init
# -------------------------
def init_db():
    with app.app_context():
        db.create_all()
        # seed default users and setting if missing
        if not User.query.filter_by(username='admin').first():
            u = User(username='admin', role='admin')
            u.password = 'admin123'
            db.session.add(u)
        if not User.query.filter_by(username='user').first():
            u = User(username='user', role='user')
            u.password = 'user123'
            db.session.add(u)
        if not Setting.query.filter_by(key='last_bill_number').first():
            db.session.add(Setting(key='last_bill_number', value=0))
        db.session.commit()
        # ensure bills are sequential at startup
        try:
            renumber_bills()
        except Exception:
            logging.exception("Renumber on startup failed")

# -------------------------
# Auth decorators
# -------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            logging.warning(f"Access denied: not logged in for {request.path}")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_only(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            logging.warning(f"Access denied: user '{session.get('username')}' not admin for {request.path}")
            return "Access Denied. Admins only.", 403
        return f(*args, **kwargs)
    return decorated

@app.before_request
def before_request():
    g.role = session.get('role')

# -------------------------
# Routes (kept original functionality + new bills split)
# -------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.verify_password(password):
            session['username'] = username
            session['role'] = user.role
            logging.info(f"User '{username}' logged in as {user.role}")
            if user.role == 'admin':
                return redirect(url_for('dashboard'))
            return redirect(url_for('billing_selection'))
        else:
            return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')

@app.route('/logout')
def logout():
    user = session.pop('username', None)
    session.pop('role', None)
    logging.info(f"User '{user}' logged out")
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

# --- BILLS selection and listing ---

# Keep endpoint name 'bills' to match your existing templates (url_for('bills'))
@app.route('/bills')
@login_required
def bills():
    # selection page with fertilizer/pesticide cards
    return render_template('bills_selection.html')

# List bills filtered by product type
@app.route('/bills/<product_type>')
@login_required
def bills_by_type(product_type):
    if product_type not in ('fertilizer', 'pesticide'):
        return redirect(url_for('bills'))
    return render_template('bills.html', product_type=product_type)

# Get bills (optionally filter by product_type query param)
@app.route('/get_bills')
@login_required
def get_bills():
    product_type = request.args.get('product_type')
    try:
        if product_type in ('fertilizer', 'pesticide'):
            # only bills that include at least one item whose product has the requested product_type
            bills_q = db.session.query(Bill).join(BillItem, Bill.id == BillItem.bill_id).join(
                Product, BillItem.product_name == Product.name
            ).filter(Product.product_type == product_type).distinct().order_by(Bill.bill_number.desc())
            bills = bills_q.all()
        else:
            bills = Bill.query.order_by(Bill.bill_number.desc()).all()

        out = []
        for b in bills:
            out.append({
                'bill_number': b.bill_number,
                'customer_name': b.customer_name,
                'bill_date': b.bill_date.strftime('%Y-%m-%d'),
                'grand_total': b.grand_total
            })
        return jsonify(out)
    except Exception as e:
        logging.exception("Failed to fetch bills")
        return jsonify({'error': 'Failed to fetch bills'}), 500

# Cancel bill (admin only) -> revert stock, delete bill+items, renumber
@app.route('/cancel_bill/<int:bill_number>', methods=['POST'])
@login_required
@admin_only
def cancel_bill(bill_number):
    try:
        bill = Bill.query.filter_by(bill_number=bill_number).first()
        if not bill:
            return jsonify({'error': 'Bill not found'}), 404

        items = BillItem.query.filter_by(bill_id=bill.id).all()
        for item in items:
            product = Product.query.filter_by(name=item.product_name).first()
            if product:
                product.stock_qty += item.qty
                db.session.add(product)
            else:
                raise ValueError(f"Product '{item.product_name}' not found while cancelling")
            db.session.delete(item)

        db.session.delete(bill)
        db.session.commit()

        # Permanently renumber remaining bills
        renumber_bills()
        return jsonify({'success': 'Bill cancelled and bills renumbered'}), 200
    except ValueError as ve:
        db.session.rollback()
        logging.error(str(ve))
        return jsonify({'error': str(ve)}), 500
    except Exception as e:
        db.session.rollback()
        logging.exception("Unexpected error during cancellation")
        return jsonify({'error': 'Unexpected error'}), 500

# -------------------------
# Inventory & product routes (unchanged behavior)
# -------------------------
@app.route('/inventory')
@login_required
@admin_only
def inventory_selection():
    return render_template('inventory_selection.html')

@app.route('/inventory/<product_type>')
@login_required
@admin_only
def inventory(product_type):
    products = []
    try:
        products_q = Product.query.filter_by(product_type=product_type).order_by(Product.name.asc()).all()
        for p in products_q:
            products.append({
                'id': p.id,
                'name': p.name,
                'company_name': p.company_name,
                'product_type': p.product_type,
                'mfg_date': p.mfg_date,
                'exp_date': p.exp_date,
                'batch_num': p.batch_num,
                'hsn_code': p.hsn_code,
                'pack_size': p.pack_size,
                'rate': p.rate,
                'stock_qty': p.stock_qty,
                'gst_percentage': p.gst_percentage
            })
    except Exception:
        logging.exception("Error fetching inventory")
    return render_template('inventory.html', products=products, product_type=product_type)

@app.route('/add_product', methods=['POST'])
@login_required
@admin_only
def add_product_web():
    data = request.form
    try:
        rate = float(data['rate'])
        stock_qty = int(data['stock_qty'])
        gst = float(data['gst_percentage'])
    except Exception:
        return jsonify({'error': 'Invalid numeric inputs'}), 400
    if rate < 0 or stock_qty < 0 or gst < 0:
        return jsonify({'error': 'Negative values not allowed'}), 400
    try:
        p = Product(
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
            gst_percentage=gst
        )
        db.session.add(p)
        db.session.commit()
        return redirect(url_for('inventory', product_type=data['product_type']))
    except Exception as e:
        db.session.rollback()
        logging.exception("Error adding product")
        return jsonify({'error': str(e)}), 400

@app.route('/edit_product_form/<int:product_id>')
@login_required
@admin_only
def edit_product_form(product_id):
    product = Product.query.get(product_id)
    if not product:
        return "Product not found", 404
    return render_template('edit_product_form.html', product=product)

@app.route('/update_product', methods=['POST'])
@login_required
@admin_only
def update_product():
    data = request.form
    try:
        rate = float(data['rate'])
        stock_qty = int(data['stock_qty'])
        gst = float(data['gst_percentage'])
    except Exception:
        return jsonify({'error': 'Invalid numeric inputs'}), 400
    product = Product.query.get(data['product_id'])
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    try:
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
        product.gst_percentage = gst
        db.session.commit()
        return redirect(url_for('inventory', product_type=product.product_type))
    except Exception:
        db.session.rollback()
        logging.exception("Error updating product")
        return jsonify({'error': 'Update failed'}), 400

# -------------------------
# Billing (generate_pdf) - unchanged except uses Setting for bill numbering
# -------------------------
@app.route('/billing')
@login_required
def billing_selection():
    return render_template('billing_selection.html')

@app.route('/billing/<product_type>')
@login_required
def billing(product_type):
    products_list = []
    try:
        products_q = Product.query.filter_by(product_type=product_type).order_by(Product.name.asc()).all()
        for p in products_q:
            products_list.append({'id': p.id, 'name': p.name, 'company_name': p.company_name})
    except Exception:
        logging.exception("Error fetching billing products")
    return render_template('billing.html', products=products_list, today_date=datetime.date.today(), product_type=product_type)

@app.route('/product/<int:product_id>')
@login_required
def get_product_details(product_id):
    try:
        p = Product.query.get(product_id)
        if not p:
            return jsonify({'error': 'Product not found'}), 404
        return jsonify({
            'id': p.id,
            'name': p.name,
            'company_name': p.company_name,
            'product_type': p.product_type,
            'mfg_date': p.mfg_date,
            'exp_date': p.exp_date,
            'batch_num': p.batch_num,
            'hsn_code': p.hsn_code,
            'pack_size': p.pack_size,
            'rate': p.rate,
            'stock_qty': p.stock_qty,
            'gst_percentage': p.gst_percentage
        })
    except Exception:
        logging.exception("Error getting product details")
        return jsonify({'error': 'Error'}), 500

@app.route('/generate_pdf', methods=['POST'])
@login_required
def generate_pdf():
    data = request.json
    try:
        # get and increment last bill number setting
        s = Setting.query.filter_by(key='last_bill_number').first()
        if not s:
            s = Setting(key='last_bill_number', value=0)
            db.session.add(s)
            db.session.commit()
        new_num = s.value + 1
        s.value = new_num
        db.session.add(s)

        # create bill header
        nbill = Bill(
            bill_number=new_num,
            customer_name=data['customerName'],
            customer_village=data.get('village', 'N/A'),
            customer_mobile_num=data.get('mobileNum', 'N/A'),
            bill_date=datetime.datetime.strptime(data['billDate'], '%Y-%m-%d').date(),
            grand_total=data['grandTotal']
        )
        db.session.add(nbill)
        db.session.flush()  # get nbill.id

        # items + stock update
        for it in data['products']:
            qty = int(it['qty'])
            rate = float(it['rate'])
            amount = float(it['amount'])
            gst = float(it['gst'])
            if qty <= 0 or rate < 0 or amount < 0 or gst < 0:
                db.session.rollback()
                return jsonify({'error': 'Invalid product values'}), 400
            prod = Product.query.filter_by(name=it['name']).first()
            if not prod:
                db.session.rollback()
                return jsonify({'error': f"Product {it['name']} not found"}), 404
            if prod.stock_qty < qty:
                db.session.rollback()
                return jsonify({'error': f"Insufficient stock for {it['name']}. Available {prod.stock_qty}"}), 400
            prod.stock_qty -= qty
            db.session.add(prod)
            bi = BillItem(
                bill_id=nbill.id,
                product_name=it['name'],
                qty=qty,
                rate=rate,
                amount=amount,
                gst_percentage=gst
            )
            db.session.add(bi)

        db.session.commit()

        # determine bill_type for template
        product_names = [it['name'] for it in data['products']]
        bill_type = 'general'
        if product_names:
            types = db.session.query(Product.product_type).filter(Product.name.in_(product_names)).distinct().all()
            t_list = [t[0] for t in types]
            if 'pesticide' in t_list:
                bill_type = 'pesticide'
            elif 'fertilizer' in t_list:
                bill_type = 'fertilizer'

        pdf_template_data = {
            'billNumber': new_num,
            'customerName': data['customerName'],
            'billDate': data['billDate'],
            'grandTotal': data['grandTotal'],
            'village': data.get('village', 'N/A'),
            'mobileNum': data.get('mobileNum', 'N/A'),
            'products': data['products'],
            'totalBeforeTax': data.get('totalBeforeTax', 0),
            'totalGst': data.get('totalGst', 0),
            'bill_type': bill_type
        }
        html_string = render_template('bill_template.html', bill_data=pdf_template_data)
        pdf_bytes = HTML(string=html_string).write_pdf()
        filename = f"bill_{uuid.uuid4().hex}.pdf"
        with open(os.path.join('temp', filename), 'wb') as f:
            f.write(pdf_bytes)
        return jsonify({'filename': filename}), 200
    except Exception:
        db.session.rollback()
        logging.exception("Error generating PDF")
        return jsonify({'error': 'Error generating PDF'}), 500

@app.route('/serve_pdf/<filename>')
@login_required
def serve_pdf(filename):
    path = os.path.join('temp', filename)
    if os.path.exists(path):
        return send_from_directory('temp', filename, as_attachment=False)
    return jsonify({'error': 'File not found'}), 404

@app.route('/view_bill/<int:bill_number>')
@login_required
def view_bill(bill_number):
    try:
        bill = Bill.query.filter_by(bill_number=bill_number).first()
        if not bill:
            return "Bill not found", 404

        # get items with product details
        items_q = db.session.query(
            BillItem, Product.company_name, Product.mfg_date, Product.exp_date,
            Product.batch_num, Product.pack_size, Product.product_type
        ).join(Product, BillItem.product_name == Product.name).filter(BillItem.bill_id == bill.id).all()

        items = []
        types = []
        for bi, company_name, mfg, exp, batch, pack, ptype in items_q:
            items.append({
                'name': bi.product_name,
                'qty': bi.qty,
                'rate': bi.rate,
                'amount': bi.amount,
                'gst': bi.gst_percentage,
                'company_name': company_name,
                'mfg_date': mfg,
                'exp_date': exp,
                'batch_num': batch,
                'pack_size': pack
            })
            types.append(ptype)

        bill_type = 'general'
        if 'pesticide' in types:
            bill_type = 'pesticide'
        elif 'fertilizer' in types:
            bill_type = 'fertilizer'

        bill_data = {
            'billNumber': bill.bill_number,
            'customerName': bill.customer_name,
            'billDate': bill.bill_date.strftime('%Y-%m-%d'),
            'grandTotal': bill.grand_total,
            'village': bill.customer_village,
            'mobileNum': bill.customer_mobile_num,
            'products': items,
            'totalBeforeTax': 0,
            'totalGst': 0,
            'bill_type': bill_type
        }

        # recalc totals
        for it in items:
            gst_percentage = it['gst']
            if gst_percentage > 0:
                base_price = it['rate'] / (1 + gst_percentage / 100)
                gst_amount = it['rate'] - base_price
            else:
                base_price = it['rate']
                gst_amount = 0
            bill_data['totalBeforeTax'] += base_price * it['qty']
            bill_data['totalGst'] += gst_amount * it['qty']

        html_string = render_template('bill_template.html', bill_data=bill_data)
        pdf_bytes = HTML(string=html_string).write_pdf()
        return send_file(BytesIO(pdf_bytes), mimetype='application/pdf', as_attachment=False,
                         download_name=f'bill_{bill_number}.pdf')
    except Exception:
        logging.exception("Error viewing bill")
        return jsonify({'error': 'Error viewing bill'}), 500

# -------------------------
# Reports, invoices, users - left intact (keep behavior)
# -------------------------
@app.route('/reports')
@login_required
@admin_only
def reports_selection():
    return render_template('reports_selection.html')

@app.route('/reports/<product_type>')
@login_required
@admin_only
def reports(product_type):
    products = []
    try:
        products_q = Product.query.filter_by(product_type=product_type).order_by(Product.name.asc()).all()
        products = [p.name for p in products_q]
    except Exception:
        logging.exception("Error fetching report products")
    return render_template('reports.html', products=products, product_type=product_type)

@app.route('/sales_report', methods=['GET'])
@login_required
@admin_only
def sales_report():
    # Implementation unchanged (copied from your existing code)
    report_type = request.args.get('type')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    product_name = request.args.get('product')
    product_type_filter = request.args.get('product_type')

    try:
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except Exception:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD.'}), 400

    query = db.session.query(BillItem, Bill, Product).join(Bill, BillItem.bill_id == Bill.id).join(Product, BillItem.product_name == Product.name).filter(
        Bill.bill_date.between(start_date, end_date)
    )
    if product_name and product_name != 'all':
        query = query.filter(BillItem.product_name == product_name)
    if product_type_filter and product_type_filter != 'all':
        query = query.filter(Product.product_type == product_type_filter)

    try:
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
            return jsonify({'error': 'Invalid report type'}), 400

        return jsonify(report_data), 200
    except Exception:
        logging.exception("Error generating sales report")
        return jsonify({'error': 'Error generating report'}), 500

# Invoice uploads
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
        return "No file part", 400
    file = request.files['invoice']
    if file.filename == '':
        return "No selected file", 400
    if file and file.filename.endswith('.pdf'):
        original = secure_filename(file.filename)
        stored = f"{uuid.uuid4().hex}.pdf"
        path = os.path.join(app.config['UPLOAD_FOLDER'], stored)
        file.save(path)
        try:
            inv = Invoice(original_filename=original, stored_filename=stored, upload_date=datetime.date.today().strftime('%Y-%m-%d'))
            db.session.add(inv)
            db.session.commit()
        except Exception:
            db.session.rollback()
            os.remove(path)
            logging.exception("Failed to save invoice record")
            return jsonify({'error': 'DB error'}), 500
        return redirect(url_for('uploaded_invoices'))
    return "Invalid file type. Only PDF allowed.", 400

@app.route('/uploaded_invoices')
@login_required
@admin_only
def uploaded_invoices():
    invoices = []
    try:
        q = Invoice.query.order_by(Invoice.upload_date.desc()).all()
        for inv in q:
            invoices.append({'original_filename': inv.original_filename, 'stored_filename': inv.stored_filename, 'upload_date': inv.upload_date})
    except Exception:
        logging.exception("Error fetching invoices")
    return render_template('uploaded_invoices.html', invoices=invoices)

@app.route('/view_uploaded_invoice/<stored_filename>')
@login_required
@admin_only
def view_uploaded_invoice(stored_filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], stored_filename)

# User management (unchanged)
@app.route('/user_management')
@login_required
@admin_only
def user_management():
    users = []
    try:
        q = User.query.all()
        for u in q:
            users.append({'id': u.id, 'username': u.username, 'role': u.role})
    except Exception:
        logging.exception("Error fetching users")
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
        return "Fields required", 400
    if User.query.filter_by(username=username).first():
        return "Username exists", 400
    try:
        u = User(username=username, role=role)
        u.password = password
        db.session.add(u)
        db.session.commit()
        return redirect(url_for('user_management'))
    except Exception:
        db.session.rollback()
        logging.exception("Error adding user")
        return jsonify({'error': 'Error'}), 500

@app.route('/edit_user_form/<int:user_id>')
@login_required
@admin_only
def edit_user_form(user_id):
    u = User.query.get(user_id)
    if not u:
        return "User not found", 404
    return render_template('edit_user_form.html', user=u)

@app.route('/update_user', methods=['POST'])
@login_required
@admin_only
def update_user():
    user_id = int(request.form['user_id'])
    new_username = request.form['username']
    new_role = request.form['role']
    new_password = request.form.get('password')
    u = User.query.get(user_id)
    if not u:
        return jsonify({'error': 'User not found'}), 404
    if User.query.filter(User.username == new_username, User.id != user_id).first():
        return "Username already exists", 400
    try:
        u.username = new_username
        u.role = new_role
        if new_password:
            u.password = new_password
        db.session.commit()
        return redirect(url_for('user_management'))
    except Exception:
        db.session.rollback()
        logging.exception("Error updating user")
        return jsonify({'error': 'Error'}), 500


