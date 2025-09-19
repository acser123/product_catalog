# Product Catalog Application

This is a simple, self-contained Flask application for managing a product catalog. It uses SQLite as its database and demonstrates a dynamic schema, allowing users to add, modify, and remove fields from the product model directly through the web interface.

## Features

*   **CRUD Operations**: Create, Read, Update, and Delete products.
*   **Dynamic Schema**: Modify the product table's schema (add/remove/rename columns) directly from the UI.
*   **Versioning**: All changes to product fields are versioned. It's possible to view the history of changes and roll back to a previous version of a field.
*   **Product Comparison**: Select and compare multiple products side-by-side.
*   **JSON API**: A simple API endpoint to fetch all products in JSON format.
*   **Self-Contained**: The application, including HTML templates, is contained within a single Python file.

## Setup and Installation

### Prerequisites

*   Python 3.6+
*   `pip` for installing packages

### Installation

1.  **Clone the repository** (or download the source code).

2.  **Navigate to the project directory**:
    ```bash
    cd /path/to/project
    ```

3.  **Create a virtual environment** (recommended):
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

4.  **Install the required packages**:
    The application requires `Flask` and `Flask-SQLAlchemy`. You can install them using pip:
    ```bash
    pip install Flask Flask-SQLAlchemy
    ```
    Alternatively, you can create a `requirements.txt` file with the following content:
    ```
    Flask
    Flask-SQLAlchemy
    ```
    And then install from the file:
    ```bash
    pip install -r requirements.txt
    ```

## How to Run the Application

Once the setup is complete, you can run the application with the following command:

```bash
python product_catalog.py
```

The application will start a development server, and you can access it by opening your web browser and navigating to:

[http://127.0.0.1:5000](http://127.0.0.1:5000)

A `catalog.db` file will be created in the project directory to store the product data.

## Usage

*   **Home Page**: Lists all products. You can search for products using the search bar.
*   **Add Product**: Click on "Add product" to go to a form for creating a new product.
*   **View/Edit/Delete**: From the product list, you can click to view details, edit, or delete a product.
*   **Compare Products**: On the home page, check the "Compare" box for two or more products and click "Compare Selected" to see a side-by-side comparison.
*   **Schema Designer**: Click on "Schema Designer" to modify the database schema for products. You can add new columns, drop existing ones, or rename them.
*   **Versions**: Click on "Versions" to see a log of all changes made to product data. You can filter by product ID and roll back any change.

## API Endpoint

The application provides a simple JSON API to retrieve all products.

*   **URL**: `/api/products`
*   **Method**: `GET`
*   **Response**:
    ```json
    {
      "products": [
        {
          "id": 1,
          "name": "Laptop",
          "category": "Electronics",
          "price_cents": 120000,
          "price": 1200.00
        }
      ]
    }
    ```
