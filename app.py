from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os
from datetime import datetime

app = Flask(__name__, static_folder='.', static_url_path='')

# Path to the SQLite database file
DATABASE = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            price REAL NOT NULL,
            initial_quantity INTEGER NOT NULL DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            batch_number TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
            UNIQUE(product_id, batch_number)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            bill_date TEXT NOT NULL,
            total_amount REAL NOT NULL,
            discount REAL DEFAULT 0.0,
            tax REAL DEFAULT 0.0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bill_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price_at_purchase REAL NOT NULL,
            FOREIGN KEY (bill_id) REFERENCES bills (id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# ---- ROUTES ----

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


@app.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not all([username, password]):
        return jsonify({'error': 'Username and password are required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
        conn.commit()
        return jsonify({'message': 'User registered successfully'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists'}), 409
    finally:
        conn.close()


@app.route('/login', methods=['POST'])
def login_user():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not all([username, password]):
        return jsonify({'error': 'Username and password are required'}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password)).fetchone()
    conn.close()

    if user:
        return jsonify({'message': 'Login successful', 'username': user['username']}), 200
    else:
        return jsonify({'error': 'Invalid username or password'}), 401


@app.route('/products', methods=['GET'])
def get_products():
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    return jsonify([dict(row) for row in products])


@app.route('/products', methods=['POST'])
def add_product():
    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    price = data.get('price')
    initial_quantity = data.get('initial_quantity', 0)

    if not all([name, price is not None]):
        return jsonify({'error': 'Name and price are required'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO products (name, description, price, initial_quantity) VALUES (?, ?, ?, ?)',
            (name, description, price, initial_quantity)
        )
        product_id = cursor.lastrowid
        conn.commit()

        if initial_quantity > 0:
            batch_number = f"INITIAL-{product_id}"
            cursor.execute(
                'INSERT OR IGNORE INTO inventory (product_id, batch_number, quantity) VALUES (?, ?, ?)',
                (product_id, batch_number, initial_quantity)
            )
            cursor.execute(
                'UPDATE inventory SET quantity = quantity + ? WHERE product_id = ? AND batch_number = ?',
                (initial_quantity, product_id, batch_number)
            )
            conn.commit()

        conn.close()
        return jsonify({'message': 'Product added successfully', 'id': product_id}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Product with this name already exists.'}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    price = data.get('price')

    if not all([name, price is not None]):
        return jsonify({'error': 'Name and price are required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE products SET name = ?, description = ?, price = ? WHERE id = ?',
        (name, description, price, product_id)
    )
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()

    if rows_affected == 0:
        return jsonify({'error': 'Product not found'}), 404
    return jsonify({'message': 'Product updated successfully'}), 200


@app.route('/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()

    if rows_affected == 0:
        return jsonify({'error': 'Product not found'}), 404
    return jsonify({'message': 'Product deleted successfully'}), 200


@app.route('/inventory', methods=['GET'])
def get_inventory():
    conn = get_db_connection()
    inventory = conn.execute('''
        SELECT i.id, p.name AS product_name, p.description, p.price, i.batch_number, i.quantity, i.product_id
        FROM inventory i
        JOIN products p ON i.product_id = p.id
    ''').fetchall()
    conn.close()
    return jsonify([dict(row) for row in inventory])


@app.route('/inventory', methods=['POST'])
def add_or_update_inventory():
    data = request.get_json()
    product_id = data.get('product_id')
    batch_number = data.get('batch_number')
    quantity = data.get('quantity')

    if not all([product_id, batch_number, quantity is not None]):
        return jsonify({'error': 'Product ID, batch number, and quantity are required'}), 400
    if not isinstance(quantity, int) or quantity <= 0:
        return jsonify({'error': 'Quantity must be a positive integer'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    product = conn.execute('SELECT id FROM products WHERE id = ?', (product_id,)).fetchone()
    if not product:
        conn.close()
        return jsonify({'error': 'Product not found'}), 404

    existing_batch = conn.execute(
        'SELECT id, quantity FROM inventory WHERE product_id = ? AND batch_number = ?',
        (product_id, batch_number)
    ).fetchone()

    if existing_batch:
        new_quantity = existing_batch['quantity'] + quantity
        cursor.execute(
            'UPDATE inventory SET quantity = ? WHERE id = ?',
            (new_quantity, existing_batch['id'])
        )
        message = 'Inventory quantity updated successfully'
    else:
        cursor.execute(
            'INSERT INTO inventory (product_id, batch_number, quantity) VALUES (?, ?, ?)',
            (product_id, batch_number, quantity)
        )
        message = 'New inventory batch added successfully'

    conn.commit()
    conn.close()
    return jsonify({'message': message}), 201


@app.route('/inventory/<int:inventory_id>', methods=['DELETE'])
def delete_inventory_batch(inventory_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM inventory WHERE id = ?', (inventory_id,))
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()

    if rows_affected == 0:
        return jsonify({'error': 'Inventory batch not found'}), 404
    return jsonify({'message': 'Inventory batch deleted successfully'}), 200


@app.route('/bill', methods=['POST'])
def generate_bill():
    data = request.get_json()
    customer_name = data.get('customer_name')
    items = data.get('items')
    discount = data.get('discount', 0.0)
    tax_rate = data.get('tax_rate', 0.0)

    if not all([customer_name, items]):
        return jsonify({'error': 'Customer name and items are required for billing'}), 400
    if not isinstance(items, list) or not items:
        return jsonify({'error': 'Items must be a non-empty list'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    total_amount = 0.0
    bill_items_to_insert = []

    try:
        for item in items:
            product_id = item.get('product_id')
            quantity_requested = item.get('quantity')

            if not all([product_id, quantity_requested is not None]):
                raise ValueError("Each item must have product_id and quantity.")
            if not isinstance(quantity_requested, int) or quantity_requested <= 0:
                raise ValueError(f"Invalid quantity for product_id {product_id}.")

            product = conn.execute('SELECT price FROM products WHERE id = ?', (product_id,)).fetchone()
            if not product:
                raise ValueError(f"Product with ID {product_id} not found.")
            product_price = product['price']

            available_inventory = conn.execute(
                'SELECT id, quantity FROM inventory WHERE product_id = ? ORDER BY id ASC',
                (product_id,)
            ).fetchall()

            current_quantity_needed = quantity_requested
            deducted_from_batches = []

            for inv_batch in available_inventory:
                batch_id = inv_batch['id']
                batch_quantity = inv_batch['quantity']

                if current_quantity_needed <= 0:
                    break

                if batch_quantity >= current_quantity_needed:
                    new_batch_quantity = batch_quantity - current_quantity_needed
                    deducted_from_batches.append((new_batch_quantity, batch_id))
                    current_quantity_needed = 0
                else:
                    deducted_from_batches.append((0, batch_id))
                    current_quantity_needed -= batch_quantity

            if current_quantity_needed > 0:
                raise ValueError(f"Insufficient stock for product ID {product_id}.")

            for new_q, b_id in deducted_from_batches:
                if new_q == 0:
                    cursor.execute('DELETE FROM inventory WHERE id = ?', (b_id,))
                else:
                    cursor.execute('UPDATE inventory SET quantity = ? WHERE id = ?', (new_q, b_id))

            item_total = product_price * quantity_requested
            total_amount += item_total
            bill_items_to_insert.append((product_id, quantity_requested, product_price))

        total_amount_after_discount = total_amount * (1 - discount)
        final_total_amount = total_amount_after_discount * (1 + tax_rate)

        bill_date = datetime.now().isoformat()
        cursor.execute(
            'INSERT INTO bills (customer_name, bill_date, total_amount, discount, tax) VALUES (?, ?, ?, ?, ?)',
            (customer_name, bill_date, final_total_amount, discount, tax_rate)
        )
        bill_id = cursor.lastrowid

        for product_id, quantity, price_at_purchase in bill_items_to_insert:
            cursor.execute(
                'INSERT INTO bill_items (bill_id, product_id, quantity, price_at_purchase) VALUES (?, ?, ?, ?)',
                (bill_id, product_id, quantity, price_at_purchase)
            )

        conn.commit()
        conn.close()
        return jsonify({'message': 'Bill generated successfully', 'bill_id': bill_id, 'total_amount': final_total_amount}), 201

    except ValueError as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500


@app.route('/bills', methods=['GET'])
def get_bills():
    conn = get_db_connection()
    bills = conn.execute('SELECT * FROM bills ORDER BY bill_date DESC').fetchall()
    bills_data = []

    for bill in bills:
        bill_dict = dict(bill)
        items = conn.execute('''
            SELECT bi.quantity, bi.price_at_purchase, p.name AS product_name, p.description
            FROM bill_items bi
            JOIN products p ON bi.product_id = p.id
            WHERE bi.bill_id = ?
        ''', (bill['id'],)).fetchall()
        bill_dict['items'] = [dict(item) for item in items]
        bills_data.append(bill_dict)

    conn.close()
    return jsonify(bills_data)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
