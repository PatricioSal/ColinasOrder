"""
whatsapp_webhook.py

Python Flask server that receives incoming WhatsApp messages
from the Node.js whatsapp-web.js listener and processes them
using the existing sales agent logic.

Architecture:
  Node.js (whatsapp_listener.js)
      ↓  POST /webhook  (message arrives)
  Python Flask (this file)
      ↓  parse_message / match_customer / match_item
  PostgreSQL + SQL Server
      ↑  reply string returned in HTTP response
  Node.js sends reply back to WhatsApp

Usage:
  py whatsapp_webhook.py
"""

import os
import sys
import json
import logging
import uuid
import requests
from datetime import datetime
from flask import Flask, request, jsonify, session
from dotenv import load_dotenv

from whatsapp_sales_agent import (
    parse_message,
    match_customer,
    get_customer_history,
    match_item,
    get_db_connection,
)

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
FLASK_PORT       = 5050          # Must match PYTHON_WEBHOOK port in whatsapp_listener.js
NODE_SEND_URL    = 'http://localhost:3000/send'   # Node.js /send endpoint
PUSH_TO_MSSQL    = os.getenv("PUSH_TO_MSSQL", "False").lower() in ("true", "1", "yes")

# ── SQL Server connection string (shared by webhook + dashboard login) ────────
MSSQL_CONN_STR = os.getenv("MSSQL_CONN_STR", "")


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('webhook.log', encoding='utf-8'),
    ]
)
log = logging.getLogger(__name__)

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'wa-order-bot-secret-2024')

# Bot reply prefixes — prevent processing our own replies
BOT_REPLY_PREFIXES = (
    "Draft Sales Order",
    "Order draft processed",
    "Order received but failed",
    "Thank you for your message",
)

def send_whatsapp(chat_id: str, message: str):
    """Send a WhatsApp message via Node.js listener."""
    try:
        resp = requests.post(NODE_SEND_URL, json={"chat_id": chat_id, "message": message}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Failed to send WhatsApp reply: {e}")

# ── Webhook Endpoint ──────────────────────────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True, silent=True) or {}

    sender_phone = data.get('sender_phone', '')
    sender_name  = data.get('sender_name', '') or 'Unknown'
    body         = data.get('body', '').strip()
    chat_id      = data.get('chat_id', '')
    is_group     = data.get('is_group', False)
    timestamp    = data.get('timestamp')
    body         = data.get('body', '')
    has_pdf      = data.get('has_pdf', False)
    pdf_data     = data.get('pdf_data')
    pdf_name     = data.get('pdf_name', 'order.pdf')

    if has_pdf and pdf_data:
        try:
            import fitz
            import base64
            pdf_bytes = base64.b64decode(pdf_data)
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pdf_text = []
            for page in doc:
                pdf_text.append(page.get_text("text"))
            
            extracted_text = "\n".join(pdf_text).strip()
            if extracted_text:
                body = body + f"\n\n[PDF CONTENTS ({pdf_name})]:\n{extracted_text}"
                log.info(f"[WEBHOOK] Extracted {len(extracted_text)} characters from PDF {pdf_name}")
            else:
                log.warning(f"[WEBHOOK] Failed to extract any text from PDF {pdf_name}. Might be an image scan.")
        except Exception as e:
            log.error(f"[WEBHOOK] Failed to process PDF {pdf_name}: {e}")

    if not body:
        return jsonify({"ok": True, "reply": None})

    # Skip bot's own replies
    if any(body.startswith(p) for p in BOT_REPLY_PREFIXES):
        log.info(f"[SKIP] Bot reply loop prevented: '{body[:60]}'")
        return jsonify({"ok": True, "reply": None})

    log.info(f"[WEBHOOK] From '{sender_name}' ({sender_phone}): \"{body}\"")

    try:
        reply = process_order(sender_name, sender_phone, body, chat_id)
        return jsonify({"ok": True, "reply": reply})
    except Exception as e:
        log.exception(f"[ERROR] process_order failed: {e}")
        error_reply = "Sorry, there was an error processing your order. Please contact the sales team."
        return jsonify({"ok": False, "reply": error_reply})

# ── Order Processing ──────────────────────────────────────────────────────────
def process_order(sender_name: str, sender_phone: str, text: str, chat_id: str) -> str:
    """
    Full order processing pipeline.
    Saves order to local PostgreSQL for human review.
    Returns a reply string to send back to WhatsApp.
    """
    conn      = get_db_connection()
    sql_audit = []
    flags     = []

    # 1. Parse message
    log.info("  Parsing message...")
    parsed = parse_message(text)
    log.info(f"  Message type: {parsed['message_type']}")

    if parsed['message_type'] == 'non_order':
        log.info("  Non-order — logging and skipping.")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO orders (customer_id, product_id, quantity, raw_message, source, status, special_instructions, created_at, needs_review) "
            "VALUES (NULL, NULL, NULL, %s, 'whatsapp', 'non_order', NULL, NOW(), FALSE);",
            (text,)
        )
        conn.commit()
        cur.close()
        conn.close()
        return "Thank you for your message. Your inquiry has been logged."

    # 2. Match customer
    parsed_cust_name = parsed['company_name']
    log.info(f"  Matching customer: '{parsed_cust_name}' (phone: '{sender_phone}')...")
    customer, confidence, cust_flags = match_customer(conn, parsed_cust_name, sender_phone, sql_audit)
    flags.extend(cust_flags)
    log.info(f"  Customer: '{customer['name']}' (ID: {customer['id']}, conf: {confidence})")

    # 3. Order history
    history = get_customer_history(conn, customer['id'], sql_audit)

    # 4. Match items
    order_lines = []
    has_errors  = bool(cust_flags)

    log.info(f"  Items parsed: {len(parsed['items'])}")
    for item in parsed['items']:
        log.info(f"    Matching '{item['name']}' x{item['qty']} (SKU: {item.get('sku')})...")
        product, item_flags = match_item(conn, item['name'], history, sql_audit, sku=item.get('sku'))
        flags.extend(item_flags)
        if item_flags or not product:
            has_errors = True

        if product:
            log.info(f"    -> {product['name']} (SKU: {product['sku']}, ${product['price']:.2f})")
            order_lines.append({
                "product_id": product['id'],
                "item_name":  product['name'],
                "original_name": item['name'],
                "sku":        product['sku'],
                "qty":        item['qty'],
                "uom":        item.get('uom', 'EA'),
                "secondary_qty": item.get('secondary_qty', 0.0),
                "price":      float(product['price']),
                "total":      float(product['price']) * item['qty'],
                "notes":      ", ".join(item_flags) if item_flags else "Matched directly",
            })
        else:
            log.info(f"    -> NO MATCH for '{item['name']}'")
            order_lines.append({
                "product_id": None,
                "item_name":  item['name'],
                "original_name": item['name'],
                "sku":        "UNKNOWN",
                "qty":        item['qty'],
                "uom":        item.get('uom', 'EA'),
                "secondary_qty": item.get('secondary_qty', 0.0),
                "price":      0.0,
                "total":      0.0,
                "notes":      ", ".join(item_flags),
            })

    # 5. Write to local PostgreSQL with a shared batch_id
    #    All lines from this WhatsApp message share the same batch_id so the
    #    dashboard can group them into a single reviewable order.
    grand_total   = sum(l['total'] for l in order_lines)
    special_instr = parsed['special_instructions'] or 'None'
    delivery_info = parsed['delivery_info'] or 'None specified'
    batch_id      = str(uuid.uuid4())

    log.info(f"  Writing {len(order_lines)} lines to local DB (batch {batch_id[:8]}, total: ${grand_total:.2f})...")
    cur = conn.cursor()
    # Ensure extra columns exist (idempotent migrations)
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS batch_id UUID;")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS sender_name  VARCHAR(200);")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS sender_phone VARCHAR(50);")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_overrides JSONB;")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS line_note TEXT;")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS uom VARCHAR(50);")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS secondary_qty NUMERIC;")
    for line in order_lines:
        needs_review = has_errors or (
            "direct" not in line['notes'].lower() and
            "history" not in line['notes'].lower()
        )
        cur.execute(
            "INSERT INTO orders (customer_id, product_id, quantity, raw_message, source, status, "
            "                   special_instructions, created_at, needs_review, batch_id,"
            "                   sender_name, sender_phone, line_note, uom, secondary_qty) "
            "VALUES (%s, %s, %s, %s, 'whatsapp', 'pending_review', %s, NOW(), %s, %s, %s, %s, %s, %s, %s);",
            (customer['id'], line['product_id'], line['qty'], text,
             special_instr, needs_review, batch_id, sender_name, sender_phone, line['original_name'], line['uom'], line['secondary_qty'])
        )
    conn.commit()
    cur.close()
    conn.close()
    log.info("  Local DB write complete — awaiting human review.")

    # 6. Print sales draft to log
    _print_draft(customer, sender_phone, confidence, order_lines, grand_total, delivery_info, flags)

    # 7. Reply to WhatsApp — order queued for review, NOT yet confirmed
    flag_note = " Some items may need manual verification." if flags else ""
    return (
        f"\u2705 Order received! {len(order_lines)} item(s), estimated total: ${grand_total:.2f}.\n"
        f"A team member will review and confirm your order shortly.{flag_note}"
    )


def next_business_day():
    """Returns the next Mon-Fri after today (skips Sat/Sun)."""
    from datetime import date, timedelta
    d = date.today() + timedelta(days=1)
    while d.weekday() >= 5:   # 5 = Saturday, 6 = Sunday
        d += timedelta(days=1)
    return d


def _push_to_mssql(conn, customer, order_lines, grand_total, special_instr, flags, overrides=None):
    """Push draft order to remote SQL Server. Returns reply string."""
    try:
        import pyodbc
        ms = pyodbc.connect(MSSQL_CONN_STR, timeout=5)
        ms.autocommit = False
        cur = ms.cursor()

        # ── 1. Pull customer pre-fill from SQL Server ─────────────────────────
        cur.execute("""
            SELECT CustomerName, CustomerShortName, CustomerTaxID,
                   CustomerAddress1, CustomerAddress2, CustomerCounty,
                   CustomerCity, CustomerState, CustomerCountry, CustomerZipcode,
                   PaymentTermsID, DeliveryTermsID, SalesmanID,
                   Phone, DeliveryNotes
            FROM Tbl_Sales_Customers
            WHERE CustomerID = ?
        """, (customer['id'],))
        cust_row = cur.fetchone()

        if cust_row:
            (cust_name, cust_short, cust_tax,
             addr1, addr2, county, city, state, country, zipcode,
             pay_terms, del_terms, salesman_id,
             cust_phone, del_notes) = cust_row
        else:
            # Fallback to what we already know if customer not found in MSSQL
            cust_name   = customer['name']
            cust_short  = customer['name']
            cust_tax    = None
            addr1 = addr2 = county = city = state = country = zipcode = None
            pay_terms = del_terms = salesman_id = None
            cust_phone  = None
            del_notes   = None

        # Apply any overrides from the dashboard review tab
        if overrides:
            cust_name   = overrides.get('name', cust_name)
            cust_tax    = overrides.get('tax_id', cust_tax)
            addr1       = overrides.get('address1', addr1)
            addr2       = overrides.get('address2', addr2)
            city        = overrides.get('city', city)
            state       = overrides.get('state', state)
            country     = overrides.get('country', country)
            zipcode     = overrides.get('zipcode', zipcode)
            pay_terms   = overrides.get('payment_terms', pay_terms)
            del_terms   = overrides.get('delivery_terms', del_terms)
            salesman_id = overrides.get('salesman_id', salesman_id)
            cust_phone  = overrides.get('phone', cust_phone)
            del_notes   = overrides.get('delivery_notes', del_notes)

        # ── 2. Calculate next business day ────────────────────────────────────
        ship_date = next_business_day()

        # ── 3. Get next order number ──────────────────────────────────────────
        cur.execute("SELECT ISNULL(MAX(SalesOrderNo), 0) FROM Tbl_Sales_SalesOrder")
        new_order_no = int(cur.fetchone()[0]) + 1

        safe_notes = (special_instr or '')[:200]
        log.info(f"  [MSSQL] Pre-fill: {cust_name} | {addr1}, {city}, {state} {zipcode} | "
                 f"PayTerms={pay_terms} | DelTerms={del_terms} | Salesman={salesman_id} | Ship={ship_date}")

        # ── 4. Insert sales order header with all pre-filled fields ───────────
        cur.execute("""
            INSERT INTO Tbl_Sales_SalesOrder (
                SalesOrderNo, CustomerID,
                CustomerName, CustomerTaxID,
                CustomerAddress1, CustomerAddress2, CustomerCounty,
                CustomerCity, CustomerState, CustomerCountry, CustomerZipcode,
                PaymentTermsID, DeliveryTermsID, SalesmanID,
                CustomerContactName,
                DateIssued, ShipDate, RequiredDate,
                IsRelease, MadeBy, Cancel,
                Subtotal, Tax, Total, Notes
            ) VALUES (
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?,
                GETDATE(), ?, ?,
                0, 0, 0,
                ?, 0.00, ?, ?
            )
        """, (
            new_order_no, customer['id'],
            (cust_name or '')[:100], (cust_tax or '')[:50],
            (addr1 or '')[:150], (addr2 or '')[:150], (county or '')[:100],
            (city or '')[:100], (state or '')[:50], (country or '')[:50], (zipcode or '')[:20],
            pay_terms, del_terms, salesman_id,
            (cust_short or '')[:100],
            ship_date, ship_date,
            grand_total, grand_total, safe_notes
        ))

        cur.execute("SELECT @@IDENTITY")
        sales_order_id = int(cur.fetchone()[0])

        # ── 5. Insert order detail lines ──────────────────────────────────────
        for idx, line in enumerate(order_lines, 1):
            if line['product_id']:
                uom_raw = line.get('uom', 'EA').upper()
                qty = float(line.get('qty', 0.0))
                sec_qty = float(line.get('secondary_qty', 0.0))
                
                if uom_raw in ['CSE', 'CASE', 'CS']:
                    qty_cs = qty
                    qty_lb = sec_qty
                elif uom_raw in ['LB', 'LBS']:
                    qty_cs = 0.0
                    qty_lb = qty
                else:
                    qty_cs = 0.0
                    qty_lb = qty
                    
                # Use the product's designated UofM from the database
                uom_db = line.get('product_uom', 'CASE (CS)')

                # Fetch the official unit cost (LastCost) from MSSQL materials
                cur.execute("SELECT TOP 1 LastCost FROM Tbl_WH_Materials WHERE MaterialID = ?", (line['product_id'],))
                cost_row = cur.fetchone()
                unit_cost = float(cost_row[0]) if cost_row and cost_row[0] is not None else 0.0

                cur.execute("""
                    INSERT INTO Tbl_Sales_SalesOrder_Details (
                        SalesOrderID, ItemNo, MaterialID, PartNo, Description,
                        QuantityCs, Quantity,
                        UnitPrice, Amount, UofM, IsTaxable, UnitCost, Notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """, (
                    sales_order_id, idx, line['product_id'],
                    line['sku'][:50], line['item_name'][:200],
                    qty_cs, qty_lb,
                    line['price'], line['total'], uom_db, unit_cost,
                    line['notes'][:100]
                ))

        ms.commit()
        cur.close()
        ms.close()
        log.info(f"  [MSSQL] Draft created: SalesOrderID={sales_order_id}, No={new_order_no}, ShipDate={ship_date}")

        reply = f"📋 Draft Sales Order #{new_order_no} created! (ID: {sales_order_id}) Ship: {ship_date.strftime('%a %b %d')}"
        if flags:
            reply += " ⚠️ Needs review."
        return reply

    except Exception as e:
        log.error(f"  [MSSQL ERROR] {e}")
        return "Order received but failed to save to remote database. Please contact sales team."



def _print_draft(customer, phone, confidence, order_lines, grand_total, delivery_info, flags):
    log.info("\n" + "=" * 60)
    log.info("  SALES DRAFT")
    log.info("=" * 60)
    log.info(f"  Customer : {customer['name']} (ID: {customer['id']}) [{confidence}]")
    log.info(f"  Phone    : {phone or customer.get('phone', 'N/A')}")
    for i, line in enumerate(order_lines, 1):
        log.info(f"  Line {i}   : {line['item_name']} x{line['qty']} @ ${line['price']:.2f} = ${line['total']:.2f} [{line['notes']}]")
    log.info(f"  Total    : ${grand_total:.2f}")
    log.info(f"  Delivery : {delivery_info}")
    log.info("  Flags:")
    for f in flags:
        log.info(f"    - {f}")
    if not flags:
        log.info("    None — clean order")
    log.info("=" * 60 + "\n")


# ── Health check ──────────────────────────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


# ── Dashboard API Routes ────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def api_login():
    """Test MSSQL connection — called by dashboard Connect button."""
    try:
        import pyodbc
        c = pyodbc.connect(MSSQL_CONN_STR, timeout=5)
        c.close()
        session['connected'] = True
        log.info('[DASHBOARD] Login successful — MSSQL connection verified.')
        return jsonify({'ok': True})
    except Exception as e:
        log.warning(f'[DASHBOARD] Login failed: {e}')
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/orders/pending')
def api_orders_pending():
    """Return pending orders grouped by batch_id, enriched with MSSQL customer profile."""
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT
                o.batch_id::text,
                o.customer_id,
                COALESCE(c.name, 'Unknown Customer') AS customer_name,
                o.raw_message,
                o.special_instructions,
                MIN(o.created_at)                    AS received_at,
                bool_or(o.needs_review)              AS needs_review,
                MAX(o.sender_name)                   AS sender_name,
                MAX(o.sender_phone)                  AS sender_phone,
                json_agg(json_build_object(
                    'id',        o.id,
                    'product',   COALESCE(p.name, o.id::text),
                    'sku',       COALESCE(p.sku, 'UNKNOWN'),
                    'qty',       o.quantity,
                    'price',     COALESCE(p.price, 0),
                    'total',     COALESCE(p.price * o.quantity, 0),
                    'line_note', o.line_note
                ) ORDER BY o.id) AS lines
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            LEFT JOIN products  p ON o.product_id  = p.id
            WHERE o.status = 'pending_review'
              AND o.batch_id IS NOT NULL
            GROUP BY o.batch_id, o.customer_id, c.name, o.raw_message, o.special_instructions
            ORDER BY MIN(o.created_at) ASC;
        """)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = []
        for row in rows:
            d = dict(zip(cols, row))
            if d.get('received_at'):
                d['received_at'] = d['received_at'].isoformat()

            # ── Enrich with MSSQL customer profile ────────────────────────────
            d['customer_details'] = None
            cust_id = d.get('customer_id')
            if cust_id:
                try:
                    import pyodbc
                    ms  = pyodbc.connect(MSSQL_CONN_STR, timeout=4)
                    cur2 = ms.cursor()
                    cur2.execute("""
                        SELECT
                            CustomerName, Phone,
                            CustomerAddress1, CustomerAddress2,
                            CustomerCity, CustomerState, CustomerZipcode, CustomerCountry,
                            PaymentTermsID, DeliveryTermsID,
                            SalesmanID, DeliveryNotes, CustomerTaxID
                        FROM Tbl_Sales_Customers
                        WHERE CustomerID = ?
                    """, (cust_id,))
                    crow = cur2.fetchone()
                    ms.close()
                    if crow:
                        d['customer_details'] = {
                            'name':          crow[0],
                            'phone':         crow[1],
                            'address1':      crow[2],
                            'address2':      crow[3],
                            'city':          crow[4],
                            'state':         crow[5],
                            'zipcode':       crow[6],
                            'country':       crow[7],
                            'payment_terms': crow[8],
                            'delivery_terms':crow[9],
                            'salesman_id':   crow[10],
                            'delivery_notes':crow[11],
                            'tax_id':        crow[12],
                        }
                except Exception as ex:
                    log.warning(f'[API /orders/pending] MSSQL lookup failed: {ex}')
            result.append(d)
        return jsonify(result)
    except Exception as e:
        log.error(f'[API /orders/pending] {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/orders/edit', methods=['POST'])
def api_orders_edit():
    """Update quantities, products, special instructions, or customer details for a pending order."""
    data = request.json or {}
    batch_id = data.get('batch_id')
    lines = data.get('lines', [])
    deleted_lines = data.get('deleted_lines', [])
    special = data.get('special_instructions')
    overrides = data.get('customer_overrides')

    if not batch_id:
        return jsonify({'error': 'Missing batch_id'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        if special is not None:
            cur.execute("UPDATE orders SET special_instructions = %s WHERE batch_id = %s", (special, batch_id))
            
        if overrides is not None:
            cur.execute("UPDATE orders SET customer_overrides = %s WHERE batch_id = %s", (json.dumps(overrides), batch_id))
            
        if deleted_lines:
            cur.execute("DELETE FROM orders WHERE id = ANY(%s) AND batch_id = %s", (deleted_lines, batch_id))
            
        for line in lines:
            line_id = line.get('id')
            qty = line.get('qty')
            prod_id = line.get('product_id')
            note = line.get('line_note')
            
            if line_id is not None:
                updates = []
                params = []
                if qty is not None:
                    updates.append("quantity = %s")
                    params.append(qty)
                if prod_id is not None:
                    updates.append("product_id = %s")
                    params.append(prod_id)
                if note is not None:
                    updates.append("line_note = %s")
                    params.append(note)
                
                if updates:
                    query = f"UPDATE orders SET {', '.join(updates)} WHERE id = %s AND batch_id = %s"
                    params.extend([line_id, batch_id])
                    cur.execute(query, tuple(params))
                
        conn.commit()
        cur.close()
        conn.close()
        log.info(f"[API /orders/edit] Batch {batch_id[:8]} updated. Deleted {len(deleted_lines)} lines.")
        return jsonify({'ok': True})
    except Exception as e:
        log.error(f'[API /orders/edit] {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/orders/confirm', methods=['POST'])
def api_confirm_order():
    """Push a pending order batch to MSSQL and mark it confirmed."""
    data     = request.get_json() or {}
    batch_id = data.get('batch_id')
    if not batch_id:
        return jsonify({'ok': False, 'error': 'batch_id required'}), 400
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT o.id, o.customer_id, c.name AS customer_name,
                   o.product_id, p.name AS product_name, p.sku, p.price,
                   o.quantity, o.special_instructions, o.needs_review,
                   o.customer_overrides, o.uom, o.secondary_qty, p.description
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            LEFT JOIN products  p ON o.product_id  = p.id
            WHERE o.batch_id = %s AND o.status = 'pending_review';
        """, (batch_id,))
        rows = cur.fetchall()
        if not rows:
            cur.close()
            conn.close()
            return jsonify({'ok': False, 'error': 'Order not found or already processed'}), 404

        # Reconstruct data structures for _push_to_mssql
        customer = {'id': rows[0][1], 'name': rows[0][2]}
        order_lines = []
        for r in rows:
            qty   = float(r[7]) if r[7] else 0
            price = float(r[6]) if r[6] else 0.0
            
            desc = r[13] or ""
            product_uom = desc.replace("UM: ", "").strip() if desc.startswith("UM: ") else "CASE (CS)"
            
            order_lines.append({
                'product_id': r[3],
                'item_name':  r[4] or 'Unknown',
                'sku':        r[5] or 'UNKNOWN',
                'qty':        qty,
                'price':      price,
                'total':      price * qty,
                'notes':      'Confirmed via dashboard',
                'uom':        r[11] or 'EA',
                'secondary_qty': float(r[12]) if r[12] else 0.0,
                'product_uom': product_uom
            })
        grand_total   = sum(l['total'] for l in order_lines)
        special_instr = rows[0][8] or 'None'
        overrides     = rows[0][10] if rows[0][10] else None

        # Push to MSSQL
        reply = _push_to_mssql(conn, customer, order_lines, grand_total, special_instr, [], overrides=overrides)

        # Mark all lines confirmed in local DB
        order_ids = [r[0] for r in rows]
        cur.execute(
            "UPDATE orders SET status = 'confirmed' WHERE id = ANY(%s);",
            (order_ids,)
        )
        conn.commit()
        cur.close()
        conn.close()
        log.info(f'[DASHBOARD] Batch {batch_id[:8]} confirmed and pushed to MSSQL.')
        return jsonify({'ok': True, 'reply': reply})
    except Exception as e:
        log.error(f'[API /orders/confirm] {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/orders/reject', methods=['POST'])
def api_reject_order():
    """Hard-delete a pending order batch (no trace kept)."""
    data     = request.get_json() or {}
    batch_id = data.get('batch_id')
    if not batch_id:
        return jsonify({'ok': False, 'error': 'batch_id required'}), 400
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("DELETE FROM orders WHERE batch_id = %s;", (batch_id,))
        conn.commit()
        cur.close()
        conn.close()
        log.info(f'[DASHBOARD] Batch {batch_id[:8]} rejected and deleted.')
        return jsonify({'ok': True})
    except Exception as e:
        log.error(f'[API /orders/reject] {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/status')
def api_status():
    """Live health check for all four services."""
    result = {'flask': True, 'node': False, 'mssql': False, 'postgres': False}
    try:
        r = requests.get('http://localhost:3000/status', timeout=2)
        result['node'] = r.status_code == 200
    except Exception:
        pass
    try:
        import pyodbc
        c = pyodbc.connect(MSSQL_CONN_STR, timeout=3)
        c.close()
        result['mssql'] = True
    except Exception:
        pass
    try:
        c = get_db_connection()
        c.close()
        result['postgres'] = True
    except Exception:
        pass
    return jsonify(result)


@app.route('/api/orders')
def api_orders():
    """Return last 50 orders with customer and product info."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT o.id,
                   COALESCE(c.name, 'Unknown')  AS customer,
                   COALESCE(p.name, '—')        AS product,
                   o.quantity, o.status, o.needs_review,
                   o.raw_message, o.created_at
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            LEFT JOIN products  p ON o.product_id  = p.id
            ORDER BY o.created_at DESC LIMIT 50;
        """)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            if d.get('created_at'):
                d['created_at'] = d['created_at'].isoformat()
            if d.get('quantity') is not None:
                d['quantity'] = float(d['quantity'])
            result.append(d)
        return jsonify(result)
    except Exception as e:
        log.error(f'[API /orders] {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def api_stats():
    """Return aggregate counts for the stats cards."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM orders WHERE created_at::date = CURRENT_DATE) AS orders_today,
                (SELECT COUNT(*) FROM orders WHERE needs_review = TRUE)             AS needs_review,
                (SELECT COUNT(*) FROM customers)                                    AS customers,
                (SELECT COUNT(*) FROM products)                                     AS products;
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({
            'orders_today': row[0],
            'needs_review':  row[1],
            'customers':     row[2],
            'products':      row[3],
        })
    except Exception as e:
        log.error(f'[API /stats] {e}')
        return jsonify({'error': str(e)}), 500



# ── Entry point ───────────────────────────────────────────────────────────────
@app.route('/api/products')
def api_products():
    """Return all known products for dropdown selection."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name, sku, price FROM products ORDER BY name ASC")
        prods = [{'id': r[0], 'name': r[1], 'sku': r[2], 'price': r[3]} for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(prods)
    except Exception as e:
        log.error(f'[API /products] {e}')
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    log.info("=" * 60)
    log.info("  WhatsApp Order Webhook — Python Flask")
    log.info("=" * 60)
    log.info(f"  Listening on:  http://localhost:{FLASK_PORT}/webhook")
    log.info(f"  Health check:  http://localhost:{FLASK_PORT}/health")
    log.info(f"  Push to MSSQL: {PUSH_TO_MSSQL}")
    log.info("=" * 60)
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
