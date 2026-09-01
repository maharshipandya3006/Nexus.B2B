'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { useDashboardRealtime, RealtimeEvent } from '@/lib/useRealtime';
import Link from 'next/link';

// Strict 3-Color Deal Status Configuration: Green (Paid/Completed/Agreed), Yellow (Pending/Independent Acceptance), Red (Terminated/Failed)
function getDealStatusConfig(status: string, buyerApproved?: number, merchantApproved?: number) {
  const s = (status || '').toLowerCase();
  if (['paid', 'completed', 'fulfilled'].includes(s)) {
    return {
      type: 'success',
      badge: 'bg-emerald-50 text-emerald-700 border border-emerald-300',
      dot: 'bg-emerald-500',
      borderHover: 'hover:border-emerald-500',
      label: 'SETTLED & PAID',
    };
  }
  if (buyerApproved === 1 && merchantApproved === 1) {
    return {
      type: 'success',
      badge: 'bg-emerald-50 text-emerald-700 border border-emerald-300',
      dot: 'bg-emerald-500',
      borderHover: 'hover:border-emerald-500',
      label: 'MUTUALLY AGREED',
    };
  }
  if (buyerApproved === 1 && merchantApproved === 0) {
    return {
      type: 'warning',
      badge: 'bg-amber-50 text-amber-800 border border-amber-300',
      dot: 'bg-amber-400',
      borderHover: 'hover:border-amber-400',
      label: 'ACCEPTED BY BUYER',
    };
  }
  if (merchantApproved === 1 && buyerApproved === 0) {
    return {
      type: 'warning',
      badge: 'bg-amber-50 text-amber-800 border border-amber-300',
      dot: 'bg-amber-400',
      borderHover: 'hover:border-amber-400',
      label: 'ACCEPTED BY MERCHANT',
    };
  }
  if (['failed', 'verification_failed', 'cancelled', 'rejected', 'terminated', 'expired'].includes(s)) {
    return {
      type: 'danger',
      badge: 'bg-red-50 text-red-700 border border-red-300',
      dot: 'bg-red-500',
      borderHover: 'hover:border-red-400',
      label: s.toUpperCase(),
    };
  }
  if (['mutually_approved', 'approved', 'quote_agreed'].includes(s)) {
    return {
      type: 'success',
      badge: 'bg-emerald-50 text-emerald-700 border border-emerald-300',
      dot: 'bg-emerald-500',
      borderHover: 'hover:border-emerald-500',
      label: 'MUTUALLY AGREED',
    };
  }
  if (s === 'awaiting_merchant_approval') {
    return {
      type: 'warning',
      badge: 'bg-amber-50 text-amber-800 border border-amber-300',
      dot: 'bg-amber-400',
      borderHover: 'hover:border-amber-400',
      label: 'ACCEPTED BY BUYER',
    };
  }
  if (s === 'awaiting_buyer_approval') {
    return {
      type: 'warning',
      badge: 'bg-amber-50 text-amber-800 border border-amber-300',
      dot: 'bg-amber-400',
      borderHover: 'hover:border-amber-400',
      label: 'ACCEPTED BY MERCHANT',
    };
  }
  return {
    type: 'warning',
    badge: 'bg-amber-50 text-amber-800 border border-amber-300',
    dot: 'bg-amber-400',
    borderHover: 'hover:border-amber-400',
    label: s === 'ai_negotiation_completed' ? 'PENDING AGREEMENT' : s.toUpperCase(),
  };
}

export default function MerchantDashboard() {
  const [user, setUser] = useState<any>(null);
  const [merchantProfile, setMerchantProfile] = useState<any>(null);
  const [inventory, setInventory] = useState<any[]>([]);
  const [transactions, setTransactions] = useState<any[]>([]);
  const [orders, setOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  // Profile Edit State
  const [isEditingProfile, setIsEditingProfile] = useState(false);
  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [businessCategory, setBusinessCategory] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);

  // New Inventory Form State
  const [sku, setSku] = useState('');
  const [name, setName] = useState('');
  const [stock, setStock] = useState(100);
  const [basePrice, setBasePrice] = useState(1000);
  const [minMargin, setMinMargin] = useState(800);
  const [velocity, setVelocity] = useState(1.0);
  const [addingItem, setAddingItem] = useState(false);

  // Inventory Adjustment / Removal State
  const [selectedItemForAdjustment, setSelectedItemForAdjustment] = useState<any | null>(null);
  const [unitsToRemove, setUnitsToRemove] = useState<number>(1);
  const [deleteIfZero, setDeleteIfZero] = useState<boolean>(false);
  const [adjustingStock, setAdjustingStock] = useState<boolean>(false);
  const [adjustmentError, setAdjustmentError] = useState<string | null>(null);
  const [adjustmentSuccess, setAdjustmentSuccess] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
      if (!token) {
        setLoading(false);
        router.push('/auth');
        return;
      }

      const userData = await api.getMe();
      if (userData.role !== 'merchant') {
        if (userData.role === 'buyer') {
          router.replace('/buyer');
        } else {
          router.replace('/auth');
        }
        return;
      }
      setUser(userData);

      const [invData, txData, ordersData, merchants] = await Promise.all([
        api.getInventory().catch((e) => {
          console.warn('[Merchant Inventory Sync]', e);
          return [];
        }),
        api.getTransactions().catch((e) => {
          console.warn('[Merchant Transactions Sync]', e);
          return [];
        }),
        api.getOrders().catch(() => []),
        api.getMerchants().catch(() => []),
      ]);
      
      // Find own profile
      const myProfile = merchants.find((m: any) => m.user_id === userData.id);
      if (myProfile) {
        setMerchantProfile(myProfile);
        setDisplayName(myProfile.display_name || '');
        setDescription(myProfile.description || '');
        setContactEmail(myProfile.contact_email || '');
        setBusinessCategory(myProfile.business_category || '');
      }

      // Filter inventory to only this merchant's items
      const myInventory = invData.filter((i: any) => i.merchant_id === userData.id);
      setInventory(myInventory);
      setTransactions(txData);
      setOrders(ordersData);
    } catch (err: any) {
      console.error('[Merchant Data Sync Error]', err);
      // ONLY log out if the session is genuinely invalid (401 that could not be refreshed)
      if (err?.status === 401) {
        localStorage.removeItem('token');
        localStorage.removeItem('role');
        router.push('/auth');
      }
      // For network errors, timeouts, or temporary server issues: keep session active!
    } finally {
      setLoading(false);
    }
  }, [router]);

  const handleDashboardEvent = useCallback((event: RealtimeEvent) => {
    console.log('[Merchant Live Sync]', event.event_type, event.data);

    // Immediately update table row if transaction_id matches
    const targetTxId = event.transaction_id || event.data?.transaction_id;
    if (targetTxId) {
      setTransactions((prev) => {
        const idx = prev.findIndex((t) => t.id === targetTxId);
        if (idx >= 0) {
          const updated = [...prev];
          updated[idx] = {
            ...updated[idx],
            transaction_number: event.data.transaction_number ?? updated[idx].transaction_number,
            status: event.data.status ?? updated[idx].status,
            final_price: event.data.final_price ?? updated[idx].final_price,
            buyer_approved: event.data.buyer_approved !== undefined ? event.data.buyer_approved : updated[idx].buyer_approved,
            merchant_approved: event.data.merchant_approved !== undefined ? event.data.merchant_approved : updated[idx].merchant_approved,
          };
          return updated;
        }
        return prev;
      });
    }

    // Live update inventory on real-time event
    if (event.event_type === 'INVENTORY_UPDATED' && event.data?.inventory_id) {
      const { inventory_id, current_stock, reserved_stock, available_stock } = event.data;
      setInventory((prev) => prev.map((item) => {
        if (item.id === inventory_id) {
          const avail = available_stock !== undefined ? available_stock : (current_stock - (reserved_stock || 0));
          return {
            ...item,
            current_stock: current_stock ?? item.current_stock,
            reserved_stock: reserved_stock ?? item.reserved_stock,
            available_stock: avail,
          };
        }
        return item;
      }));
    } else if (event.event_type === 'INVENTORY_DELETED' && event.data?.inventory_id) {
      setInventory((prev) => prev.filter((item) => item.id !== event.data.inventory_id));
      if (selectedItemForAdjustment?.id === event.data.inventory_id) {
        setSelectedItemForAdjustment(null);
      }
    }

    // Refresh data in background
    fetchData();
  }, [fetchData, selectedItemForAdjustment]);

  const { status: wsStatus } = useDashboardRealtime({
    onEvent: handleDashboardEvent,
    onReconnect: fetchData,
  });

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleOpenAdjustModal = (item: any) => {
    const avail = item.available_stock !== undefined 
      ? item.available_stock 
      : (item.current_stock - (item.reserved_stock || 0));
    setSelectedItemForAdjustment(item);
    setUnitsToRemove(avail > 0 ? 1 : 0);
    setDeleteIfZero(false);
    setAdjustmentError(null);
    setAdjustmentSuccess(null);
  };

  const handleCloseAdjustModal = () => {
    setSelectedItemForAdjustment(null);
    setAdjustmentError(null);
    setAdjustmentSuccess(null);
  };

  const handleConfirmRemoval = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedItemForAdjustment) return;

    const avail = selectedItemForAdjustment.available_stock !== undefined 
      ? selectedItemForAdjustment.available_stock 
      : (selectedItemForAdjustment.current_stock - (selectedItemForAdjustment.reserved_stock || 0));

    if (unitsToRemove <= 0) {
      setAdjustmentError('Please specify a quantity greater than 0.');
      return;
    }

    if (unitsToRemove > avail) {
      setAdjustmentError(`Cannot remove ${unitsToRemove} units. Only ${avail} units are currently available.`);
      return;
    }

    setAdjustingStock(true);
    setAdjustmentError(null);
    try {
      const response = await api.removeInventory(selectedItemForAdjustment.id, {
        units_to_remove: unitsToRemove,
        delete_if_zero: deleteIfZero,
      });

      if (response.status === 'deleted') {
        setInventory(prev => prev.filter(i => i.id !== selectedItemForAdjustment.id));
        setAdjustmentSuccess('Listing successfully deleted from exchange.');
      } else {
        setInventory(prev => prev.map(i => (i.id === response.id ? response : i)));
        setAdjustmentSuccess(`Successfully removed ${unitsToRemove} units.`);
      }

      setTimeout(() => {
        handleCloseAdjustModal();
      }, 1000);
    } catch (err: any) {
      setAdjustmentError(err.message || 'Failed to remove inventory units.');
    } finally {
      setAdjustingStock(false);
    }
  };

  const handleDeleteListingDirect = async (item: any) => {
    if (!confirm(`Are you sure you want to permanently delete SKU ${item.sku} (${item.name}) from your listing?`)) {
      return;
    }
    try {
      await api.deleteInventory(item.id);
      setInventory(prev => prev.filter(i => i.id !== item.id));
      handleCloseAdjustModal();
    } catch (err: any) {
      alert(err.message || 'Failed to delete listing.');
    }
  };

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingProfile(true);
    try {
      const updated = await api.updateMerchantProfile({
        display_name: displayName,
        description,
        contact_email: contactEmail,
        business_category: businessCategory,
      });
      setMerchantProfile(updated);
      setIsEditingProfile(false);
      alert('Merchant profile updated successfully.');
    } catch (err: any) {
      alert(err.message || 'Failed to update merchant profile.');
    } finally {
      setSavingProfile(false);
    }
  };

  const handleAddInventory = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddingItem(true);
    try {
      const newItem = await api.addInventory({
        sku,
        name,
        current_stock: stock,
        base_price: basePrice,
        minimum_margin_limit: minMargin,
        demand_velocity: velocity,
      });
      setInventory([...inventory, newItem]);
      // Reset form
      setSku(''); 
      setName(''); 
      setStock(100); 
      setBasePrice(1000); 
      setMinMargin(800); 
      setVelocity(1.0);
    } catch (err: any) {
      alert(err.message || 'Failed to add item');
    } finally {
      setAddingItem(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    router.push('/');
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center font-mono text-xs uppercase tracking-wider text-[#000000] bg-[#ffffff]">
        Initializing Merchant Node Telemetry...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#ffffff] text-[#000000] p-6 md:p-8 max-w-7xl mx-auto">
      {/* Top Header matching Homepage System */}
      <header className="border-b border-[#000000]/10 pb-6 mb-8">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight uppercase text-[#000000]">
                Nexus B2B Exchange
              </h1>
              <span className="px-3 py-1 text-xs font-mono font-bold uppercase tracking-wider rounded-full border border-[#000000]/20 bg-slate-50 text-[#000000]">
                Wholesale Merchant Node
              </span>
              <div 
                role="status"
                aria-live="polite"
                aria-label={`Real-time stream status: ${wsStatus}`}
                className="flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono border border-slate-200 bg-white shadow-2xs"
              >
                <span className={`w-2 h-2 rounded-full motion-reduce:animate-none ${
                  wsStatus === 'connected' ? 'bg-emerald-500 animate-pulse' :
                  wsStatus === 'reconnecting' ? 'bg-amber-400 animate-ping' :
                  wsStatus === 'connecting' ? 'bg-amber-400 animate-pulse' :
                  'bg-slate-300'
                }`} />
                <span className="font-bold text-slate-700 tracking-wider">
                  {wsStatus === 'connected' ? 'STREAM ACTIVE' :
                   wsStatus === 'reconnecting' ? 'RECONNECTING...' :
                   wsStatus === 'connecting' ? 'CONNECTING...' : 'OFFLINE'}
                </span>
              </div>
            </div>
            <p className="text-slate-500 mt-1.5 font-mono text-xs">
              AUTHENTICATED ENTITY: <span className="font-bold text-[#000000]">{merchantProfile?.display_name || user?.username}</span> | MULTI-MERCHANT SOURCING NODE
            </p>
          </div>
          <div className="flex items-center gap-2.5">
            <button 
              onClick={() => setIsEditingProfile(!isEditingProfile)}
              className="px-4 py-2 min-h-[40px] inline-flex items-center justify-center text-xs font-bold font-mono tracking-wider uppercase rounded-full border border-[#000000] bg-[#ffffff] text-[#000000] hover:bg-[#e9e9e9] active:scale-[0.98] transition-all shadow-xs"
              aria-label={isEditingProfile ? 'Close business profile editor' : 'Edit business profile'}
            >
              {isEditingProfile ? 'Close Profile' : 'Edit Business Profile'}
            </button>
            <button 
              onClick={handleLogout} 
              className="px-4 py-2 min-h-[40px] inline-flex items-center justify-center text-xs font-bold font-mono tracking-wider uppercase rounded-full border border-[#000000] bg-[#000000] text-[#ffffff] hover:bg-[#000000]/85 active:scale-[0.98] transition-all shadow-xs"
              aria-label="Disconnect node and sign out"
            >
              Disconnect Node
            </button>
          </div>
        </div>
      </header>

      {/* Profile Edit Drawer / Form */}
      {isEditingProfile && (
        <section className="mb-8 p-6 bg-white rounded-2xl border border-slate-200/90 shadow-sm">
          <h2 className="text-lg font-extrabold uppercase tracking-tight text-[#000000] mb-4">
            Merchant Entity Profile Configuration
          </h2>
          <form onSubmit={handleUpdateProfile} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                Display Trading Name
              </label>
              <input
                type="text"
                required
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black bg-white"
                placeholder="e.g. Nexus Global Tech"
              />
            </div>
            <div>
              <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                Business Category
              </label>
              <input
                type="text"
                value={businessCategory}
                onChange={e => setBusinessCategory(e.target.value)}
                className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black bg-white"
                placeholder="e.g. Electronics, Components"
              />
            </div>
            <div>
              <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                Contact Email
              </label>
              <input
                type="email"
                value={contactEmail}
                onChange={e => setContactEmail(e.target.value)}
                className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black bg-white"
                placeholder="sales@merchant.com"
              />
            </div>
            <div>
              <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                Company Description
              </label>
              <input
                type="text"
                value={description}
                onChange={e => setDescription(e.target.value)}
                className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black bg-white"
                placeholder="Premium distributor of enterprise semiconductors..."
              />
            </div>
            <div className="md:col-span-2 flex justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={() => setIsEditingProfile(false)}
                className="px-4 py-2 text-xs font-mono font-bold uppercase tracking-wider rounded-full border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={savingProfile}
                className="px-5 py-2 text-xs font-mono font-bold uppercase tracking-wider rounded-full bg-black text-white hover:bg-black/85 transition-all shadow-xs"
              >
                {savingProfile ? 'Saving...' : 'Save Profile Changes'}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left Column: Inventory & Core Provisioning */}
        <div className="lg:col-span-2 space-y-8">
          
          {/* Active Inventory with Reserved Stock Tracking */}
          <section className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-xs relative">
            <div className="flex justify-between items-center mb-6 border-b border-slate-100 pb-4">
              <div>
                <h2 className="text-lg sm:text-xl font-extrabold uppercase tracking-tight text-[#000000]">
                  Merchant Inventory Listings
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Real-time warehouse stock & active buyer reservations
                </p>
              </div>
              <span className="text-xs font-mono px-3 py-1 bg-slate-50 border border-slate-200 text-[#000000] rounded-full font-bold uppercase tracking-wider">
                {inventory.length} Listed SKUs
              </span>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="text-[11px] text-slate-500 uppercase tracking-wider font-mono bg-slate-50">
                    <th className="p-3 rounded-l-lg">SKU / Product</th>
                    <th className="p-3">Total Stock</th>
                    <th className="p-3">Reserved</th>
                    <th className="p-3">Available</th>
                    <th className="p-3">Base Price</th>
                    <th className="p-3">Min Floor</th>
                    <th className="p-3 rounded-r-lg text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="text-sm divide-y divide-slate-100">
                  {inventory.map(item => {
                    const avail = item.available_stock !== undefined 
                      ? item.available_stock 
                      : (item.current_stock - (item.reserved_stock || 0));

                    return (
                      <tr key={item.id} className="hover:bg-slate-50/70 transition-colors">
                        <td className="p-3">
                          <div className="font-bold text-[#000000]">{item.name}</div>
                          <div className="text-xs font-mono text-slate-500">{item.sku}</div>
                        </td>
                        <td className="p-3 font-mono font-medium">{item.current_stock}</td>
                        <td className="p-3 font-mono">
                          {item.reserved_stock > 0 ? (
                            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold font-mono bg-amber-50 text-amber-800 border border-amber-200">
                              {item.reserved_stock} reserved
                            </span>
                          ) : (
                            <span className="text-slate-400 text-xs">0</span>
                          )}
                        </td>
                        <td className="p-3 font-mono">
                          <span className={`px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold ${
                            avail === 0 
                              ? 'bg-red-50 text-red-700 border border-red-200' 
                              : 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                          }`}>
                            {avail === 0 ? '0 (Out of Stock)' : `${avail} units`}
                          </span>
                        </td>
                        <td className="p-3 font-mono font-semibold text-[#000000]">
                          ₹{item.base_price.toLocaleString()}
                        </td>
                        <td className="p-3 font-mono text-slate-500 text-xs">
                          ₹{item.minimum_margin_limit.toLocaleString()}
                        </td>
                        <td className="p-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleOpenAdjustModal(item)}
                            className="px-3 py-1.5 rounded-full text-xs font-mono font-bold uppercase tracking-wider border border-[#000000]/20 bg-white text-[#000000] hover:bg-[#000000] hover:text-white hover:border-[#000000] transition-all shadow-2xs inline-flex items-center gap-1.5"
                            aria-label={`Adjust or remove stock for ${item.name}`}
                          >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            Adjust Stock
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {inventory.length === 0 && (
                    <tr>
                      <td colSpan={7} className="p-8 text-center text-slate-400 font-mono text-sm">
                        No inventory items provisioned yet. Use the form below to add listings.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

          </section>

          {/* Provision New Inventory Listing */}
          <section className="bg-white p-6 md:p-8 rounded-2xl border border-slate-200/90 shadow-xs">
            <h2 className="text-lg sm:text-xl font-extrabold uppercase tracking-tight text-[#000000] mb-1">
              Provision New Product Listing
            </h2>
            <p className="text-xs text-slate-500 font-mono mb-6 border-b border-slate-100 pb-3">
              Listing will be strictly associated with your merchant profile ({merchantProfile?.display_name || user?.username})
            </p>

            <form onSubmit={handleAddInventory} className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                  SKU Identifier
                </label>
                <input 
                  type="text" 
                  required 
                  value={sku} 
                  onChange={e => setSku(e.target.value)} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono" 
                  placeholder="e.g. PROD-GPU-5090" 
                />
              </div>
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                  Product Display Name
                </label>
                <input 
                  type="text" 
                  required 
                  value={name} 
                  onChange={e => setName(e.target.value)} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black" 
                  placeholder="NVIDIA RTX 5090 Enterprise GPU" 
                />
              </div>
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                  Warehouse Stock Units
                </label>
                <input 
                  type="number" 
                  required 
                  min="1" 
                  value={stock} 
                  onChange={e => setStock(parseInt(e.target.value) || 1)} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono" 
                />
              </div>
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                  Catalog Base Price (₹)
                </label>
                <input 
                  type="number" 
                  required 
                  min="1" 
                  value={basePrice} 
                  onChange={e => setBasePrice(parseFloat(e.target.value) || 1)} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono" 
                />
              </div>
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                  Strict Margin Floor (₹)
                </label>
                <input 
                  type="number" 
                  required 
                  min="1" 
                  value={minMargin} 
                  onChange={e => setMinMargin(parseFloat(e.target.value) || 1)} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono" 
                />
                <span className="text-[10px] text-slate-400 font-mono mt-1 block">
                  Agent will NEVER accept an offer below this floor
                </span>
              </div>
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-1.5">
                  Market Velocity Multiplier
                </label>
                <input 
                  type="number" 
                  required 
                  step="0.1" 
                  value={velocity} 
                  onChange={e => setVelocity(parseFloat(e.target.value) || 1.0)} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono" 
                />
              </div>
              <div className="md:col-span-2 pt-2">
                <button 
                  type="submit" 
                  disabled={addingItem} 
                  className="w-full py-3.5 bg-black hover:bg-black/85 text-white rounded-full font-bold font-mono text-xs uppercase tracking-wider transition-all disabled:opacity-50 min-h-[46px] shadow-xs"
                >
                  {addingItem ? 'Publishing Listing...' : 'Publish Product to Exchange →'}
                </button>
              </div>
            </form>
          </section>

          {/* Orders & Settlement Section */}
          <section className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-xs relative">
            <h2 className="text-lg sm:text-xl font-extrabold uppercase tracking-tight text-[#000000] mb-1">
              Confirmed Purchase Orders & Settlements
            </h2>
            <p className="text-xs text-slate-500 font-mono mb-4 border-b border-slate-100 pb-3">
              Direct Razorpay checkout orders fulfilled by your inventory
            </p>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="text-[11px] text-slate-500 uppercase tracking-wider font-mono bg-slate-50">
                    <th className="p-3 rounded-l-lg">Order ID</th>
                    <th className="p-3">Asset</th>
                    <th className="p-3">Volume</th>
                    <th className="p-3">Agreed Amount</th>
                    <th className="p-3">Razorpay Order ID</th>
                    <th className="p-3 rounded-r-lg">Status</th>
                  </tr>
                </thead>
                <tbody className="text-sm divide-y divide-slate-100">
                  {orders.map(order => (
                    <tr key={order.id} className="hover:bg-slate-50/70 transition-colors">
                      <td className="p-3 font-mono font-bold text-[#000000]">#{order.id}</td>
                      <td className="p-3">
                        <div className="font-bold text-xs text-[#000000]">{order.item_name || 'Listing'}</div>
                        <div className="text-[10px] font-mono text-slate-400">{order.item_sku}</div>
                      </td>
                      <td className="p-3 font-mono text-xs">{order.quantity} units</td>
                      <td className="p-3 font-mono font-semibold text-emerald-700 text-xs">
                        ₹{order.total_amount?.toLocaleString()}
                      </td>
                      <td className="p-3 font-mono text-[11px] text-slate-500">
                        {order.razorpay_order_id || 'Pending Gateway'}
                      </td>
                      <td className="p-3">
                        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono uppercase font-bold ${
                          order.payment_status === 'confirmed' 
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' 
                            : order.payment_status === 'failed' 
                              ? 'bg-red-50 text-red-700 border border-red-200' 
                              : 'bg-amber-50 text-amber-800 border border-amber-200'
                        }`}>
                          {order.payment_status || order.order_status}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {orders.length === 0 && (
                    <tr>
                      <td colSpan={6} className="p-6 text-center text-slate-400 font-mono text-sm">
                        No purchase orders placed yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

        </div>

        {/* Right Column: Negotiation Sessions & Dual Approval — STRICT 3-COLOR SYSTEM */}
        <div className="space-y-6">
          <section className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-xs h-full">
            <h2 className="text-lg sm:text-xl font-extrabold uppercase tracking-tight text-[#000000] mb-1">
              Incoming Deals
            </h2>
            <p className="text-xs text-slate-500 font-mono mb-4 border-b border-slate-100 pb-3">
              AI negotiations awaiting consensus & approval
            </p>
            
            <div className="space-y-3">
              {transactions.map(tx => {
                const statusCfg = getDealStatusConfig(tx.status, tx.buyer_approved, tx.merchant_approved);

                return (
                  <Link href={`/transaction/${tx.id}`} key={tx.id} className="block group">
                    <div className={`p-4 rounded-xl bg-white hover:bg-slate-50/80 border border-slate-200 ${statusCfg.borderHover} transition-all shadow-2xs hover:shadow-xs relative`}>
                      <div className="flex justify-between items-start mb-2">
                        <span className="text-xs font-mono font-bold text-[#000000]">
                          {tx.transaction_number || `TXN #${tx.id}`}
                        </span>
                        <span className={`text-[10px] uppercase font-mono tracking-wider px-2.5 py-0.5 rounded-full font-bold ${statusCfg.badge}`}>
                          {statusCfg.label}
                        </span>
                      </div>

                      <p className="text-xs font-mono text-slate-700 font-medium">
                        {tx.quantity}x {tx.sku}
                      </p>

                      {tx.final_price && (
                        <div className="flex justify-between items-center text-xs font-mono mt-2.5 pt-2 border-t border-slate-100">
                          <span className="text-slate-500">Agreed Settlement:</span>
                          <span className="font-bold text-[#000000]">
                            ₹{(tx.final_price * tx.quantity).toLocaleString()}
                          </span>
                        </div>
                      )}

                      {tx.status === 'agreed' && tx.merchant_approved === 0 && (
                        <div className="mt-2.5 pt-2 border-t border-slate-100 flex items-center gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>
                          <span className="text-[10px] font-mono text-amber-800 font-bold uppercase tracking-wider">
                            Awaiting Your Approval
                          </span>
                        </div>
                      )}
                    </div>
                  </Link>
                );
              })}
              
              {transactions.length === 0 && (
                <div className="text-center p-8 border border-dashed border-slate-200 rounded-xl text-sm text-slate-400 font-mono">
                  No active negotiations detected for your inventory.
                </div>
              )}
            </div>
          </section>
        </div>

      </div>

      {/* Modal: Stock Removal & Listing Management */}
      {selectedItemForAdjustment && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs"
          role="dialog"
          aria-modal="true"
          aria-labelledby="modal-stock-title"
        >
          <div className="bg-white rounded-2xl border border-black shadow-2xl max-w-lg w-full p-6 md:p-8 space-y-6 relative overflow-hidden">
            {/* Header */}
            <div className="flex justify-between items-start border-b border-slate-100 pb-4">
              <div>
                <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500 font-bold">
                  Inventory Operations
                </span>
                <h3 id="modal-stock-title" className="text-xl font-extrabold uppercase tracking-tight text-[#000000] mt-0.5">
                  Adjust Listing Stock
                </h3>
                <p className="text-xs text-slate-500 font-mono mt-1">
                  SKU: <span className="font-semibold text-black">{selectedItemForAdjustment.sku}</span> | {selectedItemForAdjustment.name}
                </p>
              </div>
              <button
                type="button"
                onClick={handleCloseAdjustModal}
                className="p-1.5 rounded-full text-slate-400 hover:text-black hover:bg-slate-100 transition-colors"
                aria-label="Close modal"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Inventory Diagnostics Cards */}
            {(() => {
              const currentAvail = selectedItemForAdjustment.available_stock !== undefined 
                ? selectedItemForAdjustment.available_stock 
                : (selectedItemForAdjustment.current_stock - (selectedItemForAdjustment.reserved_stock || 0));
              const safeUnits = Math.min(currentAvail, Math.max(0, unitsToRemove || 0));
              const newAvail = Math.max(0, currentAvail - safeUnits);
              const willBeOutOfStock = newAvail === 0;

              return (
                <form onSubmit={handleConfirmRemoval} className="space-y-5">
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-center">
                      <div className="text-[10px] uppercase font-mono text-slate-500 font-bold">Total Warehouse</div>
                      <div className="text-xl font-bold font-mono text-black mt-1">
                        {selectedItemForAdjustment.current_stock}
                      </div>
                    </div>
                    <div className="p-3 bg-amber-50/70 rounded-xl border border-amber-200 text-center">
                      <div className="text-[10px] uppercase font-mono text-amber-800 font-bold">Active Reserved</div>
                      <div className="text-xl font-bold font-mono text-amber-900 mt-1">
                        {selectedItemForAdjustment.reserved_stock || 0}
                      </div>
                    </div>
                    <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-center">
                      <div className="text-[10px] uppercase font-mono text-slate-700 font-bold">Max Removable</div>
                      <div className="text-xl font-bold font-mono text-black mt-1">
                        {currentAvail}
                      </div>
                    </div>
                  </div>

                  {/* Units to remove input */}
                  <div>
                    <label className="block text-xs uppercase font-mono text-slate-700 font-bold mb-1.5">
                      Units to Remove from Listing
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min="1"
                        max={currentAvail}
                        value={unitsToRemove}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          setUnitsToRemove(isNaN(val) ? 0 : val);
                          setAdjustmentError(null);
                        }}
                        disabled={currentAvail === 0}
                        className="w-full py-2.5 px-3.5 text-base font-mono rounded-xl border border-slate-300 focus:outline-none focus:border-black focus:ring-1 focus:ring-black font-medium"
                        placeholder="Enter quantity to remove"
                        required
                      />
                    </div>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {[1, 5, 10].map(qty => (
                        qty <= currentAvail && (
                          <button
                            key={qty}
                            type="button"
                            onClick={() => setUnitsToRemove(qty)}
                            className="px-3 py-1 text-xs font-mono font-bold rounded-full border border-slate-200 hover:bg-slate-100 text-slate-700 transition-colors"
                          >
                            Remove {qty}
                          </button>
                        )
                      ))}
                      {currentAvail > 0 && (
                        <button
                          type="button"
                          onClick={() => setUnitsToRemove(currentAvail)}
                          className="px-3 py-1 text-xs font-mono font-bold rounded-full border border-black bg-black text-white hover:bg-black/85 transition-colors"
                        >
                          Remove All ({currentAvail})
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Projection Preview */}
                  <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-xs font-mono space-y-1.5">
                    <div className="flex justify-between text-slate-600">
                      <span>Projected Available Stock:</span>
                      <span className={`font-bold ${willBeOutOfStock ? 'text-red-600' : 'text-emerald-700'}`}>
                        {currentAvail} → {newAvail} units
                      </span>
                    </div>
                    <div className="flex justify-between text-slate-600">
                      <span>Projected Warehouse Stock:</span>
                      <span className="font-semibold text-black">
                        {selectedItemForAdjustment.current_stock} → {Math.max(0, selectedItemForAdjustment.current_stock - unitsToRemove)}
                      </span>
                    </div>
                    {willBeOutOfStock && (
                      <div className="pt-2 text-xs font-sans text-amber-900 bg-amber-50 p-3 rounded-xl border border-amber-200 flex items-start gap-2.5 mt-2">
                        <svg className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                        <span className="leading-relaxed">
                          <strong className="font-semibold">Out of Stock Notice:</strong> Removing {unitsToRemove} units will reduce available stock to <strong>0</strong>. Buyers will see this product marked as <em>Out of Stock</em> and will not be able to initiate new purchase bids.
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Delete if zero checkbox option (only if no active reservations) */}
                  {selectedItemForAdjustment.reserved_stock === 0 && (
                    <label className="flex items-start gap-2.5 text-xs text-slate-600 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={deleteIfZero}
                        onChange={(e) => setDeleteIfZero(e.target.checked)}
                        className="mt-0.5 rounded border-slate-300 text-black focus:ring-black"
                      />
                      <span>
                        Permanently delete this product listing if remaining stock becomes 0
                      </span>
                    </label>
                  )}

                  {/* Feedback alerts */}
                  {adjustmentError && (
                    <div className="p-3 text-xs bg-red-50 text-red-700 border border-red-200 rounded-xl font-mono">
                      {adjustmentError}
                    </div>
                  )}
                  {adjustmentSuccess && (
                    <div className="p-3 text-xs bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-xl font-mono">
                      {adjustmentSuccess}
                    </div>
                  )}

                  {/* Actions */}
                  <div className="flex items-center justify-between pt-2 border-t border-slate-100">
                    {selectedItemForAdjustment.reserved_stock === 0 ? (
                      <button
                        type="button"
                        onClick={() => handleDeleteListingDirect(selectedItemForAdjustment)}
                        className="text-xs font-mono font-bold text-red-600 hover:text-red-800 uppercase tracking-wider underline transition-colors"
                      >
                        Delete Listing
                      </button>
                    ) : (
                      <span className="text-[11px] font-mono text-slate-400">
                        ({selectedItemForAdjustment.reserved_stock} reserved — deletion locked)
                      </span>
                    )}

                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={handleCloseAdjustModal}
                        className="px-4 py-2 text-xs font-mono font-bold uppercase tracking-wider rounded-full border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={adjustingStock || unitsToRemove <= 0 || unitsToRemove > currentAvail}
                        className="px-5 py-2 text-xs font-mono font-bold uppercase tracking-wider rounded-full bg-black text-white hover:bg-black/85 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-xs"
                      >
                        {adjustingStock ? 'Applying...' : `Confirm Removal (${unitsToRemove})`}
                      </button>
                    </div>
                  </div>
                </form>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}

