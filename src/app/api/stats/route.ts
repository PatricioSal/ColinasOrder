import { NextResponse } from 'next/server';
import { getPool } from '@/lib/mssql';

export async function GET() {
  try {
    const pool = await getPool();

    const [todayResult, reviewResult, custResult, prodResult] = await Promise.all([
      pool.request().query(`
        SELECT COUNT(*) AS cnt FROM Tbl_Web_PendingOrders
        WHERE CAST(CreatedAt AS DATE) = CAST(GETDATE() AS DATE)
      `),
      pool.request().query(`
        SELECT COUNT(*) AS cnt FROM Tbl_Web_PendingOrders
        WHERE Status = 'pending_review' AND NeedsReview = 1
      `),
      pool.request().query(`
        SELECT COUNT(*) AS cnt FROM Tbl_Sales_Customers WHERE Inactive = 0
      `),
      pool.request().query(`
        SELECT COUNT(*) AS cnt FROM Tbl_WH_Materials WHERE Inactive = 0
      `),
    ]);

    return NextResponse.json({
      ordersToday: todayResult.recordset[0]?.cnt || 0,
      needsReview: reviewResult.recordset[0]?.cnt || 0,
      customers: custResult.recordset[0]?.cnt || 0,
      products: prodResult.recordset[0]?.cnt || 0,
    });
  } catch {
    return NextResponse.json({ ordersToday: 0, needsReview: 0, customers: 0, products: 0 });
  }
}
