# --- TODO LIST ---
# [x] STEP 1: Verify WhatsApp Business API Connection active/status
# [x] STEP 2: Retrieve incoming messages (Simulation fallback)
# [x] STEP 3: Parse message body using regex/heuristics to extract company, items, qty, delivery, and instructions
# [x] STEP 4: Match Customer (Exact phone, fuzzy name, or fallback to [NEW_CUSTOMER])
# [x] STEP 5: Match Product (Exact SKU, fuzzy catalog, order history preference, or fallback to [UNKNOWN_ITEM])
# [x] STEP 6: Insert Order(s) into database (pending_review, needs_review, message_type logging)
# [x] STEP 7: Generate human-readable Sales Draft and print executed SQL statements for audit

import os
import re
import sys
import json
import difflib
import unicodedata
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

# Load env variables
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "whatsapp_orders")
DB_USER = os.getenv("DB_USER", "openpg")
DB_PASSWORD = os.getenv("DB_PASSWORD", "openpgpwd")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY", "")

# Connect to postgres
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

# Confirm WhatsApp Business connection status
def check_whatsapp_connection():
    print("Checking WhatsApp Business API connection status...")
    if WHATSAPP_API_KEY:
        # If we had a real API endpoint, we would send a request here.
        # e.g., requests.get("https://graph.facebook.com/v17.0/me", headers={"Authorization": f"Bearer {WHATSAPP_API_KEY}"})
        print(f"WhatsApp Business Connection: ACTIVE (Key: ...{WHATSAPP_API_KEY[-5:] if len(WHATSAPP_API_KEY) > 5 else WHATSAPP_API_KEY})")
        return True
    else:
        print("WhatsApp Business Connection: SIMULATION MODE (No API Key in .env)")
        return False

# Sample Incoming WhatsApp Messages to process
SIMULATED_INBOX = [
    {
        "sender_phone": "+15129993743",
        "sender_name": "Emilio Salazar",
        "message_body": "Hey, it's Emilio from Colinas Foods. I'd like to order 5 cases of Vinegar, White Distilled 5% to be delivered next Monday. Thanks!",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
]

# Fetch latest incoming WhatsApp messages
def fetch_messages():
    active = check_whatsapp_connection()
    if active:
        # In a production environment, we would fetch from the Meta Graph API endpoint.
        # For this operation, we return the inbox for processing.
        return SIMULATED_INBOX
    else:
        print("Using simulated inbox messages...")
        return SIMULATED_INBOX

# ---------------------------------------------------------------------------
# TEXT NORMALIZATION HELPERS
# ---------------------------------------------------------------------------

def strip_accents(text):
    """Remove Unicode diacritics: Díaz -> Diaz, café -> cafe."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )

def normalize_phone(phone_str):
    """Return last 10 digits of any phone string for comparison."""
    if not phone_str:
        return ""
    digits = "".join(c for c in phone_str if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits

# Catalog abbreviations found in product names — expand before scoring
PRODUCT_ABBREVS = {
    "bnlss": "boneless",
    "bnls":  "boneless",
    "b/i":   "bone in",
    "bi":    "bone in",
    "fz":    "frozen",
    "ref":   "refrigerated",
    "ckd":   "cooked",
    "ea":    "each",
    "cs":    "case",
    "lb":    "pound",
    "lbs":   "pound",
    "pc":    "piece",
    "pcs":   "pieces",
    "whl":   "whole",
    "chx":   "chicken",
    "bef":   "beef",
    "cfg":   "chicken",
    "cfm":   "chicken marinade",
    "ir":    "inside round",
    "gn":    "ground",
}

# Spanish <-> English common food terms
SPANISH_EN = {
    "pechuga":    "breast",
    "pechugas":   "breast",
    "muslo":      "thigh",
    "muslos":     "thigh",
    "pierna":     "leg",
    "piernas":    "leg",
    "alita":      "wing",
    "alitas":     "wing",
    "res":        "beef",
    "pollo":      "chicken",
    "cerdo":      "pork",
    "puerco":     "pork",
    "camaron":    "shrimp",
    "camarones":  "shrimp",
    "bistek":     "bistec",
    "bistec":     "bistec",
    "suadero":    "suadero",
    "costilla":   "rib",
    "costillas":  "rib",
    "chorizo":    "chorizo",
    "molida":     "ground",
    "molido":     "ground",
    "marinado":   "marinade",
    "marinada":   "marinade",
    "fajita":     "fajita",
    "fajitas":    "fajita",
    "taco":       "taco",
    "tacos":      "taco",
    "queso":      "cheese",
    "gaonera":    "ribeye",
    "arrachera":  "skirt",
    "diezmillo":  "chuck",
    "paleta":     "shoulder",
    "lomo":       "loin",
    "filete":     "fillet",
    "milanesa":   "milanesa",
    "higado":     "liver",
    "menudo":     "tripe",
    "barbacoa":   "barbacoa",
    "lengua":     "tongue",
    "tripas":     "tripe",
    "carnitas":   "carnitas",
    "pastor":     "pastor",
}

# Noise words in product names that don't help disambiguation
PRODUCT_NOISE = {
    "raw", "fresh", "choice", "select", "premium", "bulk", "shelf",
    "stable", "imported", "whole", "natural", "organic", "usda",
    "grade", "a", "and", "or", "the", "in", "of", "for", "with",
    "style", "type", "cut", "sliced", "diced", "strips",
}

def normalize_text(text):
    """
    Lowercase, strip accents, expand abbreviations and Spanish terms,
    remove punctuation. Returns a clean string ready for tokenization.
    """
    text = strip_accents(text.lower())
    # Pre-pass: normalise slash-joined abbreviations (b/i -> bi, b/i -> bone in)
    # before we strip all punctuation, so the lookup key is still intact.
    text = re.sub(r'\b([a-z]+)/([a-z]+)\b', lambda m: m.group(1) + m.group(2), text)
    # Strip remaining punctuation (keep alphanumeric + spaces)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = text.split()
    expanded = []
    for tok in tokens:
        tok = PRODUCT_ABBREVS.get(tok, tok)   # expand catalog abbreviations
        tok = SPANISH_EN.get(tok, tok)          # translate Spanish food terms
        expanded.extend(tok.split())            # "bone in" becomes two tokens
    return " ".join(expanded)

def token_set(text, noise=None):
    """Return set of meaningful tokens from a normalized string."""
    tokens = set(normalize_text(text).split())
    if noise:
        tokens -= noise
    # Drop single-char tokens
    return {t for t in tokens if len(t) > 1}

def token_f1(query_tokens, candidate_tokens):
    """
    F1 between two token sets:
      precision = |intersection| / |query|   (how much of what was asked is covered)
      recall    = |intersection| / |candidate| (how much of the product name matches)
    Weighted toward precision so short queries don't over-match long product names.
    """
    if not query_tokens or not candidate_tokens:
        return 0.0
    common = query_tokens & candidate_tokens
    if not common:
        return 0.0
    precision = len(common) / len(query_tokens)
    recall    = len(common) / len(candidate_tokens)
    if precision + recall == 0:
        return 0.0
    # Weighted F1: weight precision 2x (penalise candidate noise less)
    return (3 * precision * recall) / (2 * precision + recall)

def seq_ratio(a, b):
    """SequenceMatcher ratio on normalized strings."""
    na, nb = normalize_text(a), normalize_text(b)
    return difflib.SequenceMatcher(None, na, nb).ratio()

# Aspen Systems PDF Parser
def parse_aspen_pdf(body):
    lines = [l.strip() for l in body.split('\n') if l.strip()]
    items = []
    company_name = None
    
    # Extract Company Name
    for i, line in enumerate(lines):
        if line.lower() == "bill to:" or line.lower() == "ship to:":
            if i + 1 < len(lines):
                company_name = lines[i+1].strip()
                break

    # Extract Items
    i = 0
    while i < len(lines):
        uom_val = lines[i].upper()
        if uom_val in ['CSE', 'LB', 'EA', 'CS', 'CASE', 'LBS'] and i >= 3:
            try:
                qty = float(lines[i-1].replace(',', ''))
                
                # Description is usually 2 lines up. Vendor codes are typically format 'CF xxxx'
                desc_idx = i - 2
                sku = None
                vendor_line = lines[desc_idx]
                
                if vendor_line.startswith('CF '):
                    sku = vendor_line.replace('CF ', '').strip()
                    desc_idx = i - 3
                elif len(vendor_line) <= 8 and vendor_line.replace('.','').isdigit():
                    sku = vendor_line.strip()
                    desc_idx = i - 3
                    
                item_name = lines[desc_idx]
                
                secondary_qty = 0.0
                if i + 1 < len(lines):
                    try:
                        secondary_qty = float(lines[i+1].replace(',', ''))
                    except ValueError:
                        pass
                
                # Skip invalid rows
                if len(item_name) > 3 and not item_name.replace('.','').isdigit():
                    items.append({
                        "name": item_name, 
                        "qty": qty,
                        "sku": sku,
                        "uom": uom_val,
                        "secondary_qty": secondary_qty
                    })
            except ValueError:
                pass
        i += 1
        
    # Remove duplicates or empty
    items = [it for it in items if it["name"]]
    
    return {
        "message_type": "order" if items else "non_order",
        "company_name": company_name,
        "items": items,
        "delivery_info": None,
        "special_instructions": "Extracted from Aspen PDF"
    }

# NLP and Regex Parser
def parse_message(body):
    if "aspen-systems.com" in body.lower() or ("Product Code" in body and "Order Qty" in body):
        return parse_aspen_pdf(body)

    body_lower = body.lower()
    
    # Check if this is an order message
    order_keywords = ["order", "need", "want", "send", "buy", "request", "add", "case", "bag", "box", "pound", "lb", "qty", "x"]
    has_qty = any(c.isdigit() for c in body)
    has_keyword = any(kw in body_lower for kw in order_keywords)
    
    if not (has_qty or has_keyword):
        return {
            "message_type": "non_order",
            "company_name": None,
            "items": [],
            "delivery_info": None,
            "special_instructions": None
        }
    
    # Extract customer/company name
    company_name = None
    
    # Pattern 0: "[Company] order:" or "[Company]:" at the start of the string
    m = re.match(r"^([a-zA-Z0-9'\s]+?)(?:\s+order)?\s*:", body, re.IGNORECASE)
    if m:
        company_name = m.group(1).strip()
    else:
        # Pattern 0.5: "para [Company] mañana..."
        m = re.search(r"(?:para|for)\s+([a-zA-Z0-9'\s]+?)(?:\n|mañana|hoy|el\b|la\b|los|las|order|pedido|!|$)", body, re.IGNORECASE)
        if m:
            company_name = m.group(1).strip()
        else:
            # Pattern 1: "this is [Name] from [Company]" or "it's [Name] from [Company]"
            m = re.search(r"(?:this is|it's)\s+([a-zA-Z0-9'\s]+)\s+from\s+([a-zA-Z0-9'\s]+)", body, re.IGNORECASE)
            if m:
                company_name = m.group(2).strip()
            else:
                # Pattern 2: "from [Company]"
                m = re.search(r"from\s+([a-zA-Z0-9'\s]+)", body, re.IGNORECASE)
                if m:
                    company_name = m.group(1).strip()
                else:
                    # Pattern 3: "this is [Company]" or "it's [Company]"
                    m = re.search(r"(?:this is|it's)\s+([a-zA-Z0-9'\s]+)", body, re.IGNORECASE)
                    if m:
                        company_name = m.group(1).strip()
                
    # Clean up company_name ending text (like "to be delivered" or "Thanks")
    if company_name:
        for stop_word in ["to be", "deliver", "thanks", "need", "can you", "we want", "please", "mañana", "hoy"]:
            if f" {stop_word}" in company_name.lower():
                idx = company_name.lower().index(f" {stop_word}")
                company_name = company_name[:idx].strip()
                
    # Extract delivery info
    delivery_info = None
    m = re.search(r"deliver(?:y|ed)?\s+(?:to|by|at)?\s+([^.\n]+)", body, re.IGNORECASE)
    if m:
        delivery_info = m.group(1).strip()
        # Clean instructions out of delivery info if merged
        if "leave at" in delivery_info.lower() or "instruction" in delivery_info.lower():
            for kw in ["leave at", "instruction", "special"]:
                if f" {kw}" in delivery_info.lower():
                    idx = delivery_info.lower().index(f" {kw}")
                    delivery_info = delivery_info[:idx].strip()
                    
    # Extract special instructions
    special_instructions = None
    m = re.search(r"(?:special\s+)?instruction[s]?:\s*([^.\n]+)", body, re.IGNORECASE)
    if m:
        special_instructions = m.group(1).strip()
    else:
        m = re.search(r"leave\s+at\s+([^.\n]+)", body, re.IGNORECASE)
        if m:
            special_instructions = f"Leave at {m.group(1).strip()}"
            
    # Extract items and quantities
    items = []
    
    # Clean body to process list items
    # Separators: "and", "y" (Spanish and), "e" (Spanish and before vowels),
    #             newlines, commas before digits, explicit "add to my order"
    parts = re.split(
        r'\s+and\s+|\s+y\s+|\s+e\s+|\n|\s*,\s*(?=\d)|\s+add\s+to\s+my\s+order:\s*',
        body,
        flags=re.IGNORECASE
    )
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Pattern B: Item name followed by standalone 'x' and quantity (e.g. "Laurel Molido x 10")
        # Run FIRST — more specific than Pattern A. Uses \bx\b so 'x' inside words is safe.
        m2 = re.search(r'^(.+?)\s+\bx\b\s*(\d+(?:\.\d+)?)\s*$', part.strip(), re.IGNORECASE)
        if m2:
            item_name = m2.group(1).strip().rstrip("?").strip()
            qty = float(m2.group(2))
            if item_name:
                items.append({"name": item_name, "qty": qty})
            continue

        # Pattern A: Quantity followed by units and item name (e.g. "5 cases of Vinegar", "X50# pastor")
        m1 = re.search(r'(?:\b|[xX]\s*)(\d+(?:\.\d+)?)\s*(?:cases|units|bags|boxes|pounds|lbs|dozen|doz|pcs|pieces|cs|ea|lb|#)?\s*(?:of)?\s*([^.]+)', part, re.IGNORECASE)
        if m1:
            qty = float(m1.group(1))
            item_name = m1.group(2).strip()
            # Clean up item_name from delivery details
            for stop in ["to be", "deliver", "thanks", "special", "leave at"]:
                if f" {stop}" in item_name.lower():
                    idx = item_name.lower().index(f" {stop}")
                    item_name = item_name[:idx].strip()
            
            # Check validity using whole word boundaries to prevent substring matches (e.g., "hi" in "white")
            is_valid = True
            for kw in ["order", "hi", "hey", "hello", "it's", "this is"]:
                if re.search(r'\b' + re.escape(kw) + r'\b', item_name.lower()):
                    is_valid = False
                    break
            
            if item_name and is_valid:
                items.append({"name": item_name, "qty": qty})
                continue
            
    # Remove duplicates or empty
    items = [it for it in items if it["name"]]
    
    return {
        "message_type": "order" if items else "non_order",
        "company_name": company_name,
        "items": items,
        "delivery_info": delivery_info,
        "special_instructions": special_instructions
    }

# Legacy alias kept for any callers outside this file
def similarity_score(a, b):
    return seq_ratio(a, b)

# ---------------------------------------------------------------------------
# CUSTOMER MATCHING
# ---------------------------------------------------------------------------

def match_customer(conn, parsed_name, sender_phone, sql_audit):
    """
    Match an incoming sender to a customer record using a multi-pass strategy:
      1. Exact phone (last-10-digits normalised, handles = signs, spaces, non-breaking chars)
      2. Accent-stripped exact name/company match
      3. Token F1 overlap on accent-stripped, stop-word-removed tokens
      4. SequenceMatcher on accent-stripped cleaned strings
      5. Fallback -> CASH SALES
    """
    cur = conn.cursor()
    query = "SELECT id, name, company, phone FROM customers;"
    sql_audit.append("EXECUTE: SELECT id, name, company, phone FROM customers;")
    cur.execute(query)
    cols = [col[0] for col in cur.description]
    all_customers = [dict(zip(cols, row)) for row in cur.fetchall()]

    # --- 1. (REMOVED) Exact phone match removed because WhatsApp sender is the employee, not the customer ---

    # --- 2 + 3 + 4. Name / company text matching ---
    if parsed_name:
        # Strip accents from the parsed name so Díaz == DIAZ
        parsed_norm = strip_accents(parsed_name).lower().strip()

        # Customer-specific stop words (terms that appear in many names)
        cust_stop = {
            'customer', 'rep', 'agent', 'from', 'co', 'inc', 'corp',
            'limited', 'ltd', 'llc', 'and', 'the', 'company', 'sales',
            'restaurant', 'restaurante', 'mexican', 'cantina', 'grocery',
            'food', 'foods', 'mart', 'supermarket', 'tienda', 'carniceria',
            'market', 'taqueria', 'tacos', 'taco', 'casa', 'c',
        }
        parsed_tokens = (
            set(re.findall(r'\w+', parsed_norm)) - cust_stop
        )

        best_match = None
        best_score = 0.0

        for c in all_customers:
            c_name = strip_accents(c["name"]).lower()
            c_comp = strip_accents(c["company"] or "").lower()
            combined = c_name + " " + c_comp

            # 2. Exact / substring on accent-stripped strings
            if parsed_norm == c_name or parsed_norm == c_comp:
                score = 1.0
            elif parsed_norm in combined:
                score = 0.9
            elif c_name in parsed_norm or c_comp in parsed_norm:
                score = 0.85
            else:
                # 3. Token F1 overlap
                c_tokens = (
                    set(re.findall(r'\w+', combined)) - cust_stop
                )
                score = token_f1(parsed_tokens, c_tokens) if parsed_tokens and c_tokens else 0.0

                # 4. SequenceMatcher on cleaned strings (accent-stripped, stop-word-removed)
                p_str = " ".join(sorted(parsed_tokens))
                c_str = " ".join(sorted(c_tokens))
                sm = difflib.SequenceMatcher(None, p_str, c_str).ratio() if p_str and c_str else 0.0
                score = max(score, sm)

            if score > best_score:
                best_score = score
                best_match = c

        if best_match and best_score >= 0.75:
            cur.close()
            confidence = "HIGH" if best_score >= 0.90 else "MEDIUM"
            flags = [] if best_score >= 0.90 else [
                f"[CUSTOMER_CONFIRMATION] '{parsed_name}' matched to "
                f"'{best_match['name']}' with {best_score:.1%} confidence."
            ]
            return best_match, confidence, flags
        elif best_match and best_score >= 0.5:
            cur.close()
            return best_match, "LOW", [
                f"[CUSTOMER_NEEDS_REVIEW] Weak match: '{parsed_name}' -> "
                f"'{best_match['name']}' ({best_score:.1%}). Verify customer."
            ]

    # --- 5. Fallback -> CASH SALES ---
    fallback_cust = next((c for c in all_customers if c["id"] == 1714), None)
    if not fallback_cust:
        fallback_cust = next((c for c in all_customers if "cash" in c["name"].lower()), None)
    if not fallback_cust and all_customers:
        fallback_cust = all_customers[0]

    cur.close()
    if fallback_cust:
        return fallback_cust, "LOW", [
            f"[CUSTOMER_NEEDS_REVIEW] Could not match '{parsed_name or 'Unknown'}'. "
            f"Defaulted to '{fallback_cust['name']}' (ID: {fallback_cust['id']})."
        ]
    raise Exception("No customers found in database to fallback to.")


# Fetch customer's last 5 orders
def get_customer_history(conn, customer_id, sql_audit):
    """
    Returns the customer's recent distinct products as full product dicts.
    JOINs with products so we have name, SKU, price for history matching.
    """
    cur = conn.cursor()
    query = """
    SELECT DISTINCT ON (p.id)
           p.id, p.name, p.sku, p.price, p.description
    FROM orders o
    JOIN products p ON o.product_id = p.id
    WHERE o.customer_id = %s
      AND o.product_id IS NOT NULL
    ORDER BY p.id, o.created_at DESC
    LIMIT 30;
    """
    sql_audit.append(f"EXECUTE: get_customer_history for customer_id={customer_id}")
    cur.execute(query, (customer_id,))
    cols = [col[0] for col in cur.description]
    rows = cur.fetchall()
    cur.close()
    return [dict(zip(cols, row)) for row in rows]

# ---------------------------------------------------------------------------
# PRODUCT MATCHING
# ---------------------------------------------------------------------------

PRODUCT_NOISE = {'case', 'cases', 'box', 'boxes', 'lb', 'lbs', 'pound', 'pounds', 'of', 'and', 'the', 'pcs', 'ea'}

def _fetch_product_candidates(cur, item_name, cols):
    seen_ids = set()
    candidates = []
    def add_rows(rows):
        for row in rows:
            d = dict(zip(cols, row))
            if d["id"] not in seen_ids:
                seen_ids.add(d["id"])
                candidates.append(d)
                
    # Quick SP->EN mapping for common items not in DB correctly
    translations = {
        "pulpo": "octopus",
        "tuetano": "marrow",
        "javon": "scour",
        "jabon": "scour",
        "limon": "lemon",
        "cebolla": "onion",
        "ajo": "garlic",
        "queso": "cheese",
        "fresa": "strawberry"
    }
    
    # Translate query words if present
    query_words = item_name.lower().split()
    translated_words = [translations.get(w, w) for w in query_words]
    translated_name = " ".join(translated_words)
    
    cur.execute("SELECT * FROM products WHERE LOWER(name) LIKE LOWER(%s) OR LOWER(sku) = LOWER(%s) OR LOWER(description) LIKE LOWER(%s) LIMIT 10;", (f"%{translated_name}%", item_name, f"%{translated_name}%"))
    add_rows(cur.fetchall())
    
    expanded = normalize_text(translated_name)
    tokens = [t for t in expanded.split() if len(t) > 2 and t not in PRODUCT_NOISE]
    
    for tok in tokens:
        if len(candidates) >= 60: break
        # Try exact token
        cur.execute("SELECT * FROM products WHERE LOWER(name) LIKE LOWER(%s) LIMIT 20;", (f"%{tok}%",))
        add_rows(cur.fetchall())
        
        # If token ends in 's', try singular (e.g. chips -> chip, thighs -> thigh)
        if tok.endswith('s') and len(tok) > 3:
            singular = tok[:-1]
            cur.execute("SELECT * FROM products WHERE LOWER(name) LIKE LOWER(%s) LIMIT 20;", (f"%{singular}%",))
            add_rows(cur.fetchall())

    return candidates

def match_item(conn, item_name, customer_history, sql_audit, sku=None):
    """
    Match an item name to a product record.

    Priority order (fastest / most accurate first):
      0. Exact provided SKU lookup.
      1. History pass  — fuzzy-score item_name against the customer's past products.
                         If score >= 0.75, return immediately (no catalog query needed).
      2. Exact SKU/name match against catalog candidates.
      3. Fuzzy scoring (token F1 + SequenceMatcher) across catalog candidates.
    """
    if sku:
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE LOWER(sku) = LOWER(%s) LIMIT 1;", (sku,))
        if cur.description:
            cols = [col[0] for col in cur.description]
            row = cur.fetchone()
            if row:
                cur.close()
                return dict(zip(cols, row)), ["[EXACT_SKU_MATCH] Matched exactly via vendor SKU."]
        cur.close()

    import difflib
    
    translations = {
        "pulpo": "octopus", "tuetano": "marrow", "javon": "scour", 
        "jabon": "scour", "limon": "lemon", "cebolla": "onion", 
        "ajo": "garlic", "queso": "cheese", "fresa": "strawberry"
    }
    translated_words = [translations.get(w, w) for w in item_name.lower().split()]
    translated_name = " ".join(translated_words)
    
    item_lower   = translated_name.strip()
    query_tokens = token_set(translated_name, noise=PRODUCT_NOISE)
    query_norm   = normalize_text(translated_name)

    # ── PASS 1: Customer history (before any catalog query) ───────────────────
    if customer_history:
        best_h, best_h_score = None, 0.0
        for prod in customer_history:
            prod_tokens = token_set(prod["name"], noise=PRODUCT_NOISE)
            prod_norm   = normalize_text(prod["name"])
            f1   = token_f1(query_tokens, prod_tokens)
            sm   = difflib.SequenceMatcher(None, query_norm, prod_norm).ratio()
            score = min(max(f1, sm) + (0.15 if query_tokens and query_tokens.issubset(prod_tokens) else 0.0), 1.0)
            if score > best_h_score:
                best_h_score, best_h = score, prod
        if best_h and best_h_score >= 0.75:
            # High-confidence history hit — skip catalog entirely
            confidence_tag = "confirmed" if best_h_score >= 0.90 else f"{best_h_score:.0%}"
            return best_h, [f"[HISTORY_MATCH] Matched from purchase history ({confidence_tag} confidence)."]

    # ── PASS 2 & 3: Catalog lookup ────────────────────────────────────────────
    cur = conn.cursor()
    cur.execute("SELECT * FROM products LIMIT 0;")
    cols = [col[0] for col in cur.description]
    sql_audit.append(f"EXECUTE: multi-pass candidate fetch for '{translated_name}'")
    candidates = _fetch_product_candidates(cur, translated_name, cols)
    cur.close()

    # Pass 2: Exact SKU or exact name
    for c in candidates:
        if c["sku"].lower() == item_lower or c["name"].lower() == item_lower:
            return c, []

    # Pass 3: Fuzzy scoring across all candidates
    best_c, best_score = None, 0.0
    for c in candidates:
        prod_tokens = token_set(c["name"], noise=PRODUCT_NOISE)
        prod_norm   = normalize_text(c["name"])
        f1    = token_f1(query_tokens, prod_tokens)
        sm    = difflib.SequenceMatcher(None, query_norm, prod_norm).ratio()
        score = min(max(f1, sm) + (0.15 if query_tokens and query_tokens.issubset(prod_tokens) else 0.0), 1.0)
        if score > best_score:
            best_score, best_c = score, c

    if best_c:
        if best_score >= 0.70:
            return best_c, ([] if best_score >= 0.85 else [f"[ITEM_NEEDS_CONFIRMATION] Matched to '{best_c['name']}' with {best_score:.1%} confidence. Verify."])
        return best_c, [f"[ITEM_NEEDS_CONFIRMATION] Low-confidence match to '{best_c['name']}' ({best_score:.1%}). Manual review required."]

    return None, [f"[UNKNOWN_ITEM] No product found in catalog matching '{item_name}'"]

# Main process function
def process_incoming_messages():
    conn = get_db_connection()
    messages = fetch_messages()
    
    print(f"\nProcessing {len(messages)} WhatsApp messages...")
    
    for idx, msg in enumerate(messages, 1):
        sql_audit = []
        follow_up_actions = []
        flags = []
        
        sender_phone = msg["sender_phone"]
        sender_name = msg["sender_name"]
        raw_message = msg["message_body"]
        timestamp = msg["timestamp"]
        
        print(f"\n==========================================")
        print(f"MESSAGE #{idx} - FROM {sender_name} ({sender_phone})")
        print(f"Raw: \"{raw_message}\"")
        print(f"==========================================")
        
        # Step 2: Parse Order Information
        parsed = parse_message(raw_message)
        
        # Rule: If the message is not an order, log and skip
        if parsed["message_type"] == "non_order":
            print("Summary: Message classified as non-order. Logging and skipping Steps 3-6...")
            
            # Insert into database as non_order
            cur = conn.cursor()
            insert_query = """
            INSERT INTO orders (
              customer_id,
              product_id,
              quantity,
              raw_message,
              source,
              status,
              special_instructions,
              created_at,
              needs_review
            ) VALUES (
              NULL, NULL, NULL, %s, 'whatsapp', 'non_order', NULL, NOW(), FALSE
            );
            """
            sql_audit.append(f"EXECUTE: INSERT INTO orders (customer_id, product_id, quantity, raw_message, source, status, special_instructions, created_at, needs_review) VALUES (NULL, NULL, NULL, '{raw_message}', 'whatsapp', 'non_order', NULL, NOW(), FALSE);")
            cur.execute(insert_query, (raw_message,))
            conn.commit()
            cur.close()
            
            print("\nSQL STATEMENTS EXECUTED:")
            for stmt in sql_audit:
                print(f"  {stmt}")
            
            print("\nHUMAN FOLLOW-UP ACTIONS:")
            print("  - None (Informational non-order message logged)")
            continue
            
        # Step 3: Match Customer
        customer, confidence, cust_flags = match_customer(conn, parsed["company_name"], sender_phone, sql_audit)
        flags.extend(cust_flags)
        
        # Pull last 5 orders
        history = get_customer_history(conn, customer["id"], sql_audit)
        
        # Process order items
        order_line_items = []
        has_errors = len(cust_flags) > 0
        
        for item in parsed["items"]:
            product, item_flags = match_item(conn, item["name"], history, sql_audit)
            flags.extend(item_flags)
            if item_flags or not product:
                has_errors = True
                
            qty = item["qty"]
            if product:
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
                order_line_items.append({
                    "product_id": None,
                    "item_name": item["name"],
                    "sku": "UNKNOWN",
                    "qty": qty,
                    "price": 0.0,
                    "total": 0.0,
                    "notes": ", ".join(item_flags)
                })
                
        # Step 5: Write Orders to Database
        # Loop over line items and insert into database
        grand_total = sum(l["total"] for l in order_line_items)
        delivery_info = parsed["delivery_info"] if parsed["delivery_info"] else "None specified"
        special_instr = parsed["special_instructions"] if parsed["special_instructions"] else "None"
        
        PUSH_TO_MSSQL = os.getenv("PUSH_TO_MSSQL", "False").lower() in ("true", "1", "yes")
        
        # Local PostgreSQL inserts (always run to maintain local logs and dashboards)
        cur = conn.cursor()
        for line in order_line_items:
            # SQL Insert Query
            insert_query = """
            INSERT INTO orders (
              customer_id,
              product_id,
              quantity,
              raw_message,
              source,
              status,
              special_instructions,
              created_at,
              needs_review
            ) VALUES (
              %s, %s, %s, %s, 'whatsapp', 'pending_review', %s, NOW(), %s
            );
            """
            
            # Check if any flags exist for this line
            line_needs_review = has_errors or ("direct" not in line["notes"].lower() and "history" not in line["notes"].lower())
            
            sql_audit.append(
                f"EXECUTE (LOCAL PG): INSERT INTO orders (customer_id, product_id, quantity, raw_message, source, status, special_instructions, created_at, needs_review) "
                f"VALUES ({customer['id']}, {line['product_id'] if line['product_id'] else 'NULL'}, {line['qty']}, '{raw_message}', 'whatsapp', 'pending_review', '{special_instr}', {line_needs_review});"
            )
            
            cur.execute(
                insert_query,
                (customer["id"], line["product_id"], line["qty"], raw_message, special_instr, line_needs_review)
            )
        conn.commit()
        cur.close()
        
        # Remote SQL Server Draft Inserts
        mssql_conn_str = (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER=your_sql_server_ip,port;"
            "DATABASE=ColinasProducts;"
            "UID=your_sql_username;"
            "PWD=***REMOVED***;"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
        )
        
        # Pre-format SQL statements for audit trail / print
        escaped_customer_name = customer['name'].replace("'", "''")
        escaped_special_instr = special_instr.replace("'", "''")
        
        # We will update mssql_header_query dynamically if we push, otherwise use a placeholder
        mssql_header_query_template = (
            f"INSERT INTO Tbl_Sales_SalesOrder (\n"
            f"    SalesOrderNo, CustomerID, CustomerName, DateIssued, IsRelease, MadeBy, Cancel, Subtotal, Tax, Total, Notes\n"
            f") VALUES (\n"
            f"    [GeneratedSalesOrderNo], {customer['id']}, '{escaped_customer_name}', GETDATE(), 0, 0, 0, {grand_total:.2f}, 0.00, {grand_total:.2f}, '{escaped_special_instr}'\n"
            f");"
        )
        
        mssql_details_queries = []
        for line_idx, line in enumerate(order_line_items, 1):
            if line["product_id"]:
                escaped_item_name = line['item_name'].replace("'", "''")
                mssql_details_queries.append(
                    f"INSERT INTO Tbl_Sales_SalesOrder_Details (\n"
                    f"    SalesOrderID, ItemNo, MaterialID, PartNo, Description, Quantity, UnitPrice, Amount, UofM, IsTaxable, Notes\n"
                    f") VALUES (\n"
                    f"    [GeneratedSalesOrderID], {line_idx}, {line['product_id']}, '{line['sku']}', '{escaped_item_name}', {line['qty']}, {line['price']:.2f}, {line['total']:.2f}, 'CASE (CS)', 1, '{line['notes']}'\n"
                    f");"
                )
            else:
                mssql_details_queries.append(f"-- SKIPPED Line {line_idx} due to unknown catalog product matching.")
                
        if PUSH_TO_MSSQL:
            import pyodbc
            try:
                ms_conn = pyodbc.connect(mssql_conn_str, timeout=5)
                ms_conn.autocommit = False
                ms_cur = ms_conn.cursor()
                
                # Fetch maximum SalesOrderNo and increment it
                ms_cur.execute("SELECT ISNULL(MAX(SalesOrderNo), 0) FROM Tbl_Sales_SalesOrder")
                max_order_no = int(ms_cur.fetchone()[0])
                new_sales_order_no = max_order_no + 1
                
                # Insert header with SalesOrderNo
                ms_cur.execute("""
                    INSERT INTO Tbl_Sales_SalesOrder (
                        SalesOrderNo, CustomerID, CustomerName, DateIssued, IsRelease, MadeBy, Cancel, Subtotal, Tax, Total, Notes
                    ) VALUES (
                        ?, ?, ?, GETDATE(), 0, 0, 0, ?, 0.00, ?, ?
                    )
                """, (new_sales_order_no, customer['id'], customer['name'], grand_total, grand_total, special_instr))
                
                # Fetch identity value
                ms_cur.execute("SELECT @@IDENTITY")
                sales_order_id = int(ms_cur.fetchone()[0])
                
                header_sql = mssql_header_query_template.replace("[GeneratedSalesOrderNo]", str(new_sales_order_no))
                sql_audit.append(f"EXECUTE (REMOTE MSSQL HEADER): Created SalesOrderID {sales_order_id}, SalesOrderNo {new_sales_order_no}\n{header_sql}")
                
                # Insert lines
                for line_idx, line in enumerate(order_line_items, 1):
                    if line["product_id"]:
                        ms_cur.execute("""
                            INSERT INTO Tbl_Sales_SalesOrder_Details (
                                SalesOrderID, ItemNo, MaterialID, PartNo, Description, Quantity, UnitPrice, Amount, UofM, IsTaxable, Notes
                            ) VALUES (
                                ?, ?, ?, ?, ?, ?, ?, ?, 'CASE (CS)', 1, ?
                            )
                        """, (sales_order_id, line_idx, line['product_id'], line['sku'], line['item_name'], line['qty'], line['price'], line['total'], line['notes']))
                        sql_audit.append(f"EXECUTE (REMOTE MSSQL DETAIL {line_idx}):\n{mssql_details_queries[line_idx-1].replace('[GeneratedSalesOrderID]', str(sales_order_id))}")
                    else:
                        sql_audit.append(f"EXECUTE (REMOTE MSSQL DETAIL {line_idx}): SKIPPED - UNKNOWN PRODUCT")
                        
                ms_conn.commit()
                ms_cur.close()
                ms_conn.close()
                print(f"Status: Successfully pushed draft order directly to SQL Server! SalesOrderID: {sales_order_id}")
            except Exception as e:
                print(f"Error inserting remote draft sales order: {e}")
                sql_audit.append(f"EXECUTE (REMOTE MSSQL ERROR): Write failed: {e}")
                follow_up_actions.append(f"[DATABASE_WRITE_ERROR] Failed to push draft order to remote SQL Server: {e}")
        else:
            sql_audit.append("PLAN (REMOTE MSSQL DRAFT - TEST MODE SIMULATED):")
            sql_audit.append(mssql_header_query_template.replace("[GeneratedSalesOrderNo]", "MOCK_NO"))
            for d_q in mssql_details_queries:
                sql_audit.append(d_q)
        
        # Step 6: Generate Sales Draft
        grand_total = sum(l["total"] for l in order_line_items)
        delivery_info = parsed["delivery_info"] if parsed["delivery_info"] else "None specified"
        special_instr = parsed["special_instructions"] if parsed["special_instructions"] else "None"
        
        # Formatting Flags
        review_flags_str = ""
        if flags:
            review_flags_str = "\n".join(f"- {f}" for f in flags)
            follow_up_actions.extend(flags)
        else:
            review_flags_str = "None"
            
        # Sales Draft format matching the exact requirements
        draft = f"""
**SALES DRAFT — Pending Approval**
**Date:** {timestamp}
**Source:** WhatsApp Message

---

**Customer**
- Name: {customer['name']} {"[NEW_CUSTOMER]" if "[NEW_CUSTOMER]" in "".join(flags) else ""}
- Company: {customer['company']}
- Phone: {sender_phone}
- Match Confidence: {confidence}

**Order Details**
| # | Item | SKU | Qty | Unit Price | Line Total | Notes |
|---|------|-----|-----|------------|------------|-------|"""
        
        for item_idx, line in enumerate(order_line_items, 1):
            draft += f"\n| {item_idx} | {line['item_name']} | {line['sku']} | {line['qty']} | ${line['price']:.2f} | ${line['total']:.2f} | {line['notes']} |"
            
        draft += f"""

**Order Total:** ${grand_total:.2f}
**Delivery Notes:** {delivery_info}
**Special Instructions:** {special_instr}

**Flags Requiring Review:**
{review_flags_str}

**Raw WhatsApp Message:**
> "{raw_message}"

---
*This draft was auto-generated from a WhatsApp message. Please verify flagged fields before confirming the order.*
"""
        # Print results
        print("\n1. PROCESSING SUMMARY:")
        print(f"  - Message parsed successfully. Message Type: order")
        print(f"  - Customer matched: {customer['name']} (ID: {customer['id']}, Confidence: {confidence})")
        print(f"  - Parsed items: {len(order_line_items)} lines matched")
        print(f"  - Flags: {len(flags)} warning(s) raised")
        
        print("\n2. SALES DRAFT:")
        print(draft)
        
        print("3. SQL STATEMENTS EXECUTED:")
        for stmt in sql_audit:
            print(f"  {stmt}")
            
        print("\n4. HUMAN FOLLOW-UP ACTIONS:")
        if follow_up_actions:
            for act in follow_up_actions:
                print(f"  - {act}")
        else:
            print("  - None (Clean order, ready for approval)")
            
    conn.close()

if __name__ == "__main__":
    process_incoming_messages()
