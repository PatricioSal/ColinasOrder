import { NextResponse } from 'next/server';
import { getPool, sql } from '@/lib/mssql';
import { verifyPassword, createToken, setAuthCookie, clearAuthCookie } from '@/lib/auth';

export async function POST(req: Request) {
  try {
    const { email, password } = await req.json();
    if (!email || !password) {
      return NextResponse.json({ ok: false, error: 'Email and password are required' }, { status: 400 });
    }

    const pool = await getPool();
    const result = await pool.request()
      .input('email', sql.VarChar, email.toLowerCase().trim())
      .query('SELECT * FROM Tbl_Web_Users WHERE LOWER(Email) = @email AND IsActive = 1');

    if (!result.recordset.length) {
      return NextResponse.json({ ok: false, error: 'Invalid credentials' }, { status: 401 });
    }

    const user = result.recordset[0];
    const valid = await verifyPassword(password, user.PasswordHash);
    if (!valid) {
      return NextResponse.json({ ok: false, error: 'Invalid credentials' }, { status: 401 });
    }

    // Update last login
    await pool.request()
      .input('userId', sql.Int, user.UserID)
      .query('UPDATE Tbl_Web_Users SET LastLoginAt = GETDATE() WHERE UserID = @userId');

    const token = createToken({
      userId: user.UserID,
      email: user.Email,
      displayName: user.DisplayName,
      role: user.Role,
    });

    await setAuthCookie(token);

    return NextResponse.json({ ok: true, user: { displayName: user.DisplayName, role: user.Role } });
  } catch (err) {
    console.error('Login error:', err);
    return NextResponse.json({ ok: false, error: 'Server error' }, { status: 500 });
  }
}

export async function DELETE() {
  await clearAuthCookie();
  return NextResponse.json({ ok: true });
}
