'use client';

import { useEffect, useState, FormEvent } from 'react';
import { useApp } from '../layout';

interface UserRow {
  UserID: number;
  Email: string;
  DisplayName: string;
  Role: string;
  IsActive: boolean;
  LastLoginAt: string | null;
  CreatedAt: string;
}

export default function AdminPage() {
  const { user, addToast } = useApp();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [newEmail, setNewEmail] = useState('');
  const [newName, setNewName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState('user');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = async () => {
    try {
      const res = await fetch('/api/users');
      const data = await res.json();
      if (Array.isArray(data)) setUsers(data);
    } catch { /* ignore */ }
  };

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!newEmail || !newName || !newPassword) {
      addToast('Please fill all fields', 'error');
      return;
    }
    setCreating(true);
    try {
      const res = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: newEmail, displayName: newName, password: newPassword, role: newRole }),
      });
      const data = await res.json();
      if (data.ok) {
        addToast(`User "${newName}" created!`, 'success');
        setNewEmail(''); setNewName(''); setNewPassword(''); setNewRole('user');
        loadUsers();
      } else {
        addToast(data.error || 'Failed to create user', 'error');
      }
    } catch { addToast('Connection error', 'error'); }
    finally { setCreating(false); }
  };

  const toggleActive = async (userId: number, currentlyActive: boolean) => {
    try {
      const res = await fetch('/api/users', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId, isActive: !currentlyActive }),
      });
      const data = await res.json();
      if (data.ok) {
        addToast(`User ${currentlyActive ? 'deactivated' : 'activated'}`, 'info');
        loadUsers();
      }
    } catch { /* ignore */ }
  };

  if (user?.role !== 'admin') {
    return (
      <div className="page-body">
        <div className="empty-state">
          <div className="icon">🔒</div>
          <p>Admin access required</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">👥 User Management</h1>
        <p className="page-subtitle">Create and manage dashboard user accounts</p>
      </div>

      <div className="page-body">
        {/* Create user form */}
        <form className="user-form" onSubmit={handleCreate}>
          <div className="form-group">
            <label>Email</label>
            <input className="form-input" type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="user@colinasfoods.com" />
          </div>
          <div className="form-group">
            <label>Display Name</label>
            <input className="form-input" value={newName} onChange={e => setNewName(e.target.value)} placeholder="Full Name" />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input className="form-input" type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="••••••••" />
          </div>
          <div className="form-group">
            <label>Role</label>
            <select className="form-input" value={newRole} onChange={e => setNewRole(e.target.value)}>
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <button className="btn btn-red" type="submit" disabled={creating}>
            {creating ? 'Creating…' : '+ Create User'}
          </button>
        </form>

        {/* Users table */}
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Name</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last Login</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.UserID}>
                  <td>{u.Email}</td>
                  <td className="fw-700">{u.DisplayName}</td>
                  <td><span className={`badge ${u.Role === 'admin' ? 'red' : 'blue'}`}>{u.Role}</span></td>
                  <td><span className={`badge ${u.IsActive ? 'green' : 'red'}`}>{u.IsActive ? 'Active' : 'Inactive'}</span></td>
                  <td className="text-2">{u.LastLoginAt ? new Date(u.LastLoginAt).toLocaleDateString() : 'Never'}</td>
                  <td>
                    <button
                      className={`btn btn-sm ${u.IsActive ? 'btn-danger' : 'btn-green'}`}
                      onClick={() => toggleActive(u.UserID, u.IsActive)}
                      disabled={u.UserID === user?.userId}
                    >
                      {u.IsActive ? 'Deactivate' : 'Activate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
