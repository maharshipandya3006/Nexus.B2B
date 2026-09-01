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

export default function BuyerDashboard() {
  const [user, setUser] = useState<any>(null);
  const [inventory, setInventory] = useState<any[]>([]);
  const [transactions, setTransactions] = useState<any[]>([]);
  const [orders, setOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  // Procurement Form State
  const [procureMode, setProcureMode] = useState<'targeted' | 'multi'>('targeted');
  const [selectedInventoryId, setSelectedInventoryId] = useState<number | null>(null);
  const [selectedSku, setSelectedSku] = useState('');
  const [quantity, setQuantity] = useState(10);
  const [budget, setBudget] = useState(0);
  const [negotiating, setNegotiating] = useState(false);
  const [multiOffers, setMultiOffers] = useState<any>(null);

  // Filters
  const [merchantFilter, setMerchantFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  const fetchData = useCallback(async () => {
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
      if (!token) {
        setLoading(false);
        router.push('/auth');
        return;
      }

      const userData = await api.getMe();
      if (userData.role !== 'buyer') {
        if (userData.role === 'merchant') {
          router.replace('/merchant');
        } else {
          router.replace('/auth');
        }
        return;
      }
      setUser(userData);

      const [invData, txData, ordersData] = await Promise.all([
        api.getInventory().catch((e) => {
          console.warn('[Buyer Inventory Sync]', e);
          return [];
        }),
        api.getTransactions().catch((e) => {
          console.warn('[Buyer Transactions Sync]', e);
          return [];
        }),
        api.getOrders().catch(() => []),
      ]);
      
      setInventory(invData);
      // Strictly maintain user's active product selection across background syncs
      // Prod M4 Chip should only be selected when explicitly chosen by the buyer
      setSelectedInventoryId((prevId) => {
        if (!prevId) return null;
        const exists = invData.some((item: any) => item.id === prevId);
        return exists ? prevId : null;
      });
      setSelectedSku((prevSku) => {
        if (!prevSku) return '';
        const exists = invData.some((item: any) => item.sku === prevSku);
        return exists ? prevSku : '';
      });
      setTransactions(txData);
      setOrders(ordersData);
    } catch (err: any) {
      console.error('[Buyer Data Sync Error]', err);
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
    console.log('[Buyer Live Sync]', event.event_type, event.data);

    // Instantly update transactions table if transaction_id matches
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

    // Instantly update catalog listing if inventory changed
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
      setSelectedInventoryId((currId) => (currId === event.data.inventory_id ? null : currId));
    }

    // Refresh data in background
    fetchData();
  }, [fetchData]);


  const { status: wsStatus } = useDashboardRealtime({
    onEvent: handleDashboardEvent,
    onReconnect: fetchData,
  });

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Unique list of merchants for filter
  const merchantsList = Array.from(
    new Set(inventory.map(i => i.merchant_name || i.wholesaler_name))
  ).filter(Boolean);

  // Filtered inventory
  const filteredInventory = inventory.filter(item => {
    const matchesMerchant = merchantFilter === 'all' || 
      (item.merchant_name === merchantFilter || item.wholesaler_name === merchantFilter);
    const matchesSearch = item.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
      item.sku.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesMerchant && matchesSearch;
  });

  const handleSelectListing = (item: any) => {
    setSelectedInventoryId(item.id);
    setSelectedSku(item.sku);
    if (item.base_price) {
      setBudget(item.base_price);
    }
    setProcureMode('targeted');
    // Scroll to procurement form
    document.getElementById('procurement-console')?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleProcure = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSku || negotiating) return;
    setNegotiating(true);
    setMultiOffers(null);
    
    try {
      if (procureMode === 'targeted') {
        if (!selectedInventoryId) {
          throw new Error('Please select a specific merchant inventory listing.');
        }
        const response = await api.initiateNegotiation({
          sku: selectedSku,
          quantity: quantity,
          buyer_max_budget: budget,
          inventory_id: selectedInventoryId,
        });
        
        if (response && response.transaction_id) {
          setNegotiating(false);
          // Navigate to the transaction view
          router.push(`/transaction/${response.transaction_id}`);
        } else {
          throw new Error('Negotiation response did not return a valid transaction ID.');
        }
      } else {
        // Multi-merchant parallel negotiation
        const response = await api.initiateMultiNegotiation({
          sku: selectedSku,
          quantity: quantity,
          buyer_max_budget: budget,
        });
        setMultiOffers(response);
      }
    } catch (err: any) {
      alert(err.message || 'Negotiation protocol failed to initialize');
    } finally {
      setNegotiating(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    router.push('/');
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-xs font-mono uppercase tracking-wider text-[#000000] bg-[#ffffff]">
        Connecting to Nexus Procurement Hub...
      </div>
    );
  }

  const selectedItem = inventory.find(i => i.id === selectedInventoryId);

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
                Buyer Procurement Node
              </span>
              <div 
                role="status"
                aria-live="polite"
                aria-label={`Real-time stream status: ${wsStatus}`}
                className="flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono border border-slate-200 bg-white shadow-2xs"
              >
                <span className={`w-2 h-2 rounded-full motion-reduce:animate-none ${
                  wsStatus === 'connected' ? 'bg-emerald-500 animate-pulse' :
                  wsStatus === 'reconnecting' || wsStatus === 'connecting' ? 'bg-amber-400 animate-ping' :
                  'bg-slate-300'
                }`} />
                <span className="font-bold text-slate-700 tracking-wider">
                  {wsStatus === 'connected' ? 'STREAM ACTIVE' : wsStatus === 'reconnecting' ? 'RECONNECTING...' : 'OFFLINE'}
                </span>
              </div>
            </div>
            <p className="text-slate-500 mt-1.5 font-mono text-xs">
              AUTHENTICATED NODE: <span className="font-bold text-[#000000]">{user?.username}</span> | MULTI-MERCHANT AUTONOMOUS SOURCING
            </p>
          </div>
          <div className="flex items-center gap-2.5">
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left Column: Market Catalog & Procurement Console */}
        <div className="lg:col-span-2 space-y-8">
          
          {/* Inventory Catalog with Explicit Merchant Ownership */}
          <section className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-xs relative">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6 border-b border-slate-100 pb-4">
              <div>
                <h2 className="text-lg sm:text-xl font-extrabold uppercase tracking-tight text-[#000000]">
                  Global Wholesale Catalog
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Real-time stock with verified merchant provenance
                </p>
              </div>

              {/* Filters */}
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  placeholder="Search SKU or name..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  className="py-1.5 px-3 text-xs rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black w-44 font-mono"
                />
                <select
                  value={merchantFilter}
                  onChange={e => setMerchantFilter(e.target.value)}
                  className="py-1.5 px-3 text-xs rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono text-slate-700 bg-white"
                >
                  <option value="all">All Merchants</option>
                  {merchantsList.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="text-[11px] text-slate-500 uppercase tracking-wider font-mono bg-slate-50">
                    <th className="p-3 rounded-l-lg">Product Listing</th>
                    <th className="p-3">Verified Merchant</th>
                    <th className="p-3">Stock Available</th>
                    <th className="p-3">Base Price</th>
                    <th className="p-3 rounded-r-lg text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="text-sm divide-y divide-slate-100">
                  {filteredInventory.map(item => {
                    const isSelected = selectedInventoryId === item.id;
                    const avail = item.available_stock !== undefined 
                      ? item.available_stock 
                      : (item.current_stock - (item.reserved_stock || 0));

                    return (
                      <tr 
                        key={item.id} 
                        className={`transition-colors ${isSelected ? 'bg-slate-50' : 'hover:bg-slate-50/70'}`}
                      >
                        <td className="p-3">
                          <div className="font-bold text-[#000000]">{item.name}</div>
                          <div className="text-xs font-mono text-slate-500">{item.sku}</div>
                        </td>
                        <td className="p-3">
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-medium bg-slate-50 text-black border border-slate-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-black"></span>
                            {item.merchant_name || item.wholesaler_name}
                          </span>
                        </td>
                        <td className="p-3">
                          <div className="font-mono text-xs">
                            <span className={`px-2.5 py-0.5 rounded-full font-semibold ${
                              avail === 0 ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                            }`}>
                              {avail > 0 ? `${avail} units` : 'OUT OF STOCK'}
                            </span>
                            {item.reserved_stock > 0 && (
                              <span className="text-[10px] text-amber-700 font-mono block mt-0.5">
                                ({item.reserved_stock} reserved)
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="p-3 font-mono font-semibold text-[#000000]">
                          ₹{item.base_price.toLocaleString()}
                        </td>
                        <td className="p-3 text-right">
                          <button
                            onClick={() => handleSelectListing(item)}
                            disabled={avail === 0}
                            className={`px-3 py-1.5 rounded-full text-xs font-mono font-bold uppercase tracking-wider transition-all ${
                              isSelected
                                ? 'bg-black text-white'
                                : 'border border-[#000000]/20 bg-white text-[#000000] hover:bg-[#000000] hover:text-white'
                            } disabled:opacity-30 disabled:cursor-not-allowed shadow-2xs`}
                          >
                            {isSelected ? 'Selected' : 'Select'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {filteredInventory.length === 0 && (
                    <tr>
                      <td colSpan={5} className="p-8 text-center text-slate-400 font-mono text-sm">
                        No inventory listings match your filter criteria.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* Procurement Deployment Console */}
          <section id="procurement-console" className="bg-white p-6 md:p-8 rounded-2xl border border-slate-200/90 shadow-xs relative">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6 border-b border-slate-100 pb-4">
              <div>
                <h2 className="text-lg sm:text-xl font-extrabold uppercase tracking-tight text-[#000000]">
                  Deploy AI Procurement Agent
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Autonomous negotiation protocol governed by strict margin bounds
                </p>
              </div>

              {/* Mode Toggle */}
              <div className="flex items-center bg-slate-100 p-1 rounded-full border border-slate-200">
                <button
                  type="button"
                  onClick={() => setProcureMode('targeted')}
                  className={`px-3.5 py-1.5 text-xs font-mono font-bold uppercase tracking-wider rounded-full transition-all ${
                    procureMode === 'targeted'
                      ? 'bg-black text-white shadow-xs'
                      : 'text-slate-600 hover:text-black'
                  }`}
                >
                  Single Merchant Listing
                </button>
                <button
                  type="button"
                  onClick={() => setProcureMode('multi')}
                  className={`px-3.5 py-1.5 text-xs font-mono font-bold uppercase tracking-wider rounded-full transition-all ${
                    procureMode === 'multi'
                      ? 'bg-black text-white shadow-xs'
                      : 'text-slate-600 hover:text-black'
                  }`}
                >
                  Multi-Merchant Quote (Compare)
                </button>
              </div>
            </div>

            {/* Target Summary Banner */}
            {procureMode === 'targeted' && selectedItem && (
              <div className="mb-6 p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-wrap items-center justify-between gap-4">
                <div>
                  <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 font-bold">Target Listing</span>
                  <div className="font-bold text-[#000000]">{selectedItem.name} ({selectedItem.sku})</div>
                  <div className="text-xs font-mono text-slate-600">
                    Seller: <span className="font-semibold text-black">{selectedItem.merchant_name || selectedItem.wholesaler_name}</span> (ID #{selectedItem.id})
                  </div>
                </div>
                <div className="text-right font-mono">
                  <div className="text-xs text-slate-500">Catalog Price: ₹{selectedItem.base_price.toLocaleString()}</div>
                  <div className="text-xs text-emerald-700 font-semibold">Available: {selectedItem.available_stock ?? selectedItem.current_stock} units</div>
                </div>
              </div>
            )}

            {procureMode === 'targeted' && !selectedItem && (
              <div className="mb-6 p-4 rounded-xl bg-slate-50 border border-dashed border-slate-300 flex items-center justify-between gap-4">
                <div className="text-xs font-mono text-slate-500">
                  No product currently selected. Select any product from the catalog table above or choose an asset from the dropdown below to configure your bid.
                </div>
              </div>
            )}

            {procureMode === 'multi' && (
              <div className="mb-6 p-4 rounded-xl bg-slate-50 border border-slate-200">
                <span className="text-[10px] font-mono uppercase tracking-wider text-black font-bold">
                  Parallel Multi-Merchant Bidding Enabled
                </span>
                <p className="text-xs text-slate-700 mt-1">
                  Our orchestrator will dispatch parallel AI negotiation agents to ALL merchants who stock <span className="font-mono font-bold text-black">{selectedSku || 'the selected asset'}</span>. You can then review and accept the best quote.
                </p>
              </div>
            )}

            <form onSubmit={handleProcure} className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-2">
                  Target Product (SKU)
                </label>
                <select 
                  value={selectedSku} 
                  onChange={e => {
                    const newSku = e.target.value;
                    setSelectedSku(newSku);
                    const matching = inventory.find(i => i.sku === newSku);
                    if (matching) {
                      setSelectedInventoryId(matching.id);
                      if (matching.base_price) setBudget(matching.base_price);
                    } else {
                      setSelectedInventoryId(null);
                    }
                  }} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono text-[#000000] bg-white"
                  required
                >
                  {!selectedSku && (
                    <option value="" disabled>-- Select a Product SKU --</option>
                  )}
                  {Array.from(new Set(inventory.map(i => i.sku))).map(skuVal => {
                    const item = inventory.find(i => i.sku === skuVal);
                    return (
                      <option key={skuVal} value={skuVal}>
                        {skuVal} — {item?.name}
                      </option>
                    );
                  })}
                </select>
              </div>

              {procureMode === 'targeted' && (
                <div>
                  <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-2">
                    Merchant Listing
                  </label>
                  <select 
                    value={selectedInventoryId || ''} 
                    onChange={e => {
                      const newId = parseInt(e.target.value);
                      setSelectedInventoryId(newId);
                      const matching = inventory.find(i => i.id === newId);
                      if (matching && matching.base_price) {
                        setBudget(matching.base_price);
                      }
                    }} 
                    className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono text-[#000000] bg-white"
                    required
                  >
                    {!selectedInventoryId && (
                      <option value="" disabled>-- Select Merchant Listing --</option>
                    )}
                    {inventory.filter(i => i.sku === selectedSku).map(listing => (
                      <option key={listing.id} value={listing.id}>
                        {listing.merchant_name || listing.wholesaler_name} (₹{listing.base_price.toLocaleString()})
                      </option>
                    ))}
                  </select>
                </div>
              )}
              
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-2">
                  Volume (Units)
                </label>
                <input 
                  type="number" 
                  required 
                  min="1" 
                  value={quantity} 
                  onChange={e => setQuantity(parseInt(e.target.value) || 1)} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono text-[#000000]" 
                />
              </div>
              
              <div>
                <label className="block text-xs uppercase font-bold font-mono tracking-wider text-slate-700 mb-2">
                  Buyer Max Budget (₹/Unit)
                </label>
                <input 
                  type="number" 
                  required 
                  min="1" 
                  value={budget || ''} 
                  onChange={e => setBudget(parseFloat(e.target.value) || 0)} 
                  className="w-full py-2.5 px-3.5 text-sm rounded-xl border border-slate-300 focus:border-black focus:ring-1 focus:ring-black font-mono text-[#000000]" 
                  placeholder={selectedItem ? `e.g. ${selectedItem.base_price}` : "e.g. 21000"}
                />
              </div>

              <div className="md:col-span-3 pt-2">
                <button 
                  type="submit" 
                  disabled={negotiating || !selectedSku || (procureMode === 'targeted' && !selectedInventoryId)} 
                  className="w-full py-3.5 bg-black hover:bg-black/85 text-white rounded-full font-bold font-mono text-xs uppercase tracking-wider transition-all shadow-xs disabled:opacity-50 disabled:cursor-not-allowed min-h-[46px]"
                >
                  {negotiating 
                    ? 'Negotiation Agents Running In Real-Time...' 
                    : !selectedSku 
                      ? 'Select A Product Above To Begin'
                      : (procureMode === 'targeted' 
                          ? `Initiate Target Negotiation with Seller (${selectedItem?.name || selectedSku}) →` 
                          : `Launch Parallel Multi-Merchant Auction for ${selectedSku} →`)}
                </button>
              </div>
            </form>

            {/* Multi-Merchant Comparison Cards */}
            {multiOffers && (
              <div className="mt-8 pt-6 border-t border-slate-200">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-lg font-extrabold uppercase tracking-tight text-[#000000]">
                    Negotiated Merchant Quotes ({multiOffers.offers.length} Sellers)
                  </h3>
                  <span className="text-xs font-mono text-slate-500">Asset: {multiOffers.sku}</span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {multiOffers.offers.map((offer: any) => {
                    const isBest = offer.transaction_id === multiOffers.best_offer_transaction_id;
                    const statusCfg = getDealStatusConfig(offer.status);

                    return (
                      <div 
                        key={offer.transaction_id}
                        className={`p-5 rounded-2xl border relative transition-all bg-white ${
                          isBest 
                            ? 'border-emerald-500 ring-1 ring-emerald-500 shadow-sm' 
                            : 'border-slate-200 hover:border-slate-300 shadow-2xs'
                        }`}
                      >
                        {isBest && (
                          <span className="absolute -top-3 right-4 px-2.5 py-0.5 bg-black text-white font-mono text-[10px] font-bold rounded-full uppercase tracking-wider shadow-xs">
                            BEST QUOTE
                          </span>
                        )}

                        <div className="flex justify-between items-start mb-2">
                          <div>
                            <div className="font-bold text-[#000000]">{offer.merchant_name}</div>
                            <div className="text-xs text-slate-400 font-mono">
                              Merchant #{offer.merchant_id} {offer.transaction_number && `• ${offer.transaction_number}`}
                            </div>
                          </div>
                          <span className={`px-2.5 py-0.5 rounded-full text-xs font-mono uppercase font-bold ${statusCfg.badge}`}>
                            {statusCfg.label}
                          </span>
                        </div>

                        <div className="my-4 py-3 border-y border-slate-100 font-mono">
                          <div className="flex justify-between text-xs text-slate-500">
                            <span>Negotiated Unit Price:</span>
                            <span className="font-bold text-base text-[#000000]">
                              {offer.final_price ? `₹${offer.final_price.toLocaleString()}` : 'No Deal'}
                            </span>
                          </div>
                          {offer.final_price && (
                            <div className="flex justify-between text-xs text-slate-500 mt-1">
                              <span>Total ({quantity} units):</span>
                              <span className="font-semibold text-emerald-700">
                                ₹{(offer.final_price * quantity).toLocaleString()}
                              </span>
                            </div>
                          )}
                        </div>

                        <div className="flex gap-2">
                          <Link 
                            href={`/transaction/${offer.transaction_id}`}
                            className={`w-full py-2.5 text-center text-xs font-bold font-mono rounded-full transition-all uppercase tracking-wider ${
                              isBest 
                                ? 'bg-black hover:bg-black/85 text-white shadow-xs' 
                                : 'border border-black text-black hover:bg-slate-100'
                            }`}
                          >
                            Review & Accept Deal →
                          </Link>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </section>

        </div>

        {/* Right Column: Procurement History & Deals — STRICT 3-COLOR SYSTEM */}
        <div className="space-y-6">
          <section className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-xs h-full">
            <h2 className="text-lg sm:text-xl font-extrabold uppercase tracking-tight text-[#000000] mb-1">
              Procurement History
            </h2>
            <p className="text-xs text-slate-500 font-mono mb-4 border-b border-slate-100 pb-3">
              Audited merchant negotiations & settlements
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

                      {/* Explicit Merchant Tag */}
                      <div className="text-xs font-mono text-slate-600 mb-1">
                        Seller: <span className="font-semibold text-black">{tx.merchant_name || 'Assigned Merchant'}</span>
                      </div>

                      <p className="text-xs font-mono text-slate-700 font-medium">
                        {tx.quantity}x {tx.sku}
                      </p>

                      {tx.final_price && (
                        <div className="flex justify-between items-center text-xs font-mono mt-2.5 pt-2 border-t border-slate-100">
                          <span className="text-slate-500">Total Settlement:</span>
                          <span className="font-bold text-[#000000]">
                            ₹{(tx.final_price * tx.quantity).toLocaleString()}
                          </span>
                        </div>
                      )}
                    </div>
                  </Link>
                );
              })}
              
              {transactions.length === 0 && (
                <div className="text-center p-8 border border-dashed border-slate-200 rounded-xl text-sm text-slate-400 font-mono">
                  No procurement sessions initiated yet.
                </div>
              )}
            </div>
          </section>
        </div>

      </div>
    </div>
  );
}
