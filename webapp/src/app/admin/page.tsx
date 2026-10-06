'use client';

import React, { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabase';
import { Users, Ban, ShieldCheck, ShieldAlert, CheckCircle2 } from 'lucide-react';
import Link from 'next/link';

interface UserProfile {
  id: string;
  full_name: string;
  phone_number: string;
  account_type: string;
  role: string;
  is_banned: boolean;
  created_at: string;
}

export default function AdminDashboard() {
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [deals, setDeals] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'users' | 'deals'>('users');

  useEffect(() => {
    checkAdminAndFetchData();
  }, []);

  const checkAdminAndFetchData = async () => {
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        setError("You must be logged in to view this page.");
        setLoading(false);
        return;
      }

      const { data: profile, error: profileError } = await supabase
        .from('profiles')
        .select('role')
        .eq('id', user.id)
        .single();
        
      if (profileError || profile?.role !== 'admin') {
        setError("Access Denied. You do not have administrator privileges.");
        setLoading(false);
        return;
      }

      setIsAdmin(true);
      fetchUsers();
      fetchDeals();
    } catch (err: any) {
      setError(err.message);
      setLoading(false);
    }
  };

  const fetchUsers = async () => {
    const { data } = await supabase.from('profiles').select('*').order('created_at', { ascending: false });
    if (data) setUsers(data);
  };

  const fetchDeals = async () => {
    const { data } = await supabase.from('deals').select('*').order('created_at', { ascending: false });
    if (data) setDeals(data);
    setLoading(false);
  };

  const toggleBanStatus = async (userId: string, currentStatus: boolean) => {
    const { error } = await supabase.from('profiles').update({ is_banned: !currentStatus }).eq('id', userId);
    if (!error) setUsers(users.map(u => u.id === userId ? { ...u, is_banned: !currentStatus } : u));
  };

  const promoteToAdmin = async (userId: string) => {
    const confirmPromote = confirm("Are you sure you want to make this user an admin?");
    if (!confirmPromote) return;
    const { error } = await supabase.from('profiles').update({ role: 'admin' }).eq('id', userId);
    if (!error) setUsers(users.map(u => u.id === userId ? { ...u, role: 'admin' } : u));
  };

  const updateDealStatus = async (dealId: string, status: string) => {
    const { error } = await supabase.from('deals').update({ status }).eq('id', dealId);
    if (error) {
      alert("Failed to update deal: " + error.message);
    } else {
      setDeals(deals.map(d => d.id === dealId ? { ...d, status } : d));
    }
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center bg-gray-50"><p className="text-xl animate-pulse">Loading Admin Panel...</p></div>;
  }

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 p-4">
        <ShieldAlert className="w-16 h-16 text-red-500 mb-4" />
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h1>
        <p className="text-gray-600 mb-6 text-center">{error}</p>
        <Link href="/" className="bg-green-600 text-white px-6 py-2 rounded-lg font-medium hover:bg-green-700">
          Return to Homepage
        </Link>
      </div>
    );
  }

  const buyers = users.filter(u => u.account_type === 'buyer');
  const sellers = users.filter(u => u.account_type === 'seller');
  const pendingDeals = deals.filter(d => d.status === 'pending');

  return (
    <div className="min-h-screen bg-gray-50 pb-12">
      <header className="bg-gray-900 text-white py-6 shadow-md">
        <div className="container mx-auto px-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-8 h-8 text-yellow-500" />
            <h1 className="text-2xl font-bold">TirfMarket Admin Control</h1>
          </div>
          <Link href="/" className="text-gray-300 hover:text-white transition-colors">
            Exit to Site
          </Link>
        </div>
      </header>

      <main className="container mx-auto px-4 mt-8">
        {/* Stats Row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex flex-col items-center">
            <span className="text-4xl font-bold text-gray-900 mb-2">{users.length}</span>
            <span className="text-sm text-gray-500 font-medium uppercase tracking-wider">Total Users</span>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex flex-col items-center">
            <span className="text-4xl font-bold text-green-600 mb-2">{sellers.length}</span>
            <span className="text-sm text-gray-500 font-medium uppercase tracking-wider">Merchants</span>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex flex-col items-center">
            <span className="text-4xl font-bold text-yellow-600 mb-2">{pendingDeals.length}</span>
            <span className="text-sm text-gray-500 font-medium uppercase tracking-wider">Pending Deals</span>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex flex-col items-center">
            <span className="text-4xl font-bold text-blue-600 mb-2">{deals.length}</span>
            <span className="text-sm text-gray-500 font-medium uppercase tracking-wider">Total Deals</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-4 mb-6">
          <button 
            onClick={() => setActiveTab('users')}
            className={`px-6 py-3 rounded-lg font-bold transition-colors ${activeTab === 'users' ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'}`}
          >
            Manage Users
          </button>
          <button 
            onClick={() => setActiveTab('deals')}
            className={`px-6 py-3 rounded-lg font-bold transition-colors flex items-center gap-2 ${activeTab === 'deals' ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'}`}
          >
            Review Deals {pendingDeals.length > 0 && <span className="bg-red-500 text-white text-xs px-2 py-1 rounded-full">{pendingDeals.length}</span>}
          </button>
        </div>

        {/* Content Area */}
        {activeTab === 'users' ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-6 border-b border-gray-100 flex justify-between items-center">
              <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                <Users className="w-5 h-5 text-green-600" /> User Management
              </h2>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="bg-gray-50 text-gray-600 text-sm uppercase font-semibold">
                  <tr>
                    <th className="px-6 py-4">User</th>
                    <th className="px-6 py-4">Contact</th>
                    <th className="px-6 py-4">Type</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {users.map(user => (
                    <tr key={user.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-6 py-4">
                        <div className="font-medium text-gray-900">{user.full_name || 'No Name'}</div>
                        <div className="text-xs text-gray-400 mt-1">ID: {user.id.substring(0, 8)}...</div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="text-sm text-gray-600">{user.phone_number || 'No Phone'}</div>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          user.role === 'admin' ? 'bg-purple-100 text-purple-800' :
                          user.account_type === 'seller' ? 'bg-green-100 text-green-800' : 'bg-blue-100 text-blue-800'
                        }`}>
                          {user.role === 'admin' ? 'Admin' : (user.account_type === 'seller' ? 'Merchant' : 'Buyer')}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        {user.is_banned ? (
                          <span className="inline-flex items-center gap-1 text-red-600 text-sm font-medium">
                            <Ban className="w-4 h-4" /> Banned
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-green-600 text-sm font-medium">
                            <CheckCircle2 className="w-4 h-4" /> Active
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex justify-end gap-2">
                          {user.role !== 'admin' && (
                            <>
                              <button 
                                onClick={() => toggleBanStatus(user.id, user.is_banned)}
                                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                                  user.is_banned 
                                    ? 'bg-gray-200 text-gray-800 hover:bg-gray-300' 
                                    : 'bg-red-50 text-red-600 hover:bg-red-100'
                                }`}
                              >
                                {user.is_banned ? 'Unban' : 'Ban User'}
                              </button>
                              <button 
                                onClick={() => promoteToAdmin(user.id)}
                                className="px-3 py-1.5 rounded-md text-sm font-medium bg-purple-50 text-purple-600 hover:bg-purple-100 transition-colors"
                              >
                                Make Admin
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">Deal Approvals</h2>
            </div>
            <div className="divide-y divide-gray-100">
              {deals.map(deal => (
                <div key={deal.id} className="p-6 flex flex-col md:flex-row gap-6 items-center hover:bg-gray-50 transition-colors">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-lg font-bold text-gray-900">{deal.title}</h3>
                      {deal.status === 'pending' && <span className="bg-yellow-100 text-yellow-800 text-xs font-bold px-2 py-1 rounded">PENDING</span>}
                      {deal.status === 'approved' && <span className="bg-green-100 text-green-800 text-xs font-bold px-2 py-1 rounded">APPROVED</span>}
                      {deal.status === 'rejected' && <span className="bg-red-100 text-red-800 text-xs font-bold px-2 py-1 rounded">REJECTED</span>}
                    </div>
                    <p className="text-gray-600 text-sm mb-2">Merchant: {deal.merchant_name || 'Unknown'} | Category: {deal.category}</p>
                    <p className="text-sm font-medium">
                      <span className="line-through text-gray-400 mr-2">ETB {deal.original_price}</span>
                      <span className="text-green-600">ETB {deal.discounted_price}</span>
                    </p>
                  </div>
                  <div className="flex gap-2 w-full md:w-auto">
                    {deal.status !== 'approved' && (
                      <button onClick={() => updateDealStatus(deal.id, 'approved')} className="flex-1 md:flex-none bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg font-medium text-sm transition-colors">
                        Approve
                      </button>
                    )}
                    {deal.status !== 'rejected' && (
                      <button onClick={() => updateDealStatus(deal.id, 'rejected')} className="flex-1 md:flex-none bg-red-100 hover:bg-red-200 text-red-700 px-4 py-2 rounded-lg font-medium text-sm transition-colors">
                        Reject
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {deals.length === 0 && <div className="p-8 text-center text-gray-500">No deals found.</div>}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
