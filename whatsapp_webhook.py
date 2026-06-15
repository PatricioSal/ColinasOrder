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
import requests
from datetime import datetime
from flask import Flask, request, jsonify
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

    if not body:
        return jsonify({"ok": True, "reply": None})

    # Skip bot's own replies
    if any(body.startswith(p) for p in BOT_REPLY_PREFIXES):
        log.info(f"[SKIP] Bot reply loop prevented: '{body[:60]}'")
        return jsonify({"ok": True, "reply": None})

    log.info(f"[WEBHOOK] From '{sender_name}' ({sender_phone}): \"{body[:80]}{'...' if len(body)>80 else ''}\"")

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
    Returns a reply string to send back to WhatsApp.
    """
    conn       = get_db_connection()
    sql_audit  = []
    flags      = []

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
    # sender_phone comes directly from WhatsApp metadata — always reliable
    parsed_cust_name = parsed['company_name'] if parsed['company_name'] else sender_name
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
        log.info(f"    Matching '{item['name']}' x{item['qty']}...")
        product, item_flags = match_item(conn, item['name'], history, sql_audit)
        flags.extend(item_flags)
        if item_flags or not product:
            has_errors = True

        if product:
            log.info(f"    -> {product['name']} (SKU: {product['sku']}, ${product['price']:.2f})")
            order_lines.append({
                "product_id": product['id'],
                "item_name":  product['name'],
                "sku":        product['sku'],
                "qty":        item['qty'],
                "price":      float(product['price']),
                "total":      float(product['price']) * item['qty'],
                "notes":      ", ".join(item_flags) if item_flags else "Matched directly",
            })
        else:
            log.info(f"    -> NO MATCH for '{item['name']}'")
            order_lines.append({
                "product_id": None,
                "item_name":  item['name'],
                "sku":        "UNKNOWN",
                "qty":        item['qty'],
                "price":      0.0,
                "total":      0.0,
                "notes":      ", ".join(item_flags),
            })

    # 5. Write to local PostgreSQL
    grand_total   = sum(l['total'] for l in order_lines)
    special_instr = parsed['special_instructions'] or 'None'
    delivery_info = parsed['delivery_info'] or 'None specified'

    log.info(f"  Writing {len(order_lines)} lines to local DB (total: ${grand_total:.2f})...")
    cur = conn.cursor()
    for line in order_lines:
        needs_review = has_errors or (
            "direct" not in line['notes'].lower() and
            "history" not in line['notes'].lower()
        )
        cur.execute(
            "INSERT INTO orders (customer_id, product_id, quantity, raw_message, source, status, special_instructions, created_at, needs_review) "
            "VALUES (%s, %s, %s, %s, 'whatsapp', 'pending_review', %s, NOW(), %s);",
            (customer['id'], line['product_id'], line['qty'], text, special_instr, needs_review)
        )
    conn.commit()
    cur.close()
    log.info("  Local DB write complete.")

    # 6. Push to remote SQL Server (if enabled)
    reply_msg = _push_to_mssql(conn, customer, order_lines, grand_total, special_instr, flags) \
        if PUSH_TO_MSSQL else None

    conn.close()

    # 7. Print sales draft to terminal
    _print_draft(customer, sender_phone, confidence, order_lines, grand_total, delivery_info, flags)

    # 8. Build reply
    if reply_msg:
        return reply_msg
    draft_reply = f"✅ Order draft saved! {len(order_lines)} item(s), total: ${grand_total:.2f}."
    if flags:
        draft_reply += " ⚠️ Needs review."
    return draft_reply


def _push_to_mssql(conn, customer, order_lines, grand_total, special_instr, flags):
    """Push draft order to remote SQL Server. Returns reply string."""
    try:
        import pyodbc
        mssql_conn_str = (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER=your_sql_server_ip,port;"
            "DATABASE=ColinasProducts;"
            "UID=your_sql_username;"
            "PWD=***REMOVED***;"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
        )
        ms = pyodbc.connect(mssql_conn_str, timeout=5)
        ms.autocommit = False
        cur = ms.cursor()

        cur.execute("SELECT ISNULL(MAX(SalesOrderNo), 0) FROM Tbl_Sales_SalesOrder")
        new_order_no = int(cur.fetchone()[0]) + 1

        safe_name  = customer['name'][:100]
        safe_notes = special_instr[:200]

        cur.execute(
            "INSERT INTO Tbl_Sales_SalesOrder "
            "(SalesOrderNo, CustomerID, CustomerName, DateIssued, IsRelease, MadeBy, Cancel, Subtotal, Tax, Total, Notes) "
            "VALUES (?, ?, ?, GETDATE(), 0, 0, 0, ?, 0.00, ?, ?)",
            (new_order_no, customer['id'], safe_name, grand_total, grand_total, safe_notes)
        )
        cur.execute("SELECT @@IDENTITY")
        sales_order_id = int(cur.fetchone()[0])

        for idx, line in enumerate(order_lines, 1):
            if line['product_id']:
                cur.execute(
                    "INSERT INTO Tbl_Sales_SalesOrder_Details "
                    "(SalesOrderID, ItemNo, MaterialID, PartNo, Description, Quantity, UnitPrice, Amount, UofM, IsTaxable, Notes) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CASE (CS)', 1, ?)",
                    (sales_order_id, idx, line['product_id'], line['sku'][:50],
                     line['item_name'][:200], line['qty'], line['price'], line['total'], line['notes'][:100])
                )

        ms.commit()
        cur.close()
        ms.close()
        log.info(f"  [MSSQL] Draft created: SalesOrderID={sales_order_id}, No={new_order_no}")

        reply = f"📋 Draft Sales Order #{new_order_no} created! (ID: {sales_order_id})"
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


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info("=" * 60)
    log.info("  WhatsApp Order Webhook — Python Flask")
    log.info("=" * 60)
    log.info(f"  Listening on:  http://localhost:{FLASK_PORT}/webhook")
    log.info(f"  Health check:  http://localhost:{FLASK_PORT}/health")
    log.info(f"  Push to MSSQL: {PUSH_TO_MSSQL}")
    log.info("=" * 60)
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
