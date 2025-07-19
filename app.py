# File: backend/app.py

from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for, session, g, send_from_directory
import sqlite3
import datetime
from weasyprint import HTML
import os
import uuid
from functools import wraps
import io
from werkzeug.utils import secure_filename

# Initialize the Flask app
app = Flask(__name__)
app.secret_key = 'your_super_secret_key' # IMPORTANT: Change this to a random, secure key

# Define upload folder
UPLOAD_FOLDER = 'invoices_uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Function to connect to the database and create tables if they don't exist
def init_db():
    conn = sqlite3.connect('billing_software.db')
    cursor = conn.cursor()

    # Create the products table with product_type as a required field
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            company_name TEXT,
            product_type TEXT NOT NULL,
            mfg_date TEXT,
            exp_date TEXT,
            batch_num TEXT,
            hsn_code TEXT,
            pack_size TEXT,
            rate REAL NOT NULL,
            stock_qty INTEGER NOT NULL,
            gst_percentage REAL
        );
    ''')
    
    # Create the bills table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_number INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            bill_date DATE NOT NULL,
            grand_total REAL NOT NULL
        );
    ''')

    # Create a bill_items table to store products for each bill
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bill_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            rate REAL NOT NULL,
            amount REAL NOT NULL,
            gst_percentage REAL NOT NULL,
            FOREIGN KEY (bill_id) REFERENCES bills (id)
        );
    ''')

    # New table to store simple settings like the last bill number
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        );
    ''')
    
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ('last_bill_number', 0))

    # New users table for login
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        );
    ''')
    
    # Seed the database with initial users if they don't exist
    cursor.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", ('admin', 'admin123', 'admin'))
    cursor.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", ('user', 'user123', 'user'))

    # New table to store uploaded invoices
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            upload_date TEXT NOT NULL
        );
    ''')

    conn.commit()
    conn.close()
    
    # Create temp directory for PDFs if it doesn't exist
    if not os.path.exists('temp'):
        os.makedirs('temp')

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Admin-only decorator
def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session.get('role') != 'admin':
            return "Access Denied. You must be an admin to view this page.", 403
        return f(*args, **kwargs)
    return decorated_function

# Before request, make user role available to all templates
@app.before_request
def before_request():
    g.role = session.get('role', None)

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE username = ? AND password = ?", (username, password))
        user_data = cursor.fetchone()
        conn.close()
        
        if user_data:
            session['username'] = username
            session['role'] = user_data[0]
            if session['role'] == 'admin':
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('billing_selection'))
        else:
            return render_template('login.html', error="Invalid credentials. Please try again.")
            
    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    return redirect(url_for('login'))

# Main route to render the dashboard
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

# Route for bills selection
@app.route('/bills')
@login_required
def bills():
    return render_template('bills.html')

# API endpoint to get all bills for searching
@app.route('/get_bills')
@login_required
def get_bills():
    conn = sqlite3.connect('billing_software.db')
    cursor = conn.cursor()
    cursor.execute('SELECT bill_number, customer_name, bill_date, grand_total FROM bills ORDER BY bill_number DESC')
    bills_data = cursor.fetchall()
    conn.close()
    
    bills_list = []
    for bill in bills_data:
        bills_list.append({
            'bill_number': bill[0],
            'customer_name': bill[1],
            'bill_date': bill[2],
            'grand_total': bill[3]
        })
    
    return jsonify(bills_list)

# Route for inventory selection
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
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM products WHERE product_type = ? ORDER BY name ASC;', (product_type,))
        products_data = cursor.fetchall()
        
        # Convert the results to a list of dictionaries for easier use in the template
        for row in products_data:
            products.append({
                'id': row[0],
                'name': row[1],
                'company_name': row[2],
                'product_type': row[3],
                'mfg_date': row[4],
                'exp_date': row[5],
                'batch_num': row[6],
                'hsn_code': row[7],
                'pack_size': row[8],
                'rate': row[9],
                'stock_qty': row[10],
                'gst_percentage': row[11]
            })
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()
    
    return render_template('inventory.html', products=products, product_type=product_type)


# API endpoint to add a new product
@app.route('/add_product', methods=['POST'])
@login_required
@admin_only
def add_product_web():
    data = request.form
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO products (
                name, company_name, product_type, mfg_date, exp_date, batch_num,
                hsn_code, pack_size, rate, stock_qty, gst_percentage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        ''', (
            data['name'], data['company_name'], data['product_type'],
            data['mfg_date'], data['exp_date'], data['batch_num'],
            data['hsn_code'], data['pack_size'], data['rate'],
            data['stock_qty'], data['gst_percentage']
        ))
        conn.commit()
        return redirect(url_for('inventory', product_type=data['product_type']))
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()

# New route to render the edit product form
@app.route('/edit_product_form/<int:product_id>')
@login_required
@admin_only
def edit_product_form(product_id):
    product = None
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        row = cursor.fetchone()
        
        if row:
            product = {
                'id': row[0],
                'name': row[1],
                'company_name': row[2],
                'product_type': row[3],
                'mfg_date': row[4],
                'exp_date': row[5],
                'batch_num': row[6],
                'hsn_code': row[7],
                'pack_size': row[8],
                'rate': row[9],
                'stock_qty': row[10],
                'gst_percentage': row[11]
            }
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()
        
    if product:
        return render_template('edit_product_form.html', product=product)
    else:
        return "Product not found.", 404

# New route to handle the product update
@app.route('/update_product', methods=['POST'])
@login_required
@admin_only
def update_product():
    data = request.form
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        
        product_id = data['product_id']
        product_type = data['product_type']
        
        cursor.execute('''
            UPDATE products SET
                name = ?, company_name = ?, product_type = ?, mfg_date = ?,
                exp_date = ?, batch_num = ?, hsn_code = ?, pack_size = ?,
                rate = ?, stock_qty = ?, gst_percentage = ?
            WHERE id = ?;
        ''', (
            data['name'], data['company_name'], data['product_type'], data['mfg_date'],
            data['exp_date'], data['batch_num'], data['hsn_code'], data['pack_size'],
            data['rate'], data['stock_qty'], data['gst_percentage'], product_id
        ))
        conn.commit()
        return redirect(url_for('inventory', product_type=product_type))
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()
        
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
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        # Fetch products only for the specified product type
        cursor.execute('SELECT id, name, company_name FROM products WHERE product_type = ? ORDER BY name ASC;', (product_type,))
        products = cursor.fetchall()
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()
    
    return render_template('billing.html', products=products, today_date=datetime.date.today(), product_type=product_type)

# New API endpoint to get a single product's details by ID
@app.route('/product/<int:product_id>')
@login_required
def get_product_details(product_id):
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM products WHERE id = ?;', (product_id,))
        product = cursor.fetchone()
        if product:
            product_dict = {
                'id': product[0],
                'name': product[1],
                'company_name': product[2],
                'product_type': product[3],
                'mfg_date': product[4],
                'exp_date': product[5],
                'batch_num': product[6],
                'hsn_code': product[7],
                'pack_size': product[8],
                'rate': product[9],
                'stock_qty': product[10],
                'gst_percentage': product[11]
            }
            return jsonify(product_dict), 200
        else:
            return jsonify({'error': 'Product not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# New API endpoint to generate the PDF bill with a simple, sequential number
@app.route('/generate_pdf', methods=['POST'])
@login_required
def generate_pdf():
    data = request.json
    
    conn = sqlite3.connect('billing_software.db')
    cursor = conn.cursor()
    
    try:
        # Get and increment the last bill number
        cursor.execute("SELECT value FROM settings WHERE key = 'last_bill_number'")
        last_bill_number = cursor.fetchone()[0]
        new_bill_number = last_bill_number + 1
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'last_bill_number'", (new_bill_number,))
        
        # Save the bill to the database
        cursor.execute('INSERT INTO bills (bill_number, customer_name, bill_date, grand_total) VALUES (?, ?, ?, ?);',
                       (new_bill_number, data['customerName'], data['billDate'], data['grandTotal']))
        bill_id = cursor.lastrowid
        
        # Save bill items and update stock
        for item in data['products']:
            cursor.execute('UPDATE products SET stock_qty = stock_qty - ? WHERE name = ?;',
                           (item['qty'], item['name']))
            cursor.execute('''
                INSERT INTO bill_items (bill_id, product_name, qty, rate, amount, gst_percentage)
                VALUES (?, ?, ?, ?, ?, ?);
            ''', (bill_id, item['name'], item['qty'], item['rate'], item['amount'], item['gst']))
            
        conn.commit()

        data['pl_no'] = 'N/A'
        data['sl_no'] = 'N/A'
        data['billNumber'] = new_bill_number
        
        # Render the HTML template with the bill data
        html_string = render_template('bill_template.html', bill_data=data)
        
        # Convert the HTML string to a PDF
        pdf_bytes = HTML(string=html_string).write_pdf()
        
        # Create a unique filename and save the PDF temporarily
        filename = f"bill_{uuid.uuid4().hex}.pdf"
        filepath = os.path.join('temp', filename)
        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)

        return jsonify({'filename': filename}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# New route to serve the temporary PDF file
@app.route('/serve_pdf/<filename>')
@login_required
def serve_pdf(filename):
    filepath = os.path.join('temp', filename)
    if os.path.exists(filepath):
        return send_from_directory('temp', filename, as_attachment=False)
    else:
        return jsonify({'error': 'File not found'}), 404

# New route to view a historical bill
@app.route('/view_bill/<int:bill_number>')
@login_required
def view_bill(bill_number):
    conn = sqlite3.connect('billing_software.db')
    cursor = conn.cursor()
    
    try:
        # Fetch bill header details
        cursor.execute('SELECT id, customer_name, bill_date, grand_total FROM bills WHERE bill_number = ?', (bill_number,))
        bill_header = cursor.fetchone()
        
        if not bill_header:
            return "Bill not found.", 404
            
        bill_id, customer_name, bill_date, grand_total = bill_header
        
        # Fetch all bill items with full product details by joining with the products table
        cursor.execute('''
            SELECT T2.product_name, T2.qty, T2.rate, T2.amount, T2.gst_percentage,
                   T3.company_name, T3.mfg_date, T3.exp_date, T3.batch_num, T3.pack_size
            FROM bill_items AS T2
            INNER JOIN products AS T3 ON T2.product_name = T3.name
            WHERE T2.bill_id = ?
        ''', (bill_id,))
        
        bill_items = cursor.fetchall()
        
        # Reconstruct the bill data dictionary
        bill_data = {
            'billNumber': bill_number,
            'customerName': customer_name,
            'billDate': bill_date,
            'grandTotal': grand_total,
            'village': 'N/A',
            'mobileNum': 'N/A',
            'products': [],
            'totalBeforeTax': 0,
            'totalGst': 0
        }
        
        for item in bill_items:
            product_name, qty, rate, amount, gst_percentage, company_name, mfg_date, exp_date, batch_num, pack_size = item
            
            bill_data['products'].append({
                'name': product_name,
                'qty': qty,
                'rate': rate,
                'amount': amount,
                'gst': gst_percentage,
                'company_name': company_name,
                'mfg_date': mfg_date,
                'exp_date': exp_date,
                'batch_num': batch_num,
                'pack_size': pack_size
            })
            
            # Recalculate totals for display
            base_price = rate / (1 + gst_percentage / 100)
            gst_amount_per_item = rate - base_price
            
            bill_data['totalBeforeTax'] += base_price * qty
            bill_data['totalGst'] += gst_amount_per_item * qty
            
        # Render the HTML template with the reconstructed data
        html_string = render_template('bill_template.html', bill_data=bill_data)
        
        # Convert HTML to PDF
        pdf_bytes = HTML(string=html_string).write_pdf()
        
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f'bill_{bill_number}.pdf'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# Route for sales reports, now handled by the new bills page
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
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM products WHERE product_type = ? ORDER BY name ASC;', (product_type,))
        products = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()
    
    return render_template('reports.html', products=products, product_type=product_type)

# API endpoint for sales reports
@app.route('/sales_report', methods=['GET'])
@login_required
@admin_only
def sales_report():
    report_type = request.args.get('type')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    product_name = request.args.get('product')
    product_type_filter = request.args.get('product_type')

    conn = sqlite3.connect('billing_software.db')
    cursor = conn.cursor()

    query_parts = {
        'select': '',
        'from': """FROM bills T1 INNER JOIN bill_items T2 ON T1.id = T2.bill_id INNER JOIN products T3 ON T2.product_name = T3.name""",
        'where': """WHERE T1.bill_date BETWEEN ? AND ?""",
        'group_by': '',
        'order_by': ''
    }

    params = [start_date, end_date]

    if product_name and product_name != 'all':
        query_parts['where'] += " AND T2.product_name = ?"
        params.append(product_name)

    if product_type_filter and product_type_filter != 'all':
        query_parts['where'] += " AND T3.product_type = ?"
        params.append(product_type_filter)

    if report_type == 'daily':
        query_parts['select'] = "SELECT T1.bill_date as period, SUM(T2.amount) as total_sales"
        query_parts['group_by'] = "GROUP BY period"
        query_parts['order_by'] = "ORDER BY T1.bill_date;"
        
    elif report_type == 'monthly':
        query_parts['select'] = "SELECT strftime('%Y-%m', T1.bill_date) as period, SUM(T2.amount) as total_sales"
        query_parts['group_by'] = "GROUP BY period"
        query_parts['order_by'] = "ORDER BY T1.bill_date;"
        
    elif report_type == 'yearly':
        query_parts['select'] = "SELECT strftime('%Y', T1.bill_date) as period, SUM(T2.amount) as total_sales"
        query_parts['group_by'] = "GROUP BY period"
        query_parts['order_by'] = "ORDER BY T1.bill_date;"
    
    elif report_type == 'total_sales_productwise':
        query_parts['select'] = "SELECT T2.product_name as product_name, SUM(T2.qty) as total_qty, SUM(T2.amount) as total_sales"
        query_parts['group_by'] = "GROUP BY T2.product_name"
        query_parts['order_by'] = "ORDER BY T2.product_name;"
        
    elif report_type == 'num_products_sold':
        query_parts['select'] = "SELECT T2.product_name as product_name, SUM(T2.qty) as total_qty"
        query_parts['group_by'] = "GROUP BY T2.product_name"
        query_parts['order_by'] = "ORDER BY T2.product_name;"
        
    else:
        return jsonify({'error': 'Invalid report type'}), 400

    query = f"{query_parts['select']} {query_parts['from']} {query_parts['where']} {query_parts['group_by']} {query_parts['order_by']}"

    try:
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        report_data = []
        if report_type == 'total_sales_productwise':
            for row in results:
                report_data.append({
                    'product_name': row[0],
                    'total_qty': row[1],
                    'total_sales': row[2]
                })
        elif report_type == 'num_products_sold':
            for row in results:
                report_data.append({
                    'product_name': row[0],
                    'total_qty': row[1]
                })
        else:
            for row in results:
                report_data.append({
                    'period': row[0],
                    'total_sales': row[1],
                })

        return jsonify(report_data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

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
        return "No file part", 400
    file = request.files['invoice']
    if file.filename == '':
        return "No selected file", 400
    if file and file.filename.endswith('.pdf'):
        original_filename = secure_filename(file.filename)
        stored_filename = f"{uuid.uuid4().hex}.pdf"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
        file.save(filepath)
        
        try:
            conn = sqlite3.connect('billing_software.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO invoices (original_filename, stored_filename, upload_date) VALUES (?, ?, ?)",
                           (original_filename, stored_filename, datetime.date.today()))
            conn.commit()
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()
            
        return redirect(url_for('uploaded_invoices'))
    return "Invalid file type. Only PDF files are allowed.", 400

@app.route('/uploaded_invoices')
@login_required
@admin_only
def uploaded_invoices():
    invoices = []
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute("SELECT original_filename, stored_filename, upload_date FROM invoices ORDER BY upload_date DESC")
        invoices_data = cursor.fetchall()
        for row in invoices_data:
            invoices.append({'original_filename': row[0], 'stored_filename': row[1], 'upload_date': row[2]})
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()
    return render_template('uploaded_invoices.html', invoices=invoices)

@app.route('/view_uploaded_invoice/<stored_filename>')
@login_required
@admin_only
def view_uploaded_invoice(stored_filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], stored_filename)


# New routes for user management
@app.route('/user_management')
@login_required
@admin_only
def user_management():
    users = []
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users")
        users_data = cursor.fetchall()
        for row in users_data:
            users.append({'id': row[0], 'username': row[1], 'role': row[2]})
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()
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
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                       (username, password, role))
        conn.commit()
    except sqlite3.IntegrityError:
        return "Username already exists. Please choose a different username.", 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
    return redirect(url_for('user_management'))

@app.route('/edit_user_form/<int:user_id>')
@login_required
@admin_only
def edit_user_form(user_id):
    user = None
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            user = {'id': user_data[0], 'username': user_data[1], 'role': user_data[2]}
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()
    if user:
        return render_template('edit_user_form.html', user=user)
    else:
        return "User not found.", 404
    
@app.route('/update_user', methods=['POST'])
@login_required
@admin_only
def update_user():
    user_id = request.form['user_id']
    new_username = request.form['username']
    new_role = request.form['role']
    new_password = request.form['password']
    
    try:
        conn = sqlite3.connect('billing_software.db')
        cursor = conn.cursor()
        
        # Check if the username is being changed to an existing one
        cursor.execute("SELECT id FROM users WHERE username = ? AND id != ?", (new_username, user_id))
        if cursor.fetchone():
            return "Username already exists. Please choose a different username.", 400
            
        if new_password:
            cursor.execute("UPDATE users SET username = ?, password = ?, role = ? WHERE id = ?",
                           (new_username, new_password, new_role, user_id))
        else:
            cursor.execute("UPDATE users SET username = ?, role = ? WHERE id = ?",
                           (new_username, new_role, user_id))
            
        conn.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
    return redirect(url_for('user_management'))

# This part runs the app
if __name__ == '__main__':
    init_db()
    app.run(debug=False)