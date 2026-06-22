import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import pyodbc
import decimal

import os
from dotenv import load_dotenv

load_dotenv()

PG_USER = os.getenv("DB_USER", "postgres")
PG_PWD = os.getenv("DB_PASSWORD", "openpgpwd")
PG_HOST = os.getenv("DB_HOST", "localhost")
PG_PORT = int(os.getenv("DB_PORT", "5432"))

MSSQL_CONN_STR = os.getenv("MSSQL_CONN_STR", "")

def create_db_if_not_exists():
    print("Connecting to default PostgreSQL database to check/create whatsapp_orders database...")
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PWD,
        database="postgres"
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'whatsapp_orders'")
    exists = cur.fetchone()
    if not exists:
        print("Creating database 'whatsapp_orders'...")
        cur.execute("CREATE DATABASE whatsapp_orders")
    else:
        print("Database 'whatsapp_orders' already exists.")
    cur.close()
    conn.close()

def create_tables(conn):
    print("Creating tables if they do not exist...")
    cur = conn.cursor()
    
    # customers table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        company VARCHAR(255),
        phone VARCHAR(100),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # products table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        sku VARCHAR(100) UNIQUE NOT NULL,
        description TEXT,
        price NUMERIC(10, 2) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS uom VARCHAR(50);")
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS qty_per_case NUMERIC(10, 2);")
    
    # orders table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        customer_id INT REFERENCES customers(id),
        product_id INT REFERENCES products(id),
        quantity_cs NUMERIC(10, 2),
        raw_message TEXT NOT NULL,
        source VARCHAR(50) NOT NULL DEFAULT 'whatsapp',
        status VARCHAR(50) NOT NULL DEFAULT 'pending_review',
        special_instructions TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        needs_review BOOLEAN NOT NULL DEFAULT TRUE
    );
    """)
    
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity NUMERIC;")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS batch_id UUID;")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS sender_name VARCHAR(200);")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS sender_phone VARCHAR(50);")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_overrides JSONB;")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS line_note TEXT;")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS uom VARCHAR(50);")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS unit_price NUMERIC(10, 2);")
    
    # Run rename scripts if columns have the old names
    cur.execute("""
    DO $$
    BEGIN
        IF EXISTS(SELECT * FROM information_schema.columns WHERE table_name='orders' AND column_name='quantity') AND
           NOT EXISTS(SELECT * FROM information_schema.columns WHERE table_name='orders' AND column_name='quantity_cs') THEN
            ALTER TABLE orders RENAME COLUMN quantity TO quantity_cs;
        END IF;
    END $$;
    """)
    cur.execute("""
    DO $$
    BEGIN
        IF EXISTS(SELECT * FROM information_schema.columns WHERE table_name='orders' AND column_name='secondary_qty') AND
           NOT EXISTS(SELECT * FROM information_schema.columns WHERE table_name='orders' AND column_name='quantity') THEN
            ALTER TABLE orders RENAME COLUMN secondary_qty TO quantity;
        END IF;
    END $$;
    """);
    
    # Ensure quantity column exists after any renames have run
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity NUMERIC;")
    
    conn.commit()
    cur.close()

def sync_data(pg_conn):
    print("Connecting to remote SQL Server...")
    ms_conn = pyodbc.connect(MSSQL_CONN_STR, timeout=5)
    ms_cur = ms_conn.cursor()
    
    # 1. Fetch Customers
    print("Syncing Customers...")
    ms_cur.execute("""
        SELECT CustomerID, CustomerName, Phone 
        FROM Tbl_Sales_Customers 
        WHERE Inactive = 0
    """)
    customers = ms_cur.fetchall()
    
    pg_cur = pg_conn.cursor()
    # Delete existing to resync cleanly
    pg_cur.execute("DELETE FROM orders WHERE source = 'sales_order'")
    pg_cur.execute("TRUNCATE customers CASCADE")
    
    count_cust = 0
    for row in customers:
        cid, name, phone = row
        if not name:
            name = f"Customer #{cid}"
        phone = phone.strip() if phone else ""
        # Let's clean phone (keep letters, digits, spaces, hyphens)
        # Check if exists
        pg_cur.execute(
            "INSERT INTO customers (id, name, company, phone) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (cid, name, name, phone)
        )
        count_cust += 1
    print(f"Synced {count_cust} customers.")
    
    # 2. Fetch Products
    print("Syncing Products...")
    pg_cur.execute("TRUNCATE products CASCADE")
    
    ms_cur.execute("""
    SELECT 
      m.MaterialID, 
      m.PartNo, 
      m.MaterialDescription, 
      m.UM, 
      m.PoundsPerCs,
      COALESCE(
        (SELECT TOP 1 sod.UnitPrice 
         FROM Tbl_Sales_SalesOrder_Details sod 
         WHERE sod.MaterialID = m.MaterialID 
         ORDER BY sod.SalesOrderDetailID DESC), 
        10.00
      ) AS Price
    FROM Tbl_WH_Materials m
    WHERE m.Inactive = 0
    """)
    products = ms_cur.fetchall()
    
    count_prod = 0
    for row in products:
        pid, sku, name, um, lbs_per_cs, price = row
        if not name:
            name = f"Material #{pid}"
        if not sku:
            sku = f"SKU-{pid}"
        price_val = float(price) if price is not None else 10.00
        if price_val <= 0:
            price_val = 10.00 # fallback
        
        qty_per_case = float(lbs_per_cs) if lbs_per_cs else 1.0
        
        # Insert or update
        pg_cur.execute(
            "INSERT INTO products (id, name, sku, description, price, uom, qty_per_case) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (pid, name, sku, f"UM: {um}", price_val, um, qty_per_case)
        )
        count_prod += 1
    print(f"Synced {count_prod} products.")
    
    # 3. Fetch recent orders to seed history
    print("Syncing Order History...")
    ms_cur.execute("""
    SELECT TOP 1500
      so.CustomerID,
      sod.MaterialID,
      sod.QuantityCs,
      sod.Quantity,
      so.DateIssued,
      sod.Notes
    FROM Tbl_Sales_SalesOrder_Details sod
    JOIN Tbl_Sales_SalesOrder so ON sod.SalesOrderID = so.SalesOrderID
    WHERE so.CustomerID IN (SELECT CustomerID FROM Tbl_Sales_Customers WHERE Inactive = 0)
      AND sod.MaterialID IN (SELECT MaterialID FROM Tbl_WH_Materials WHERE Inactive = 0)
    ORDER BY so.SalesOrderID DESC
    """)
    orders = ms_cur.fetchall()
    
    count_ord = 0
    for row in orders:
        cid, pid, qty_cs, qty_lbs, date_issued, notes = row
        qty_cs_val = float(qty_cs) if qty_cs else 0.0
        qty_lbs_val = float(qty_lbs) if qty_lbs else 0.0
        special_instr = notes if notes else ""
        date_val = date_issued if date_issued else "NOW()"
        
        pg_cur.execute(
            """
            INSERT INTO orders (customer_id, product_id, quantity_cs, quantity, raw_message, source, status, special_instructions, created_at, needs_review)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (cid, pid, qty_cs_val, qty_lbs_val, "Imported from historical sales orders", "sales_order", "completed", special_instr, date_val, False)
        )
        count_ord += 1
        
    print(f"Synced {count_ord} historical order items.")
    pg_conn.commit()
    pg_cur.close()
    ms_cur.close()
    ms_conn.close()

if __name__ == "__main__":
    create_db_if_not_exists()
    
    # Connect to whatsapp_orders database
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PWD,
        database="whatsapp_orders"
    )
    create_tables(conn)
    
    # MSSQL sync is optional — don't crash setup if ODBC driver is missing or server is unreachable
    try:
        sync_data(conn)
        print("Database sync completed successfully!")
    except Exception as e:
        print(f"\n[WARNING] Remote SQL Server sync skipped: {e}")
        print("  The app will still work. You can sync later from the dashboard settings.")
        print("  If ODBC Driver is not installed, download it from:")
        print("  https://go.microsoft.com/fwlink/?linkid=2266337")
    
    conn.close()
