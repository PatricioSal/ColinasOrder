/* ─── Order Text Parser ─────────────────────────────────────────────────────
 * Ported from whatsapp_sales_agent.py parse_message() and PDF parsers.
 * Handles: freeform text orders, Aspen Systems PDFs, Ben E. Keith PDFs,
 *          US Foods PDFs, bilingual (Spanish/English) messages.
 * ──────────────────────────────────────────────────────────────────────── */

import type { ParsedMessage, ParsedItem } from './types';

/* ── Lookup Tables ────────────────────────────────────────────────────── */
const PRODUCT_ABBREVS: Record<string, string> = {
  bnlss: 'boneless', bnls: 'boneless', 'b/i': 'bone in', bi: 'bone in',
  fz: 'frozen', ref: 'refrigerated', ckd: 'cooked', ea: 'each',
  cs: 'case', lb: 'pound', lbs: 'pound', pc: 'piece', pcs: 'pieces',
  whl: 'whole', chx: 'chicken', bef: 'beef', cfg: 'chicken',
  cfm: 'chicken marinade', ir: 'inside round', gn: 'ground',
};

const SPANISH_EN: Record<string, string> = {
  pechuga: 'breast', pechugas: 'breast', muslo: 'thigh', muslos: 'thigh',
  pierna: 'leg', piernas: 'leg', alita: 'wing', alitas: 'wing',
  res: 'beef', pollo: 'chicken', cerdo: 'pork', puerco: 'pork',
  camaron: 'shrimp', camarones: 'shrimp', bistek: 'bistec', bistec: 'bistec',
  suadero: 'suadero', costilla: 'rib', costillas: 'rib', chorizo: 'chorizo',
  molida: 'ground', molido: 'ground', marinado: 'marinade', marinada: 'marinade',
  fajita: 'fajita', fajitas: 'fajita', taco: 'taco', tacos: 'taco',
  queso: 'cheese', gaonera: 'ribeye', arrachera: 'skirt', diezmillo: 'chuck',
  paleta: 'shoulder', lomo: 'loin', filete: 'fillet', milanesa: 'milanesa',
  higado: 'liver', menudo: 'tripe', barbacoa: 'barbacoa', lengua: 'tongue',
  tripas: 'tripe', carnitas: 'carnitas', pastor: 'pastor',
  pulpo: 'octopus', tuetano: 'marrow', javon: 'scour', jabon: 'scour',
  limon: 'lemon', cebolla: 'onion', ajo: 'garlic', fresa: 'strawberry',
};

/* ── Text Helpers ─────────────────────────────────────────────────────── */
export function stripAccents(text: string): string {
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

export function normalizeText(text: string): string {
  let t = stripAccents(text.toLowerCase());
  t = t.replace(/\b([a-z]+)\/([a-z]+)\b/g, '$1$2');
  t = t.replace(/[^a-z0-9\s]/g, ' ');
  const tokens = t.split(/\s+/).filter(Boolean);
  const expanded: string[] = [];
  for (const tok of tokens) {
    const replaced = PRODUCT_ABBREVS[tok] ?? SPANISH_EN[tok] ?? tok;
    expanded.push(...replaced.split(/\s+/));
  }
  return expanded.join(' ');
}

export function tokenSet(text: string, noise?: Set<string>): Set<string> {
  const tokens = new Set(normalizeText(text).split(/\s+/).filter(t => t.length > 1));
  if (noise) noise.forEach(n => tokens.delete(n));
  return tokens;
}

export function tokenF1(queryTokens: Set<string>, candidateTokens: Set<string>): number {
  if (!queryTokens.size || !candidateTokens.size) return 0;
  const common = new Set([...queryTokens].filter(t => candidateTokens.has(t)));
  if (!common.size) return 0;
  const precision = common.size / queryTokens.size;
  const recall = common.size / candidateTokens.size;
  if (precision + recall === 0) return 0;
  return (3 * precision * recall) / (2 * precision + recall);
}

export function seqRatio(a: string, b: string): number {
  const na = normalizeText(a);
  const nb = normalizeText(b);
  if (!na || !nb) return 0;
  // Simple Levenshtein-based ratio (port of Python's SequenceMatcher)
  const longer = na.length > nb.length ? na : nb;
  const shorter = na.length > nb.length ? nb : na;
  if (longer.length === 0) return 1.0;
  const editDist = levenshtein(longer, shorter);
  return (longer.length - editDist) / longer.length;
}

function levenshtein(a: string, b: string): number {
  const m = a.length, n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = a[i - 1] === b[j - 1]
        ? dp[i - 1][j - 1]
        : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[m][n];
}

/* ── PDF Parsers ──────────────────────────────────────────────────────── */

function parseAspenPdf(body: string): ParsedMessage {
  const lines = body.split('\n').map(l => l.trim()).filter(Boolean);
  const items: ParsedItem[] = [];
  let companyName: string | null = null;

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].toLowerCase() === 'bill to:' || lines[i].toLowerCase() === 'ship to:') {
      if (i + 1 < lines.length) companyName = lines[i + 1].trim();
      break;
    }
  }

  let i = 0;
  while (i < lines.length) {
    const uom = lines[i].toUpperCase();
    if (['CSE', 'LB', 'EA', 'CS', 'CASE', 'LBS'].includes(uom) && i >= 3) {
      try {
        const qty = parseFloat(lines[i - 1].replace(/,/g, ''));
        if (isNaN(qty)) { i++; continue; }
        let descIdx = i - 2;
        let sku: string | null = null;
        const vendorLine = lines[descIdx];
        if (vendorLine.startsWith('CF ')) {
          sku = vendorLine.replace('CF ', '').trim();
          descIdx = i - 3;
        } else if (vendorLine.length <= 8 && vendorLine.replace(/\./g, '').match(/^\d+$/)) {
          sku = vendorLine.trim();
          descIdx = i - 3;
        }
        const itemName = lines[descIdx];
        let secondaryQty = 0;
        if (i + 1 < lines.length) {
          const sq = parseFloat(lines[i + 1].replace(/,/g, ''));
          if (!isNaN(sq)) secondaryQty = sq;
        }
        if (itemName.length > 3 && !itemName.replace(/\./g, '').match(/^\d+$/)) {
          items.push({ name: itemName, qty, sku, uom, secondaryQty });
        }
      } catch { /* skip */ }
    }
    i++;
  }
  return {
    messageType: items.length ? 'order' : 'non_order',
    companyName: companyName || '',
    items,
    deliveryInfo: null,
    specialInstructions: 'Extracted from Aspen PDF',
  };
}

function parseBekPdf(body: string): ParsedMessage {
  const lines = body.split('\n').map(l => l.trim()).filter(Boolean);
  const items: ParsedItem[] = [];

  for (const line of lines) {
    const m = line.match(/^\s*([A-Za-z0-9\-]+)\s+(\d+)\s+(\d{10,15})\s+(.+?)\s+([A-Za-z0-9/.\-]+)\s+(.+?)\s+(\d+(?:\.\d+)?)\s+\d+\.\d+\s+[\d.,]+$/i);
    if (m) {
      const sku = m[1];
      const itemName = m[6].trim();
      const qty = parseFloat(m[7]);
      if (itemName) items.push({ name: itemName, qty, sku, uom: 'CS' });
    }
  }
  return {
    messageType: items.length ? 'order' : 'non_order',
    companyName: 'Ben E. Keith',
    items,
    deliveryInfo: null,
    specialInstructions: 'Extracted from Ben E. Keith PDF',
  };
}

function parseUsFoodsPdf(body: string): ParsedMessage {
  const lines = body.split('\n').map(l => l.trim()).filter(Boolean);
  const items: ParsedItem[] = [];

  for (const line of lines) {
    const m = line.match(/^(\d+(?:\.\d+)?)\s+(CASES|CASE|LBS|LB|CS|CSE|EA)\s+([A-Za-z0-9\-]+)\s+(.+)$/i);
    if (m) {
      const qty = parseFloat(m[1]);
      const uom = m[2].toUpperCase();
      const sku = m[3];
      const rawDesc = m[4].trim();
      const itemName = rawDesc.replace(/(?:\s+[\d.,]+)+$/, '').trim();
      if (itemName) items.push({ name: itemName, qty, sku, uom });
    }
  }
  return {
    messageType: items.length ? 'order' : 'non_order',
    companyName: 'US Foods',
    items,
    deliveryInfo: null,
    specialInstructions: 'Extracted from US Foods PDF',
  };
}

/* ── Main Parser ──────────────────────────────────────────────────────── */
export function parseMessage(body: string): ParsedMessage {
  // Detect PDF formats
  if (body.toLowerCase().includes('aspen-systems.com') || (body.includes('Product Code') && body.includes('Order Qty')))
    return parseAspenPdf(body);
  if (body.toLowerCase().includes('us foods') || body.toLowerCase().includes('usf purchase order'))
    return parseUsFoodsPdf(body);
  if (body.toLowerCase().includes('ben e. keith') || body.toLowerCase().includes('ben e keith'))
    return parseBekPdf(body);

  const bodyLower = body.toLowerCase();

  // Check if this is an order message
  const orderKeywords = ['order', 'need', 'want', 'send', 'buy', 'request', 'add', 'case', 'bag', 'box', 'pound', 'lb', 'qty', 'x'];
  const hasQty = /\d/.test(body);
  const hasKeyword = orderKeywords.some(kw => bodyLower.includes(kw));

  if (!hasQty && !hasKeyword) {
    return { messageType: 'non_order', companyName: '', items: [], deliveryInfo: null, specialInstructions: null };
  }

  // Extract company name
  let companyName: string | null = null;
  let m: RegExpMatchArray | null;

  m = body.match(/^([a-zA-Z0-9'\s]+?)(?:\s+order)?\s*:/i);
  if (m) { companyName = m[1].trim(); }
  else {
    m = body.match(/(?:para|for)\s+([a-zA-Z0-9'\s]+?)(?:\n|mañana|hoy|el\b|la\b|los|las|order|pedido|!|$)/i);
    if (m) companyName = m[1].trim();
    else {
      m = body.match(/(?:this is|it's)\s+([a-zA-Z0-9'\s]+)\s+from\s+([a-zA-Z0-9'\s]+)/i);
      if (m) companyName = m[2].trim();
      else {
        m = body.match(/from\s+([a-zA-Z0-9'\s]+)/i);
        if (m) companyName = m[1].trim();
        else {
          m = body.match(/(?:this is|it's)\s+([a-zA-Z0-9'\s]+)/i);
          if (m) companyName = m[1].trim();
        }
      }
    }
  }

  // Clean company name
  if (companyName) {
    for (const stop of ['to be', 'deliver', 'thanks', 'need', 'can you', 'we want', 'please', 'mañana', 'hoy']) {
      const idx = companyName.toLowerCase().indexOf(` ${stop}`);
      if (idx >= 0) companyName = companyName.substring(0, idx).trim();
    }
  }

  // Extract delivery info
  let deliveryInfo: string | null = null;
  m = body.match(/deliver(?:y|ed)?\s+(?:to|by|at)?\s+([^.\n]+)/i);
  if (m) deliveryInfo = m[1].trim();

  // Extract special instructions
  let specialInstructions: string | null = null;
  m = body.match(/(?:special\s+)?instructions?:\s*([^.\n]+)/i);
  if (m) specialInstructions = m[1].trim();
  else {
    m = body.match(/leave\s+at\s+([^.\n]+)/i);
    if (m) specialInstructions = `Leave at ${m[1].trim()}`;
  }

  // Extract items
  const items: ParsedItem[] = [];
  const parts = body.split(/\s+and\s+|\s+y\s+|\s+e\s+|\n|\s*,\s*(?=\d)|\s+add\s+to\s+my\s+order:\s*/i);

  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed) continue;

    // Pattern B: "Item name x QTY"
    const m2 = trimmed.match(/^(.+?)\s+(?:x|X)\s*(\d+(?:\.\d+)?)\s*$/i);
    if (m2) {
      const itemName = m2[1].trim().replace(/\?$/, '').trim();
      const qty = parseFloat(m2[2]);
      if (itemName) { items.push({ name: itemName, qty, sku: null, uom: 'EA' }); continue; }
    }

    // Pattern A: "QTY units of Item name"
    const m1 = trimmed.match(/(?:\b|[xX]\s*)(\d+(?:\.\d+)?)\s*(?:cases|units|bags|boxes|pounds|lbs|dozen|doz|pcs|pieces|cs|ea|lb|#)?\s*(?:of)?\s*([^.]+)/i);
    if (m1) {
      const qty = parseFloat(m1[1]);
      let itemName = m1[2].trim();
      for (const stop of ['to be', 'deliver', 'thanks', 'special', 'leave at']) {
        const idx = itemName.toLowerCase().indexOf(` ${stop}`);
        if (idx >= 0) itemName = itemName.substring(0, idx).trim();
      }
      let isValid = true;
      for (const kw of ['order', 'hi', 'hey', 'hello', "it's", 'this is']) {
        if (new RegExp(`\\b${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(itemName)) {
          isValid = false; break;
        }
      }
      if (itemName && isValid) { items.push({ name: itemName, qty, sku: null, uom: 'EA' }); continue; }
    }
  }

  return {
    messageType: items.length ? 'order' : 'non_order',
    companyName: companyName || '',
    items: items.filter(i => i.name),
    deliveryInfo,
    specialInstructions,
  };
}
