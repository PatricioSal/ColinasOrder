import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, user='openpg', password='openpgpwd', database='whatsapp_orders')
cur = conn.cursor()
cur.execute("SELECT id, name, sku, qty_per_case, uom FROM products WHERE sku IN ('11694','03003','03131') OR name ILIKE '%ribeye%' OR name ILIKE '%chicken thigh%' OR name ILIKE '%wagyu%'")
for r in cur.fetchall():
    print(r)
cur.close()
conn.close()
