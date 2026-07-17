'use client';

import { useState, useRef, DragEvent, ChangeEvent } from 'react';
import { useRouter } from 'next/navigation';
import { useApp } from '../layout';

export default function DirectEntryPage() {
  const { addToast, refreshStats } = useApp();
  const router = useRouter();
  const [text, setText] = useState('');
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') setPdfFile(file);
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setPdfFile(file);
  };

  const handleSubmit = async () => {
    if (!text.trim() && !pdfFile) {
      addToast('Please enter order text or attach a PDF.', 'error');
      return;
    }
    setLoading(true);

    let pdfBase64: string | null = null;
    let pdfName: string | null = null;
    if (pdfFile) {
      const buffer = await pdfFile.arrayBuffer();
      pdfBase64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
      pdfName = pdfFile.name;
    }

    try {
      const res = await fetch('/api/webhook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          body: text.trim(),
          hasPdf: !!pdfFile,
          pdfData: pdfBase64,
          pdfName,
        }),
      });
      const data = await res.json();
      if (data.ok) {
        addToast(`✓ Order submitted! ${data.lineCount} item(s), $${data.total?.toFixed(2) || '0.00'}`, 'success');
        setText('');
        setPdfFile(null);
        refreshStats();
        setTimeout(() => router.push('/dashboard/review'), 1500);
      } else {
        addToast(data.error || 'Failed to submit order', 'error');
      }
    } catch {
      addToast('Connection error', 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">📝 New Order</h1>
        <p className="page-subtitle">Paste order text or upload a purchase order PDF</p>
      </div>

      <div className="page-body">
        <div className="direct-entry-grid">
          {/* Left: Input */}
          <div>
            <div className="form-group">
              <label>Order Text</label>
              <textarea
                className="form-input form-textarea"
                style={{ minHeight: 220 }}
                placeholder="Paste the order text here...&#10;&#10;Example:&#10;Customer: EL BUEN SAZON&#10;1010 BEEF HIND SHANK SL 1/2 IN x5&#10;1009 BEEF FEET CUT x100"
                value={text}
                onChange={e => setText(e.target.value)}
              />
            </div>

            {/* PDF Drop Zone */}
            <div
              className={`pdf-drop-zone ${dragOver ? 'dragover' : ''}`}
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileRef.current?.click()}
            >
              <span className="icon">📎</span>
              <span>Drag & drop a PDF here, or click to browse</span>
              <input ref={fileRef} type="file" accept=".pdf" onChange={handleFileChange} style={{ display: 'none' }} />
            </div>

            {pdfFile && (
              <div className="pdf-selected">
                📄 {pdfFile.name}
                <button onClick={() => setPdfFile(null)} style={{ background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer', marginLeft: 'auto' }}>✗</button>
              </div>
            )}

            <button
              className="btn btn-green btn-lg"
              style={{ width: '100%', marginTop: 20, justifyContent: 'center' }}
              onClick={handleSubmit}
              disabled={loading}
            >
              {loading ? <><span className="loading-spinner" /> Processing…</> : '🚀 Submit Order'}
            </button>
          </div>

          {/* Right: Format example */}
          <div className="entry-example">
            <h3>💡 Best Format Example</h3>
            <pre>{`Customer: EL BUEN SAZON

1010 BEEF HIND SHANK SL 1/2 IN x5
1009 BEEF FEET CUT x100
1007 BEEF TRIPE CUT 1X1 x60

Delivery: Monday morning

---
Note: You can also just upload a
PDF and leave the text blank!
The parser handles PDF extraction
automatically.

Supported PDF formats:
• Aspen Systems PO
• Ben E. Keith PO
• US Foods PO
• Generic text-based PO`}</pre>
          </div>
        </div>
      </div>
    </>
  );
}
