/**
 * whatsapp_listener.js
 *
 * WhatsApp listener using whatsapp-web.js.
 * - Connects to WhatsApp via QR code scan (session is saved so you only scan once)
 * - Listens for new messages in group chats (and optionally 1:1)
 * - POSTs each incoming message to the Python Flask webhook (localhost:5050/webhook)
 * - Exposes a /send endpoint so Python can send replies back
 *
 * Usage:
 *   node whatsapp_listener.js
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode  = require('qrcode-terminal');
const axios   = require('axios');
const express = require('express');

// ── Config ────────────────────────────────────────────────────────────────────
const PYTHON_WEBHOOK = 'http://localhost:5050/webhook';  // Python Flask endpoint
const LISTENER_PORT  = 3000;                              // Port this server listens on
const GROUP_ONLY     = true;   // Set false to also process 1:1 messages

// Only process messages from these group name(s).
// Leave as an empty array [] to listen to ALL groups.
// NOTE: This is now mutable — updated live via POST /config from the dashboard.
let currentGroupFilter = ['Testing'];

// ── WhatsApp Client ───────────────────────────────────────────────────────────
const client = new Client({
    authStrategy: new LocalAuth({ dataPath: './whatsapp_session' }),
    puppeteer: {
        headless: true,                 // No browser window needed
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
    }
});

client.on('qr', (qr) => {
    console.log('\n📱  Scan this QR code in WhatsApp → Linked Devices → Link a Device:\n');
    qrcode.generate(qr, { small: true }, function (qrcodeStr) {
        console.log(qrcodeStr);
        axios.post(`${PYTHON_WEBHOOK.replace('/webhook', '')}/api/qr`, { qr: qrcodeStr, status: 'qr' })
             .catch(err => console.error('Failed to send QR to Flask:', err.message));
    });
    console.log('\n(Session will be saved — you only need to scan once)\n');
});

client.on('authenticated', () => {
    console.log('✅  WhatsApp authenticated — session saved.');
    axios.post(`${PYTHON_WEBHOOK.replace('/webhook', '')}/api/qr`, { qr: null, status: 'authenticated' })
         .catch(err => {});
});

client.on('auth_failure', (msg) => {
    console.error('❌  Authentication failed:', msg);
    axios.post(`${PYTHON_WEBHOOK.replace('/webhook', '')}/api/qr`, { qr: null, status: 'failure', error: msg })
         .catch(err => {});
    process.exit(1);
});

client.on('ready', async () => {
    axios.post(`${PYTHON_WEBHOOK.replace('/webhook', '')}/api/qr`, { qr: null, status: 'ready' })
         .catch(err => {});
    console.log('\n====================================');
    console.log('  WhatsApp Listener — READY');
    console.log('====================================');
    console.log(`  Posting messages to: ${PYTHON_WEBHOOK}`);
    console.log(`  Reply endpoint:      http://localhost:${LISTENER_PORT}/send`);
    console.log(`  Group only mode:     ${GROUP_ONLY}`);
    console.log(`  Group filter:        ${currentGroupFilter.length ? currentGroupFilter.join(', ') : '(all groups)'}`);
    console.log('====================================\n');

    // Print all available groups so the user can pick which one to use
    try {
        const chats = await client.getChats();
        const groups = chats.filter(c => c.isGroup);

        if (currentGroupFilter.length > 0) {
            // Only show the groups we're actually listening to
            const matched = groups.filter(g => currentGroupFilter.includes(g.name));
            if (matched.length === 0) {
                console.warn(`  ⚠️  WARNING: No groups found matching filter: ${JSON.stringify(currentGroupFilter)}`);
                console.warn('  Check the group name is spelled exactly as it appears in WhatsApp.');
            } else {
                console.log('  Listening to:');
                matched.forEach(g => console.log(`    ✅  "${g.name}"`));
            }
            // Warn about any filter names that didn't match
            currentGroupFilter.forEach(name => {
                if (!groups.find(g => g.name === name)) {
                    console.warn(`  ⚠️  Group "${name}" not found on this account — check spelling.`);
                }
            });
        } else {
            // No filter — show all groups
            console.log(`  Listening to ALL ${groups.length} group(s):`);
            groups.forEach((g, i) => console.log(`    ${i + 1}. "${g.name}"`));
        }
    } catch (e) {
        console.warn('  Could not list groups:', e.message);
    }

});

client.on('disconnected', (reason) => {
    console.warn('⚠️  WhatsApp disconnected:', reason);
    console.log('   Attempting to reconnect...');
    client.initialize();
});

// ── Message Handler ───────────────────────────────────────────────────────────
client.on('message', async (msg) => {
    // Skip our own outgoing messages to prevent reply loops
    if (msg.fromMe) return;

    const isGroup = msg.from.endsWith('@g.us');
    if (GROUP_ONLY && !isGroup) return;

    // Apply group name filter (if configured)
    if (isGroup && currentGroupFilter.length > 0) {
        const chat = await msg.getChat();
        if (!currentGroupFilter.includes(chat.name)) {
            console.log(`[FILTERED] Ignored msg from group "${chat.name}" — not in filter`);
            return;  // message is from a different group — ignore it
        }
        console.log(`[ACCEPTED] Message from group "${chat.name}"`);
    }

    // Extract sender info
    // For group messages: msg.author = sender phone, msg.from = group id
    // For 1:1 messages:  msg.author is undefined,   msg.from = sender phone
    const senderPhone = isGroup
        ? (msg.author || '').replace('@c.us', '')
        : msg.from.replace('@c.us', '');

    const senderName = msg._data?.notifyName || msg._data?.pushName || '';
    const chatId     = msg.from;
    const body       = msg.body || '';

    let hasPdf = false;
    let pdfData = null;
    let pdfName = null;

    if (msg.hasMedia) {
        try {
            const media = await msg.downloadMedia();
            if (media && media.mimetype === 'application/pdf') {
                hasPdf = true;
                pdfData = media.data; // Base64 encoded string
                pdfName = media.filename || 'order.pdf';
            }
        } catch (e) {
            console.error('   ✗ Failed to download media:', e.message);
        }
    }

    if (!body.trim() && !hasPdf) return;  // ignore empty / non-pdf media-only messages

    const ts = new Date().toISOString();
    console.log(`[${ts.slice(11,19)}] MSG from ${senderName} (${senderPhone}): "${body.slice(0, 80)}${body.length > 80 ? '...' : ''}"${hasPdf ? ' [PDF ATTACHED]' : ''}`);

    // POST to Python
    try {
        const resp = await axios.post(PYTHON_WEBHOOK, {
            sender_phone: senderPhone ? `+${senderPhone}` : '',
            sender_name:  senderName,
            body:         body,
            chat_id:      chatId,
            is_group:     isGroup,
            timestamp:    ts,
            has_pdf:      hasPdf,
            pdf_data:     pdfData,
            pdf_name:     pdfName
        }, { timeout: 30000 });

        // Python may return a reply string
        const reply = resp.data?.reply;
        if (reply && typeof reply === 'string' && reply.trim()) {
            await msg.reply(reply);
            console.log(`   ↳ Reply sent: "${reply.slice(0, 60)}${reply.length > 60 ? '...' : ''}"`);
        }
    } catch (err) {
        console.error('   ✗ Failed to POST to Python:', err.message);
    }
});

// ── REST endpoint so Python can trigger a reply ───────────────────────────────
// POST /send  { chat_id: "...", message: "..." }
const app = express();
app.use(express.json());

app.post('/send', async (req, res) => {
    const { chat_id, message } = req.body;
    if (!chat_id || !message) {
        return res.status(400).json({ error: 'chat_id and message are required' });
    }
    try {
        await client.sendMessage(chat_id, message);
        console.log(`   ↳ [/send] Sent to ${chat_id}: "${message.slice(0, 60)}"`);
        res.json({ ok: true });
    } catch (err) {
        console.error('   ✗ [/send] Failed:', err.message);
        res.status(500).json({ error: err.message });
    }
});

app.get('/status', (req, res) => {
    res.json({ status: client.info ? 'ready' : 'not_ready', info: client.info });
});

// ── Dashboard API — group selection ─────────────────────────────────────────
// GET /groups  → list all WhatsApp groups + which ones are currently active
app.get('/groups', async (req, res) => {
    try {
        if (!client.info) {
            return res.status(503).json({ ok: false, error: 'WhatsApp is still starting up or syncing. Please wait a moment and click Refresh...' });
        }
        const chats  = await client.getChats();
        const groups = chats
            .filter(c => c.isGroup)
            .map(g => ({
                name:   g.name,
                id:     g.id._serialized,
                active: currentGroupFilter.includes(g.name),
            }));
        res.json({ ok: true, groups, current: currentGroupFilter });
    } catch (e) {
        res.status(500).json({ ok: false, error: e.message });
    }
});

// POST /config { groups: ["Group A", "Group B"] } → update filter live
app.post('/config', (req, res) => {
    const { groups } = req.body;
    if (!Array.isArray(groups)) {
        return res.status(400).json({ error: 'groups must be an array of strings' });
    }
    currentGroupFilter = groups;
    console.log(`[CONFIG] Group filter updated: ${JSON.stringify(currentGroupFilter)}`);
    res.json({ ok: true, current: currentGroupFilter });
});

app.listen(LISTENER_PORT, () => {
    console.log(`📡  Listener REST API running on port ${LISTENER_PORT}`);
});

// ── Start ─────────────────────────────────────────────────────────────────────
console.log('🔄  Initializing WhatsApp client...');
client.initialize();
