import { NextResponse } from 'next/server';
import { getPool, sql } from '@/lib/mssql';
import { getCurrentUser } from '@/lib/auth';

export async function POST(req: Request) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });

  try {
    const { batchId } = await req.json();
    if (!batchId) return NextResponse.json({ ok: false, error: 'Missing batchId' }, { status: 400 });

    const pool = await getPool();

    // Delete lines first (FK constraint)
    await pool.request()
      .input('batchId', sql.UniqueIdentifier, batchId)
      .query('DELETE FROM Tbl_Web_PendingOrderLines WHERE BatchID = @batchId');

    // Delete order
    await pool.request()
      .input('batchId', sql.UniqueIdentifier, batchId)
      .query("DELETE FROM Tbl_Web_PendingOrders WHERE BatchID = @batchId");

    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error('Reject error:', err);
    return NextResponse.json({ ok: false, error: 'Failed to reject' }, { status: 500 });
  }
}
