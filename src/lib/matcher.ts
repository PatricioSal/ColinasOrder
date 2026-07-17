/* ─── Customer & Product Fuzzy Matching ──────────────────────────────────
 * Ported from whatsapp_sales_agent.py match_customer() and match_item().
 * Queries run against MSSQL tables: Tbl_Sales_Customers, Tbl_WH_Materials.
 * ──────────────────────────────────────────────────────────────────────── */

import { getPool, sql } from './mssql';
import { stripAccents, tokenSet, tokenF1, seqRatio, normalizeText } from './parser';
import type { Customer, Product, MatchedOrderLine, ParsedItem } from './types';

const PRODUCT_NOISE = new Set(['case', 'cases', 'box', 'boxes', 'lb', 'lbs', 'pound', 'pounds', 'of', 'and', 'the', 'pcs', 'ea']);

const CUST_STOP = new Set([
  'customer', 'rep', 'agent', 'from', 'co', 'inc', 'corp',
  'limited', 'ltd', 'llc', 'and', 'the', 'company', 'sales',
  'restaurant', 'restaurante', 'mexican', 'cantina', 'grocery',
  'food', 'foods', 'mart', 'supermarket', 'tienda', 'carniceria',
  'market', 'taqueria', 'tacos', 'taco', 'casa', 'c',
]);

/* ── Customer Matching ────────────────────────────────────────────────── */
export async function matchCustomer(
  parsedName: string | null,
): Promise<{ customer: Customer; confidence: string; flags: string[] }> {
  const pool = await getPool();
  const result = await pool.request().query(`
    SELECT CustomerID AS id, CustomerName AS name, Phone AS phone
    FROM Tbl_Sales_Customers WHERE Inactive = 0
  `);
  const allCustomers: Customer[] = result.recordset;

  if (parsedName) {
    const parsedNorm = stripAccents(parsedName).toLowerCase().trim();
    const parsedTokens = new Set(
      parsedNorm.match(/\w+/g)?.filter(t => !CUST_STOP.has(t)) || []
    );

    let bestMatch: Customer | null = null;
    let bestScore = 0;

    for (const c of allCustomers) {
      const cName = stripAccents(c.name || '').toLowerCase();
      const combined = cName;

      let score: number;
      if (parsedNorm === cName) {
        score = 1.0;
      } else if (combined.includes(parsedNorm)) {
        score = 0.9;
      } else if (parsedNorm.includes(cName)) {
        score = 0.85;
      } else {
        const cTokens = new Set(
          combined.match(/\w+/g)?.filter(t => !CUST_STOP.has(t)) || []
        );
        score = parsedTokens.size && cTokens.size ? tokenF1(parsedTokens, cTokens) : 0;

        const pStr = [...parsedTokens].sort().join(' ');
        const cStr = [...cTokens].sort().join(' ');
        if (pStr && cStr) {
          const sm = seqRatio(pStr, cStr);
          score = Math.max(score, sm);
        }
      }

      if (score > bestScore) {
        bestScore = score;
        bestMatch = c;
      }
    }

    if (bestMatch && bestScore >= 0.75) {
      const confidence = bestScore >= 0.9 ? 'HIGH' : 'MEDIUM';
      const flags = bestScore >= 0.9 ? [] : [
        `[CUSTOMER_CONFIRMATION] '${parsedName}' matched to '${bestMatch.name}' with ${(bestScore * 100).toFixed(0)}% confidence.`
      ];
      return { customer: bestMatch, confidence, flags };
    }
    if (bestMatch && bestScore >= 0.5) {
      return {
        customer: bestMatch,
        confidence: 'LOW',
        flags: [`[CUSTOMER_NEEDS_REVIEW] Weak match: '${parsedName}' -> '${bestMatch.name}' (${(bestScore * 100).toFixed(0)}%). Verify customer.`],
      };
    }
  }

  // Fallback → CASH SALES (ID 1714) or first customer
  const fallback = allCustomers.find(c => c.id === 1714)
    || allCustomers.find(c => c.name.toLowerCase().includes('cash'))
    || allCustomers[0];

  if (!fallback) throw new Error('No customers found in database');

  return {
    customer: fallback,
    confidence: 'LOW',
    flags: [`[CUSTOMER_NEEDS_REVIEW] Could not match '${parsedName || 'Unknown'}'. Defaulted to '${fallback.name}' (ID: ${fallback.id}).`],
  };
}

/* ── Product Matching ─────────────────────────────────────────────────── */
export async function matchItem(
  itemName: string,
  customerHistory: Product[],
  sku?: string | null,
): Promise<{ product: Product | null; flags: string[] }> {
  const pool = await getPool();

  // Pass 0: Exact SKU
  if (sku) {
    const skuPadded = sku.startsWith('0') ? sku : '0' + sku;
    const skuResult = await pool.request()
      .input('sku1', sql.VarChar, sku)
      .input('sku2', sql.VarChar, skuPadded)
      .query(`
        SELECT TOP 1 MaterialID AS id, PartNo AS sku, MaterialDescription AS name,
               UM AS uom, PoundsPerCs AS qtyPerCase,
               COALESCE((SELECT TOP 1 UnitPrice FROM Tbl_Sales_SalesOrder_Details WHERE MaterialID = m.MaterialID ORDER BY SalesOrderDetailID DESC), 10.00) AS price
        FROM Tbl_WH_Materials m WHERE m.Inactive = 0 AND (LOWER(m.PartNo) = LOWER(@sku1) OR LOWER(m.PartNo) = LOWER(@sku2))
      `);
    if (skuResult.recordset.length > 0) {
      const p = skuResult.recordset[0];
      return { product: { ...p, qtyPerCase: p.qtyPerCase || 1 }, flags: ['[EXACT_SKU_MATCH] Matched exactly via vendor SKU.'] };
    }
  }

  // Translate Spanish terms
  const translations: Record<string, string> = {
    pulpo: 'octopus', tuetano: 'marrow', javon: 'scour', jabon: 'scour',
    limon: 'lemon', cebolla: 'onion', ajo: 'garlic', queso: 'cheese', fresa: 'strawberry',
  };
  const translatedWords = itemName.toLowerCase().split(/\s+/).map(w => translations[w] || w);
  const translatedName = translatedWords.join(' ');
  const queryTokens = tokenSet(translatedName, PRODUCT_NOISE);
  const queryNorm = normalizeText(translatedName);

  // Pass 1: Customer history
  if (customerHistory.length > 0) {
    let bestH: Product | null = null;
    let bestHScore = 0;
    for (const prod of customerHistory) {
      const prodTokens = tokenSet(prod.name, PRODUCT_NOISE);
      const prodNorm = normalizeText(prod.name);
      const f1 = tokenF1(queryTokens, prodTokens);
      const sm = seqRatio(queryNorm, prodNorm);
      const isSubset = queryTokens.size > 0 && [...queryTokens].every(t => prodTokens.has(t));
      const score = Math.min(Math.max(f1, sm) + (isSubset ? 0.15 : 0), 1.0);
      if (score > bestHScore) { bestHScore = score; bestH = prod; }
    }
    if (bestH && bestHScore >= 0.75) {
      const tag = bestHScore >= 0.9 ? 'confirmed' : `${(bestHScore * 100).toFixed(0)}%`;
      return { product: bestH, flags: [`[HISTORY_MATCH] Matched from purchase history (${tag} confidence).`] };
    }
  }

  // Pass 2 & 3: Catalog lookup
  const candidates: Product[] = [];
  const seenIds = new Set<number>();

  const addRows = (rows: Product[]) => {
    for (const r of rows) {
      if (!seenIds.has(r.id)) { seenIds.add(r.id); candidates.push(r); }
    }
  };

  // Search by name and tokens
  const searchResult = await pool.request()
    .input('name', sql.VarChar, `%${translatedName}%`)
    .input('sku', sql.VarChar, itemName.toLowerCase())
    .query(`
      SELECT TOP 30 MaterialID AS id, PartNo AS sku, MaterialDescription AS name,
             UM AS uom, PoundsPerCs AS qtyPerCase,
             COALESCE((SELECT TOP 1 UnitPrice FROM Tbl_Sales_SalesOrder_Details WHERE MaterialID = m.MaterialID ORDER BY SalesOrderDetailID DESC), 10.00) AS price
      FROM Tbl_WH_Materials m WHERE m.Inactive = 0
        AND (LOWER(m.MaterialDescription) LIKE LOWER(@name) OR LOWER(m.PartNo) = @sku)
    `);
  addRows(searchResult.recordset.map((r: Record<string, unknown>) => ({ ...r, qtyPerCase: (r.qtyPerCase as number) || 1 })) as Product[]);

  // Token-based search
  const tokens = normalizeText(translatedName).split(/\s+/).filter(t => t.length > 2 && !PRODUCT_NOISE.has(t));
  for (const tok of tokens.slice(0, 3)) {
    if (candidates.length >= 60) break;
    const tokResult = await pool.request()
      .input('tok', sql.VarChar, `%${tok}%`)
      .query(`
        SELECT TOP 20 MaterialID AS id, PartNo AS sku, MaterialDescription AS name,
               UM AS uom, PoundsPerCs AS qtyPerCase,
               COALESCE((SELECT TOP 1 UnitPrice FROM Tbl_Sales_SalesOrder_Details WHERE MaterialID = m.MaterialID ORDER BY SalesOrderDetailID DESC), 10.00) AS price
        FROM Tbl_WH_Materials m WHERE m.Inactive = 0 AND LOWER(m.MaterialDescription) LIKE LOWER(@tok)
      `);
    addRows(tokResult.recordset.map((r: Record<string, unknown>) => ({ ...r, qtyPerCase: (r.qtyPerCase as number) || 1 })) as Product[]);
  }

  // Exact name/SKU
  for (const c of candidates) {
    if (c.sku.toLowerCase() === itemName.toLowerCase() || c.name.toLowerCase() === itemName.toLowerCase()) {
      return { product: c, flags: [] };
    }
  }

  // Fuzzy scoring
  let bestC: Product | null = null;
  let bestScore = 0;
  for (const c of candidates) {
    const prodTokens = tokenSet(c.name, PRODUCT_NOISE);
    const prodNorm = normalizeText(c.name);
    const f1 = tokenF1(queryTokens, prodTokens);
    const sm = seqRatio(queryNorm, prodNorm);
    const isSubset = queryTokens.size > 0 && [...queryTokens].every(t => prodTokens.has(t));
    const score = Math.min(Math.max(f1, sm) + (isSubset ? 0.15 : 0), 1.0);
    if (score > bestScore) { bestScore = score; bestC = c; }
  }

  if (bestC) {
    if (bestScore >= 0.70) {
      const flags = bestScore >= 0.85 ? [] : [`[ITEM_NEEDS_CONFIRMATION] Matched to '${bestC.name}' with ${(bestScore * 100).toFixed(0)}% confidence. Verify.`];
      return { product: bestC, flags };
    }
    return { product: bestC, flags: [`[ITEM_NEEDS_CONFIRMATION] Low-confidence match to '${bestC.name}' (${(bestScore * 100).toFixed(0)}%). Manual review required.`] };
  }

  return { product: null, flags: [`[UNKNOWN_ITEM] No product found in catalog matching '${itemName}'`] };
}

/* ── Get customer order history from MSSQL ────────────────────────────── */
export async function getCustomerHistory(customerId: number): Promise<Product[]> {
  const pool = await getPool();
  const result = await pool.request()
    .input('custId', sql.Int, customerId)
    .query(`
      SELECT DISTINCT m.MaterialID AS id, m.PartNo AS sku, m.MaterialDescription AS name,
             m.UM AS uom, m.PoundsPerCs AS qtyPerCase,
             COALESCE((SELECT TOP 1 sod2.UnitPrice FROM Tbl_Sales_SalesOrder_Details sod2 WHERE sod2.MaterialID = m.MaterialID ORDER BY sod2.SalesOrderDetailID DESC), 10.00) AS price
      FROM Tbl_Sales_SalesOrder_Details sod
      JOIN Tbl_Sales_SalesOrder so ON sod.SalesOrderID = so.SalesOrderID
      JOIN Tbl_WH_Materials m ON sod.MaterialID = m.MaterialID
      WHERE so.CustomerID = @custId AND m.Inactive = 0
    `);
  return result.recordset.map((r: Record<string, unknown>) => ({ ...r, qtyPerCase: (r.qtyPerCase as number) || 1 })) as Product[];
}

/* ── Full order processing pipeline ───────────────────────────────────── */
export async function processOrder(
  parsedItems: ParsedItem[],
  parsedCompanyName: string | null,
  rawMessage: string,
  specialInstructions: string | null,
  submittedBy: number | null,
  submitterName: string | null,
): Promise<{ batchId: string; needsReview: boolean; lineCount: number; total: number }> {
  const { v4: uuidv4 } = await import('uuid');
  const { getCustomerPrice } = await import('./pricing');

  // 1. Match customer
  const { customer, flags: custFlags } = await matchCustomer(parsedCompanyName);
  let hasErrors = custFlags.length > 0;

  // 2. Get history
  const history = await getCustomerHistory(customer.id);

  // 3. Match items
  const orderLines: MatchedOrderLine[] = [];
  for (const item of parsedItems) {
    const { product, flags: itemFlags } = await matchItem(item.name, history, item.sku);
    if (itemFlags.length > 0 || !product) hasErrors = true;

    if (product) {
      const qtyPerCase = product.qtyPerCase || 1;
      const cases = item.qty;
      const realQty = cases * qtyPerCase;
      const truePrice = await getCustomerPrice(customer.id, product.id, product.price);
      const productUom = product.uom || 'CASE (CS)';
      const isLbBased = productUom.toUpperCase().includes('LB') || productUom.toUpperCase().includes('POUND');

      orderLines.push({
        productId: product.id,
        itemName: product.name,
        originalName: item.name,
        sku: product.sku,
        qty: cases,
        uom: item.uom || 'EA',
        secondaryQty: realQty,
        price: truePrice,
        total: truePrice * (isLbBased ? realQty : cases),
        notes: itemFlags.length > 0 ? itemFlags.join(', ') : 'Matched directly',
        productUom,
      });
    } else {
      orderLines.push({
        productId: null,
        itemName: item.name,
        originalName: item.name,
        sku: 'UNKNOWN',
        qty: item.qty,
        uom: item.uom || 'EA',
        secondaryQty: item.secondaryQty || 0,
        price: 0,
        total: 0,
        notes: itemFlags.join(', '),
      });
    }
  }

  // 4. Write to Tbl_Web_PendingOrders + Lines
  const batchId = uuidv4();
  const grandTotal = orderLines.reduce((s, l) => s + l.total, 0);
  const pool = await getPool();

  const headerResult = await pool.request()
    .input('batchId', sql.UniqueIdentifier, batchId)
    .input('customerId', sql.Int, customer.id)
    .input('customerName', sql.NVarChar, customer.name)
    .input('rawMessage', sql.NVarChar(sql.MAX), rawMessage)
    .input('specialInstructions', sql.NVarChar(500), specialInstructions || null)
    .input('needsReview', sql.Bit, hasErrors ? 1 : 0)
    .input('submittedBy', sql.Int, submittedBy)
    .input('submitterName', sql.VarChar(100), submitterName)
    .query(`
      INSERT INTO Tbl_Web_PendingOrders (BatchID, CustomerID, CustomerName, RawMessage, SpecialInstructions, NeedsReview, SubmittedBy, SubmitterName)
      OUTPUT INSERTED.PendingOrderID
      VALUES (@batchId, @customerId, @customerName, @rawMessage, @specialInstructions, @needsReview, @submittedBy, @submitterName)
    `);

  const pendingOrderId = headerResult.recordset[0].PendingOrderID;

  for (const line of orderLines) {
    const lineNeedsReview = hasErrors || (!line.notes.toLowerCase().includes('direct') && !line.notes.toLowerCase().includes('history'));
    await pool.request()
      .input('pendingOrderId', sql.Int, pendingOrderId)
      .input('batchId', sql.UniqueIdentifier, batchId)
      .input('productId', sql.Int, line.productId)
      .input('originalName', sql.NVarChar(255), line.originalName)
      .input('quantityCs', sql.Decimal(10, 2), Math.min(line.qty, 9999999.99))
      .input('quantityLbs', sql.Decimal(10, 2), Math.min(line.secondaryQty, 9999999.99))
      .input('unitPrice', sql.Decimal(10, 2), line.price)
      .input('uom', sql.VarChar(50), line.uom)
      .input('lineNote', sql.NVarChar(500), line.originalName)
      .input('needsReview', sql.Bit, lineNeedsReview ? 1 : 0)
      .query(`
        INSERT INTO Tbl_Web_PendingOrderLines (PendingOrderID, BatchID, ProductID, OriginalName, QuantityCs, QuantityLbs, UnitPrice, UOM, LineNote, NeedsReview)
        VALUES (@pendingOrderId, @batchId, @productId, @originalName, @quantityCs, @quantityLbs, @unitPrice, @uom, @lineNote, @needsReview)
      `);
  }

  return { batchId, needsReview: hasErrors, lineCount: orderLines.length, total: grandTotal };
}
