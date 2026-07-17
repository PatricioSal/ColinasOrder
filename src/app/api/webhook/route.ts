import { NextResponse } from 'next/server';
import { getCurrentUser } from '@/lib/auth';
import { parseMessage } from '@/lib/parser';
import { processOrder } from '@/lib/matcher';

export async function POST(req: Request) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });

  try {
    const { body, hasPdf, pdfData } = await req.json();
    let orderText = body || '';

    // PDF extraction
    if (hasPdf && pdfData) {
      try {
        const pdfParseModule = await import('pdf-parse');
        const pdfParse = (pdfParseModule as unknown as { default: (buf: Buffer) => Promise<{ text: string }> }).default || pdfParseModule;
        const buffer = Buffer.from(pdfData, 'base64');
        const pdfResult = await (pdfParse as (buf: Buffer) => Promise<{ text: string }>)(buffer);
        const pdfText = pdfResult.text || '';
        // Combine: if there's typed text, use that as primary; PDF as secondary
        orderText = orderText ? `${orderText}\n\n--- PDF Content ---\n${pdfText}` : pdfText;
      } catch (pdfErr) {
        console.error('PDF parse error:', pdfErr);
        if (!orderText) {
          return NextResponse.json({ ok: false, error: 'Failed to extract text from PDF' }, { status: 400 });
        }
        // If we have typed text, continue without PDF
      }
    }

    if (!orderText.trim()) {
      return NextResponse.json({ ok: false, error: 'No order text provided' }, { status: 400 });
    }

    // Parse the message
    const parsed = parseMessage(orderText);

    if (parsed.messageType === 'non_order' || parsed.items.length === 0) {
      return NextResponse.json({
        ok: false,
        error: 'Could not detect any order items. Try formatting like: "5 cases of Chicken Breast" or "Product Name x 10"',
      }, { status: 400 });
    }

    // Process: match customer, match products, write to pending
    const result = await processOrder(
      parsed.items,
      parsed.companyName,
      orderText,
      parsed.specialInstructions,
      user.userId,
      user.displayName,
    );

    return NextResponse.json({
      ok: true,
      batchId: result.batchId,
      needsReview: result.needsReview,
      lineCount: result.lineCount,
      total: result.total,
    });

  } catch (err) {
    console.error('Webhook error:', err);
    return NextResponse.json({ ok: false, error: 'Server error processing order' }, { status: 500 });
  }
}
