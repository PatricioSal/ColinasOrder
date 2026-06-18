# WhatsApp Order Bot — Setup Guide

> **How long does setup take?** ~20-30 minutes on a fresh computer.

---

## Prerequisites

Make sure the following are installed before starting:

| Requirement | Version | Download |
|---|---|---|
| Python | 3.10 or newer | https://www.python.org/downloads/ |
| Node.js | 18 or newer | https://nodejs.org/ |
| PostgreSQL | 14 or newer | https://www.postgresql.org/download/ |
| ODBC Driver 18 for SQL Server | latest | https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server |

> **Tip:** During Python installation, check **"Add Python to PATH"**.  
> During PostgreSQL installation, note your username and password — you'll need them in Step 3.

---

## Step 1 — Get the Project Files

**Option A — Copy the folder**  
Copy the entire `WhatsAppOrder` folder to the new computer (USB drive, OneDrive, etc.).

**Option B — Clone from GitHub**
```bash
git clone https://github.com/PatricioSal/ColinasOrder.git WhatsAppOrder
cd WhatsAppOrder
```

---

## Step 2 — Install Python Dependencies

Open a terminal **inside the `WhatsAppOrder` folder** and run:

```bash
pip install -r requirements.txt
```

This installs: `flask`, `python-dotenv`, `psycopg2-binary`, `requests`, `pyodbc`.

> If `pip` is not found, try `python -m pip install -r requirements.txt`

---

## Step 3 — Install Node.js Dependencies

In the same terminal, run:

```bash
npm install
```

This downloads `whatsapp-web.js`, `express`, `axios`, and `qrcode-terminal` into the `node_modules` folder.

---

## Step 4 — Configure the `.env` File

Copy the template below and save it as `.env` in the project root:

```env
# PostgreSQL (local database)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=whatsapp_orders
DB_USER=openpg
DB_PASSWORD=openpgpwd

# Set to True to push draft orders to the remote SQL Server
# Set to False for local-only mode / testing
PUSH_TO_MSSQL=True

# WhatsApp Business API key (leave as mock value if not using Meta API)
WHATSAPP_API_KEY=mock_api_key_for_testing_12345
WHATSAPP_PHONE_NUMBER_ID=1234567890
```

> **Change `DB_USER` and `DB_PASSWORD`** to match the PostgreSQL account you set up on this computer.

---

## Step 5 — Set Up the Database

Run the database setup script to create tables and sync data from the remote SQL Server:

```bash
py db_setup.py
```

Expected output:
```
Connecting to default PostgreSQL database...
Database 'whatsapp_orders' already exists.
Creating tables if they do not exist...
Syncing Customers...   Synced 847 customers.
Syncing Products...    Synced 1203 products.
Syncing Order History... Synced 1500 historical order items.
Database sync completed successfully!
```

> **Requires a network connection** to the remote SQL Server (207.200.18.74).  
> If the connection fails, the local PostgreSQL will be empty — orders will still log but product matching won't work until synced.

---

## Step 6 — Create the Desktop Shortcut (One-Time)

Double-click **`create_shortcut.bat`** in the project folder.

You'll see:
```
SUCCESS! Shortcut created on your Desktop: "WhatsApp Order Bot"
```

> If you get an error, right-click the file and choose **"Run as administrator"**.

---

## Step 7 — Start the Bot

**Double-click the "WhatsApp Order Bot" icon on your Desktop.**

Two color-coded terminal windows will open:

| Window | Color | What it does |
|---|---|---|
| `WhatsApp Bot — Python Webhook` | 🟢 Green | Receives messages, runs AI matching, writes to DB |
| `WhatsApp Bot — Node Listener` | 🔵 Cyan | Connects to WhatsApp, forwards messages |

> **Don't close either window** while the bot is running.

---

## Step 8 — Scan the QR Code (First Time Only)

The first time you start the bot on a new computer, the Node terminal will display a QR code:

```
📱  Scan this QR code in WhatsApp → Linked Devices → Link a Device:

[QR CODE APPEARS HERE]

(Session will be saved — you only need to scan once)
```

**On your phone:**
1. Open WhatsApp
2. Tap the three dots (⋮) → **Linked Devices**
3. Tap **Link a Device**
4. Scan the QR code on screen

After scanning, the terminal will show:
```
✅  WhatsApp authenticated — session saved.
   WhatsApp Listener — READY
```

> The session is saved in the `whatsapp_session/` folder. You **won't need to scan again** unless the session expires (typically 14 days of inactivity).

---

## Step 9 — Verify Everything is Running

Check that both services are healthy:

- **Python:** Open a browser and go to `http://localhost:5050/health`  
  You should see: `{"status": "ok", "time": "2024-..."}`

- **Node:** The terminal should show `WhatsApp Listener — READY` and list the groups it's listening to.

---

## Troubleshooting

### `py` or `python` not found
- Make sure Python is installed and **"Add to PATH"** was checked during install.
- Try `python whatsapp_webhook.py` instead of `py whatsapp_webhook.py`.

### `node` not found
- Make sure Node.js is installed. Download from https://nodejs.org/
- Restart the terminal after installing.

### PostgreSQL connection error (`could not connect to server`)
- Make sure the PostgreSQL service is running:  
  Windows: Search **"Services"** → find **postgresql** → Start it.
- Check that `DB_USER` and `DB_PASSWORD` in `.env` match your PostgreSQL setup.

### QR code not appearing
- The Node window needs a few seconds to initialize. Wait 10-15 seconds.
- If it crashes immediately, make sure `npm install` completed without errors.

### Orders not being processed / bot not responding
- Check the `webhook.log` file in the project folder for errors.
- Make sure both terminals (Python + Node) are still open and running.
- Verify the group name in `whatsapp_listener.js` matches exactly (line: `const GROUP_FILTER = ['Testing'];`).

### Session expired / need to re-scan QR
- Delete the `whatsapp_session/` folder in the project directory.
- Restart the bot — a new QR code will appear.

---

## Daily Usage

| Task | Action |
|---|---|
| Start the bot | Double-click **"WhatsApp Order Bot"** on Desktop |
| Stop the bot | Close both terminal windows |
| View logs | Open `webhook.log` in the project folder |
| Re-sync products & customers | Run `py db_setup.py` |
| Check database | Run `py db_browser.py` |
