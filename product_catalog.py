"""
Simple Flask + SQLite product catalog app in a single file.
Features:
- SQLite database (SQLAlchemy)
- CRUD for products (create, read, update, delete)
- Small web UI using Bootstrap served from the same file (render_template_string)

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
    price_cents = db.Column(db.Integer, nullable=False, default=0)  # store price as integer cents
    stock = db.Column(db.Integer, nullable=False, default=0)
    category = db.Column(db.String(80), nullable=True)
    image_url = db.Column(db.String(400), nullable=True)

    def price_display(self):
        return f"{self.price_cents / 100:.2f}"

# --- Database helper --------------------------------------------------------
# -- @app.before_first_request
# -- def create_tables():
# --    db.create_all()
with app.app_context():
    db.create_all()
# --- Templates (kept inline so this file is self-contained) -----------------
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

# Register templates with Flask's template loader using a dict loader trick
from jinja2 import DictLoader
app.jinja_loader = DictLoader({
    'layout': layout,
    'index.html': index_tpl,
    'view.html': view_tpl,
    'form.html': form_tpl,
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
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip() or None
        description = request.form.get('description', '').strip() or None
        price_raw = request.form.get('price', '0').strip()
        stock_raw = request.form.get('stock', '0').strip()
        image_url = request.form.get('image_url', '').strip() or None

        try:
            # Normalize price to cents
            price = Decimal(price_raw)
            price_cents = int((price * 100).quantize(Decimal('1')))
        except Exception:
            flash('Invalid price format')
            return redirect(url_for('add_product'))

        try:
            stock = int(stock_raw)
        except Exception:
            stock = 0

        p = Product(name=name, category=category, description=description,
                    price_cents=price_cents, stock=stock, image_url=image_url)
        db.session.add(p)
        db.session.commit()
        flash('Product added')
        return redirect(url_for('index'))

    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'form.html')[0], title='Add product', product=None)

@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    p = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        p.name = request.form.get('name', p.name).strip()
        p.category = request.form.get('category', p.category).strip() or None
        p.description = request.form.get('description', p.description).strip() or None
        price_raw = request.form.get('price', p.price_display()).strip()
        stock_raw = request.form.get('stock', str(p.stock)).strip()
        p.image_url = request.form.get('image_url', p.image_url).strip() or None

        try:
            price = Decimal(price_raw)
            p.price_cents = int((price * 100).quantize(Decimal('1')))
        except Exception:
            flash('Invalid price format')
            return redirect(url_for('edit_product', product_id=product_id))

        try:
            p.stock = int(stock_raw)
        except Exception:
            p.stock = 0

        db.session.commit()
        flash('Product updated')
        return redirect(url_for('view_product', product_id=product_id))

    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'form.html')[0], title='Edit product', product=p)

@app.route('/delete/<int:product_id>')
def delete_product(product_id):
    p = Product.query.get_or_404(product_id)
    db.session.delete(p)
    db.session.commit()
    flash('Product deleted')
    return redirect(url_for('index'))

# --- API (simple JSON endpoints) --------------------------------------------
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
    # Create DB file location if needed
    os.makedirs(BASE_DIR, exist_ok=True)
    print('Starting app — database file:', DB_PATH)
    app.run(debug=True)
