
from flask import Flask, render_template_string, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///catalog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = "secret"
db = SQLAlchemy(app)

# -----------------------
# Database Models
# -----------------------
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(250), nullable=True)

class ProductVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=False)
    field_name = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# -----------------------
# Routes
# -----------------------
@app.route('/')
def index():
    products = Product.query.all()
    return render_template_string(TEMPLATES['index'], products=products)

@app.route('/product/<int:product_id>')
def view_product(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template_string(TEMPLATES['view'], product=product)

@app.route('/product/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        description = request.form['description']
        image_url = request.form['image_url']
        product = Product(name=name, price=price, description=description, image_url=image_url)
        db.session.add(product)
        db.session.commit()
        flash("Product added successfully!", "success")
        return redirect(url_for('index'))
    return render_template_string(TEMPLATES['add'])

@app.route('/product/<int:product_id>/edit', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        # Log changes for versioning
        for field in ['name', 'price', 'description', 'image_url']:
            old_value = str(getattr(product, field))
            new_value = str(request.form[field])
            if old_value != new_value:
                version = ProductVersion(
                    product_id=product.id,
                    field_name=field,
                    old_value=old_value,
                    new_value=new_value
                )
                db.session.add(version)
                setattr(product, field, request.form[field] if field != 'price' else float(new_value))
        db.session.commit()
        flash("Product updated successfully!", "success")
        return redirect(url_for('view_product', product_id=product.id))
    return render_template_string(TEMPLATES['edit'], product=product)

@app.route('/product/<int:product_id>/delete')
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash("Product deleted successfully!", "success")
    return redirect(url_for('index'))

@app.route('/product/<int:product_id>/history')
def product_history(product_id):
    product = Product.query.get_or_404(product_id)
    history = ProductVersion.query.filter_by(product_id=product_id).order_by(ProductVersion.timestamp.desc()).all()
    return render_template_string(TEMPLATES['history'], product=product, history=history)

@app.route('/product/<int:product_id>/rollback/<int:version_id>')
def rollback_version(product_id, version_id):
    product = Product.query.get_or_404(product_id)
    version = ProductVersion.query.get_or_404(version_id)
    if version.product_id != product.id:
        flash("Invalid rollback attempt.", "danger")
        return redirect(url_for('product_history', product_id=product.id))

    # Perform rollback: set field to old_value
    current_value = str(getattr(product, version.field_name))
    setattr(product, version.field_name, version.old_value if version.field_name != 'price' else float(version.old_value))

    # Log rollback as a new version entry
    rollback_entry = ProductVersion(
        product_id=product.id,
        field_name=version.field_name,
        old_value=current_value,
        new_value=version.old_value
    )
    db.session.add(rollback_entry)
    db.session.commit()

    flash(f"Rolled back {version.field_name} to {version.old_value}.", "success")
    return redirect(url_for('product_history', product_id=product.id))

# -----------------------
# Templates
# -----------------------
TEMPLATES = {}

TEMPLATES['index'] = """
Simple Flask + SQLite product catalog app in a single file.
Features:
- SQLite database (SQLAlchemy)
- CRUD for products (create, read, update, delete)
- Product comparison view (compare two or more products side by side)
- Schema Designer GUI (add / drop / modify columns) with safe SQLite table-recreate migration
- Field value versioning with GUI to view and rollback versions
- Small web UI using Bootstrap served from the same file (render_template_string)

Important notes about Schema Designer:
- Adding columns uses `ALTER TABLE ADD COLUMN` when possible.
- Dropping or modifying column types in SQLite requires creating a new table with the desired schema, copying data over, and replacing the old table. This is implemented here.
- SQLAlchemy model (the `Product` class) will NOT automatically pick up runtime schema changes. After changing schema you should **restart the app** to let SQLAlchemy re-import the model and reflect new columns. The GUI will still show the SQLite schema immediately.

Requirements:
    pip install flask flask_sqlalchemy

Run:
    python product_catalog.py
    then open http://127.0.0.1:5000

"""

from flask import Flask, request, redirect, url_for, render_template_string, flash
from flask_sqlalchemy import SQLAlchemy
from decimal import Decimal
import os
import sqlite3
import re
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'catalog.db')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-secret-change-me'

db = SQLAlchemy(app)

# --- Models -----------------------------------------------------------------
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    category = db.Column(db.String(80), nullable=True)
    image_url = db.Column(db.String(400), nullable=True)

    def price_display(self):
        return f"{self.price_cents / 100:.2f}"

# Version table will be created manually if missing
VERSION_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS product_field_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT,
    changed_by TEXT
)
'''

# --- Database helper --------------------------------------------------------
# @app.before_first_request
# def create_tables():
#     db.create_all()

import sqlite3

def get_sqlite_connection():
    """Open a SQLite connection with row access by column name."""
    conn = sqlite3.connect("catalog.db")
    conn.row_factory = sqlite3.Row
    return conn
        
with app.app_context():
    db.create_all()

with get_sqlite_connection() as conn:
    conn.execute(VERSION_TABLE_SQL)
    conn.commit()

# --- Low-level SQLite helpers -----------------------------------------------
def get_sqlite_connection():
    return sqlite3.connect(DB_PATH)

def get_table_info(table_name='product'):
    # Return list of (cid, name, type, notnull, dflt_value, pk)
    with get_sqlite_connection() as conn:
        cur = conn.execute(f"PRAGMA table_info({table_name})")
        rows = cur.fetchall()
    return rows

def get_create_table_sql(table_name='product'):
    with get_sqlite_connection() as conn:
        cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        row = cur.fetchone()
    return row[0] if row else None

def sanitize_identifier(name):
    # very simple sanitizer for SQL identifiers (columns/table)
    return re.sub(r'[^0-9A-Za-z_]', '_', name)

def add_column_sqlite(table_name, column_name, column_type, default=None):
    column_name = sanitize_identifier(column_name)
    sql_type = column_type.upper()
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"
    if default is not None and default != '':
        sql += f" DEFAULT '{default}'"
    with get_sqlite_connection() as conn:
        conn.execute(sql)
        conn.commit()

def recreate_table_with_schema(table_name, new_columns):
    # new_columns: list of tuples (name, type, dflt)
    # Steps: create temp table, copy matching columns, drop old, rename temp
    temp_name = f"{table_name}_new"
    cols_defs = []
    for name, ctype, dflt in new_columns:
        part = f"{name} {ctype}"
        if dflt is not None and dflt != '':
            part += f" DEFAULT '{dflt}'"
        cols_defs.append(part)
    cols_sql = ", ".join(cols_defs)

    with get_sqlite_connection() as conn:
        cur = conn.cursor()
        # create temp
        cur.execute(f"CREATE TABLE {temp_name} ({cols_sql})")

        # figure out intersection of old and new columns to copy data
        cur.execute(f"PRAGMA table_info({table_name})")
        old_info = cur.fetchall()
        old_cols = [r[1] for r in old_info]
        new_cols = [name for name,_,_ in new_columns]
        common = [c for c in new_cols if c in old_cols]

        if common:
            common_cols_sql = ",".join(common)
            cur.execute(f"INSERT INTO {temp_name} ({common_cols_sql}) SELECT {common_cols_sql} FROM {table_name}")
        # drop old and rename
        cur.execute(f"DROP TABLE {table_name}")
        cur.execute(f"ALTER TABLE {temp_name} RENAME TO {table_name}")
        conn.commit()

# --- Versioning helpers -----------------------------------------------------
def ensure_version_table():
    with get_sqlite_connection() as conn:
        conn.execute(VERSION_TABLE_SQL)
        conn.commit()

def record_field_versions(product_id, diffs, changed_by='web'):
    # diffs: list of (field, old, new)
    if not diffs:
        return
    ensure_version_table()
    now = datetime.utcnow().isoformat()
    with get_sqlite_connection() as conn:
        cur = conn.cursor()
        for field, old, new in diffs:
            cur.execute("INSERT INTO product_field_versions (product_id, field_name, old_value, new_value, changed_at, changed_by) VALUES (?,?,?,?,?,?)",
                        (product_id, field, None if old is None else str(old), None if new is None else str(new), now, changed_by))
        conn.commit()

def get_versions(product_id=None, limit=200):
    ensure_version_table()
    with get_sqlite_connection() as conn:
        cur = conn.cursor()
        if product_id:
            cur.execute("SELECT id, product_id, field_name, old_value, new_value, changed_at, changed_by FROM product_field_versions WHERE product_id=? ORDER BY id DESC LIMIT ?", (product_id, limit))
        else:
            cur.execute("SELECT id, product_id, field_name, old_value, new_value, changed_at, changed_by FROM product_field_versions ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
    return rows

def get_version_by_id(vid):
    ensure_version_table()
    with get_sqlite_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, product_id, field_name, old_value, new_value, changed_at, changed_by FROM product_field_versions WHERE id=?", (vid,))
        row = cur.fetchone()
    return row

def rollback_version(vid, performer='web'):
    v = get_version_by_id(vid)
    if not v:
        raise ValueError('version not found')
    _, product_id, field, old, new, changed_at, changed_by = v
    # set product.field = old
    with get_sqlite_connection() as conn:
        # use parameterized UPDATE
        conn.execute(f"UPDATE product SET {field} = ? WHERE id = ?", (old, product_id))
        conn.commit()
    # record rollback as a new version (old was current value before rollback)
    # fetch current after rollback to capture previous value? Simpler: record that we set field to old
    record_field_versions(product_id, [(field, new, old)], changed_by=performer)

# --- Templates --------------------------------------------------------------
layout = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Product Catalog</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
      <div class="container-fluid">
        <a class="navbar-brand" href="{{ url_for('index') }}">Catalog</a>
        <div class="collapse navbar-collapse">
          <ul class="navbar-nav me-auto">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">Products</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('add_product') }}">Add product</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('compare') }}">Compare</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('schema') }}">Schema Designer</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('versions') }}">Versions</a></li>
          </ul>
        </div>
      </div>
    </nav>

    <div class="container">
      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="alert alert-info">{{ messages[0] }}</div>
        {% endif %}
      {% endwith %}

      {% block content %}{% endblock %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

index_tpl = """
{% extends 'layout' %}
{% block content %}
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h1>Products</h1>
    <form class="d-flex" method="get" action="{{ url_for('index') }}">
      <input class="form-control me-2" name="q" placeholder="Search name or category" value="{{ request.args.get('q','') }}">
      <button class="btn btn-outline-secondary" type="submit">Search</button>
    </form>
  </div>

  {% if products|length == 0 %}
    <p class="text-muted">No products yet. <a href="{{ url_for('add_product') }}">Add one</a>.</p>
  {% else %}
    <form method="get" action="{{ url_for('compare') }}">
      <div class="row row-cols-1 row-cols-md-3 g-3">
        {% for p in products %}
          <div class="col">
            <div class="card h-100">
              {% if p.image_url %}
                <img src="{{ p.image_url }}" class="card-img-top" alt="{{ p.name }}" style="height:200px;object-fit:cover;">
              {% endif %}
              <div class="card-body">
                <h5 class="card-title">{{ p.name }}</h5>
                <h6 class="card-subtitle mb-2 text-muted">{{ p.category or 'Uncategorized' }}</h6>
                <p class="card-text">{{ p.description[:140] }}{% if p.description|length > 140 %}…{% endif %}</p>
                <div class="form-check">
                  <input class="form-check-input" type="checkbox" name="ids" value="{{ p.id }}">
                  <label class="form-check-label">Compare</label>
                </div>
              </div>
              <div class="card-footer d-flex justify-content-between align-items-center">
                <strong class="me-2">€{{ p.price_display() }}</strong>
                <div>
                  <a class="btn btn-sm btn-primary" href="{{ url_for('view_product', product_id=p.id) }}">View</a>
                  <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('edit_product', product_id=p.id) }}">Edit</a>
                  <a class="btn btn-sm btn-danger" href="{{ url_for('delete_product', product_id=p.id) }}" onclick="return confirm('Delete this product?');">Delete</a>
                </div>
              </div>
            </div>
          </div>
        {% endfor %}
      </div>
      <div class="mt-3">
        <button class="btn btn-success" type="submit">Compare Selected</button>
      </div>
    </form>
  {% endif %}
{% endblock %}
"""

view_tpl = """
{% extends 'layout' %}
{% block content %}
  <div class="row">
    <div class="col-md-5">
      {% if product.image_url %}
        <img src="{{ product.image_url }}" alt="{{ product.name }}" class="img-fluid rounded">
      {% else %}
        <div class="border rounded p-5 text-center text-muted">No image</div>
      {% endif %}
    </div>
    <div class="col-md-7">
      <h1>{{ product.name }}</h1>
      <h5 class="text-muted">{{ product.category or 'Uncategorized' }}</h5>
      <p>{{ product.description }}</p>
      <p><strong>Price:</strong> €{{ product.price_display() }}</p>
      <p><strong>Stock:</strong> {{ product.stock }}</p>

      <a class="btn btn-primary" href="{{ url_for('edit_product', product_id=product.id) }}">Edit</a>
      <a class="btn btn-danger" href="{{ url_for('delete_product', product_id=product.id) }}" onclick="return confirm('Delete this product?');">Delete</a>
      <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">Back</a>
    </div>
  </div>
{% endblock %}
"""

form_tpl = """
{% extends 'layout' %}
{% block content %}
  <h1>{{ title }}</h1>
  <form method="post">
    <div class="mb-3">
      <label class="form-label">Name</label>
      <input name="name" class="form-control" required value="{{ product.name if product else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label">Category</label>
      <input name="category" class="form-control" value="{{ product.category if product else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label">Description</label>
      <textarea name="description" class="form-control" rows="4">{{ product.description if product else '' }}</textarea>
    </div>
    <div class="row g-3">
      <div class="col-md-4 mb-3">
        <label class="form-label">Price (e.g. 12.50)</label>
        <input name="price" class="form-control" required value="{{ product.price_display() if product else '' }}">
      </div>
      <div class="col-md-4 mb-3">
        <label class="form-label">Stock</label>
        <input name="stock" type="number" class="form-control" value="{{ product.stock if product else 0 }}">
      </div>
      <div class="col-md-4 mb-3">
        <label class="form-label">Image URL</label>
        <input name="image_url" class="form-control" value="{{ product.image_url if product else '' }}">
      </div>
    </div>

    <button class="btn btn-primary" type="submit">Save</button>
    <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">Cancel</a>
  </form>
{% endblock %}
"""

compare_tpl = """
{% extends 'layout' %}
{% block content %}
  <h1>Compare Products</h1>
  {% if products|length < 2 %}
    <p class="text-muted">Select at least two products to compare from the <a href="{{ url_for('index') }}">product list</a>.</p>
  {% else %}
    <div class="table-responsive">
      <table class="table table-bordered text-center align-middle">
        <thead class="table-light">
          <tr>
            <th>Attribute</th>
            {% for p in products %}
              <th>{{ p.name }}</th>
            {% endfor %}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Image</td>
            {% for p in products %}
              <td>{% if p.image_url %}<img src="{{ p.image_url }}" style="max-height:100px;">{% else %}-{% endif %}</td>
            {% endfor %}
          </tr>
          <tr>
            <td>Category</td>
            {% for p in products %}<td>{{ p.category or '-' }}</td>{% endfor %}
          </tr>
          <tr>
            <td>Description</td>
            {% for p in products %}<td>{{ p.description or '-' }}</td>{% endfor %}
          </tr>
          <tr>
            <td>Price</td>
            {% for p in products %}<td>€{{ p.price_display() }}</td>{% endfor %}
          </tr>
          <tr>
            <td>Stock</td>
            {% for p in products %}<td>{{ p.stock }}</td>{% endfor %}
          </tr>
        </tbody>
      </table>
    </div>
  {% endif %}
{% endblock %}
"""

schema_tpl = """
{% extends 'layout' %}
{% block content %}
  <h1>Schema Designer</h1>
  <p class="text-muted">Modify the <code>product</code> table schema. <strong>Note:</strong> after dropping/modifying columns you should restart the app to reload SQLAlchemy models.</p>

  <div class="row">
    <div class="col-md-6">
      <h4>Current Columns</h4>
      <table class="table table-sm">
        <thead><tr><th>Name</th><th>Type</th><th>NotNull</th><th>PK</th><th>Default</th><th>Actions</th></tr></thead>
        <tbody>
          {% for col in cols %}
            <tr>
              <td>{{ col[1] }}</td>
              <td>{{ col[2] }}</td>
              <td>{{ col[3] }}</td>
              <td>{{ col[5] }}</td>
              <td>{{ col[4] }}</td>
              <td>
                <form method="post" style="display:inline;" action="{{ url_for('drop_column') }}" onsubmit="return confirm('Drop column {{ col[1] }}? This will remove data for that column.');">
                  <input type="hidden" name="col" value="{{ col[1] }}">
                  <button class="btn btn-sm btn-danger" type="submit">Drop</button>
                </form>
                <button class="btn btn-sm btn-outline-secondary" data-bs-toggle="modal" data-bs-target="#modifyModal{{ loop.index }}">Modify</button>

                <!-- Modify modal -->
                <div class="modal fade" id="modifyModal{{ loop.index }}" tabindex="-1" aria-hidden="true">
                  <div class="modal-dialog">
                    <div class="modal-content">
                      <form method="post" action="{{ url_for('modify_column') }}">
                        <div class="modal-header"><h5 class="modal-title">Modify {{ col[1] }}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                        <div class="modal-body">
                          <input type="hidden" name="col_old" value="{{ col[1] }}">
                          <div class="mb-3"><label>New name</label><input name="col_new" class="form-control" value="{{ col[1] }}"></div>
                          <div class="mb-3"><label>Type (e.g. TEXT, INTEGER)</label><input name="col_type" class="form-control" value="{{ col[2] }}"></div>
                          <div class="mb-3"><label>Default (optional)</label><input name="col_default" class="form-control" value="{{ col[4] if col[4] else '' }}"></div>
                        </div>
                        <div class="modal-footer"><button class="btn btn-primary" type="submit">Apply</button></div>
                      </form>
                    </div>
                  </div>
                </div>

              </td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="col-md-6">
      <h4>Add Column</h4>
      <form method="post" action="{{ url_for('add_column') }}">
        <div class="mb-3"><label>Name</label><input name="name" class="form-control" required></div>
        <div class="mb-3"><label>Type</label><input name="type" class="form-control" placeholder="TEXT, INTEGER, REAL" required></div>
        <div class="mb-3"><label>Default (optional)</label><input name="default" class="form-control"></div>
        <button class="btn btn-success" type="submit">Add Column</button>
      </form>

      <hr>
      <h4>Raw CREATE TABLE</h4>
      <pre>{{ create_sql }}</pre>
    </div>
  </div>
{% endblock %}
"""

versions_tpl = """
{% extends 'layout' %}
{% block content %}
  <h1>Field Versions</h1>
  <form method="get" class="row g-2 mb-3">
    <div class="col-auto"><input name="product_id" class="form-control" placeholder="Product ID" value="{{ request.args.get('product_id','') }}"></div>
    <div class="col-auto"><button class="btn btn-secondary" type="submit">Filter</button></div>
    <div class="col-auto"><a class="btn btn-outline-secondary" href="{{ url_for('versions') }}">Clear</a></div>
  </form>
  <table class="table table-sm table-bordered">
    <thead><tr><th>ID</th><th>Product</th><th>Field</th><th>Old</th><th>New</th><th>When</th><th>By</th><th>Actions</th></tr></thead>
    <tbody>
      {% for v in versions %}
        <tr>
          <td>{{ v[0] }}</td>
          <td><a href="{{ url_for('view_product', product_id=v[1]) }}">{{ v[1] }}</a></td>
          <td>{{ v[2] }}</td>
          <td>{{ v[3] }}</td>
          <td>{{ v[4] }}</td>
          <td>{{ v[5] }}</td>
          <td>{{ v[6] }}</td>
          <td>
            <form method="post" action="{{ url_for('rollback') }}" style="display:inline;" onsubmit="return confirm('Rollback this change? This will set the field to the previous value.')">
              <input type="hidden" name="vid" value="{{ v[0] }}">
              <button class="btn btn-sm btn-warning" type="submit">Rollback</button>
            </form>
            <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('version_view', vid=v[0]) }}">View</a>
          </td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
{% endblock %}
"""

version_view_tpl = """
{% extends 'layout' %}
{% block content %}
  <h1>Version {{ v[0] }}</h1>
  <dl class="row">
    <dt class="col-sm-3">Product</dt><dd class="col-sm-9"><a href="{{ url_for('view_product', product_id=v[1]) }}">{{ v[1] }}</a></dd>
    <dt class="col-sm-3">Field</dt><dd class="col-sm-9">{{ v[2] }}</dd>
    <dt class="col-sm-3">Old value</dt><dd class="col-sm-9">{{ v[3] }}</dd>
    <dt class="col-sm-3">New value</dt><dd class="col-sm-9">{{ v[4] }}</dd>
    <dt class="col-sm-3">Changed at</dt><dd class="col-sm-9">{{ v[5] }}</dd>
    <dt class="col-sm-3">Changed by</dt><dd class="col-sm-9">{{ v[6] }}</dd>
  </dl>
  <form method="post" action="{{ url_for('rollback') }}" onsubmit="return confirm('Rollback this change?');">
    <input type="hidden" name="vid" value="{{ v[0] }}">
    <button class="btn btn-warning">Rollback</button>
    <a class="btn btn-outline-secondary" href="{{ url_for('versions') }}">Back</a>
  </form>
{% endblock %}
"""

# Register templates with Flask's template loader
from jinja2 import DictLoader
app.jinja_loader = DictLoader({
    'layout': layout,
    'index.html': index_tpl,
    'view.html': view_tpl,
    'form.html': form_tpl,
    'compare.html': compare_tpl,
    'schema.html': schema_tpl,
    'versions.html': versions_tpl,
    'version_view.html': version_view_tpl,
})

# --- Routes -----------------------------------------------------------------
@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    if q:
        like = f"%{q}%"
        products = Product.query.filter(
            db.or_(Product.name.ilike(like), Product.category.ilike(like))
        ).order_by(Product.id.desc()).all()
    else:
        products = Product.query.order_by(Product.id.desc()).all()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'index.html')[0], products=products)

@app.route('/product/<int:product_id>')
def view_product(product_id):
    p = Product.query.get_or_404(product_id)
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'view.html')[0], product=p)

@app.route('/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        # Read current schema to know columns
        cols_info = get_table_info('product')
        col_names = [c[1] for c in cols_info if c[1] != 'id']

        # Build values dict from form and defaults
        values = {}
        for name in col_names:
            if name == 'price_cents':
                # form uses 'price'
                price_raw = request.form.get('price', '0').strip()
                try:
                    price = Decimal(price_raw)
                    values['price_cents'] = int((price * 100).quantize(Decimal('1')))
                except Exception:
                    flash('Invalid price format')
                    return redirect(url_for('add_product'))
            else:
                values[name] = request.form.get(name, None)

        # Insert via SQLAlchemy for known columns if possible
        p = Product(
            name=values.get('name') or 'Unnamed',
            description=values.get('description'),
            price_cents=values.get('price_cents', 0) or 0,
            stock=int(values.get('stock') or 0),
            category=values.get('category'),
            image_url=values.get('image_url')
        )
        db.session.add(p)
        db.session.commit()

        # For any extra dynamic columns, update directly
        extra_cols = {k: v for k, v in values.items() if k not in ['name','description','price_cents','stock','category','image_url']}
        if extra_cols:
            with get_sqlite_connection() as conn:
                set_clause = ",".join([f"{k}=?" for k in extra_cols.keys()])
                params = list(extra_cols.values()) + [p.id]
                conn.execute(f"UPDATE product SET {set_clause} WHERE id = ?", params)
                conn.commit()

        # record creation versions
        diffs = []
        for k, v in values.items():
            diffs.append((k, None, v))
        record_field_versions(p.id, diffs, changed_by='create')

        flash('Product added')
        return redirect(url_for('index'))

    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'form.html')[0], title='Add product', product=None)

@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    # We'll perform edit via raw SQL to support dynamic columns and capture versions
    cols_info = get_table_info('product')
    col_names = [c[1] for c in cols_info]

    # fetch current row as dict
    with get_sqlite_connection() as conn:
        cur = conn.execute(f"SELECT * FROM product WHERE id = ?", (product_id,))
        row = cur.fetchone()
        if not row:
            return 'Not found', 404
        current = dict(zip([d[0] for d in cur.description], row))

    if request.method == 'POST':
        new_values = {}
        for name in col_names:
            if name == 'id':
                continue
            if name == 'price_cents':
                price_raw = request.form.get('price', '').strip()
                if price_raw == '':
                    # keep existing
                    new_values['price_cents'] = current.get('price_cents')
                else:
                    try:
                        price = Decimal(price_raw)
                        new_values['price_cents'] = int((price * 100).quantize(Decimal('1')))
                    except Exception:
                        flash('Invalid price format')
                        return redirect(url_for('edit_product', product_id=product_id))
            else:
                # prefer form value if present, otherwise current
                if name in request.form:
                    val = request.form.get(name)
                    new_values[name] = val
                else:
                    new_values[name] = current.get(name)

        # compute diffs
        diffs = []
        for name, newv in new_values.items():
            oldv = current.get(name)
            # normalize None/empty
            if oldv is None:
                oldv_norm = None
            else:
                oldv_norm = str(oldv)
            if newv is None:
                newv_norm = None
            else:
                newv_norm = str(newv)
            if oldv_norm != newv_norm:
                diffs.append((name, oldv, newv))

        # apply update via SQL
        set_clause = ",".join([f"{k}=?" for k in new_values.keys()])
        params = list(new_values.values()) + [product_id]
        with get_sqlite_connection() as conn:
            conn.execute(f"UPDATE product SET {set_clause} WHERE id = ?", params)
            conn.commit()

        # record versions
        record_field_versions(product_id, diffs, changed_by='edit')

        flash('Product updated')
        return redirect(url_for('view_product', product_id=product_id))

    # For GET render SQL-backed product to include dynamic fields
    product = SimpleNamespace(**current)
    # For template compatibility, ensure product has expected attributes
    if not hasattr(product, 'price_cents'):
        product.price_cents = 0
    def price_display():
        return f"{product.price_cents/100:.2f}"
    product.price_display = price_display

    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'form.html')[0], title='Edit product', product=product)

from types import SimpleNamespace

@app.route('/delete/<int:product_id>')
def delete_product(product_id):
    p = Product.query.get_or_404(product_id)
    db.session.delete(p)
    db.session.commit()
    flash('Product deleted')
    return redirect(url_for('index'))

@app.route('/compare')
def compare():
    ids = request.args.getlist('ids', type=int)
    if not ids:
        products = []
    else:
        products = Product.query.filter(Product.id.in_(ids)).all()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'compare.html')[0], products=products)

# --- Schema designer routes -----------------------------------------------
@app.route('/schema')
def schema():
    cols = get_table_info('product')
    create_sql = get_create_table_sql('product')
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'schema.html')[0], cols=cols, create_sql=create_sql)

@app.route('/schema/add', methods=['POST'])
def add_column():
    name = sanitize_identifier(request.form.get('name', '').strip())
    ctype = request.form.get('type', 'TEXT').strip().upper()
    dflt = request.form.get('default') or None
    try:
        # SQLite can ALTER TABLE ADD COLUMN
        add_column_sqlite('product', name, ctype, dflt)
        flash(f'Added column {name} {ctype}')
    except Exception as e:
        flash(f'Error adding column: {e}')
    return redirect(url_for('schema'))

@app.route('/schema/drop', methods=['POST'])
def drop_column():
    col = sanitize_identifier(request.form.get('col', ''))
    try:
        # To drop: rebuild table without the column
        old = get_table_info('product')
        new = []
        for cid, name, ctype, notnull, dflt, pk in old:
            if name != col:
                new.append((name, ctype, dflt))
        if len(new) == len(old):
            flash('Column not found')
            return redirect(url_for('schema'))
        recreate_table_with_schema('product', new)
        flash(f'Dropped column {col}.')
    except Exception as e:
        flash(f'Error dropping column: {e}')
    return redirect(url_for('schema'))

@app.route('/schema/modify', methods=['POST'])
def modify_column():
    col_old = sanitize_identifier(request.form.get('col_old', ''))
    col_new = sanitize_identifier(request.form.get('col_new', col_old).strip())
    col_type = request.form.get('col_type', 'TEXT').strip().upper()
    col_default = request.form.get('col_default') or None

    try:
        old = get_table_info('product')
        new = []
        for cid, name, ctype, notnull, dflt, pk in old:
            if name == col_old:
                new.append((col_new, col_type, col_default))
            else:
                new.append((name, ctype, dflt))
        recreate_table_with_schema('product', new)
        flash(f'Modified column {col_old} -> {col_new} ({col_type})')
    except Exception as e:
        flash(f'Error modifying column: {e}')
    return redirect(url_for('schema'))

# --- Versions GUI routes --------------------------------------------------
@app.route('/versions')
def versions():
    pid = request.args.get('product_id', type=int)
    versions = get_versions(product_id=pid, limit=500)
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'versions.html')[0], versions=versions)

@app.route('/version/<int:vid>')
def version_view(vid):
    v = get_version_by_id(vid)
    if not v:
        return 'Not found', 404
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'version_view.html')[0], v=v)

@app.route('/rollback', methods=['POST'])
def rollback():
    vid = int(request.form.get('vid'))
    try:
        rollback_version(vid, performer='web')
        flash('Rolled back version')
    except Exception as e:
        flash(f'Error during rollback: {e}')
    return redirect(url_for('versions'))

# --- API --------------------------------------------------------------------
@app.route('/api/products')
def api_products():
    products = Product.query.all()
    return {
        'products': [
            {
                'id': p.id,
                'name': p.name,
                'description': p.description,
                'price': p.price_cents / 100.0,
                'stock': p.stock,
                'category': p.category,
                'image_url': p.image_url,
            }
            for p in products
        ]
    }

if __name__ == '__main__':
    os.makedirs(BASE_DIR, exist_ok=True)
    print('Starting app — database file:', DB_PATH)
    app.run(debug=True)