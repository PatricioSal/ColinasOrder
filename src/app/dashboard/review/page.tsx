'use client';

import { useEffect, useState, useCallback } from 'react';
import { useApp } from '../layout';
import type { PendingOrder, PendingOrderLine, EditOrderPayload } from '@/lib/types';

export default function ReviewPage() {
  const { addToast, refreshStats } = useApp();
  const [orders, setOrders] = useState<PendingOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [editOrder, setEditOrder] = useState<PendingOrder | null>(null);
  const [actionLoading, setActionLoading] = useState<string>('');

  const loadOrders = useCallback(async () => {
    try {
      const res = await fetch('/api/orders/pending');
      const data = await res.json();
      if (Array.isArray(data)) setOrders(data);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadOrders(); }, [loadOrders]);

  const toggleExpand = (batchId: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(batchId) ? next.delete(batchId) : next.add(batchId);
      return next;
    });
  };

  const handleConfirm = async (batchId: string) => {
    setActionLoading(batchId);
    try {
      const res = await fetch('/api/orders/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batchId }),
      });
      const data = await res.json();
      if (data.ok) {
        addToast('✓ Order confirmed and sent to SQL Server!', 'success');
        setOrders(prev => prev.filter(o => o.BatchID !== batchId));
        refreshStats();
      } else {
        addToast(data.error || 'Failed to confirm', 'error');
      }
    } catch { addToast('Connection error', 'error'); }
    finally { setActionLoading(''); }
  };

  const handleReject = async (batchId: string) => {
    if (!confirm('Are you sure you want to reject this order? This cannot be undone.')) return;
    setActionLoading(batchId);
    try {
      const res = await fetch('/api/orders/reject', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batchId }),
      });
      const data = await res.json();
      if (data.ok) {
        addToast('Order rejected and deleted', 'info');
        setOrders(prev => prev.filter(o => o.BatchID !== batchId));
        refreshStats();
      } else {
        addToast(data.error || 'Failed to reject', 'error');
      }
    } catch { addToast('Connection error', 'error'); }
    finally { setActionLoading(''); }
  };

  return (
    <>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="page-title">✅ Review Orders</h1>
            <p className="page-subtitle">Review pending orders and confirm to send to SQL Server</p>
          </div>
          <button className="btn btn-ghost" onClick={() => { setLoading(true); loadOrders(); }}>
            ↻ Refresh
          </button>
        </div>
      </div>

      <div className="page-body">
        {loading ? (
          <div className="empty-state"><div className="loading-spinner" /></div>
        ) : orders.length === 0 ? (
          <div className="empty-state">
            <div className="icon">✓</div>
            <p>All caught up — no pending orders.</p>
          </div>
        ) : (
          orders.map(order => {
            const isExpanded = expanded.has(order.BatchID);
            const grandTotal = order.lines.reduce((s, l) => s + (l.total || 0), 0);
            const isLoading = actionLoading === order.BatchID;

            return (
              <div key={order.BatchID} className={`order-card ${order.NeedsReview ? 'needs-review' : ''}`}>
                <div className="order-card-header" onClick={() => toggleExpand(order.BatchID)}>
                  <div className="order-card-left">
                    <div>
                      <div className="order-card-customer">{order.CustomerName || 'Unknown'}</div>
                      <div className="order-card-total">${grandTotal.toFixed(2)}</div>
                    </div>
                    {order.NeedsReview && <span className="badge amber">⚠ Needs Review</span>}
                  </div>
                  <div className="order-card-meta">
                    <span>{order.SubmitterName || 'System'}</span>
                    <span>{order.CreatedAt ? new Date(order.CreatedAt).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : ''}</span>
                    <span style={{ fontSize: 14 }}>{isExpanded ? '▲' : '▼'}</span>
                  </div>
                </div>

                {isExpanded && (
                  <div className="order-card-body">
                    {/* Original message */}
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', marginTop: 12, marginBottom: 4 }}>
                      💬 Original Message
                    </div>
                    <div className="order-card-message">{order.RawMessage}</div>

                    {/* Line items */}
                    <table className="order-lines-table">
                      <thead>
                        <tr>
                          <th>Product</th>
                          <th>SKU</th>
                          <th style={{ textAlign: 'center' }}>Cases | Lbs</th>
                          <th style={{ textAlign: 'right' }}>Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {order.lines.map((line, i) => {
                          const isUnknown = !line.SKU || line.SKU === 'UNKNOWN';
                          return (
                            <tr key={i}>
                              <td className={isUnknown ? 'unknown' : ''}>{line.ProductName || line.OriginalName || 'Unknown'}</td>
                              <td className="text-2">{line.SKU || '—'}</td>
                              <td className="text-center">{line.QuantityCs}{line.QuantityLbs ? ` | ${line.QuantityLbs}` : ''}</td>
                              <td className="text-right">${(line.total || 0).toFixed(2)}</td>
                            </tr>
                          );
                        })}
                        <tr className="order-total-row">
                          <td colSpan={3} className="text-right text-2">TOTAL</td>
                          <td className="text-right text-green fw-700">${grandTotal.toFixed(2)}</td>
                        </tr>
                      </tbody>
                    </table>

                    {order.SpecialInstructions && order.SpecialInstructions.toLowerCase() !== 'none' && (
                      <div style={{ marginTop: 8, fontSize: 13, color: 'var(--amber)' }}>
                        📝 {order.SpecialInstructions}
                      </div>
                    )}

                    {/* Actions */}
                    <div className="order-actions">
                      <div className="action-result" />
                      <button className="btn btn-danger btn-sm" onClick={() => handleReject(order.BatchID)} disabled={isLoading}>
                        ✗ Reject
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditOrder(order)} disabled={isLoading}>
                        ✎ Edit
                      </button>
                      <button className="btn btn-green btn-sm" onClick={() => handleConfirm(order.BatchID)} disabled={isLoading}>
                        {isLoading ? <span className="loading-spinner" /> : '✓ Confirm & Send to SQL'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Edit Modal */}
      {editOrder && (
        <EditModal
          order={editOrder}
          onClose={() => setEditOrder(null)}
          onSaved={() => { setEditOrder(null); loadOrders(); addToast('Order updated', 'success'); }}
        />
      )}
    </>
  );
}

/* ── Edit Modal ───────────────────────────────────────────────────────── */
function EditModal({ order, onClose, onSaved }: { order: PendingOrder; onClose: () => void; onSaved: () => void }) {
  const [tab, setTab] = useState<'lines' | 'customer' | 'notes'>('lines');
  const [lines, setLines] = useState<PendingOrderLine[]>([...order.lines]);
  const [deletedLines, setDeletedLines] = useState<number[]>([]);
  const [specialInstructions, setSpecialInstructions] = useState(order.SpecialInstructions || '');
  const [overrides, setOverrides] = useState<Record<string, string>>({
    address1: order.customerDetails?.address1 || '',
    address2: order.customerDetails?.address2 || '',
    city: order.customerDetails?.city || '',
    state: order.customerDetails?.state || '',
    zipcode: order.customerDetails?.zipcode || '',
    country: order.customerDetails?.country || '',
    paymentTerms: String(order.customerDetails?.paymentTerms || ''),
    deliveryTerms: String(order.customerDetails?.deliveryTerms || ''),
    salesmanId: String(order.customerDetails?.salesmanId || ''),
    taxId: order.customerDetails?.taxId || '',
    phone: order.customerDetails?.phone || '',
    deliveryNotes: order.customerDetails?.deliveryNotes || '',
  });
  const [saving, setSaving] = useState(false);

  const updateLine = (idx: number, field: string, value: number | string) => {
    setLines(prev => prev.map((l, i) => i === idx ? { ...l, [field]: value } : l));
  };

  const deleteLine = (idx: number) => {
    const line = lines[idx];
    setDeletedLines(prev => [...prev, line.LineID]);
    setLines(prev => prev.filter((_, i) => i !== idx));
  };

  const handleSave = async () => {
    setSaving(true);
    const payload: EditOrderPayload = {
      batchId: order.BatchID,
      lines: lines.map(l => ({
        lineId: l.LineID,
        qty: l.QuantityCs,
        secondaryQty: l.QuantityLbs,
        productId: l.ProductID,
        lineNote: l.LineNote || undefined,
      })),
      deletedLines,
      specialInstructions,
      customerOverrides: Object.keys(overrides).some(k => overrides[k]) ? overrides : null,
    };

    try {
      const res = await fetch('/api/orders/edit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.ok) onSaved();
    } catch { /* ignore */ }
    finally { setSaving(false); }
  };

  return (
    <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-header">
          <h2>Editing: {order.CustomerName}</h2>
        </div>

        <div className="modal-tabs">
          <button className={`modal-tab ${tab === 'lines' ? 'active' : ''}`} onClick={() => setTab('lines')}>Line Items</button>
          <button className={`modal-tab ${tab === 'customer' ? 'active' : ''}`} onClick={() => setTab('customer')}>Customer Details</button>
          <button className={`modal-tab ${tab === 'notes' ? 'active' : ''}`} onClick={() => setTab('notes')}>Notes</button>
        </div>

        <div className="modal-body">
          {tab === 'lines' && (
            <>
              {lines.map((line, i) => (
                <div key={i} className="line-item-row">
                  <div className="line-item-top">
                    <input className="form-input" value={line.ProductName || line.OriginalName || ''} readOnly style={{ flex: 1 }} />
                    <span className="line-label">Cases:</span>
                    <input className="form-input qty-input" type="number" value={line.QuantityCs}
                      onChange={e => updateLine(i, 'QuantityCs', parseFloat(e.target.value) || 0)} />
                    <span className="line-label">Lbs:</span>
                    <input className="form-input qty-input" type="number" value={line.QuantityLbs}
                      onChange={e => updateLine(i, 'QuantityLbs', parseFloat(e.target.value) || 0)} />
                    <span className="line-label">Note:</span>
                    <input className="form-input note-input" value={line.LineNote || ''}
                      onChange={e => updateLine(i, 'LineNote', e.target.value)} />
                    <button className="line-item-delete" onClick={() => deleteLine(i)}>✗</button>
                  </div>
                </div>
              ))}
              {lines.length === 0 && <div className="empty-state">All lines deleted</div>}
            </>
          )}

          {tab === 'customer' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {Object.entries(overrides).map(([key, val]) => (
                <div key={key} className="form-group">
                  <label>{key.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase())}</label>
                  <input className="form-input" value={val} onChange={e => setOverrides(prev => ({ ...prev, [key]: e.target.value }))} />
                </div>
              ))}
            </div>
          )}

          {tab === 'notes' && (
            <div className="form-group">
              <label>Special Instructions</label>
              <textarea className="form-input form-textarea" value={specialInstructions}
                onChange={e => setSpecialInstructions(e.target.value)} />
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-blue" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
