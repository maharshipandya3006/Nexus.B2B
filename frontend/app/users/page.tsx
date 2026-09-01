'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Link from 'next/link';

interface User {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
}

export default function UserManagementPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [editRole, setEditRole] = useState('');
  const [me, setMe] = useState<User | null>(null);
  const router = useRouter();

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [currentUser, allUsers] = await Promise.all([
        api.getMe(),
        api.getUsers()
      ]);
      setMe(currentUser);
      setUsers(allUsers);
    } catch (err: any) {
      if (err.status === 401) {
        localStorage.removeItem('token');
        localStorage.removeItem('role');
        router.push('/auth');
      } else {
        setError('Failed to load user data.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to terminate this identity? This action cannot be undone.')) return;
    
    try {
      await api.deleteUser(id);
      setUsers(users.filter(u => u.id !== id));
    } catch (err: any) {
      setError(err.message || 'Failed to delete user.');
    }
  };

  const handleUpdateRole = async (id: number) => {
    try {
      const updated = await api.updateUser(id, { role: editRole });
      setUsers(users.map(u => u.id === id ? { ...u, role: updated.role } : u));
      setEditingUserId(null);
    } catch (err: any) {
      setError(err.message || 'Failed to update user role.');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    router.push('/auth');
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center text-neon-blue font-mono">Initializing System...</div>;
  }

  return (
    <div className="min-h-screen p-8 max-w-6xl mx-auto">
      <header className="flex justify-between items-center mb-8 border-b border-cyber-light/30 pb-4">
        <div>
          <h1 className="text-3xl font-bold tracking-widest neon-text-blue uppercase">Nexus Identity Core</h1>
          <p className="text-text-muted font-mono text-sm mt-1">Global User Management Node</p>
        </div>
        <div className="flex items-center gap-4">
          <Link href={me?.role === 'merchant' ? '/merchant' : '/buyer'} className="px-4 py-2 rounded border border-cyber-light bg-cyber-black hover:bg-cyber-light/20 transition-colors font-mono text-xs">
            Return to Dashboard
          </Link>
          <button onClick={handleLogout} className="px-4 py-2 rounded bg-red-900/30 text-red-400 hover:bg-red-900/50 transition-colors font-mono text-xs">
            Sever Connection
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-6 p-4 bg-red-900/30 border border-red-500/50 text-red-200 text-sm rounded flex justify-between items-center">
          {error}
          <button onClick={() => setError('')} className="text-red-400 hover:text-red-200 font-bold">✕</button>
        </div>
      )}

      <div className="glass-card rounded-xl overflow-hidden neon-border-blue relative">
        {/* Decorative corner accents */}
        <div className="absolute top-0 left-0 w-8 h-8 border-t-2 border-l-2 border-neon-blue opacity-50"></div>
        <div className="absolute bottom-0 right-0 w-8 h-8 border-b-2 border-r-2 border-neon-blue opacity-50"></div>

        <div className="overflow-x-auto p-1">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-cyber-light/50 bg-cyber-black/50">
                <th className="p-4 text-xs uppercase tracking-wider text-text-muted font-mono">Identity (ID)</th>
                <th className="p-4 text-xs uppercase tracking-wider text-text-muted font-mono">Protocol (Username)</th>
                <th className="p-4 text-xs uppercase tracking-wider text-text-muted font-mono">Access Level (Role)</th>
                <th className="p-4 text-xs uppercase tracking-wider text-text-muted font-mono">Status</th>
                <th className="p-4 text-xs uppercase tracking-wider text-text-muted font-mono text-right">Directives</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-b border-cyber-light/20 hover:bg-cyber-light/10 transition-colors group">
                  <td className="p-4 font-mono text-neon-blue text-sm">SYS-{user.id.toString().padStart(4, '0')}</td>
                  <td className="p-4 font-bold text-[#012652]">
                    {user.username}
                    {me?.id === user.id && <span className="ml-2 text-xs bg-neon-blue/20 text-neon-blue px-2 py-0.5 rounded-full border border-neon-blue/50">YOU</span>}
                  </td>
                  <td className="p-4">
                    {editingUserId === user.id ? (
                      <div className="flex gap-2">
                        <select
                          value={editRole}
                          onChange={(e) => setEditRole(e.target.value)}
                          className="p-1 rounded bg-cyber-black border-cyber-light text-[#012652] font-mono text-xs focus:ring-1 focus:ring-neon-blue"
                        >
                          <option value="buyer">buyer</option>
                          <option value="merchant">merchant</option>
                          <option value="admin">admin</option>
                        </select>
                        <button 
                          onClick={() => handleUpdateRole(user.id)}
                          className="px-2 py-1 bg-green-900/40 text-green-400 rounded hover:bg-green-900/60 font-mono text-xs"
                        >
                          Save
                        </button>
                        <button 
                          onClick={() => setEditingUserId(null)}
                          className="px-2 py-1 bg-cyber-light/20 text-text-muted rounded hover:bg-cyber-light/40 font-mono text-xs"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <span className={`inline-block px-2 py-1 rounded text-xs font-mono uppercase tracking-widest ${
                        user.role === 'merchant' ? 'bg-neon-blue/10 text-neon-blue border border-neon-blue/30' : 
                        user.role === 'buyer' ? 'bg-neon-purple/10 text-neon-purple border border-neon-purple/30' :
                        'bg-yellow-900/20 text-yellow-500 border border-yellow-700/50'
                      }`}>
                        {user.role}
                      </span>
                    )}
                  </td>
                  <td className="p-4">
                    <span className="flex items-center gap-2 text-xs font-mono text-green-400">
                      <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></div> Active
                    </span>
                  </td>
                  <td className="p-4 text-right">
                    <div className="flex justify-end gap-3 opacity-50 group-hover:opacity-100 transition-opacity">
                      {editingUserId !== user.id && (
                        <button 
                          onClick={() => { setEditingUserId(user.id); setEditRole(user.role); }}
                          className="text-text-muted hover:text-neon-blue font-mono text-xs transition-colors"
                        >
                          [EDIT]
                        </button>
                      )}
                      {me?.id !== user.id && (
                        <button 
                          onClick={() => handleDelete(user.id)}
                          className="text-text-muted hover:text-red-500 font-mono text-xs transition-colors"
                        >
                          [TERMINATE]
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-text-muted font-mono">No identities found in system.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
