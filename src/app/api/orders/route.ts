import { NextResponse } from 'next/server';
import { getPool } from '@/lib/mssql';

export async function GET() {
  try {
    const pool = await getPool();
    const result = await pool.request().query(`
      SELECT TOP 50
        po.BatchID AS id,
        po.CustomerName AS customer,
        STUFF((
          SELECT ', ' + COALESCE(m.MaterialDescription, pol.OriginalName)
          FROM Tbl_Web_PendingOrderLines pol
          LEFT JOIN Tbl_WH_Materials m ON pol.ProductID = m.MaterialID
          WHERE pol.PendingOrderID = po.PendingOrderID
          FOR XML PATH(''), TYPE
        ).value('.','varchar(max)'), 1, 2, '') AS product,
        (SELECT SUM(pol2.QuantityCs) FROM Tbl_Web_PendingOrderLines pol2 WHERE pol2.PendingOrderID = po.PendingOrderID) AS quantity,
        po.Status AS status,
        CAST(po.NeedsReview AS bit) AS needsReview,
        po.CreatedAt AS createdAt
      FROM Tbl_Web_PendingOrders po
      ORDER BY po.CreatedAt DESC
    `);
    return NextResponse.json(result.recordset);
  } catch {
    return NextResponse.json([]);
  }
}
