import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    dbname=os.getenv('DB_NAME', 'whatsapp_orders'),
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', ''),
    port=int(os.getenv('DB_PORT', 5432))
)
cur = conn.cursor()
cur.execute("DELETE FROM orders WHERE status = 'pending_review'")
deleted = cur.rowcount
conn.commit()
cur.close()
conn.close()
print(f"Cleared {deleted} pending test order(s) from DB.")
