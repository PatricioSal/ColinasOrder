/* ─── Customer-specific Tiered Pricing ────────────────────────────────────
 * Ported from whatsapp_webhook.py _get_mssql_customer_price().
 * Looks up PriceListID + TierNo, then resolves Price/Price1/Price2.
 * ──────────────────────────────────────────────────────────────────────── */

import { getPool, sql } from './mssql';

export async function getCustomerPrice(
  customerId: number,
  materialId: number,
  fallbackPrice: number,
): Promise<number> {
  try {
    const pool = await getPool();

    // 1. Get customer's PriceListID and TierNo
    const custResult = await pool.request()
      .input('custId', sql.Int, customerId)
      .query(`
        SELECT PriceListID, PreiceListID_TierNo
        FROM Tbl_Sales_Customers
        WHERE CustomerID = @custId
      `);

    if (!custResult.recordset.length) return fallbackPrice;
    const { PriceListID, PreiceListID_TierNo } = custResult.recordset[0];
    if (!PriceListID) return fallbackPrice;
    const tierNo = PreiceListID_TierNo || 0;

    // 2. Get price from price list
    const priceResult = await pool.request()
      .input('plId', sql.Int, PriceListID)
      .input('matId', sql.Int, materialId)
      .query(`
        SELECT Price, Price1, Price2
        FROM Tbl_Sales_PriceLists_Materials
        WHERE PriceListID = @plId AND MaterialID = @matId
      `);

    if (!priceResult.recordset.length) return fallbackPrice;
    const row = priceResult.recordset[0];

    if (tierNo === 1 && row.Price1 != null && parseFloat(row.Price1) > 0) {
      return parseFloat(row.Price1);
    }
    if (tierNo === 2 && row.Price2 != null && parseFloat(row.Price2) > 0) {
      return parseFloat(row.Price2);
    }
    if (row.Price != null && parseFloat(row.Price) > 0) {
      return parseFloat(row.Price);
    }

    return fallbackPrice;
  } catch {
    return fallbackPrice;
  }
}
