'use client';

import { useEffect, useState, createContext, useContext, useCallback } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import type { JWTPayload, DashboardStats } from '@/lib/types';

/* ── Toast Context ────────────────────────────────────────────────────── */
interface Toast { id: number; message: string; type: 'success' | 'error' | 'info' }
interface AppContextType {
  user: JWTPayload | null;
  stats: DashboardStats;
  refreshStats: () => void;
  addToast: (message: string, type: Toast['type']) => void;
}

const AppContext = createContext<AppContextType>({
  user: null,
  stats: { ordersToday: 0, needsReview: 0, customers: 0, products: 0 },
  refreshStats: () => {},
  addToast: () => {},
});

export const useApp = () => useContext(AppContext);

/* ── Layout ───────────────────────────────────────────────────────────── */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<JWTPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<DashboardStats>({ ordersToday: 0, needsReview: 0, customers: 0, products: 0 });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const router = useRouter();
  const pathname = usePathname();

  // Auth check
  useEffect(() => {
    fetch('/api/auth/me').then(r => r.json()).then(d => {
      if (d.ok) setUser(d.user);
      else router.push('/');
    }).catch(() => router.push('/')).finally(() => setLoading(false));
  }, [router]);

  // Stats polling
  const refreshStats = useCallback(() => {
    fetch('/api/stats').then(r => r.json()).then(d => {
      if (!d.error) setStats(d);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!user) return;
    refreshStats();
    const interval = setInterval(refreshStats, 15000);
    return () => clearInterval(interval);
  }, [user, refreshStats]);

  // Toast
  const addToast = useCallback((message: string, type: Toast['type']) => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }, []);

  const handleLogout = async () => {
    await fetch('/api/auth/login', { method: 'DELETE' });
    router.push('/');
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <div className="loading-spinner" />
      </div>
    );
  }

  if (!user) return null;

  const navItems = [
    { href: '/dashboard', icon: '🏠', label: 'Home' },
    { href: '/dashboard/entry', icon: '📝', label: 'New Order' },
    { href: '/dashboard/review', icon: '✅', label: 'Review Orders', badge: stats.needsReview },
    ...(user.role === 'admin' ? [{ href: '/dashboard/admin', icon: '👥', label: 'Users' }] : []),
  ];

  const initials = user.displayName.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();

  return (
    <AppContext.Provider value={{ user, stats, refreshStats, addToast }}>
      <div className="dashboard-layout">
        {/* Sidebar */}
        <aside className="sidebar">
          <div className="sidebar-brand">
            <h1>📦 Colinas Foods</h1>
            <span>Order Dashboard</span>
          </div>

          <nav className="sidebar-nav">
            <div className="sidebar-section">
              <div className="sidebar-section-title">📋 Order Management</div>
              {navItems.map(item => (
                <a
                  key={item.href}
                  href={item.href}
                  className={`sidebar-link ${pathname === item.href ? 'active' : ''}`}
                  onClick={e => { e.preventDefault(); router.push(item.href); }}
                >
                  <span className="icon">{item.icon}</span>
                  {item.label}
                  {item.badge ? <span className="sidebar-badge">{item.badge}</span> : null}
                </a>
              ))}
            </div>
          </nav>

          <div className="sidebar-user">
            <div className="sidebar-user-avatar">{initials}</div>
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">{user.displayName}</div>
              <span className="sidebar-user-role">{user.role}</span>
            </div>
            <button className="sidebar-logout" onClick={handleLogout} title="Cerrar Sesión">⏻</button>
          </div>
        </aside>

        {/* Main content */}
        <main className="main-content">
          {children}
        </main>

        {/* Toasts */}
        <div className="toast-container">
          {toasts.map(t => (
            <div key={t.id} className={`toast ${t.type}`}>
              {t.type === 'success' ? '✓' : t.type === 'error' ? '✗' : 'ℹ'} {t.message}
            </div>
          ))}
        </div>
      </div>
    </AppContext.Provider>
  );
}
