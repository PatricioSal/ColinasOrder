import { NextResponse } from 'next/server';
import { getPool, sql } from '@/lib/mssql';

export async function GET() {
  try {
    const pool = await getPool();

    // Get all pending orders
    const ordersResult = await pool.request().query(`
      SELECT
        po.PendingOrderID, po.BatchID, po.CustomerID, po.CustomerName,
        po.RawMessage, po.SpecialInstructions, po.Status,
        CAST(po.NeedsReview AS bit) AS NeedsReview,
        po.SubmitterName, po.CreatedAt, po.CustomerOverrides
      FROM Tbl_Web_PendingOrders po
      WHERE po.Status = 'pending_review'
      ORDER BY po.NeedsReview DESC, po.CreatedAt DESC
    `);

    const orders = ordersResult.recordset;

    // Get all lines for these orders
    const orderIds = orders.map((o: { PendingOrderID: number }) => o.PendingOrderID);
    if (orderIds.length === 0) return NextResponse.json([]);

    const linesResult = await pool.request().query(`
      SELECT
        pol.LineID, pol.PendingOrderID, pol.ProductID,
        m.MaterialDescription AS ProductName, m.PartNo AS SKU,
        pol.OriginalName, pol.QuantityCs, pol.QuantityLbs,
        pol.UnitPrice, pol.UOM, pol.LineNote,
        CAST(pol.NeedsReview AS bit) AS NeedsReview,
        m.PoundsPerCs AS qtyPerCase, m.UM AS productUom
      FROM Tbl_Web_PendingOrderLines pol
      LEFT JOIN Tbl_WH_Materials m ON pol.ProductID = m.MaterialID
      WHERE pol.PendingOrderID IN (${orderIds.join(',')})
      ORDER BY pol.LineID
    `);

    // Get customer details for enrichment
    const customerIds = [...new Set(orders.map((o: { CustomerID: number | null }) => o.CustomerID).filter(Boolean))];
    let customerMap: Record<number, Record<string, unknown>> = {};
    if (customerIds.length > 0) {
      const custResult = await pool.request().query(`
        SELECT CustomerID, CustomerName, Phone,
               CustomerAddress1, CustomerAddress2,
               CustomerCity, CustomerState, CustomerZipcode, CustomerCountry,
               PaymentTermsID, DeliveryTermsID, SalesmanID, CustomerTaxID
        FROM Tbl_Sales_Customers
        WHERE CustomerID IN (${customerIds.join(',')})
      `);
      for (const c of custResult.recordset) {
        customerMap[c.CustomerID] = {
          name: c.CustomerName, phone: c.Phone,
          address1: c.CustomerAddress1, address2: c.CustomerAddress2,
          city: c.CustomerCity, state: c.CustomerState, zipcode: c.CustomerZipcode, country: c.CustomerCountry,
          paymentTerms: c.PaymentTermsID, deliveryTerms: c.DeliveryTermsID,
          salesmanId: c.SalesmanID, taxId: c.CustomerTaxID,
        };
      }
    }

    // Group lines by order
    const linesByOrder: Record<number, Array<Record<string, unknown>>> = {};
    for (const line of linesResult.recordset) {
      if (!linesByOrder[line.PendingOrderID]) linesByOrder[line.PendingOrderID] = [];
      const productUom = (line.productUom || 'CASE (CS)').toUpperCase();
      const isLbBased = productUom.includes('LB') || productUom.includes('POUND');
      const total = (line.UnitPrice || 0) * (isLbBased ? (line.QuantityLbs || 0) : (line.QuantityCs || 0));
      linesByOrder[line.PendingOrderID].push({ ...line, total });
    }

    const enriched = orders.map((o: Record<string, unknown>) => ({
      ...o,
      lines: linesByOrder[(o.PendingOrderID as number)] || [],
      customerDetails: o.CustomerID ? (customerMap[(o.CustomerID as number)] || null) : null,
    }));

    return NextResponse.json(enriched);
  } catch (err) {
    console.error('Pending orders error:', err);
    return NextResponse.json([]);
  }
}
