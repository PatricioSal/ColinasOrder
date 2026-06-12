import os
import re
import sys
import time
import hashlib
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from whatsapp_sales_agent import (
    parse_message,
    match_customer,
    get_customer_history,
    match_item,
    get_db_connection
)

# Load env variables
load_dotenv()

PROFILE_DIR = "whatsapp_profile"

# Global flag to stop the watcher loop (set when browser is closed)
browser_closed = False

def log(msg):
    """Print a timestamped log message to terminal, flushing immediately."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def fingerprint(sender, text):
    return hashlib.sha1(f"{sender}|{text}".encode("utf-8")).hexdigest()

def send_whatsapp_reply(page, reply_text):
    try:
        # Locate the text area of WhatsApp Web message composer
        input_box = page.locator("div[role='textbox']")
        if input_box.count() == 0:
            input_box = page.locator("div[contenteditable='true']")
            
        if input_box.count() > 0:
            input_box.first.click()
            # Type and press Enter
            page.keyboard.type(reply_text)
            page.keyboard.press("Enter")
            log(f"[REPLY SENT] \"{reply_text}\"")
        else:
            log("Warning: Message input box not found. Could not reply.")
    except Exception as e:
        log(f"Error sending reply: {e}")

def process_message(sender, text, page):
    log(f"[NEW MESSAGE] From '{sender}': \"{text[:80]}{'...' if len(text) > 80 else ''}\"")
    
    conn = get_db_connection()
    sql_audit = []
    follow_up_actions = []
    flags = []
    
    # 1. Parse Order Details
    log("  Parsing message...")
    parsed = parse_message(text)
    log(f"  Message type: {parsed['message_type']}")
    
    # If the message is a non-order, log it and return
    if parsed["message_type"] == "non_order":
        log("  Message classified as non-order. Logging to database...")
        cur = conn.cursor()
        insert_query = """
        INSERT INTO orders (
          customer_id, product_id, quantity, raw_message, source, status, special_instructions, created_at, needs_review
        ) VALUES (
          NULL, NULL, NULL, %s, 'whatsapp', 'non_order', NULL, NOW(), FALSE
        );
        """
        cur.execute(insert_query, (text,))
        conn.commit()
        cur.close()
        conn.close()
        log("  Non-order logged.")
        send_whatsapp_reply(page, "Thank you for your message. Your inquiry has been logged.")
        return
        
    # 2. Match Customer
    # Determine if sender name looks like a phone number, otherwise match by name/company
    sender_phone = ""
    clean_sender = "".join(c for c in sender if c.isdigit() or c == "+")
    if len(clean_sender) >= 7 and (clean_sender.startswith("+") or clean_sender.isdigit()):
        sender_phone = clean_sender
        
    parsed_cust_name = parsed["company_name"] if parsed["company_name"] else sender
    
    log(f"  Matching customer: '{parsed_cust_name}' (phone: '{sender_phone}')...")
    customer, confidence, cust_flags = match_customer(conn, parsed_cust_name, sender_phone, sql_audit)
    flags.extend(cust_flags)
    log(f"  Customer matched: '{customer['name']}' (ID: {customer['id']}, confidence: {confidence})")
    
    # 3. Pull last 5 orders
    history = get_customer_history(conn, customer["id"], sql_audit)
    
    # 4. Match items
    order_line_items = []
    has_errors = len(cust_flags) > 0
    
    log(f"  Parsed items: {len(parsed['items'])}")
    for item in parsed["items"]:
        log(f"    Matching item: '{item['name']}' x{item['qty']}...")
        product, item_flags = match_item(conn, item["name"], history, sql_audit)
        flags.extend(item_flags)
        if item_flags or not product:
            has_errors = True
            
        qty = item["qty"]
        if product:
            log(f"    -> Matched to: '{product['name']}' (SKU: {product['sku']}, Price: ${product['price']:.2f})")
            order_line_items.append({
                "product_id": product["id"],
                "item_name": product["name"],
                "sku": product["sku"],
                "qty": qty,
                "price": float(product["price"]),
                "total": float(product["price"]) * qty,
                "notes": ", ".join(item_flags) if item_flags else "Matched directly"
            })
        else:
            log(f"    -> No match found for '{item['name']}'")
            order_line_items.append({
                "product_id": None,
                "item_name": item["name"],
                "sku": "UNKNOWN",
                "qty": qty,
                "price": 0.0,
                "total": 0.0,
                "notes": ", ".join(item_flags)
            })
            
    # 5. Write to local PG database
    grand_total = sum(l["total"] for l in order_line_items)
    special_instr = parsed["special_instructions"] if parsed["special_instructions"] else "None"
    delivery_info = parsed["delivery_info"] if parsed["delivery_info"] else "None specified"
    
    log(f"  Writing to local database ({len(order_line_items)} lines, total: ${grand_total:.2f})...")
    cur = conn.cursor()
    for line in order_line_items:
        insert_query = """
        INSERT INTO orders (
          customer_id, product_id, quantity, raw_message, source, status, special_instructions, created_at, needs_review
        ) VALUES (
          %s, %s, %s, %s, 'whatsapp', 'pending_review', %s, NOW(), %s
        );
        """
        line_needs_review = has_errors or ("direct" not in line["notes"].lower() and "history" not in line["notes"].lower())
        cur.execute(
            insert_query,
            (customer["id"], line["product_id"], line["qty"], text, special_instr, line_needs_review)
        )
    conn.commit()
    cur.close()
    log("  Local database write complete.")
    
    # 6. Push to remote SQL Server as unreleased/draft if enabled
    PUSH_TO_MSSQL = os.getenv("PUSH_TO_MSSQL", "False").lower() in ("true", "1", "yes")
    if PUSH_TO_MSSQL:
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
        log("  Connecting to remote SQL Server...")
        try:
            ms_conn = pyodbc.connect(mssql_conn_str, timeout=5)
            ms_conn.autocommit = False
            ms_cur = ms_conn.cursor()
            
            # Fetch maximum SalesOrderNo and increment it
            ms_cur.execute("SELECT ISNULL(MAX(SalesOrderNo), 0) FROM Tbl_Sales_SalesOrder")
            max_order_no = int(ms_cur.fetchone()[0])
            new_sales_order_no = max_order_no + 1
            
            # Truncate varchar fields to safe lengths to avoid SQL truncation errors
            safe_customer_name = customer['name'][:100] if customer['name'] else ''
            safe_notes_header = special_instr[:200] if special_instr else ''

            # Insert header (draft order, IsRelease=0) with SalesOrderNo
            ms_cur.execute("""
                INSERT INTO Tbl_Sales_SalesOrder (
                    SalesOrderNo, CustomerID, CustomerName, DateIssued, IsRelease, MadeBy, Cancel, Subtotal, Tax, Total, Notes
                ) VALUES (
                    ?, ?, ?, GETDATE(), 0, 0, 0, ?, 0.00, ?, ?
                )
            """, (new_sales_order_no, customer['id'], safe_customer_name, grand_total, grand_total, safe_notes_header))
            
            ms_cur.execute("SELECT @@IDENTITY")
            sales_order_id = int(ms_cur.fetchone()[0])
            
            # Insert detail lines
            for line_idx, line in enumerate(order_line_items, 1):
                if line["product_id"]:
                    safe_sku = (line['sku'] or '')[:50]
                    safe_item_name = (line['item_name'] or '')[:200]
                    safe_line_notes = (line['notes'] or '')[:100]
                    ms_cur.execute("""
                        INSERT INTO Tbl_Sales_SalesOrder_Details (
                            SalesOrderID, ItemNo, MaterialID, PartNo, Description, Quantity, UnitPrice, Amount, UofM, IsTaxable, Notes
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, 'CASE (CS)', 1, ?
                        )
                    """, (sales_order_id, line_idx, line['product_id'], safe_sku, safe_item_name, line['qty'], line['price'], line['total'], safe_line_notes))
            
            ms_conn.commit()
            ms_cur.close()
            ms_conn.close()
            log(f"  [SUCCESS] Remote draft created! SalesOrderID: {sales_order_id}, SalesOrderNo: {new_sales_order_no}")
            
            # Send live reply back on WhatsApp with confirmation
            reply_msg = f"Draft Sales Order #{new_sales_order_no} created! (ID: {sales_order_id})"
            if flags:
                reply_msg += " Needs review."
            send_whatsapp_reply(page, reply_msg)
        except Exception as e:
            log(f"  [ERROR] Failed to write to remote database: {e}")
            follow_up_actions.append(f"[DATABASE_WRITE_ERROR] Failed to push draft to remote SQL Server: {e}")
            send_whatsapp_reply(page, f"Order received but failed to save to database. Please contact sales team.")
            
    # Send reply in test mode (if not pushed to MSSQL)
    if not PUSH_TO_MSSQL:
        reply_msg = f"Order draft processed and saved locally! (test mode)."
        if flags:
            reply_msg += " Needs review."
        send_whatsapp_reply(page, reply_msg)
            
    # 7. Print Sales Draft to terminal
    review_flags_str = "\n".join(f"  - {f}" for f in flags) if flags else "  None"
    
    log("\n" + "=" * 60)
    log("  SALES DRAFT")
    log("=" * 60)
    log(f"  Customer : {customer['name']} (ID: {customer['id']}) [{confidence}]")
    log(f"  Phone    : {sender_phone if sender_phone else customer.get('phone', 'N/A')}")
    for i, line in enumerate(order_line_items, 1):
        log(f"  Line {i}   : {line['item_name']} x{line['qty']} @ ${line['price']:.2f} = ${line['total']:.2f} [{line['notes']}]")
    log(f"  Total    : ${grand_total:.2f}")
    log(f"  Delivery : {delivery_info}")
    log(f"  Flags:")
    for f in flags:
        log(f"    - {f}")
    if not flags:
        log("    None - clean order")
    log("=" * 60 + "\n")
    
    conn.close()

# ============================================================
# Main Watcher
# ============================================================
with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False
    )
    page = browser.new_page()

    # Register a handler: when the page is closed (browser window closed), stop the loop
    def on_page_close():
        global browser_closed
        log("Browser window was closed. Stopping watcher...")
        browser_closed = True

    page.on("close", lambda: on_page_close())
    
    # Also handle browser context close (e.g., crash or X button)
    browser.on("close", lambda: on_page_close())

    log("Navigating to WhatsApp Web...")
    try:
        page.goto("https://web.whatsapp.com/", timeout=30000)
    except Exception as e:
        log(f"Warning during navigation: {e}")

    print("\n" + "=" * 60, flush=True)
    print("  WhatsApp Order Agent - READY", flush=True)
    print("=" * 60, flush=True)
    print("  1. Log into WhatsApp Web in the browser window.", flush=True)
    print("  2. Open the chat you want to monitor.", flush=True)
    print("  3. Press ENTER here when ready.", flush=True)
    print("  (To stop: close the browser window, or press Ctrl+C here)", flush=True)
    print("=" * 60 + "\n", flush=True)

    input()

    last_seen = None
    log("Watcher started. Monitoring for new incoming messages...")

    # Bot reply patterns to ignore (prevent self-feedback loop)
    BOT_REPLY_PREFIXES = (
        "Draft Sales Order",
        "Order draft processed",
        "Order received but failed",
        "Failed to push order",
        "Thank you for your message",
    )

    poll_count = 0
    try:
        while not browser_closed:
            try:
                messages = page.locator("div[role='row']")
                count = messages.count()

                poll_count += 1

                if count > 0:
                    # Scan the last 5 rows to find the most recent message
                    # (avoids missing incoming messages if the last row is an outgoing reply)
                    scan_start = max(0, count - 5)
                    for i in range(count - 1, scan_start - 1, -1):
                        row = messages.nth(i)

                        # Get the full HTML to detect message direction
                        try:
                            outer_html = row.evaluate("el => el.outerHTML")
                        except Exception:
                            continue

                        # Skip outgoing messages (contain message-out class)
                        if 'message-out' in outer_html:
                            continue

                        raw_text = row.inner_text().strip()
                        if not raw_text:
                            continue

                        # --- Strip trailing WhatsApp timestamp (e.g. "11:19 AM" or "10:45") ---
                        # WhatsApp Web appends the time on the last line of the bubble text.
                        clean_text = re.sub(
                            r'[\r\n]+\d{1,2}:\d{2}\s*(?:AM|PM)?\s*$', '', raw_text,
                            flags=re.IGNORECASE
                        ).strip()
                        # Fallback: also remove trailing time if it ended up inline
                        clean_text = re.sub(
                            r'\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\s*$', '', clean_text,
                            flags=re.IGNORECASE
                        ).strip()

                        if not clean_text:
                            continue

                        # --- Detect feedback loop BEFORE any splitting ---
                        if any(clean_text.startswith(prefix) for prefix in BOT_REPLY_PREFIXES):
                            continue  # skip this row silently and check older rows

                        # --- Parse sender and body ---
                        # WhatsApp group messages: first line = sender name, rest = body
                        # 1:1 messages: entire text is the body, no sender prefix
                        lines = clean_text.split('\n', 1)
                        if len(lines) == 2 and len(lines[0]) < 60 and not re.match(r'^\d', lines[0]):
                            sender = lines[0].strip()
                            body = lines[1].strip()
                        else:
                            sender = "WhatsApp"
                            body = clean_text

                        key = fingerprint(sender, body)

                        if key != last_seen:
                            last_seen = key
                            log(f"  Sender: '{sender}' | Body: '{body[:80]}{'...' if len(body)>80 else ''}'")
                            try:
                                process_message(sender, body, page)
                            except Exception as e:
                                import traceback
                                log(f"[ERROR] Exception in process_message: {e}")
                                traceback.print_exc(file=sys.stdout)
                                sys.stdout.flush()
                        # Only process the newest unprocessed message per cycle
                        break

            except Exception as e:
                if browser_closed:
                    break
                # Playwright raises errors when page is closed - catch and exit
                err_str = str(e).lower()
                if "target closed" in err_str or "browser has been closed" in err_str or "connection closed" in err_str or "page closed" in err_str:
                    log("Browser connection lost. Stopping watcher...")
                    browser_closed = True
                    break
                log(f"[WARN] Loop error (continuing): {e}")

            time.sleep(2)

    except KeyboardInterrupt:
        log("Ctrl+C received. Stopping watcher...")

    finally:
        log("Watcher stopped.")
        try:
            if not browser_closed:
                browser.close()
        except Exception:
            pass
        log("Done. Goodbye!")