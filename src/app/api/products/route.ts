import { NextResponse } from 'next/server';
import { getPool, sql } from '@/lib/mssql';

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const q = searchParams.get('q') || '';
    if (!q || q.length < 2) return NextResponse.json([]);

    const pool = await getPool();
    const result = await pool.request()
      .input('q', sql.VarChar, `%${q}%`)
      .query(`
        SELECT TOP 20 MaterialID AS id, PartNo AS sku, MaterialDescription AS name,
               UM AS uom, PoundsPerCs AS qtyPerCase
        FROM Tbl_WH_Materials
        WHERE Inactive = 0 AND (MaterialDescription LIKE @q OR PartNo LIKE @q)
        ORDER BY MaterialDescription
      `);

    return NextResponse.json(result.recordset);
  } catch {
    return NextResponse.json([]);
  }
}
