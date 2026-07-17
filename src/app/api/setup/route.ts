import { NextResponse } from 'next/server';
import { getPool } from '@/lib/mssql';
import { hashPassword } from '@/lib/auth';

export async function POST() {
  try {
    const pool = await getPool();

    // Create Tbl_Web_Users
    await pool.request().query(`
      IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Tbl_Web_Users')
      CREATE TABLE Tbl_Web_Users (
        UserID        INT IDENTITY(1,1) PRIMARY KEY,
        Email         VARCHAR(255) NOT NULL UNIQUE,
        PasswordHash  VARCHAR(255) NOT NULL,
        DisplayName   VARCHAR(100) NOT NULL,
        Role          VARCHAR(20) NOT NULL DEFAULT 'user',
        IsActive      BIT NOT NULL DEFAULT 1,
        CreatedBy     INT NULL,
        CreatedAt     DATETIME DEFAULT GETDATE(),
        LastLoginAt   DATETIME NULL
      )
    `);

    // Create Tbl_Web_PendingOrders
    await pool.request().query(`
      IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Tbl_Web_PendingOrders')
      CREATE TABLE Tbl_Web_PendingOrders (
        PendingOrderID      INT IDENTITY(1,1) PRIMARY KEY,
        BatchID             UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
        CustomerID          INT NULL,
        CustomerName        NVARCHAR(255) NULL,
        RawMessage          NVARCHAR(MAX) NOT NULL,
        SpecialInstructions NVARCHAR(500) NULL,
        Status              VARCHAR(30) NOT NULL DEFAULT 'pending_review',
        NeedsReview         BIT NOT NULL DEFAULT 1,
        SubmittedBy         INT NULL,
        SubmitterName       VARCHAR(100) NULL,
        CustomerOverrides   NVARCHAR(MAX) NULL,
        CreatedAt           DATETIME DEFAULT GETDATE(),
        UpdatedAt           DATETIME DEFAULT GETDATE()
      )
    `);

    // Create Tbl_Web_PendingOrderLines
    await pool.request().query(`
      IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Tbl_Web_PendingOrderLines')
      CREATE TABLE Tbl_Web_PendingOrderLines (
        LineID           INT IDENTITY(1,1) PRIMARY KEY,
        PendingOrderID   INT NOT NULL,
        BatchID          UNIQUEIDENTIFIER NOT NULL,
        ProductID        INT NULL,
        OriginalName     NVARCHAR(255) NULL,
        QuantityCs       DECIMAL(10,2) NULL,
        QuantityLbs      DECIMAL(10,2) NULL,
        UnitPrice        DECIMAL(10,2) NULL,
        UOM              VARCHAR(50) NULL,
        LineNote         NVARCHAR(500) NULL,
        NeedsReview      BIT NOT NULL DEFAULT 0
      )
    `);

    // Seed admin user if not exists
    const adminExists = await pool.request().query(
      "SELECT COUNT(*) AS cnt FROM Tbl_Web_Users WHERE Email = 'emilios@colinasfoods.com'"
    );

    if (adminExists.recordset[0].cnt === 0) {
      const hash = await hashPassword('Admin123!');
      await pool.request().query(`
        INSERT INTO Tbl_Web_Users (Email, PasswordHash, DisplayName, Role)
        VALUES ('emilios@colinasfoods.com', '${hash}', 'Emilio Salazar', 'admin')
      `);
    }

    return NextResponse.json({
      ok: true,
      message: 'Setup complete! Tables created and admin user seeded.',
      tables: ['Tbl_Web_Users', 'Tbl_Web_PendingOrders', 'Tbl_Web_PendingOrderLines'],
      admin: 'emilios@colinasfoods.com',
    });

  } catch (err) {
    console.error('Setup error:', err);
    return NextResponse.json({ ok: false, error: String(err) }, { status: 500 });
  }
}
