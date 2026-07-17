import { NextResponse } from 'next/server';
import { getPool, sql } from '@/lib/mssql';
import { getCurrentUser } from '@/lib/auth';

/* ── Helper: next business day ────────────────────────────────────────── */
function nextBusinessDay(): Date {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
  return d;
}

export async function POST(req: Request) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });

  try {
    const { batchId } = await req.json();
    if (!batchId) return NextResponse.json({ ok: false, error: 'Missing batchId' }, { status: 400 });

    const pool = await getPool();

    // 1. Get pending order
    const orderResult = await pool.request()
      .input('batchId', sql.UniqueIdentifier, batchId)
      .query(`
        SELECT * FROM Tbl_Web_PendingOrders WHERE BatchID = @batchId AND Status = 'pending_review'
      `);

    if (!orderResult.recordset.length) {
      return NextResponse.json({ ok: false, error: 'Order not found or already processed' }, { status: 404 });
    }

    const order = orderResult.recordset[0];

    // 2. Get lines
    const linesResult = await pool.request()
      .input('orderId', sql.Int, order.PendingOrderID)
      .query(`
        SELECT pol.*, m.PartNo, m.MaterialDescription, m.UM AS productUom, m.PoundsPerCs
        FROM Tbl_Web_PendingOrderLines pol
        LEFT JOIN Tbl_WH_Materials m ON pol.ProductID = m.MaterialID
        WHERE pol.PendingOrderID = @orderId
      `);

    const lines = linesResult.recordset;

    // 3. Pull customer pre-fill from Tbl_Sales_Customers
    let custName = order.CustomerName || '';
    let custTax = '', addr1 = '', addr2 = '', county = '', city = '', state = '', country = '', zipcode = '';
    let payTerms: number | null = null, delTerms: number | null = null, salesmanId: number | null = null;
    let custPhone = '', delNotes = '', custShort = '';

    if (order.CustomerID) {
      const custResult = await pool.request()
        .input('custId', sql.Int, order.CustomerID)
        .query(`
          SELECT CustomerName, CustomerShortName, CustomerTaxID,
                 CustomerAddress1, CustomerAddress2, CustomerCounty,
                 CustomerCity, CustomerState, CustomerCountry, CustomerZipcode,
                 PaymentTermsID, DeliveryTermsID, SalesmanID,
                 Phone, DeliveryNotes
          FROM Tbl_Sales_Customers WHERE CustomerID = @custId
        `);

      if (custResult.recordset.length) {
        const c = custResult.recordset[0];
        custName = c.CustomerName || custName;
        custShort = c.CustomerShortName || custName;
        custTax = c.CustomerTaxID || '';
        addr1 = c.CustomerAddress1 || '';
        addr2 = c.CustomerAddress2 || '';
        county = c.CustomerCounty || '';
        city = c.CustomerCity || '';
        state = c.CustomerState || '';
        country = c.CustomerCountry || '';
        zipcode = c.CustomerZipcode || '';
        payTerms = c.PaymentTermsID;
        delTerms = c.DeliveryTermsID;
        salesmanId = c.SalesmanID;
        custPhone = c.Phone || '';
        delNotes = c.DeliveryNotes || '';
      }
    }

    // Apply customer overrides
    if (order.CustomerOverrides) {
      try {
        const ov = JSON.parse(order.CustomerOverrides);
        if (ov.address1) addr1 = ov.address1;
        if (ov.address2) addr2 = ov.address2;
        if (ov.city) city = ov.city;
        if (ov.state) state = ov.state;
        if (ov.country) country = ov.country;
        if (ov.zipcode) zipcode = ov.zipcode;
        if (ov.paymentTerms) payTerms = parseInt(ov.paymentTerms);
        if (ov.deliveryTerms) delTerms = parseInt(ov.deliveryTerms);
        if (ov.salesmanId) salesmanId = parseInt(ov.salesmanId);
        if (ov.phone) custPhone = ov.phone;
        if (ov.deliveryNotes) delNotes = ov.deliveryNotes;
        if (ov.taxId) custTax = ov.taxId;
      } catch { /* ignore parse error */ }
    }

    // 4. Calculate grand total and ship date
    let grandTotal = 0;
    for (const line of lines) {
      const uom = (line.productUom || 'CASE (CS)').toUpperCase();
      const isLbBased = uom.includes('LB') || uom.includes('POUND');
      grandTotal += (line.UnitPrice || 0) * (isLbBased ? (line.QuantityLbs || 0) : (line.QuantityCs || 0));
    }

    const shipDate = nextBusinessDay();
    const safeNotes = (order.SpecialInstructions || '').substring(0, 200);

    // 5. Get next SalesOrderNo
    const maxResult = await pool.request().query('SELECT ISNULL(MAX(SalesOrderNo), 0) AS maxNo FROM Tbl_Sales_SalesOrder');
    const newOrderNo = (maxResult.recordset[0].maxNo || 0) + 1;

    // 6. Insert sales order header
    const headerResult = await pool.request()
      .input('orderNo', sql.Int, newOrderNo)
      .input('custId', sql.Int, order.CustomerID)
      .input('custName', sql.VarChar(100), (custName || '').substring(0, 100))
      .input('custTax', sql.VarChar(50), (custTax || '').substring(0, 50))
      .input('addr1', sql.VarChar(150), (addr1 || '').substring(0, 150))
      .input('addr2', sql.VarChar(150), (addr2 || '').substring(0, 150))
      .input('county', sql.VarChar(100), (county || '').substring(0, 100))
      .input('city', sql.VarChar(100), (city || '').substring(0, 100))
      .input('state', sql.VarChar(50), (state || '').substring(0, 50))
      .input('country', sql.VarChar(50), (country || '').substring(0, 50))
      .input('zipcode', sql.VarChar(20), (zipcode || '').substring(0, 20))
      .input('payTerms', sql.Int, payTerms)
      .input('delTerms', sql.Int, delTerms)
      .input('salesmanId', sql.Int, salesmanId)
      .input('custShort', sql.VarChar(100), (custShort || '').substring(0, 100))
      .input('shipDate', sql.Date, shipDate)
      .input('subtotal', sql.Decimal(18, 2), grandTotal)
      .input('total', sql.Decimal(18, 2), grandTotal)
      .input('notes', sql.VarChar(200), safeNotes)
      .query(`
        INSERT INTO Tbl_Sales_SalesOrder (
          SalesOrderNo, CustomerID,
          CustomerName, CustomerTaxID,
          CustomerAddress1, CustomerAddress2, CustomerCounty,
          CustomerCity, CustomerState, CustomerCountry, CustomerZipcode,
          PaymentTermsID, DeliveryTermsID, SalesmanID,
          CustomerContactName,
          DateIssued, ShipDate, RequiredDate,
          IsRelease, MadeBy, Cancel,
          Subtotal, Tax, Total, Notes
        ) VALUES (
          @orderNo, @custId,
          @custName, @custTax,
          @addr1, @addr2, @county,
          @city, @state, @country, @zipcode,
          @payTerms, @delTerms, @salesmanId,
          @custShort,
          GETDATE(), @shipDate, @shipDate,
          0, 0, 0,
          @subtotal, 0.00, @total, @notes
        );
        SELECT SCOPE_IDENTITY() AS SalesOrderID;
      `);

    const salesOrderId = headerResult.recordset[0].SalesOrderID;

    // 7. Insert line items
    for (let idx = 0; idx < lines.length; idx++) {
      const line = lines[idx];
      if (!line.ProductID) continue;

      const uom = (line.productUom || 'CASE (CS)').toUpperCase();
      const isLbBased = uom.includes('LB') || uom.includes('POUND');
      const qtyCases = line.QuantityCs || 0;
      const qtyLbs = line.QuantityLbs || 0;
      const unitPrice = line.UnitPrice || 0;
      const amount = unitPrice * (isLbBased ? qtyLbs : qtyCases);

      // Get unit cost
      const costResult = await pool.request()
        .input('matId', sql.Int, line.ProductID)
        .query('SELECT TOP 1 LastCost FROM Tbl_WH_Materials WHERE MaterialID = @matId');
      const unitCost = costResult.recordset[0]?.LastCost || 0;
      const margin = unitPrice > 0 ? (unitPrice - unitCost) / unitPrice : 0;

      await pool.request()
        .input('soId', sql.Int, salesOrderId)
        .input('itemNo', sql.Int, idx + 1)
        .input('matId', sql.Int, line.ProductID)
        .input('partNo', sql.VarChar(50), (line.PartNo || '').substring(0, 50))
        .input('desc', sql.VarChar(200), (line.MaterialDescription || line.OriginalName || '').substring(0, 200))
        .input('qtyCases', sql.Decimal(18, 2), qtyCases)
        .input('qty', sql.Decimal(18, 2), qtyLbs)
        .input('qtyBal', sql.Decimal(18, 2), qtyLbs)
        .input('unitPriceList', sql.Decimal(18, 4), unitPrice)
        .input('unitPrice', sql.Decimal(18, 4), unitPrice)
        .input('amount', sql.Decimal(18, 2), amount)
        .input('uom', sql.VarChar(50), line.productUom || 'CASE (CS)')
        .input('unitCost', sql.Decimal(18, 4), unitCost)
        .input('margin', sql.Decimal(18, 4), margin)
        .input('notes', sql.VarChar(100), (line.OriginalName || '').substring(0, 100))
        .query(`
          INSERT INTO Tbl_Sales_SalesOrder_Details (
            SalesOrderID, ItemNo, MaterialID, PartNo, Description,
            QuantityCs, Quantity, QuantityBalance,
            UnitPriceList, UnitPrice, Amount, UofM,
            IsTaxable, UnitCost, Margin, RealCost, RealMargin, Notes
          ) VALUES (
            @soId, @itemNo, @matId, @partNo, @desc,
            @qtyCases, @qty, @qtyBal,
            @unitPriceList, @unitPrice, @amount, @uom,
            1, @unitCost, @margin, 0.0, 0.0, @notes
          )
        `);
    }

    // 8. Mark pending order as confirmed
    await pool.request()
      .input('batchId', sql.UniqueIdentifier, batchId)
      .query("UPDATE Tbl_Web_PendingOrders SET Status = 'confirmed', UpdatedAt = GETDATE() WHERE BatchID = @batchId");

    return NextResponse.json({
      ok: true,
      salesOrderId,
      salesOrderNo: newOrderNo,
      shipDate: shipDate.toISOString().split('T')[0],
      message: `Draft Sales Order #${newOrderNo} created! Ship: ${shipDate.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}`,
    });

  } catch (err) {
    console.error('Confirm error:', err);
    return NextResponse.json({ ok: false, error: 'Failed to create sales order. ' + (err instanceof Error ? err.message : '') }, { status: 500 });
  }
}
