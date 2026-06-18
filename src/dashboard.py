"""
dashboard.py  —  WhatsApp Order Bot Desktop Dashboard

Double-click (or run via DASHBOARD.bat) to launch everything:
  • Starts the Python Flask webhook in the background
  • Starts the Node.js WhatsApp listener in the background
  • Opens this GUI — close it to stop all services

Requires:  pip install customtkinter requests
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import base64
from datetime import datetime
import subprocess
import threading
import time
import os
import sys
import json
import requests
from pathlib import Path

# ── Theme ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# ── Paths & URLs ───────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent
ROOT_DIR    = PROJECT_DIR.parent
FLASK_URL   = "http://localhost:5050"
NODE_URL    = "http://localhost:3000"
LOG_FILE    = ROOT_DIR / "webhook.log"

# ── Palette ────────────────────────────────────────────────────────────────────
BG      = "#0d1117"
SURFACE = "#161b22"
CARD    = "#21262d"
BORDER  = "#30363d"
GREEN   = "#25d366"
GREEN_D = "#1da854"
WARN    = "#d29922"
WARN_BG = "#2a1f00"
ERROR   = "#f85149"
BLUE    = "#58a6ff"
TEXT    = "#e6edf3"
TEXT2   = "#8b949e"
TEXT3   = "#3d444d"


# ══════════════════════════════════════════════════════════════════════════════
class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("WhatsApp Order Bot")
        self.geometry("1060x760")
        self.minsize(900, 660)
        self.configure(fg_color=BG)

        # Subprocess handles
        self._flask_proc = None
        self._node_proc  = None

        # State
        self._connected       = False
        self._paused_log      = False
        self._group_vars      = {}     # group_name -> ctk.BooleanVar
        self._group_cbs       = []     # list of CTkCheckBox widgets
        self._refresh_ctr     = 0
        self._review_cards    = {}     # batch_id -> frame widget
        self._tabs_ref        = None   # CTkTabview reference
        self._review_tab_name = "  Review  "
        self._all_products    = []     # cached list of {id, name}

        self._build_connect_screen()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Connect screen ─────────────────────────────────────────────────────────
    def _build_connect_screen(self):
        self._conn_frame = ctk.CTkFrame(self, fg_color=BG)
        self._conn_frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(self._conn_frame, text="💬",
                     font=ctk.CTkFont(size=56)).pack(pady=(0, 8))

        ctk.CTkLabel(self._conn_frame,
                     text="WhatsApp Order Bot",
                     font=ctk.CTkFont(size=26, weight="bold"),
                     text_color=TEXT).pack()

        ctk.CTkLabel(self._conn_frame,
                     text="Order Processing Dashboard",
                     font=ctk.CTkFont(size=13),
                     text_color=TEXT2).pack(pady=(4, 32))

        self._status_lbl = ctk.CTkLabel(self._conn_frame, text="",
                                         font=ctk.CTkFont(size=13),
                                         text_color=TEXT2, width=320)
        self._status_lbl.pack(pady=(0, 10))

        self._conn_btn = ctk.CTkButton(
            self._conn_frame,
            text="Connect to SQL Server",
            font=ctk.CTkFont(size=14, weight="bold"),
            width=270, height=46,
            fg_color=GREEN, hover_color=GREEN_D,
            text_color="#000000",
            corner_radius=8,
            command=self._do_connect,
        )
        self._conn_btn.pack(pady=(0, 10))

        self._settings_btn = ctk.CTkButton(
            self._conn_frame,
            text="⚙  Connection Settings",
            font=ctk.CTkFont(size=12),
            width=270, height=36,
            fg_color=CARD, hover_color=SURFACE,
            border_width=1, border_color=BORDER,
            text_color=TEXT,
            corner_radius=8,
            command=self._open_settings_dialog,
        )
        self._settings_btn.pack(pady=(0, 10))

        self._error_lbl = ctk.CTkLabel(self._conn_frame, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=ERROR,
                                        wraplength=330)
        self._error_lbl.pack()

    def _do_connect(self):
        self._conn_btn.configure(state="disabled", text="Connecting…")
        self._error_lbl.configure(text="")
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _set_conn_status(self, msg, color=WARN):
        self.after(0, lambda: self._status_lbl.configure(text=msg, text_color=color))

    def _connect_worker(self):
        """Start Flask + Node, wait for them, verify MSSQL — all in background."""
        try:
            # 0. Kill any orphaned node/flask processes from previous crashes
            self._set_conn_status("Cleaning up old processes…")
            try:
                subprocess.run(
                    ["powershell", "-Command", "Get-NetTCPConnection -LocalPort 3000,5050 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=5
                )
            except Exception:
                pass

            # 1. Start Python Flask webhook
            self._set_conn_status("Starting Python webhook…")
            self._flask_proc = subprocess.Popen(
                [sys.executable, str(PROJECT_DIR / "whatsapp_webhook.py")],
                cwd=str(ROOT_DIR),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            time.sleep(2.5)

            # 2. Start Node.js listener
            self._set_conn_status("Starting WhatsApp listener…")
            self._node_proc = subprocess.Popen(
                ["node", str(PROJECT_DIR / "whatsapp_listener.js")],
                cwd=str(ROOT_DIR),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            time.sleep(2)

            # 3. Wait for Flask to be reachable
            self._set_conn_status("Waiting for services to be ready…")
            for _ in range(20):
                try:
                    requests.get(f"{FLASK_URL}/health", timeout=2)
                    break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError(
                    "Flask webhook did not start within 20 seconds.\n"
                    "Make sure Python and all pip packages are installed."
                )

            # 4. Verify MSSQL connection
            self._set_conn_status("Connecting to SQL Server…")
            resp = requests.post(f"{FLASK_URL}/api/login", timeout=12)
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(
                    f"SQL Server connection failed:\n{data.get('error', 'Unknown error')}"
                )

            self.after(0, self._show_dashboard)

        except Exception as exc:
            self.after(0, lambda: self._connect_failed(str(exc)))

    def _connect_failed(self, msg: str):
        self._conn_btn.configure(state="normal", text="Connect to SQL Server")
        self._status_lbl.configure(text="Connection failed.", text_color=ERROR)
        self._error_lbl.configure(text=msg)
        for proc in (self._flask_proc, self._node_proc):
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
        self._flask_proc = self._node_proc = None

    # ── Dashboard shell ────────────────────────────────────────────────────────
    def _show_dashboard(self):
        self._conn_frame.place_forget()
        self._connected = True
        self._build_dashboard()
        threading.Thread(target=self._bg_refresh_loop, daemon=True).start()
        threading.Thread(target=self._bg_log_tail,     daemon=True).start()

    def _build_dashboard(self):
        # Fetch products once
        threading.Thread(target=self._fetch_products_bg, daemon=True).start()

        # Top bar
        topbar = ctk.CTkFrame(self, fg_color=SURFACE, height=50, corner_radius=0)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        inner = ctk.CTkFrame(topbar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20)

        ctk.CTkLabel(inner,
                     text="💬  WhatsApp Order Bot",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(side="left", pady=12)

        pills = ctk.CTkFrame(inner, fg_color="transparent")
        pills.pack(side="right", pady=12)
        self._pills = {}
        for name in ("Flask", "Node", "MSSQL", "Postgres"):
            lbl = ctk.CTkLabel(pills,
                               text=f"● {name}",
                               font=ctk.CTkFont(size=11, weight="bold"),
                               text_color=TEXT3,
                               fg_color=CARD,
                               corner_radius=20,
                               padx=10, pady=3)
            lbl.pack(side="left", padx=3)
            self._pills[name] = lbl

        # Tabview
        tabs = ctk.CTkTabview(
            self,
            fg_color=BG,
            segmented_button_fg_color=SURFACE,
            segmented_button_selected_color=GREEN,
            segmented_button_selected_hover_color=GREEN_D,
            segmented_button_unselected_color=SURFACE,
            segmented_button_unselected_hover_color=CARD,
        )
        tabs.pack(fill="both", expand=True, padx=16, pady=(10, 14))
        self._tabs_ref = tabs

        tabs.add("  Dashboard  ")
        tabs.add(self._review_tab_name)
        tabs.add("  Direct Entry  ")
        tabs.add("  Groups  ")
        tabs.add("  Live Logs  ")
        tabs.add("  Settings  ")

        self._build_tab_dashboard(tabs.tab("  Dashboard  "))
        self._build_tab_review(tabs.tab(self._review_tab_name))
        self._build_tab_direct_entry(tabs.tab("  Direct Entry  "))
        self._build_tab_groups(tabs.tab("  Groups  "))
        self._build_tab_logs(tabs.tab("  Live Logs  "))
        self._build_tab_settings(tabs.tab("  Settings  "))

    # ── Dashboard tab ──────────────────────────────────────────────────────────
    def _build_tab_dashboard(self, parent):
        parent.configure(fg_color=BG)

        cards = ctk.CTkFrame(parent, fg_color="transparent")
        cards.pack(fill="x", pady=(4, 18))
        cards.columnconfigure((0, 1, 2, 3), weight=1)

        self._stats = {}
        defs = [
            ("orders_today", "Orders Today",  TEXT, BORDER),
            ("needs_review", "Needs Review",  WARN, "#4a3800"),
            ("customers",    "Customers",     TEXT, BORDER),
            ("products",     "Products",      TEXT, BORDER),
        ]
        for col, (key, label, color, bcolor) in enumerate(defs):
            card = ctk.CTkFrame(cards, fg_color=CARD, corner_radius=10,
                                border_width=1, border_color=bcolor)
            card.grid(row=0, column=col, padx=6, sticky="ew")
            ctk.CTkLabel(card, text=label.upper(),
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=TEXT2).pack(anchor="w", padx=16, pady=(14, 4))
            val = ctk.CTkLabel(card, text="—",
                               font=ctk.CTkFont(size=30, weight="bold"),
                               text_color=color)
            val.pack(anchor="w", padx=16, pady=(0, 14))
            self._stats[key] = val

        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(hdr, text="Recent Orders",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkLabel(hdr, text="Click a pending order to open the Review tab →",
                     font=ctk.CTkFont(size=10),
                     text_color=TEXT3).pack(side="left", padx=12)
        self._refresh_lbl = ctk.CTkLabel(hdr, text="",
                                          font=ctk.CTkFont(size=11),
                                          text_color=TEXT3)
        self._refresh_lbl.pack(side="right")

        wrap = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10,
                            border_width=1, border_color=BORDER)
        wrap.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("T.Treeview",
                        background=CARD, foreground=TEXT,
                        fieldbackground=CARD, borderwidth=0,
                        rowheight=28, font=("Segoe UI", 11))
        style.configure("T.Treeview.Heading",
                        background=SURFACE, foreground=TEXT2,
                        relief="flat", font=("Segoe UI", 10, "bold"),
                        borderwidth=0)
        style.map("T.Treeview",
                  background=[("selected", "#2d3748")],
                  foreground=[("selected", TEXT)])
        style.layout("T.Treeview",
                     [("T.Treeview.treearea", {"sticky": "nswe"})])

        cols = ("id", "customer", "product", "qty", "status", "flag", "time")
        self._tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                   style="T.Treeview", selectmode="none")
        col_defs = [
            ("id",       "#",        46,  "center"),
            ("customer", "Customer", 185, "w"),
            ("product",  "Product",  230, "w"),
            ("qty",      "Qty",      54,  "center"),
            ("status",   "Status",   110, "center"),
            ("flag",     "Review",   80,  "center"),
            ("time",     "Time",     60,  "center"),
        ]
        for cid, heading, width, anchor in col_defs:
            self._tree.heading(cid, text=heading)
            self._tree.column(cid, width=width, minwidth=30, anchor=anchor)
        self._tree.tag_configure("needs_review", background=WARN_BG, foreground=WARN)
        self._tree.tag_configure("pending",      background="#1a2540", foreground=BLUE)

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        vsb.pack(side="right", fill="y", pady=4)

        # Single-click a pending_review row → jump to Review tab
        self._tree.bind("<ButtonRelease-1>", self._on_order_click)

    def _on_order_click(self, event):
        """Jump to the Review tab when user clicks a pending_review row."""
        item = self._tree.identify_row(event.y)
        if not item:
            return
        values = self._tree.item(item, "values")
        # values = (id, customer, product, qty, status, flag, time)
        if len(values) >= 5 and values[4] == "pending_review":
            if self._tabs_ref:
                self._tabs_ref.set(self._review_tab_name)
                self._load_review()

    # ── Review tab ─────────────────────────────────────────────────────────────
    def _build_tab_review(self, parent):
        parent.configure(fg_color=BG)

        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(hdr,
                     text="Pending Orders — Review & Confirm",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT).pack(side="left")

        ctk.CTkButton(hdr, text="↻ Refresh",
                      width=90, height=30,
                      fg_color=CARD, hover_color=SURFACE,
                      border_width=1, border_color=BORDER,
                      text_color=TEXT2, font=ctk.CTkFont(size=12),
                      command=self._load_review).pack(side="right")

        # Empty-state label (shown when no pending orders)
        self._review_empty = ctk.CTkLabel(parent,
                                           text="✓  All caught up — no pending orders.",
                                           font=ctk.CTkFont(size=13),
                                           text_color=TEXT2)

        # Scrollable card list
        self._review_scroll = ctk.CTkScrollableFrame(parent,
                                                      fg_color="transparent",
                                                      corner_radius=0)
        self._review_scroll.pack(fill="both", expand=True)
        self._review_scroll.columnconfigure(0, weight=1)

    def _load_review(self):
        threading.Thread(target=self._load_review_worker, daemon=True).start()

    def _load_review_worker(self):
        try:
            orders = requests.get(f"{FLASK_URL}/api/orders/pending", timeout=6).json()
            self.after(0, lambda o=orders: self._render_review(o))
        except Exception as e:
            self.after(0, lambda msg=str(e): self._render_review_error(msg))

    def _render_review(self, orders):
        # Prevent glitchy reloads: skip redraw if the data hasn't changed
        if getattr(self, "_last_orders", None) == orders:
            return
        self._last_orders = orders

        # Clear existing cards
        for w in self._review_scroll.winfo_children():
            w.destroy()
        self._review_cards.clear()
        self._review_empty.pack_forget()

        if not orders:
            self._review_empty.pack(pady=60)
            self._update_review_tab_label(0)
            return

        self._update_review_tab_label(len(orders))

        for idx, order in enumerate(orders):
            self._create_order_card(order, idx)

    def _render_review_error(self, msg):
        for w in self._review_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._review_scroll,
                     text=f"⚠ Could not load orders: {msg}",
                     text_color=ERROR,
                     font=ctk.CTkFont(size=12)).pack(pady=20)

    def _create_order_card(self, order, idx):
        batch_id     = order.get("batch_id", "")
        customer     = order.get("customer_name", "Unknown")
        raw_msg      = order.get("raw_message", "")
        special      = order.get("special_instructions", "")
        received_at  = order.get("received_at", "")
        needs_review = order.get("needs_review", False)
        lines        = order.get("lines", [])
        sender_name  = order.get("sender_name") or "—"
        sender_phone = order.get("sender_phone") or "—"
        details      = order.get("customer_details") or {}

        time_str = received_at[11:16] if len(received_at) >= 16 else "—"
        date_str = received_at[:10]   if len(received_at) >= 10 else ""
        
        # Pre-calculate total
        grand_total = sum(float(l.get("total", 0)) for l in lines)

        border_col = "#4a3800" if needs_review else BORDER
        card = ctk.CTkFrame(self._review_scroll, fg_color=CARD, corner_radius=10, border_width=1, border_color=border_col)
        card.grid(row=idx, column=0, sticky="ew", padx=4, pady=(0, 10))
        card.columnconfigure(0, weight=1)

        # ── Mini Tab Header ──────────────────────────────────────────────────
        header_frame = ctk.CTkFrame(card, fg_color="transparent")
        header_frame.pack(fill="x", padx=14, pady=10)

        # Left side: Customer and Total
        left_header = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_header.pack(side="left", fill="y")
        
        ctk.CTkLabel(left_header, text=customer, font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(left_header, text=f"Total: ${grand_total:,.2f}", font=ctk.CTkFont(size=12, weight="bold"), text_color=GREEN).pack(anchor="w")
        
        # Center: Sender
        center_header = ctk.CTkFrame(header_frame, fg_color="transparent")
        center_header.pack(side="left", fill="y", padx=30)
        ctk.CTkLabel(center_header, text="Sent by:", font=ctk.CTkFont(size=10), text_color=TEXT3).pack(anchor="w")
        ctk.CTkLabel(center_header, text=sender_name, font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT).pack(anchor="w")

        if needs_review:
            ctk.CTkLabel(header_frame, text="⚠ Needs Review", font=ctk.CTkFont(size=10, weight="bold"), text_color=WARN, fg_color=WARN_BG, corner_radius=6, padx=8, pady=2).pack(side="left", padx=20)

        # Right side: Expand Button
        right_header = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_header.pack(side="right", fill="y")
        ctk.CTkLabel(right_header, text=f"{date_str} {time_str}", font=ctk.CTkFont(size=11), text_color=TEXT3).pack(anchor="e", pady=(0, 5))
        
        content_frame = ctk.CTkFrame(card, fg_color="transparent")
        
        def toggle_expand(cf=content_frame, btn=None):
            if cf.winfo_ismapped():
                cf.pack_forget()
                btn.configure(text="▼ Expand Details")
            else:
                cf.pack(fill="x", expand=True)
                btn.configure(text="▲ Collapse")
                
        expand_btn = ctk.CTkButton(right_header, text="▼ Expand Details", width=120, height=28, fg_color=SURFACE, hover_color=BORDER, text_color=TEXT)
        expand_btn.configure(command=lambda: toggle_expand(btn=expand_btn))
        expand_btn.pack(anchor="e")

        # ── Expandable Content ────────────────────────────────────────────────
        # WhatsApp message preview
        ctk.CTkFrame(content_frame, height=1, fg_color=BORDER).pack(fill="x", padx=14, pady=(5, 6))
        ctk.CTkLabel(content_frame, text="💬 ORIGINAL MESSAGE", font=ctk.CTkFont(size=9, weight="bold"), text_color=TEXT3, anchor="w").pack(fill="x", padx=14, pady=(0, 2))
        msg_box = ctk.CTkTextbox(content_frame, height=100, fg_color="transparent", text_color=TEXT2, font=ctk.CTkFont(size=11, slant="italic"))
        msg_box.pack(fill="x", padx=14, pady=(0, 8))
        msg_box.insert("0.0", raw_msg)
        msg_box.configure(state="disabled")

        ctk.CTkFrame(content_frame, height=1, fg_color=BORDER).pack(fill="x", padx=14, pady=(0, 6))

        # Line items
        lines_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        lines_frame.pack(fill="x", padx=14)
        lines_frame.columnconfigure(0, weight=1)
        lines_frame.columnconfigure((1, 2, 3), weight=0)

        hdr_defs = [("Product", "w"), ("SKU", "center"), ("Cases | Lbs", "center"), ("Total", "e")]
        for col, (htext, anchor) in enumerate(hdr_defs):
            ctk.CTkLabel(lines_frame, text=htext.upper(), font=ctk.CTkFont(size=9, weight="bold"), text_color=TEXT3, anchor=anchor).grid(row=0, column=col, sticky="ew", pady=(0, 2))

        for r, line in enumerate(lines, start=1):
            product = line.get("product", "Unknown")
            sku     = line.get("sku", "—")
            qty     = line.get("qty", 0)
            sec_qty = line.get("secondary_qty", 0)
            total   = float(line.get("total", 0))
            unknown = sku == "UNKNOWN"
            row_color = WARN if unknown else TEXT

            qty_str = f"{qty} | {sec_qty}" if sec_qty else str(qty)

            ctk.CTkLabel(lines_frame, text=self._trunc(product, 40), font=ctk.CTkFont(size=12), text_color=row_color, anchor="w").grid(row=r, column=0, sticky="ew", pady=1)
            ctk.CTkLabel(lines_frame, text=sku, font=ctk.CTkFont(size=12), text_color=TEXT2, anchor="center").grid(row=r, column=1, sticky="ew", padx=8, pady=1)
            ctk.CTkLabel(lines_frame, text=qty_str, font=ctk.CTkFont(size=12), text_color=TEXT, anchor="center").grid(row=r, column=2, sticky="ew", padx=8, pady=1)
            ctk.CTkLabel(lines_frame, text=f"${total:,.2f}", font=ctk.CTkFont(size=12), text_color=TEXT, anchor="e").grid(row=r, column=3, sticky="ew", pady=1)

        ctk.CTkFrame(lines_frame, height=1, fg_color=BORDER).grid(row=len(lines)+1, column=0, columnspan=4, sticky="ew", pady=(4, 2))
        ctk.CTkLabel(lines_frame, text="TOTAL", font=ctk.CTkFont(size=10, weight="bold"), text_color=TEXT2, anchor="e").grid(row=len(lines)+2, column=2, sticky="e")
        ctk.CTkLabel(lines_frame, text=f"${grand_total:,.2f}", font=ctk.CTkFont(size=13, weight="bold"), text_color=GREEN, anchor="e").grid(row=len(lines)+2, column=3, sticky="ew", pady=(0, 6))

        if special and special.lower() not in ("none", ""):
            ctk.CTkLabel(content_frame, text=f"📝 {special}", font=ctk.CTkFont(size=11), text_color=WARN, anchor="w").pack(fill="x", padx=14, pady=(4, 0))

        # Action buttons
        ctk.CTkFrame(content_frame, height=1, fg_color=BORDER).pack(fill="x", padx=14, pady=(8, 0))
        btns = ctk.CTkFrame(content_frame, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=10)

        result_lbl = ctk.CTkLabel(btns, text="", font=ctk.CTkFont(size=12), text_color=TEXT2)
        result_lbl.pack(side="left", padx=(0, 12))

        ctk.CTkButton(btns, text="✗ Reject", width=100, height=34, fg_color=CARD, hover_color="#3d1f1f", border_width=1, border_color=ERROR, text_color=ERROR, font=ctk.CTkFont(size=12, weight="bold"), command=lambda b=batch_id, c=card, l=result_lbl: self._reject_order(b, c, l)).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="✎ Edit Order", width=100, height=34, fg_color=CARD, hover_color=SURFACE, border_width=1, border_color=BLUE, text_color=BLUE, font=ctk.CTkFont(size=12, weight="bold"), command=lambda o=order: self._open_edit_dialog(o)).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="✓ Confirm & Send to SQL", width=180, height=34, fg_color=GREEN, hover_color=GREEN_D, text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"), command=lambda b=batch_id, c=card, l=result_lbl: self._confirm_order(b, c, l)).pack(side="right")

        self._review_cards[batch_id] = card

    def _fetch_products_bg(self):
        try:
            self._all_products = requests.get(f"{FLASK_URL}/api/products", timeout=5).json()
        except Exception:
            self._all_products = []

    def _open_edit_dialog(self, order):
        """Open a popup window to edit quantities, products, and customer overrides."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Full Edit Order")
        dialog.geometry("700x600")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=f"Editing Order: {order.get('customer_name')}",
                     font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT).pack(pady=10)

        tabs = ctk.CTkTabview(dialog)
        tabs.pack(fill="both", expand=True, padx=20, pady=5)
        tab_lines = tabs.add("Line Items")
        tab_cust  = tabs.add("Customer Details")
        tab_notes = tabs.add("Notes")

        # ── Tab: Line Items ──────────────────────────────────────────────────
        lines_scroll = ctk.CTkScrollableFrame(tab_lines, fg_color="transparent")
        lines_scroll.pack(fill="both", expand=True)

        qty_entries = {}
        prod_vars = {}
        note_entries = {}
        deleted_line_ids = []

        for line in order.get("lines", []):
            row = ctk.CTkFrame(lines_scroll, fg_color=CARD)
            row.pack(fill="x", pady=4, padx=5)

            top_part = ctk.CTkFrame(row, fg_color="transparent")
            top_part.pack(fill="x")

            prod_name_var = ctk.StringVar(value=line.get("product", "Unknown"))
            prod_id_var = ctk.StringVar(value=str(line.get("product_id", "")))

            entry = ctk.CTkEntry(top_part, textvariable=prod_name_var, width=280)
            entry.pack(side="left", padx=10, pady=10)

            ctk.CTkLabel(top_part, text="Cases:", font=ctk.CTkFont(size=12), text_color=TEXT2).pack(side="left", padx=5)
            qty_entry = ctk.CTkEntry(top_part, width=60, justify="center")
            qty_entry.insert(0, str(line.get("qty", 0)))
            qty_entry.pack(side="left")

            ctk.CTkLabel(top_part, text="Note:", font=ctk.CTkFont(size=12), text_color=TEXT2).pack(side="left", padx=(10, 5))
            note_entry = ctk.CTkEntry(top_part, width=150)
            note_entry.insert(0, line.get("line_note") or "")
            note_entry.pack(side="left")

            def remove_line(r=row, lid=line["id"]):
                r.destroy()
                if lid in qty_entries: del qty_entries[lid]
                if lid in prod_vars: del prod_vars[lid]
                if lid in note_entries: del note_entries[lid]
                deleted_line_ids.append(lid)

            ctk.CTkButton(top_part, text="✗", width=30, fg_color=CARD, hover_color="#3d1f1f",
                          text_color=ERROR, command=remove_line).pack(side="left", padx=(10, 0))

            qty_entries[line["id"]] = qty_entry
            prod_vars[line["id"]]   = prod_id_var
            note_entries[line["id"]] = note_entry

            results_frame = ctk.CTkScrollableFrame(row, height=120, fg_color=SURFACE)

            def on_key(event, var=prod_name_var, rf=results_frame, idv=prod_id_var):
                idv.set("") # Clear product ID if they are typing manually
                query = var.get().lower()
                for w in rf.winfo_children():
                    w.destroy()
                
                if not query or len(query) < 2:
                    rf.pack_forget()
                    return
                
                matches = [p for p in self._all_products if query in p['name'].lower() or query in str(p['sku']).lower()][:20]
                if not matches:
                    rf.pack_forget()
                    return
                
                rf.pack(fill="x", padx=10, pady=(0, 10))
                for p in matches:
                    def select(p=p):
                        var.set(p['name'])
                        idv.set(str(p['id']))
                        rf.pack_forget()
                    
                    price = float(p.get('price') or 0.0)
                    lbl_text = f"[{p['sku']}] {p['name']} (${price:.2f})"
                    btn = ctk.CTkButton(rf, text=lbl_text, anchor="w", fg_color="transparent", 
                                        text_color=TEXT, hover_color=CARD, command=select)
                    btn.pack(fill="x", pady=1)

            entry.bind("<KeyRelease>", on_key)

            qty_entries[line["id"]] = qty_entry
            prod_vars[line["id"]] = {"name": prod_name_var, "id": prod_id_var}

        # ── Tab: Customer Details ────────────────────────────────────────────
        cust_scroll = ctk.CTkScrollableFrame(tab_cust, fg_color="transparent")
        cust_scroll.pack(fill="both", expand=True)
        
        details = order.get("customer_details") or {}
        fields = {}

        def add_field(label_text, default_val):
            f = ctk.CTkFrame(cust_scroll, fg_color="transparent")
            f.pack(fill="x", pady=4, padx=10)
            ctk.CTkLabel(f, text=label_text, width=120, anchor="w", text_color=TEXT2).pack(side="left")
            entry = ctk.CTkEntry(f)
            entry.insert(0, str(default_val) if default_val is not None else "")
            entry.pack(side="left", fill="x", expand=True)
            return entry

        fields['address1']      = add_field("Address 1", details.get("address1"))
        fields['address2']      = add_field("Address 2", details.get("address2"))
        fields['city']          = add_field("City", details.get("city"))
        fields['state']         = add_field("State", details.get("state"))
        fields['zipcode']       = add_field("Zipcode", details.get("zipcode"))
        fields['country']       = add_field("Country", details.get("country"))
        fields['payment_terms'] = add_field("Payment Terms", details.get("payment_terms"))
        fields['delivery_terms']= add_field("Delivery Terms", details.get("delivery_terms"))
        fields['salesman_id']   = add_field("Salesman ID", details.get("salesman_id"))
        fields['tax_id']        = add_field("Tax ID", details.get("tax_id"))
        fields['phone']         = add_field("Account Phone", details.get("phone"))
        fields['delivery_notes']= add_field("Delivery Notes", details.get("delivery_notes"))

        # ── Tab: Notes ───────────────────────────────────────────────────────
        notes_entry = ctk.CTkTextbox(tab_notes)
        notes_entry.insert("0.0", order.get("special_instructions") or "")
        notes_entry.pack(fill="both", expand=True, padx=10, pady=10)

        # ── Save ─────────────────────────────────────────────────────────────
        def save():
            lines_data = []
            for line_id, entry_widget in qty_entries.items():
                try:
                    qty = float(entry_widget.get())
                    prod_id_str = prod_vars[line_id]["id"].get()
                    prod_id = int(prod_id_str) if prod_id_str.isdigit() else None
                    
                    note_str = note_entries[line_id].get().strip() if line_id in note_entries else None
                    
                    lines_data.append({
                        "id": line_id, 
                        "qty": qty, 
                        "product_id": prod_id,
                        "line_note": note_str
                    })
                except ValueError:
                    pass

            special = notes_entry.get("0.0", "end").strip()

            overrides = {}
            for k, w in fields.items():
                val = w.get().strip()
                if val: overrides[k] = val
                
            payload = {
                "batch_id": order["batch_id"],
                "lines": lines_data,
                "deleted_lines": deleted_line_ids,
                "special_instructions": special,
                "customer_overrides": overrides if overrides else None
            }

            threading.Thread(target=self._save_edit_worker, args=(payload, dialog), daemon=True).start()
            dialog.destroy()

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(fill="x", pady=15, padx=20)
        
        ctk.CTkButton(btns, text="Cancel", width=100, fg_color=CARD, hover_color=SURFACE, 
                      command=dialog.destroy).pack(side="right", padx=(10, 0))
        ctk.CTkButton(btns, text="Save Changes", width=140, fg_color=BLUE, hover_color="#3182ce", 
                      command=save).pack(side="right")

    def _save_edit_worker(self, payload, dialog):
        try:
            resp = requests.post(f"{FLASK_URL}/api/orders/edit", json=payload, timeout=10)
            if resp.json().get("ok"):
                self.after(0, self._load_review)
        except Exception as e:
            print(f"Error saving edit: {e}")



    def _confirm_order(self, batch_id, card, result_lbl):
        result_lbl.configure(text="Sending to SQL Server…", text_color=WARN)
        threading.Thread(target=self._confirm_worker,
                         args=(batch_id, card, result_lbl), daemon=True).start()

    def _confirm_worker(self, batch_id, card, result_lbl):
        try:
            resp = requests.post(f"{FLASK_URL}/api/orders/confirm",
                                 json={"batch_id": batch_id}, timeout=20)
            data = resp.json()
            if data.get("ok"):
                self.after(0, lambda: result_lbl.configure(
                    text="✓ Sent to SQL Server!", text_color=GREEN))
                self.after(1800, lambda: self._remove_card(batch_id))
                self.after(2000, self._load_review)
            else:
                err = data.get("error", "Unknown error")
                self.after(0, lambda e=err: result_lbl.configure(
                    text=f"⚠ {e}", text_color=ERROR))
        except Exception as e:
            self.after(0, lambda e=e: result_lbl.configure(
                text=f"⚠ {e}", text_color=ERROR))

    def _reject_order(self, batch_id, card, result_lbl):
        result_lbl.configure(text="Rejecting…", text_color=WARN)
        threading.Thread(target=self._reject_worker,
                         args=(batch_id, card, result_lbl), daemon=True).start()

    def _reject_worker(self, batch_id, card, result_lbl):
        try:
            resp = requests.post(f"{FLASK_URL}/api/orders/reject",
                                 json={"batch_id": batch_id}, timeout=5)
            data = resp.json()
            if data.get("ok"):
                self.after(0, lambda: self._remove_card(batch_id))
                self.after(500, self._load_review)
            else:
                self.after(0, lambda d=data: result_lbl.configure(
                    text=f"⚠ {d.get('error')}", text_color=ERROR))
        except Exception as e:
            self.after(0, lambda e=e: result_lbl.configure(
                text=f"⚠ {e}", text_color=ERROR))

    def _remove_card(self, batch_id):
        card = self._review_cards.pop(batch_id, None)
        if card:
            card.destroy()

    def _update_review_tab_label(self, count):
        # CustomTkinter doesn't support renaming tabs after creation,
        # so we update a badge label stored on the tab widget.
        if self._tabs_ref and hasattr(self, "_review_badge"):
            txt = f"  Review ({count})  " if count > 0 else "  Review  "
            try:
                self._review_badge.configure(text=txt)
            except Exception:
                pass

    # ── Direct Entry tab ───────────────────────────────────────────────────────
    def _build_tab_direct_entry(self, parent):
        parent.configure(fg_color=BG)
        
        self._direct_pdf_path = None
        
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="both", expand=True, pady=10)
        container.columnconfigure(0, weight=2)
        container.columnconfigure(1, weight=1)

        # Left Column (Input)
        left_col = ctk.CTkFrame(container, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        ctk.CTkLabel(left_col, text="Enter Order Text:", 
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT).pack(anchor="w", pady=(0, 5))
        
        self._direct_text = ctk.CTkTextbox(left_col, height=250, fg_color=CARD, text_color=TEXT, 
                                          border_width=1, border_color=BORDER)
        self._direct_text.pack(fill="x", pady=(0, 15))

        pdf_frame = ctk.CTkFrame(left_col, fg_color="transparent")
        pdf_frame.pack(fill="x", pady=(0, 15))
        
        ctk.CTkButton(pdf_frame, text="📎 Attach PDF", fg_color=CARD, border_width=1, border_color=BORDER, 
                      text_color=TEXT, hover_color=SURFACE, command=self._attach_pdf).pack(side="left", padx=(0, 10))
        self._direct_pdf_lbl = ctk.CTkLabel(pdf_frame, text="No PDF selected", text_color=TEXT3)
        self._direct_pdf_lbl.pack(side="left")

        ctk.CTkButton(left_col, text="Submit Order", fg_color=GREEN, hover_color=GREEN_D, text_color=BG,
                      font=ctk.CTkFont(weight="bold"), command=self._submit_direct_entry).pack(fill="x")
                      
        self._direct_status_lbl = ctk.CTkLabel(left_col, text="", text_color=TEXT)
        self._direct_status_lbl.pack(pady=(5, 0))

        # Right Column (Format Instructions)
        right_col = ctk.CTkFrame(container, fg_color=CARD, corner_radius=10, border_width=1, border_color=BORDER)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        
        ctk.CTkLabel(right_col, text="💡 Best Format Example", font=ctk.CTkFont(size=14, weight="bold"), 
                     text_color=TEXT).pack(anchor="w", padx=16, pady=(16, 10))
                     
        example_text = (
            "Customer: EL BUEN SAZON\n\n"
            "1010 BEEF HIND SHANK SL 1/2 IN x5\n"
            "1009 BEEF FEET CUT x100\n"
            "1007 BEEF TRIPE CUT 1X1 x60\n\n"
            "Delivery: Monday morning\n\n"
            "---\n"
            "Note: You can also just upload a PDF and leave the text blank! It will parse the PDF perfectly."
        )
        ex_lbl = ctk.CTkTextbox(right_col, fg_color="transparent", text_color=TEXT2)
        ex_lbl.insert("1.0", example_text)
        ex_lbl.configure(state="disabled")
        ex_lbl.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _attach_pdf(self):
        filepath = filedialog.askopenfilename(
            title="Select PDF Order",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")]
        )
        if filepath:
            self._direct_pdf_path = filepath
            self._direct_pdf_lbl.configure(text=os.path.basename(filepath), text_color=GREEN)

    def _show_direct_status(self, msg, color=GREEN):
        self._direct_status_lbl.configure(text=msg, text_color=color)
        if hasattr(self, "_direct_status_timer") and self._direct_status_timer:
            self.after_cancel(self._direct_status_timer)
        self._direct_status_timer = self.after(5000, lambda: self._direct_status_lbl.configure(text=""))

    def _submit_direct_entry(self):
        text = self._direct_text.get("1.0", "end-1c").strip()
        pdf_path = getattr(self, "_direct_pdf_path", None)
        
        if not text and not pdf_path:
            self._show_direct_status("Please enter order text or attach a PDF.", ERROR)
            return
            
        pdf_base64 = None
        pdf_name = None
        if pdf_path:
            try:
                with open(pdf_path, "rb") as f:
                    pdf_base64 = base64.b64encode(f.read()).decode('utf-8')
                pdf_name = os.path.basename(pdf_path)
            except Exception as e:
                self._show_direct_status(f"Could not read PDF: {e}", ERROR)
                return

        payload = {
            "sender_phone": "+10000000000",
            "sender_name": "Direct Entry",
            "body": text,
            "chat_id": "direct@c.us",
            "is_group": False,
            "timestamp": datetime.now().isoformat() + "Z",
            "has_pdf": bool(pdf_path),
            "pdf_data": pdf_base64,
            "pdf_name": pdf_name
        }
        
        # We start a thread so the UI doesn't freeze while waiting for the webhook
        def _send():
            try:
                resp = requests.post(f"{FLASK_URL}/webhook", json=payload, timeout=20)
                if resp.status_code == 200:
                    self.after(0, lambda: self._show_direct_status("✓ Order submitted to Pending!", GREEN))
                    self.after(0, lambda: self._direct_text.delete("1.0", "end"))
                    self._direct_pdf_path = None
                    self.after(0, lambda: self._direct_pdf_lbl.configure(text="No PDF selected", text_color=TEXT3))
                else:
                    self.after(0, lambda: self._show_direct_status(f"Webhook Error {resp.status_code}", ERROR))
            except Exception as e:
                self.after(0, lambda: self._show_direct_status(f"Connection Error: {e}", ERROR))
                
        threading.Thread(target=_send, daemon=True).start()

    # ── Groups tab ─────────────────────────────────────────────────────────────
    def _build_tab_groups(self, parent):
        parent.configure(fg_color=BG)

        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(top, text="Select which WhatsApp groups to monitor:",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT).pack(side="left")

        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.pack(side="right")

        ctk.CTkButton(btns, text="↻ Refresh",
                      width=95, height=32,
                      fg_color=CARD, hover_color=SURFACE,
                      border_width=1, border_color=BORDER,
                      text_color=TEXT2, font=ctk.CTkFont(size=12),
                      command=self._load_groups).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btns, text="✓ Apply Selection",
                      width=145, height=32,
                      fg_color=GREEN, hover_color=GREEN_D,
                      text_color="#000000",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._apply_groups).pack(side="left")

        self._group_msg = ctk.CTkLabel(parent, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=TEXT2, anchor="w")
        self._group_msg.pack(fill="x", pady=(0, 8))

        self._groups_frame = ctk.CTkScrollableFrame(parent,
                                                     fg_color=CARD,
                                                     corner_radius=10,
                                                     border_width=1,
                                                     border_color=BORDER)
        self._groups_frame.pack(fill="both", expand=True)

    def _load_groups(self):
        self._group_msg.configure(text="Loading groups from WhatsApp…", text_color=WARN)
        threading.Thread(target=self._load_groups_worker, daemon=True).start()

    def _load_groups_worker(self):
        try:
            resp = requests.get(f"{NODE_URL}/groups", timeout=6)
            data = resp.json()
            if not data.get("ok"):
                self.after(0, lambda d=data: self._group_msg.configure(
                    text=f"Error: {d.get('error', 'Unknown')}", text_color=ERROR))
                return
            self.after(0, lambda d=data: self._render_groups(
                d.get("groups", []), d.get("current", [])))
        except Exception as e:
            self.after(0, lambda e=e: self._group_msg.configure(
                text=f"⚠ Could not reach Node listener — is WhatsApp connected? ({e})",
                text_color=ERROR))

    def _render_groups(self, groups, current):
        for cb in self._group_cbs:
            cb.destroy()
        self._group_cbs.clear()
        self._group_vars.clear()

        if not groups:
            self._group_msg.configure(
                text="No WhatsApp groups found on this account.", text_color=TEXT2)
            return

        self._group_msg.configure(
            text=f"{len(groups)} group(s) found — check the ones you want to monitor:",
            text_color=TEXT2)

        for g in groups:
            var = ctk.BooleanVar(value=g["name"] in current)
            cb = ctk.CTkCheckBox(
                self._groups_frame,
                text=g["name"],
                variable=var,
                font=ctk.CTkFont(size=13),
                text_color=TEXT,
                fg_color=GREEN, hover_color=GREEN_D,
                checkmark_color="#000000",
                border_color=BORDER,
            )
            cb.pack(anchor="w", padx=18, pady=7)
            self._group_vars[g["name"]] = var
            self._group_cbs.append(cb)

    def _apply_groups(self):
        selected = [n for n, v in self._group_vars.items() if v.get()]
        if not selected:
            self._group_msg.configure(
                text="⚠ Please select at least one group.", text_color=WARN)
            return
        threading.Thread(target=self._apply_groups_worker,
                         args=(selected,), daemon=True).start()

    def _apply_groups_worker(self, selected):
        try:
            resp = requests.post(f"{NODE_URL}/config",
                                 json={"groups": selected}, timeout=5)
            data = resp.json()
            if data.get("ok"):
                names = ", ".join(selected)
                self.after(0, lambda: self._group_msg.configure(
                    text=f"✓ Now monitoring: {names}", text_color=GREEN))
            else:
                self.after(0, lambda d=data: self._group_msg.configure(
                    text=f"Error: {d.get('error')}", text_color=ERROR))
        except Exception as e:
            self.after(0, lambda e=e: self._group_msg.configure(
                text=f"Failed to apply: {e}", text_color=ERROR))

    # ── Live Logs tab ──────────────────────────────────────────────────────────
    def _build_tab_logs(self, parent):
        parent.configure(fg_color=BG)

        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(hdr, text="Live Logs",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT).pack(side="left")
        self._pause_btn = ctk.CTkButton(hdr, text="⏸ Pause",
                                         width=90, height=30,
                                         fg_color=CARD, hover_color=SURFACE,
                                         border_width=1, border_color=BORDER,
                                         text_color=TEXT2, font=ctk.CTkFont(size=12),
                                         command=self._toggle_pause)
        self._pause_btn.pack(side="right")

        self._log_box = ctk.CTkTextbox(
            parent,
            fg_color="#010409", text_color=TEXT2,
            font=ctk.CTkFont(family="Courier New", size=11),
            corner_radius=10, border_width=1, border_color=BORDER,
            wrap="none", state="disabled",
        )
        self._log_box.pack(fill="both", expand=True)

        tb = self._log_box._textbox
        tb.tag_configure("error",   foreground=ERROR)
        tb.tag_configure("warning", foreground=WARN)
        tb.tag_configure("info",    foreground=TEXT2)
        tb.tag_configure("section", foreground=BLUE)

    def _toggle_pause(self):
        self._paused_log = not self._paused_log
        if self._paused_log:
            self._pause_btn.configure(text="▶ Resume",
                                      border_color=WARN, text_color=WARN)
        else:
            self._pause_btn.configure(text="⏸ Pause",
                                      border_color=BORDER, text_color=TEXT2)
            self._log_box._textbox.see("end")

    def _append_log(self, line: str):
        if self._paused_log:
            return
        ul = line.upper()
        if   "ERROR"   in ul:                       tag = "error"
        elif "WARNING" in ul or "WARN" in ul:       tag = "warning"
        elif "====" in line or "SALES DRAFT" in ul: tag = "section"
        else:                                       tag = "info"

        tb = self._log_box._textbox
        tb.configure(state="normal")
        tb.insert("end", line + "\n", tag)
        if int(tb.index("end-1c").split(".")[0]) > 1200:
            tb.delete("1.0", "200.0")
        tb.configure(state="disabled")
        tb.see("end")

    # ── Background workers ─────────────────────────────────────────────────────
    def _bg_log_tail(self):
        for _ in range(40):
            if LOG_FILE.exists():
                break
            time.sleep(0.5)
        if not LOG_FILE.exists():
            self.after(0, lambda: self._append_log("[INFO] Waiting for webhook.log…"))
            return
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            for line in f.readlines()[-100:]:
                stripped = line.rstrip()
                if stripped:
                    self.after(0, lambda l=stripped: self._append_log(l))
            while self._connected:
                line = f.readline()
                if line:
                    stripped = line.rstrip()
                    if stripped:
                        self.after(0, lambda l=stripped: self._append_log(l))
                else:
                    time.sleep(0.25)

    def _bg_refresh_loop(self):
        self._refresh_ctr = 0
        self.after(800,  self._load_groups)
        self.after(1000, self._load_review)
        self.after(1200, lambda: threading.Thread(
            target=self._fetch_all, daemon=True).start())

        while self._connected:
            time.sleep(1)
            self._refresh_ctr += 1
            
            # Update countdown every second
            secs = 30 - (self._refresh_ctr % 30)
            if hasattr(self, '_refresh_lbl') and self._refresh_lbl.winfo_exists():
                self.after(0, lambda s=secs: self._refresh_lbl.configure(text=f"Refreshes in {s}s"))

            if self._refresh_ctr % 5 == 0:
                threading.Thread(target=self._fetch_status, daemon=True).start()
            if self._refresh_ctr % 15 == 0:   # every 15s — review queue
                self.after(0, self._load_review)
            if self._refresh_ctr % 30 == 0:   # every 30s — stats/orders
                threading.Thread(target=self._fetch_data, daemon=True).start()

    def _fetch_all(self):
        self._fetch_status()
        self._fetch_data()

    def _fetch_status(self):
        try:
            data = requests.get(f"{FLASK_URL}/api/status", timeout=3).json()
            self.after(0, lambda d=data: self._update_pills(d))
        except Exception:
            pass

    def _update_pills(self, data):
        for label, key in (("Flask","flask"),("Node","node"),
                           ("MSSQL","mssql"),("Postgres","postgres")):
            color = GREEN if data.get(key) else ERROR
            self._pills[label].configure(text_color=color)

    def _fetch_data(self):
        try:
            s = requests.get(f"{FLASK_URL}/api/stats", timeout=5).json()
            if "error" not in s:
                self.after(0, lambda d=s: self._update_stats(d))
        except Exception:
            pass
        try:
            orders = requests.get(f"{FLASK_URL}/api/orders", timeout=5).json()
            if isinstance(orders, list):
                self.after(0, lambda o=orders: self._update_orders(o))
        except Exception:
            pass

    def _update_stats(self, data):
        for key in ("orders_today", "needs_review", "customers", "products"):
            val = data.get(key)
            txt = f"{int(val):,}" if val is not None else "—"
            self._stats[key].configure(text=txt)

    def _update_orders(self, orders):
        # Prevent glitchy reloads: skip redraw if the data hasn't changed
        if getattr(self, "_last_dashboard_orders", None) == orders:
            return
        self._last_dashboard_orders = orders

        self._tree.delete(*self._tree.get_children())
        for o in orders:
            ts   = o.get("created_at") or ""
            t    = ts[11:16] if len(ts) >= 16 else "—"
            qty  = o.get("quantity")
            qty_s = str(int(qty)) if qty is not None else "—"
            nr   = o.get("needs_review", False)
            status = o.get("status", "")
            # Colour: amber = needs review, blue = pending but clean, default = confirmed
            if status == "pending_review" and nr:
                tags = ("needs_review",)
            elif status == "pending_review":
                tags = ("pending",)
            else:
                tags = ()
            flag_txt = "⚠ Review" if nr else ("🟡 Pending" if status == "pending_review" else "✓ OK")
            self._tree.insert("", "end", values=(
                o.get("id", ""),
                self._trunc(o.get("customer") or "", 28),
                self._trunc(o.get("product")  or "", 36),
                qty_s,
                status,
                flag_txt,
                t,
            ), tags=tags)

    @staticmethod
    def _trunc(s: str, n: int) -> str:
        return s if len(s) <= n else s[:n] + "…"

    # ── Settings Configuration ────────────────────────────────────────────────
    def _load_env_dict(self):
        env_path = ROOT_DIR / ".env"
        if not env_path.exists():
            example_path = PROJECT_DIR / ".env.example"
            if example_path.exists():
                try:
                    import shutil
                    shutil.copy(example_path, env_path)
                except Exception:
                    pass
        
        env_vars = {
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
            "DB_NAME": "whatsapp_orders",
            "DB_USER": "openpg",
            "DB_PASSWORD": "openpgpwd",
            "PUSH_TO_MSSQL": "True",
            "MSSQL_CONN_STR": "",
            "WHATSAPP_API_KEY": "mock_api_key_for_testing_12345",
            "WHATSAPP_PHONE_NUMBER_ID": "1234567890",
        }
        
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip()
                            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                                v = v[1:-1]
                            env_vars[k] = v
            except Exception as e:
                print(f"Error loading .env: {e}")
        return env_vars

    def _save_env_dict(self, env_vars):
        env_path = ROOT_DIR / ".env"
        lines = []
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception:
                pass
                
        updated_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, v = stripped.split("=", 1)
                k = k.strip()
                if k in env_vars:
                    val_to_write = env_vars[k]
                    if any(char in val_to_write for char in (' ', '=', '{', ';', '"', "'")):
                        new_lines.append(f'{k}="{val_to_write}"\n')
                    else:
                        new_lines.append(f'{k}={val_to_write}\n')
                    updated_keys.add(k)
                    continue
            new_lines.append(line)
            
        for k, v in env_vars.items():
            if k not in updated_keys:
                val_to_write = v
                if any(char in val_to_write for char in (' ', '=', '{', ';', '"', "'")):
                    new_lines.append(f'{k}="{val_to_write}"\n')
                else:
                    new_lines.append(f'{k}={val_to_write}\n')
                    
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return True
        except Exception as e:
            print(f"Error saving .env: {e}")
            return False

    def _open_settings_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Connection & Environment Settings")
        dialog.geometry("620x680")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Environment Configuration",
                     font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT).pack(pady=(15, 0))

        self._build_settings_form(dialog, is_dialog=True, dialog_win=dialog)

    def _build_tab_settings(self, parent):
        parent.configure(fg_color=BG)
        self._build_settings_form(parent, is_dialog=False)

    def _build_settings_form(self, container, is_dialog=False, dialog_win=None):
        env_vars = self._load_env_dict()

        scroll = ctk.CTkScrollableFrame(container, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        scroll.columnconfigure(0, weight=1)

        def add_section(text):
            f = ctk.CTkFrame(scroll, fg_color="transparent")
            f.pack(fill="x", pady=(15, 5))
            ctk.CTkLabel(f, text=text, font=ctk.CTkFont(size=13, weight="bold"), text_color=BLUE).pack(anchor="w")
            ctk.CTkFrame(f, height=1, fg_color=BORDER).pack(fill="x", pady=4)

        entries = {}
        def add_input(label_text, key, is_checkbox=False):
            f = ctk.CTkFrame(scroll, fg_color="transparent")
            f.pack(fill="x", pady=4)
            ctk.CTkLabel(f, text=label_text, width=200, anchor="w", text_color=TEXT2).pack(side="left")
            
            if is_checkbox:
                var = ctk.BooleanVar(value=env_vars.get(key, "True").lower() == "true")
                cb = ctk.CTkCheckBox(f, text="", variable=var, fg_color=GREEN, hover_color=GREEN_D, checkmark_color="#000000", border_color=BORDER)
                cb.pack(side="left")
                entries[key] = var
            else:
                entry = ctk.CTkEntry(f, fg_color=CARD, text_color=TEXT, border_color=BORDER)
                entry.insert(0, env_vars.get(key, ""))
                entry.pack(side="left", fill="x", expand=True)
                entries[key] = entry

        add_section("Local PostgreSQL Database")
        add_input("Host Address", "DB_HOST")
        add_input("Port Number", "DB_PORT")
        add_input("Database Name", "DB_NAME")
        add_input("Username", "DB_USER")
        add_input("Password", "DB_PASSWORD")

        add_section("Remote SQL Server Integration")
        add_input("Push Drafts directly to SQL", "PUSH_TO_MSSQL", is_checkbox=True)
        add_input("SQL Server Connection String", "MSSQL_CONN_STR")

        add_section("WhatsApp Meta API Configuration (Optional)")
        add_input("API Key", "WHATSAPP_API_KEY")
        add_input("Phone Number ID", "WHATSAPP_PHONE_NUMBER_ID")

        status_lbl = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=12))
        status_lbl.pack(pady=10)

        def save():
            payload = {}
            for k, val_w in entries.items():
                if isinstance(val_w, ctk.BooleanVar):
                    payload[k] = str(val_w.get())
                else:
                    payload[k] = val_w.get().strip()
            
            if not payload["DB_HOST"] or not payload["DB_PORT"] or not payload["DB_NAME"] or not payload["DB_USER"]:
                status_lbl.configure(text="Please fill in all database fields.", text_color=ERROR)
                return
                
            success = self._save_env_dict(payload)
            if success:
                status_lbl.configure(text="OK Settings saved to .env file! Restart services to apply.", text_color=GREEN)
                if is_dialog and dialog_win:
                    self.after(1200, dialog_win.destroy)
            else:
                status_lbl.configure(text="Failed to save settings. Check write permissions.", text_color=ERROR)

        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10)
        
        save_btn = ctk.CTkButton(
            btn_frame, 
            text="Save Settings", 
            font=ctk.CTkFont(weight="bold"),
            fg_color=GREEN, hover_color=GREEN_D, text_color=BG,
            command=save
        )
        save_btn.pack(side="right")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    def _on_close(self):
        self._connected = False
        for proc in (self._flask_proc, self._node_proc):
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
        self.destroy()


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
