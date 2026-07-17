import { NextResponse } from 'next/server';
import { getPool, sql } from '@/lib/mssql';
import { getCurrentUser, hashPassword } from '@/lib/auth';

export async function GET() {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });

  const pool = await getPool();
  const result = await pool.request().query(
    'SELECT UserID, Email, DisplayName, Role, IsActive, CreatedAt, LastLoginAt FROM Tbl_Web_Users ORDER BY CreatedAt DESC'
  );
  return NextResponse.json(result.recordset);
}

export async function POST(req: Request) {
  const user = await getCurrentUser();
  if (!user || user.role !== 'admin') {
    return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
  }

  const { email, displayName, password, role } = await req.json();
  if (!email || !displayName || !password) {
    return NextResponse.json({ ok: false, error: 'All fields required' }, { status: 400 });
  }

  const hash = await hashPassword(password);
  const pool = await getPool();

  try {
    await pool.request()
      .input('email', sql.VarChar, email.toLowerCase().trim())
      .input('hash', sql.VarChar, hash)
      .input('name', sql.VarChar, displayName)
      .input('role', sql.VarChar, role || 'user')
      .input('createdBy', sql.Int, user.userId)
      .query(`
        INSERT INTO Tbl_Web_Users (Email, PasswordHash, DisplayName, Role, CreatedBy)
        VALUES (@email, @hash, @name, @role, @createdBy)
      `);
    return NextResponse.json({ ok: true });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    if (message.includes('UNIQUE') || message.includes('duplicate')) {
      return NextResponse.json({ ok: false, error: 'Email already exists' }, { status: 409 });
    }
    return NextResponse.json({ ok: false, error: 'Server error' }, { status: 500 });
  }
}

export async function PATCH(req: Request) {
  const user = await getCurrentUser();
  if (!user || user.role !== 'admin') {
    return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
  }

  const { userId, isActive } = await req.json();
  const pool = await getPool();
  await pool.request()
    .input('userId', sql.Int, userId)
    .input('isActive', sql.Bit, isActive ? 1 : 0)
    .query('UPDATE Tbl_Web_Users SET IsActive = @isActive WHERE UserID = @userId');

  return NextResponse.json({ ok: true });
}
