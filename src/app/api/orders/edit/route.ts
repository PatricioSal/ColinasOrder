import { NextResponse } from 'next/server';
import { getPool, sql } from '@/lib/mssql';
import { getCurrentUser } from '@/lib/auth';

export async function POST(req: Request) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });

  try {
    const { batchId, lines, deletedLines, specialInstructions, customerOverrides } = await req.json();
    if (!batchId) return NextResponse.json({ ok: false, error: 'Missing batchId' }, { status: 400 });

    const pool = await getPool();

    // Delete removed lines
    if (deletedLines && deletedLines.length > 0) {
      for (const lineId of deletedLines) {
        await pool.request()
          .input('lineId', sql.Int, lineId)
          .query('DELETE FROM Tbl_Web_PendingOrderLines WHERE LineID = @lineId');
      }
    }

    // Update remaining lines
    if (lines && lines.length > 0) {
      for (const line of lines) {
        await pool.request()
          .input('lineId', sql.Int, line.lineId)
          .input('qty', sql.Decimal(10, 2), line.qty || 0)
          .input('secQty', sql.Decimal(10, 2), line.secondaryQty || 0)
          .input('productId', sql.Int, line.productId || null)
          .input('lineNote', sql.NVarChar(500), line.lineNote || null)
          .query(`
            UPDATE Tbl_Web_PendingOrderLines
            SET QuantityCs = @qty, QuantityLbs = @secQty,
                ProductID = COALESCE(@productId, ProductID),
                LineNote = COALESCE(@lineNote, LineNote)
            WHERE LineID = @lineId
          `);
      }
    }

    // Update order header
    await pool.request()
      .input('batchId', sql.UniqueIdentifier, batchId)
      .input('specialInstructions', sql.NVarChar(500), specialInstructions || null)
      .input('customerOverrides', sql.NVarChar(sql.MAX), customerOverrides ? JSON.stringify(customerOverrides) : null)
      .query(`
        UPDATE Tbl_Web_PendingOrders
        SET SpecialInstructions = COALESCE(@specialInstructions, SpecialInstructions),
            CustomerOverrides = COALESCE(@customerOverrides, CustomerOverrides),
            UpdatedAt = GETDATE()
        WHERE BatchID = @batchId
      `);

    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error('Edit error:', err);
    return NextResponse.json({ ok: false, error: 'Failed to save changes' }, { status: 500 });
  }
}
