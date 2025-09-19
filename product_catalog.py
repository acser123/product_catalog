from flask import Flask, request, redirect, url_for, render_template_string, flash
from flask_sqlalchemy import SQLAlchemy
from decimal import Decimal
import os
import sqlite3
import re
from datetime import datetime
from types import SimpleNamespace
from jinja2 import DictLoader

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'catalog.db')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-secret-change-me'

db = SQLAlchemy(app)

# Add custom functions to Jinja context for templates
app.jinja_env.globals.update(hasattr=hasattr, getattr=getattr)

# --- Models -----------------------------------------------------------------
# The Product model is no longer explicitly defined.
# The schema is managed dynamically via the schema designer.

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

# Default product table schema, created if it doesn't exist
PRODUCT_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS "product" (
    id INTEGER PRIMARY KEY,
    Vendor_name TEXT
);
'''

# Table to store which columns to display on the index page
DISPLAY_COLUMNS_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS product_display_columns (
    column_name TEXT PRIMARY KEY
);
'''

# --- Low-level SQLite helpers -----------------------------------------------
def get_sqlite_connection():
    """Establishes a connection to the SQLite database.

    Returns:
        sqlite3.Connection: A connection object to the database.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_table_info(table_name='product'):
    """Retrieves schema information for a given table.

    Args:
        table_name (str): The name of the table to inspect.

    Returns:
        list: A list of tuples, where each tuple describes a column
              (cid, name, type, notnull, dflt_value, pk).
    """
    # Return list of (cid, name, type, notnull, dflt_value, pk)
    with get_sqlite_connection() as conn:
        cur = conn.execute(f"PRAGMA table_info({table_name})")
        rows = cur.fetchall()
    return rows

def get_create_table_sql(table_name='product'):
    """Fetches the 'CREATE TABLE' SQL statement for a table.

    Args:
        table_name (str): The name of the table.

    Returns:
        str: The SQL 'CREATE TABLE' statement, or None if the table doesn't exist.
    """
    with get_sqlite_connection() as conn:
        cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        row = cur.fetchone()
    return row[0] if row else None

def sanitize_identifier(name):
    """Sanitizes a string to be a valid SQL identifier.

    Replaces any character that is not a number, letter, or underscore
    with an underscore.

    Args:
        name (str): The identifier to sanitize.

    Returns:
        str: The sanitized identifier.
    """
    # very simple sanitizer for SQL identifiers (columns/table)
    return re.sub(r'[^0-9A-Za-z_]', '_', name)

def add_column_sqlite(table_name, column_name, column_type, default=None):
    """Adds a new column to a table in the SQLite database.

    Args:
        table_name (str): The name of the table to modify.
        column_name (str): The name of the new column.
        column_type (str): The data type of the new column (e.g., 'TEXT', 'INTEGER').
        default (str, optional): The default value for the new column. Defaults to None.
    """
    column_name = sanitize_identifier(column_name)
    sql_type = column_type.upper()
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"
    if default is not None and default != '':
        sql += f" DEFAULT '{default}'"
    with get_sqlite_connection() as conn:
        conn.execute(sql)
        conn.commit()

def recreate_table_with_schema(table_name, new_columns):
    """Recreates a table with a new schema, preserving data from common columns.

    This is used to perform operations not directly supported by ALTER TABLE in SQLite,
    such as dropping a column or changing a column's type.

    Args:
        table_name (str): The name of the table to recreate.
        new_columns (list): A list of tuples, where each tuple is (name, type, default).
    """
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
        new_cols_names = [name for name, _, _ in new_columns]
        common = [c for c in new_cols_names if c in old_cols]

        if common:
            common_cols_sql = ",".join(common)
            cur.execute(f"INSERT INTO {temp_name} ({common_cols_sql}) SELECT {common_cols_sql} FROM {table_name}")
        # drop old and rename
        cur.execute(f"DROP TABLE {table_name}")
        cur.execute(f"ALTER TABLE {temp_name} RENAME TO {table_name}")
        conn.commit()

# --- Versioning helpers -----------------------------------------------------
def ensure_version_table():
    """Ensures the 'product_field_versions' table exists in the database."""
    with get_sqlite_connection() as conn:
        conn.execute(VERSION_TABLE_SQL)
        conn.commit()

def record_field_versions(product_id, diffs, changed_by='web'):
    """Records changes to product fields in the versioning table.

    Args:
        product_id (int): The ID of the product that was changed.
        diffs (list): A list of tuples, each representing a change.
                      Format: (field_name, old_value, new_value).
        changed_by (str, optional): Identifier for who made the change.
                                    Defaults to 'web'.
    """
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

def get_versions(product_id=None, limit=200, sort_by='id', order='desc'):
    """Retrieves version history for products.

    Args:
        product_id (int, optional): If provided, filters versions for a specific product.
                                    Defaults to None.
        limit (int, optional): The maximum number of version records to return.
                               Defaults to 200.
        sort_by (str, optional): The column to sort by. Defaults to 'id'.
        order (str, optional): The sort order ('asc' or 'desc'). Defaults to 'desc'.

    Returns:
        list: A list of rows from the 'product_field_versions' table.
    """
    ensure_version_table()

    valid_columns = ['id', 'product_id', 'field_name', 'old_value', 'new_value', 'changed_at', 'changed_by']
    if sort_by not in valid_columns:
        sort_by = 'id'

    order_sql = 'ASC' if order.lower() == 'asc' else 'DESC'

    with get_sqlite_connection() as conn:
        cur = conn.cursor()

        sql_query = "SELECT id, product_id, field_name, old_value, new_value, changed_at, changed_by FROM product_field_versions"
        params = []

        if product_id:
            sql_query += " WHERE product_id=?"
            params.append(product_id)

        sql_query += f" ORDER BY {sort_by} {order_sql} LIMIT ?"
        params.append(limit)

        cur.execute(sql_query, params)
        rows = cur.fetchall()
    return rows

def get_version_by_id(vid):
    """Retrieves a specific version record by its ID.

    Args:
        vid (int): The ID of the version record.

    Returns:
        sqlite3.Row: The version record, or None if not found.
    """
    ensure_version_table()
    with get_sqlite_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, product_id, field_name, old_value, new_value, changed_at, changed_by FROM product_field_versions WHERE id=?", (vid,))
        row = cur.fetchone()
    return row

def rollback_version(vid, performer='web'):
    """Rolls back a specific field change to its previous value.

    Args:
        vid (int): The ID of the version record to roll back.
        performer (str, optional): Identifier for who is performing the rollback.
                                   Defaults to 'web'.

    Raises:
        ValueError: If the version ID is not found.
    """
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

# --- Database Initialization --------------------------------------------------
with app.app_context():
    with get_sqlite_connection() as conn:
        conn.execute(VERSION_TABLE_SQL)
        # Also ensure the main product table exists with a default schema
        conn.execute(PRODUCT_TABLE_SQL)
        conn.execute(DISPLAY_COLUMNS_TABLE_SQL)
        conn.commit()

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
            <li class="nav-item"><a class="nav-link" href="{{ url_for('display_designer') }}">Display Designer</a></li>
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
      <input class="form-control me-2" name="q" placeholder="Search any text field" value="{{ request.args.get('q','') }}">
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
              <div class="card-body">
                {% for col_name in col_names %}
                  <p class="card-text"><strong>{{ col_name.replace('_', ' ')|title }}:</strong> {{ getattr(p, col_name, 'N/A') }}</p>
                {% endfor %}
                <div class="form-check">
                  <input class="form-check-input" type="checkbox" name="ids" value="{{ p.id }}">
                  <label class="form-check-label">Compare</label>
                </div>
              </div>
              <div class="card-footer d-flex justify-content-between align-items-center">
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
      {% if hasattr(product, 'image_url') and product.image_url %}
        <img src="{{ product.image_url }}" alt="{{ getattr(product, 'name', 'Product image') }}" class="img-fluid rounded">
      {% else %}
        <div class="border rounded p-5 text-center text-muted">No image</div>
      {% endif %}
    </div>
    <div class="col-md-7">
      <h1>{{ getattr(product, 'name', 'Unnamed Product') }}</h1>

      <dl class="row mt-4">
        {% for col in cols %}
          {% set col_name = col[1] %}
          {% if col_name not in ['id', 'name', 'image_url'] %}
            <dt class="col-sm-4">{{ col_name.replace('_', ' ')|title }}</dt>
            <dd class="col-sm-8">
              {% set value = getattr(product, col_name, None) %}
              {% if value is not none %}
                {% if col_name == 'price_cents' %}
                  €{{ '%.2f'|format(value / 100.0) }}
                {% else %}
                  {{ value }}
                {% endif %}
              {% else %}
                <span class="text-muted">N/A</span>
              {% endif %}
            </dd>
          {% endif %}
        {% endfor %}
      </dl>

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
    {% for col in cols %}
      {% set col_name = col[1] %}
      {% set col_type = col[2]|upper %}
      {% set value = getattr(product, col_name, '') if product else '' %}
      {% set label = col_name.replace('_', ' ')|title %}

      <div class="mb-3">
        {# Special handling for price_cents to provide a more user-friendly price field #}
        {% if col_name == 'price_cents' %}
          <label class="form-label">Price (e.g. 12.50)</label>
          <input name="price" class="form-control" value="{{ product.price_display() if product and hasattr(product, 'price_display') else '' }}">

        {% elif 'TEXT' in col_type or 'CHAR' in col_type %}
          <label class="form-label">{{ label }}</label>
          <textarea name="{{ col_name }}" class="form-control" rows="3">{{ value }}</textarea>

        {% else %}
          <label class="form-label">{{ label }}</label>
          {% set input_type = 'number' if 'INT' in col_type else 'text' %}
          <input name="{{ col_name }}" type="{{ input_type }}" class="form-control" value="{{ value }}">
        {% endif %}
      </div>
    {% endfor %}

    <button class="btn btn-primary" type="submit">Save</button>
    <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">Cancel</a>
  </form>
{% endblock %}
"""

designer_tpl = """
{% extends 'layout' %}
{% block content %}
  <h1>Display Designer</h1>
  <p class="text-muted">Select which columns to display on the Products page.</p>
  <form method="post">
    <div class="mb-3">
      {% for col in all_columns %}
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="columns" value="{{ col[1] }}" id="col-{{ col[1] }}" {% if col[1] in selected_columns %}checked{% endif %}>
          <label class="form-check-label" for="col-{{ col[1] }}">
            {{ col[1].replace('_', ' ')|title }}
          </label>
        </div>
      {% endfor %}
    </div>
    <button class="btn btn-primary" type="submit">Save</button>
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
              <th>{{ getattr(p, 'name', 'Unnamed Product') }}</th>
            {% endfor %}
          </tr>
        </thead>
        <tbody>
          {% for col in cols %}
            {% set col_name = col[1] %}
            <tr>
              <td><strong>{{ col_name.replace('_', ' ')|title }}</strong></td>
              {% for p in products %}
                <td>
                  {% set value = getattr(p, col_name, None) %}
                  {% if value is not none %}
                    {% if col_name == 'price_cents' %}
                      €{{ '%.2f'|format(value / 100.0) }}
                    {% elif (col_name == 'image_url' or col_name.endswith('_url')) and (value.startswith('http') or value.startswith('/')) %}
                      <img src="{{ value }}" style="max-height:100px; max-width:150px;" alt="{{ getattr(p, 'name', 'Product image') }}">
                    {% else %}
                      {{ value }}
                    {% endif %}
                  {% else %}
                    -
                  {% endif %}
                </td>
              {% endfor %}
            </tr>
          {% endfor %}
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
    <thead>
      <tr>
        {% set columns = [('id', 'ID'), ('product_id', 'Product'), ('field_name', 'Field'), ('old_value', 'Old'), ('new_value', 'New'), ('changed_at', 'When'), ('changed_by', 'By')] %}
        {% for col, display in columns %}
          <th>
            <a href="{{ url_for('versions', sort=col, order='asc' if sort_by==col and order=='desc' else 'desc', product_id=request.args.get('product_id','')) }}" style="text-decoration: none; color: inherit;">
              {{ display }}
              {% if sort_by == col %}
                <span style="float: right;">{{ '&#9660;' if order == 'desc' else '&#9650;' }}</span>
              {% endif %}
            </a>
          </th>
        {% endfor %}
        <th>Actions</th>
      </tr>
    </thead>
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
    'designer.html': designer_tpl,
})

# --- Routes -----------------------------------------------------------------
@app.route('/')
def index():
    """Displays the list of products, with an optional search query.

    Returns:
        str: Rendered HTML of the product list page.
    """
    q = request.args.get('q', '').strip()
    with get_sqlite_connection() as conn:
        if q:
            # Get text-like columns to search
            cols_info = get_table_info('product')
            text_cols = [c[1] for c in cols_info if 'TEXT' in c[2].upper() or 'CHAR' in c[2].upper()]

            # Build a WHERE clause with ORs for all text columns
            # This is not perfectly safe against a determined attacker if they can control column names.
            # However, column names are sanitized on creation, so this is a reasonable tradeoff.
            where_clauses = [f"LOWER({col}) LIKE ?" for col in text_cols]
            sql_where = " OR ".join(where_clauses)
            params = [f"%{q.lower()}%"] * len(text_cols)

            cur = conn.execute(f"SELECT * FROM product WHERE {sql_where} ORDER BY id DESC", params)
        else:
            cur = conn.execute("SELECT * FROM product ORDER BY id DESC")

        rows = cur.fetchall()
        # Convert rows to list of SimpleNamespace objects to allow dot notation access in template
        products = [SimpleNamespace(**dict(row)) for row in rows]

    # Get the columns to display from the designer settings
    with get_sqlite_connection() as conn:
        cur = conn.execute("SELECT column_name FROM product_display_columns")
        col_names = [row[0] for row in cur.fetchall()]

    # If no columns are selected, default to the first two
    if not col_names:
        cols_info = get_table_info('product')
        col_names = [c[1] for c in cols_info[:2]]

    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'index.html')[0], products=products, col_names=col_names)

@app.route('/product/<int:product_id>')
def view_product(product_id):
    """Displays the details of a single product.

    Args:
        product_id (int): The ID of the product to display.

    Returns:
        str: Rendered HTML of the product detail page, or a 404 error if not found.
    """
    with get_sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM product WHERE id = ?", (product_id,)).fetchone()

    if not row:
        return "Product not found", 404

    product = SimpleNamespace(**dict(row))

    # Helper to safely get attributes, especially for templates
    def _getattr(obj, key, default=''):
        return getattr(obj, key, default)

    cols_info = get_table_info('product')
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'view.html')[0],
                                  product=product,
                                  cols=cols_info,
                                  getattr=_getattr)

@app.route('/add', methods=['GET', 'POST'])
def add_product():
    """Handles the creation of a new product.

    On GET, it displays the form to add a product.
    On POST, it processes the form data and creates the new product.

    Returns:
        werkzeug.wrappers.Response: A redirect to the product list on success.
        str: Rendered HTML of the add product form on GET or validation failure.
    """
    cols_info = get_table_info('product')
    # Exclude 'id' which is autoincrement
    cols_for_form = [c for c in cols_info if c[1] != 'id']

    if request.method == 'POST':
        values = {}
        # Unpack column info correctly using indexing to avoid ambiguity
        for col_info in cols_for_form:
            # c[1] is name, c[2] is type, c[3] is notnull, c[4] is default_value
            col_name = col_info[1]
            col_type = col_info[2]
            not_null = col_info[3]
            dflt_val = col_info[4]
            val = request.form.get(col_name)

            # Special handling for price, assuming a 'price' form field for user convenience
            if col_name == 'price_cents' and 'price' in request.form:
                price_raw = request.form.get('price', '0').strip()
                try:
                    price = Decimal(price_raw)
                    values['price_cents'] = int((price * 100).quantize(Decimal('1')))
                except Exception:
                    flash('Invalid price format for price_cents')
                    return redirect(url_for('add_product'))
                continue

            if val is not None and val != '':
                if 'INT' in col_type.upper():
                    try:
                        values[col_name] = int(val)
                    except (ValueError, TypeError):
                        flash(f"Invalid integer value for {col_name}")
                        return redirect(url_for('add_product'))
                else:
                    values[col_name] = val
            else: # val is missing or empty
                if not_null and dflt_val is None:
                    if 'INT' in col_type.upper():
                        values[col_name] = 0
                    elif 'TEXT' in col_type.upper():
                        values[col_name] = ''
                    else: # Best effort for other types like REAL, etc.
                        values[col_name] = None
                else:
                    values[col_name] = None

        col_names = [sanitize_identifier(k) for k in values.keys()]
        placeholders = ','.join(['?'] * len(values))
        sql = f"INSERT INTO product ({','.join(col_names)}) VALUES ({placeholders})"

        with get_sqlite_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, list(values.values()))
            new_id = cur.lastrowid
            conn.commit()

        # Record creation as a set of field versions
        diffs = [(k, None, v) for k,v in values.items()]
        record_field_versions(new_id, diffs, changed_by='create')

        flash('Product added')
        return redirect(url_for('index'))

    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'form.html')[0], title='Add product', product=None, cols=cols_for_form, getattr=getattr)

@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    """Handles editing an existing product.

    On GET, it displays the form pre-filled with the product's data.
    On POST, it processes the form data and updates the product.

    Args:
        product_id (int): The ID of the product to edit.

    Returns:
        werkzeug.wrappers.Response: A redirect to the product view on success.
        str: Rendered HTML of the edit product form on GET or validation failure.
    """
    cols_info = get_table_info('product')
    cols_for_form = [c for c in cols_info if c[1] != 'id']
    col_map = {c[1]: c for c in cols_info}

    with get_sqlite_connection() as conn:
        current_row = conn.execute("SELECT * FROM product WHERE id = ?", (product_id,)).fetchone()
    if not current_row:
        return "Product not found", 404
    current_values = dict(current_row)

    if request.method == 'POST':
        new_values = {}
        # Unpack column info correctly using indexing to avoid ambiguity
        for col_info in cols_for_form:
            # c[1] is name, c[2] is type, c[3] is notnull, c[4] is default_value
            col_name = col_info[1]
            col_type = col_info[2]
            not_null = col_info[3]
            dflt_val = col_info[4]
            val = request.form.get(col_name)

            if col_name == 'price_cents' and 'price' in request.form:
                price_raw = request.form.get('price', '').strip()
                try:
                    price = Decimal(price_raw)
                    new_values['price_cents'] = int((price * 100).quantize(Decimal('1')))
                except Exception:
                    flash('Invalid price format for price_cents')
                    return redirect(url_for('edit_product', product_id=product_id))
                continue

            if val is not None and val != '':
                if 'INT' in col_type.upper():
                    try:
                        new_values[col_name] = int(val) if val else None
                    except (ValueError, TypeError):
                        flash(f"Invalid integer value for {col_name}")
                        return redirect(url_for('edit_product', product_id=product_id))
                else:
                    new_values[col_name] = val
            else: # val is missing or empty
                if not_null and dflt_val is None:
                    if 'INT' in col_type.upper():
                        new_values[col_name] = 0
                    elif 'TEXT' in col_type.upper():
                        new_values[col_name] = ''
                    else: # Best effort for other types like REAL, etc.
                        new_values[col_name] = None
                else:
                    new_values[col_name] = None

        # Build UPDATE statement
        set_clauses = [f"{sanitize_identifier(k)}=?" for k in new_values.keys()]
        sql = f"UPDATE product SET {','.join(set_clauses)} WHERE id=?"
        params = list(new_values.values()) + [product_id]

        with get_sqlite_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

        # Compute diffs and record versions
        diffs = []
        for name, new_v in new_values.items():
            old_v = current_values.get(name)
            # Compare as strings to handle type differences (e.g. 1 vs '1')
            if str(old_v) != str(new_v):
                diffs.append((name, old_v, new_v))

        if diffs:
            record_field_versions(product_id, diffs, changed_by='edit')

        flash('Product updated')
        return redirect(url_for('view_product', product_id=product_id))

    # GET request: prepare product for template
    product = SimpleNamespace(**current_values)

    # Add a helper for templates to display price from price_cents
    def price_display_helper():
        price_cents = getattr(product, 'price_cents', 0)
        if price_cents is None: return "0.00"
        return f"{price_cents / 100:.2f}"
    product.price_display = price_display_helper

    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'form.html')[0],
                                  title='Edit product',
                                  product=product,
                                  cols=cols_for_form,
                                  getattr=getattr)

@app.route('/delete/<int:product_id>')
def delete_product(product_id):
    """Deletes a product from the catalog.

    Args:
        product_id (int): The ID of the product to delete.

    Returns:
        werkzeug.wrappers.Response: A redirect to the product list.
    """
    with get_sqlite_connection() as conn:
        # Optional: check if product exists before deleting
        cur = conn.execute("SELECT id FROM product WHERE id = ?", (product_id,))
        if cur.fetchone() is None:
            flash('Product not found.')
            return redirect(url_for('index'))

        conn.execute("DELETE FROM product WHERE id = ?", (product_id,))
        conn.commit()

    # Note: versioning for deletes could be implemented here if needed,
    # e.g. by moving the row to an archive table. For now, it's a hard delete.

    flash('Product deleted')
    return redirect(url_for('index'))

@app.route('/compare')
def compare():
    """Displays a side-by-side comparison of selected products.

    Product IDs are passed as query parameters.

    Returns:
        str: Rendered HTML of the product comparison page.
    """
    ids = request.args.getlist('ids', type=int)
    products = []
    if ids:
        # Fetch as dicts to include dynamic columns, not via SQLAlchemy model
        with get_sqlite_connection() as conn:
            # Get column names from the first cursor
            cur = conn.execute("SELECT * FROM product WHERE id = ?", (ids[0],))
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            if row:
                products.append(SimpleNamespace(**dict(zip(cols, row))))

            # Fetch other products
            for pid in ids[1:]:
                cur = conn.execute("SELECT * FROM product WHERE id = ?", (pid,))
                row = cur.fetchone()
                if row:
                    products.append(SimpleNamespace(**dict(zip(cols, row))))

    cols_info = get_table_info('product')
    # Exclude id column from comparison view
    cols_for_table = [c for c in cols_info if c[1] != 'id']
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'compare.html')[0], products=products, cols=cols_for_table, getattr=getattr)

# --- Display designer routes ----------------------------------------------
@app.route('/display-designer', methods=['GET', 'POST'])
def display_designer():
    all_columns = get_table_info('product')

    if request.method == 'POST':
        selected = request.form.getlist('columns')
        with get_sqlite_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM product_display_columns")
            for col_name in selected:
                cur.execute("INSERT INTO product_display_columns (column_name) VALUES (?)", (col_name,))
            conn.commit()
        flash('Display preferences updated')
        return redirect(url_for('display_designer'))

    with get_sqlite_connection() as conn:
        cur = conn.execute("SELECT column_name FROM product_display_columns")
        selected_columns = [row[0] for row in cur.fetchall()]

    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'designer.html')[0], all_columns=all_columns, selected_columns=selected_columns)

# --- Schema designer routes -----------------------------------------------
@app.route('/schema')
def schema():
    """Displays the schema designer page.

    Shows current columns of the 'product' table and provides forms
    for adding, modifying, or dropping columns.

    Returns:
        str: Rendered HTML of the schema designer page.
    """
    cols = get_table_info('product')
    create_sql = get_create_table_sql('product')
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'schema.html')[0], cols=cols, create_sql=create_sql)

@app.route('/schema/add', methods=['POST'])
def add_column():
    """Handles the form submission for adding a new column to the 'product' table."""
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
    """Handles the form submission for dropping a column from the 'product' table."""
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
    """Handles the form submission for modifying a column in the 'product' table."""
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
    """Displays the version history of product field changes.

    Can be filtered by product ID via a query parameter.

    Returns:
        str: Rendered HTML of the versions page.
    """
    sort_by = request.args.get('sort', 'id')
    order = request.args.get('order', 'desc')
    pid = request.args.get('product_id', type=int)

    versions_data = get_versions(product_id=pid, limit=500, sort_by=sort_by, order=order)
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'versions.html')[0],
                                  versions=versions_data,
                                  sort_by=sort_by,
                                  order=order)

@app.route('/version/<int:vid>')
def version_view(vid):
    """Displays the details of a single version record.

    Args:
        vid (int): The ID of the version record to display.

    Returns:
        str: Rendered HTML of the version detail page, or 404 if not found.
    """
    v = get_version_by_id(vid)
    if not v:
        return 'Not found', 404
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'version_view.html')[0], v=v)

@app.route('/rollback', methods=['POST'])
def rollback():
    """Handles the form submission to roll back a field change."""
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
    """Provides a JSON API endpoint for all products.

    Returns:
        dict: A dictionary containing a list of all products.
    """
    with get_sqlite_connection() as conn:
        rows = conn.execute("SELECT * FROM product ORDER BY id DESC").fetchall()

    products_list = []
    for row in rows:
        p_dict = dict(row)
        # Handle price conversion if price_cents exists
        if 'price_cents' in p_dict and p_dict['price_cents'] is not None:
            p_dict['price'] = p_dict['price_cents'] / 100.0
        products_list.append(p_dict)

    return {'products': products_list}

if __name__ == '__main__':
    os.makedirs(BASE_DIR, exist_ok=True)
    print('Starting app — database file:', DB_PATH)
    app.run(debug=True)
