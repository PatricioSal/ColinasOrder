'use client';

import { useEffect, useState } from 'react';
import { useApp } from './layout';
import type { RecentOrder } from '@/lib/types';

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Buenos días';
  if (h < 18) return 'Buenas tardes';
  return 'Buenas noches';
}

export default function DashboardHome() {
  const { user, stats } = useApp();
  const [orders, setOrders] = useState<RecentOrder[]>([]);

  useEffect(() => {
    fetch('/api/orders').then(r => r.json()).then(d => {
      if (Array.isArray(d)) setOrders(d);
    }).catch(() => {});
  }, []);

  const dateStr = new Date().toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  });

  function statusBadge(status: string, needsReview: boolean) {
    if (status === 'confirmed') return <span className="badge green">Confirmed</span>;
    if (status === 'pending_review' && needsReview) return <span className="badge amber">Needs Review</span>;
    if (status === 'pending_review') return <span className="badge blue">Pending</span>;
    if (status === 'rejected') return <span className="badge red">Rejected</span>;
    if (status === 'non_order') return <span className="badge purple">Non-order</span>;
    return <span className="badge">{status}</span>;
  }

  return (
    <>
      <div className="page-header">
        <h1 className="page-greeting">{getGreeting()}, {user?.displayName} 👋</h1>
        <p className="page-date">{dateStr}</p>
      </div>

      <div className="page-body">
        {/* Stats Cards */}
        <div className="stats-grid">
          <div className="stat-card blue">
            <div className="stat-icon">🔥</div>
            <div className="stat-value">{stats.ordersToday}</div>
            <div className="stat-label">Orders Today</div>
          </div>
          <div className="stat-card amber">
            <div className="stat-icon">⚠️</div>
            <div className="stat-value">{stats.needsReview}</div>
            <div className="stat-label">Needs Review</div>
          </div>
          <div className="stat-card green">
            <div className="stat-icon">👥</div>
            <div className="stat-value">{stats.customers}</div>
            <div className="stat-label">Customers</div>
          </div>
          <div className="stat-card purple">
            <div className="stat-icon">📦</div>
            <div className="stat-value">{stats.products}</div>
            <div className="stat-label">Products</div>
          </div>
        </div>

        {/* Recent Orders */}
        <div className="flex items-center justify-between mb-16">
          <h2 style={{ fontSize: 16, fontWeight: 700 }}>Recent Orders</h2>
          <span className="text-muted" style={{ fontSize: 12 }}>Last 50 orders</span>
        </div>

        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Customer</th>
                <th>Items</th>
                <th>Status</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 ? (
                <tr><td colSpan={5} style={{ textAlign: 'center', padding: 40, color: 'var(--text-3)' }}>No orders yet</td></tr>
              ) : (
                orders.map((o, i) => (
                  <tr key={i}>
                    <td className="text-muted">{o.id?.substring(0, 8)}</td>
                    <td className="fw-700">{o.customer}</td>
                    <td>{o.product}</td>
                    <td>{statusBadge(o.status, o.needsReview)}</td>
                    <td className="text-2">
                      {o.createdAt ? new Date(o.createdAt).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
