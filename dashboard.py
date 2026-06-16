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
from tkinter import ttk
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
FLASK_URL   = "http://localhost:5050"
NODE_URL    = "http://localhost:3000"
LOG_FILE    = PROJECT_DIR / "webhook.log"

# ── Palette ────────────────────────────────────────────────────────────────────
BG      = "#0d1117"
SURFACE = "#161b22"
CARD    = "#21262d"
BORDER  = "#30363d"
GREEN   = "#25d366"
GREEN_D = "#1da854"
WARN    = "#d29922"
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
        self.geometry("1060x740")
        self.minsize(900, 640)
        self.configure(fg_color=BG)

        # Subprocess handles
        self._flask_proc = None
        self._node_proc  = None

        # State
        self._connected   = False
        self._paused_log  = False
        self._group_vars  = {}     # group_name -> ctk.BooleanVar
        self._group_cbs   = []     # list of CTkCheckBox widgets
        self._refresh_ctr = 0

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
            # ── 1. Start Python Flask webhook ──────────────────────────────────
            self._set_conn_status("Starting Python webhook…")
            self._flask_proc = subprocess.Popen(
                [sys.executable, str(PROJECT_DIR / "whatsapp_webhook.py")],
                cwd=str(PROJECT_DIR),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            time.sleep(2.5)

            # ── 2. Start Node.js listener ──────────────────────────────────────
            self._set_conn_status("Starting WhatsApp listener…")
            self._node_proc = subprocess.Popen(
                ["node", str(PROJECT_DIR / "whatsapp_listener.js")],
                cwd=str(PROJECT_DIR),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            time.sleep(2)

            # ── 3. Wait for Flask to be reachable ─────────────────────────────
            self._set_conn_status("Waiting for services to be ready…")
            for attempt in range(20):
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

            # ── 4. Verify MSSQL connection ────────────────────────────────────
            self._set_conn_status("Connecting to SQL Server…")
            resp = requests.post(f"{FLASK_URL}/api/login", timeout=12)
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(
                    f"SQL Server connection failed:\n{data.get('error', 'Unknown error')}"
                )

            # ── Success ───────────────────────────────────────────────────────
            self.after(0, self._show_dashboard)

        except Exception as exc:
            self.after(0, lambda: self._connect_failed(str(exc)))

    def _connect_failed(self, msg: str):
        self._conn_btn.configure(state="normal", text="Connect to SQL Server")
        self._status_lbl.configure(text="Connection failed.", text_color=ERROR)
        self._error_lbl.configure(text=msg)
        # Kill any partial processes
        for proc in (self._flask_proc, self._node_proc):
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
        self._flask_proc = self._node_proc = None

    # ── Dashboard ──────────────────────────────────────────────────────────────
    def _show_dashboard(self):
        self._conn_frame.place_forget()
        self._connected = True
        self._build_dashboard()
        # Start background workers
        threading.Thread(target=self._bg_refresh_loop, daemon=True).start()
        threading.Thread(target=self._bg_log_tail,     daemon=True).start()

    def _build_dashboard(self):
        # ── Top bar ────────────────────────────────────────────────────────────
        topbar = ctk.CTkFrame(self, fg_color=SURFACE, height=50, corner_radius=0)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        inner = ctk.CTkFrame(topbar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20)

        ctk.CTkLabel(inner,
                     text="💬  WhatsApp Order Bot",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(side="left", pady=12)

        # Service status pills
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

        # ── Tabview ────────────────────────────────────────────────────────────
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

        tabs.add("  Dashboard  ")
        tabs.add("  Groups  ")
        tabs.add("  Live Logs  ")

        self._build_tab_dashboard(tabs.tab("  Dashboard  "))
        self._build_tab_groups(tabs.tab("  Groups  "))
        self._build_tab_logs(tabs.tab("  Live Logs  "))

    # ── Dashboard tab ──────────────────────────────────────────────────────────
    def _build_tab_dashboard(self, parent):
        parent.configure(fg_color=BG)

        # Stat cards
        cards = ctk.CTkFrame(parent, fg_color="transparent")
        cards.pack(fill="x", pady=(4, 18))
        cards.columnconfigure((0, 1, 2, 3), weight=1)

        self._stats = {}
        defs = [
            ("orders_today", "Orders Today",  TEXT,  BORDER),
            ("needs_review", "Needs Review",  WARN,  "#4a3800"),
            ("customers",    "Customers",     TEXT,  BORDER),
            ("products",     "Products",      TEXT,  BORDER),
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

        # Header
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(hdr, text="Recent Orders",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT).pack(side="left")
        self._refresh_lbl = ctk.CTkLabel(hdr, text="",
                                          font=ctk.CTkFont(size=11),
                                          text_color=TEXT3)
        self._refresh_lbl.pack(side="right")

        # Orders table (ttk.Treeview with dark styling)
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
            ("id",       "#",         46,  "center"),
            ("customer", "Customer",  185, "w"),
            ("product",  "Product",   230, "w"),
            ("qty",      "Qty",       54,  "center"),
            ("status",   "Status",    110, "center"),
            ("flag",     "Review",    80,  "center"),
            ("time",     "Time",      60,  "center"),
        ]
        for cid, heading, width, anchor in col_defs:
            self._tree.heading(cid, text=heading)
            self._tree.column(cid, width=width, minwidth=30, anchor=anchor)

        self._tree.tag_configure("needs_review",
                                 background="#2a1f00", foreground=WARN)

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        vsb.pack(side="right", fill="y", pady=4)

    # ── Groups tab ─────────────────────────────────────────────────────────────
    def _build_tab_groups(self, parent):
        parent.configure(fg_color=BG)

        # Top controls
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
                      text_color=TEXT2,
                      font=ctk.CTkFont(size=12),
                      command=self._load_groups).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btns, text="✓ Apply Selection",
                      width=145, height=32,
                      fg_color=GREEN, hover_color=GREEN_D,
                      text_color="#000000",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._apply_groups).pack(side="left")

        self._group_msg = ctk.CTkLabel(parent, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=TEXT2,
                                        anchor="w")
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
        # Clear old
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
                fg_color=GREEN,
                hover_color=GREEN_D,
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

        self._pause_btn = ctk.CTkButton(hdr,
                                         text="⏸ Pause",
                                         width=90, height=30,
                                         fg_color=CARD, hover_color=SURFACE,
                                         border_width=1, border_color=BORDER,
                                         text_color=TEXT2,
                                         font=ctk.CTkFont(size=12),
                                         command=self._toggle_pause)
        self._pause_btn.pack(side="right")

        self._log_box = ctk.CTkTextbox(
            parent,
            fg_color="#010409",
            text_color=TEXT2,
            font=ctk.CTkFont(family="Courier New", size=11),
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
            wrap="none",
            state="disabled",
        )
        self._log_box.pack(fill="both", expand=True)

        # Configure color tags on the underlying tk.Text widget
        tb = self._log_box._textbox
        tb.tag_configure("error",   foreground=ERROR)
        tb.tag_configure("warning", foreground=WARN)
        tb.tag_configure("info",    foreground=TEXT2)
        tb.tag_configure("section", foreground=BLUE)
        tb.tag_configure("ts",      foreground=TEXT3)

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
        if   "ERROR"   in ul:                             tag = "error"
        elif "WARNING" in ul or "WARN" in ul:             tag = "warning"
        elif "====" in line or "SALES DRAFT" in ul:       tag = "section"
        else:                                             tag = "info"

        tb = self._log_box._textbox
        tb.configure(state="normal")
        tb.insert("end", line + "\n", tag)
        if int(tb.index("end-1c").split(".")[0]) > 1200:
            tb.delete("1.0", "200.0")
        tb.configure(state="disabled")
        tb.see("end")

    # ── Background workers ─────────────────────────────────────────────────────
    def _bg_log_tail(self):
        """Tail webhook.log and push lines to the GUI thread."""
        for _ in range(40):
            if LOG_FILE.exists():
                break
            time.sleep(0.5)

        if not LOG_FILE.exists():
            self.after(0, lambda: self._append_log("[INFO] Waiting for webhook.log…"))
            return

        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            for line in lines[-100:]:
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
        """Poll status every 5s and data every 30s."""
        # Immediate first load
        self._refresh_ctr = 0
        self.after(800, self._load_groups)
        self.after(1000, lambda: threading.Thread(
            target=self._fetch_all, daemon=True).start())

        while self._connected:
            time.sleep(5)
            self._refresh_ctr += 1
            threading.Thread(target=self._fetch_status, daemon=True).start()
            if self._refresh_ctr % 6 == 0:
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
        mapping = {
            "Flask":   "flask",
            "Node":    "node",
            "MSSQL":   "mssql",
            "Postgres":"postgres",
        }
        for label, key in mapping.items():
            color = GREEN if data.get(key) else ERROR
            self._pills[label].configure(text_color=color)

    def _fetch_data(self):
        # Stats
        try:
            s = requests.get(f"{FLASK_URL}/api/stats", timeout=5).json()
            if "error" not in s:
                self.after(0, lambda d=s: self._update_stats(d))
        except Exception:
            pass
        # Orders
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
        secs_until = max(0, 30 - (self._refresh_ctr % 6) * 5)
        self._refresh_lbl.configure(text=f"Refreshes in {secs_until}s")

    def _update_orders(self, orders):
        self._tree.delete(*self._tree.get_children())
        for o in orders:
            ts  = o.get("created_at") or ""
            t   = ts[11:16] if len(ts) >= 16 else "—"
            qty = o.get("quantity")
            qty_s = str(int(qty)) if qty is not None else "—"
            nr  = o.get("needs_review", False)
            tags = ("needs_review",) if nr else ()
            self._tree.insert("", "end", values=(
                o.get("id", ""),
                self._trunc(o.get("customer") or "", 28),
                self._trunc(o.get("product")  or "", 36),
                qty_s,
                o.get("status", ""),
                "⚠ Review" if nr else "✓ OK",
                t,
            ), tags=tags)

    @staticmethod
    def _trunc(s: str, n: int) -> str:
        return s if len(s) <= n else s[:n] + "…"

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
