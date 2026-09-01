'use client';

import { useEffect, useState, use, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api, Quote } from '@/lib/api';
import { useTransactionRealtime, RealtimeEvent } from '@/lib/useRealtime';
import Link from 'next/link';
import Script from 'next/script';

// Helper to decode role from localStorage
function getRole() {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('role');
  }
  return null;
}

export default function TransactionView({ params }: { params: Promise<{ id: string }> }) {
  const [transaction, setTransaction] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [error, setError] = useState('');
  const [checkoutResult, setCheckoutResult] = useState<any>(null);
  const [activeOrder, setActiveOrder] = useState<any>(null);
  
  // Revised Quote State
  const [showRevisionForm, setShowRevisionForm] = useState(false);
  const [revisedPrice, setRevisedPrice] = useState('');
  const [revisionNote, setRevisionNote] = useState('');
  const [revisionSubmitting, setRevisionSubmitting] = useState(false);
  const [quoteActionLoading, setQuoteActionLoading] = useState(false);

  const [upsellOffer, setUpsellOffer] = useState<any>(null);
  const [upsellLoading, setUpsellLoading] = useState(false);
  const [approveLoading, setApproveLoading] = useState(false);
  
  const router = useRouter();
  const resolvedParams = use(params);
  const txId = parseInt(resolvedParams.id);

  const fetchTransactionData = useCallback(async () => {
    try {
      const tx = await api.getTransaction(txId);
      if (!tx) {
        setError('Transaction not found or access denied.');
        setLoading(false);
        return;
      }
      setTransaction(tx);
      
      const txLogs = await api.getTransactionLogs(txId).catch(() => []);
      setLogs(txLogs);

      const quoteHistory = await api.getQuoteHistory(txId).catch(() => []);
      setQuotes(quoteHistory);

      // Check if an order already exists for this negotiation
      const orders = await api.getOrders().catch(() => []);
      const matchingOrder = orders.find((o: any) => o.negotiation_id === txId);
      if (matchingOrder) {
        setActiveOrder(matchingOrder);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch transaction data.');
    } finally {
      setLoading(false);
    }
  }, [txId]);

  // Real-Time Event Handler: Instant UI synchronization across buyer & merchant
  const handleRealtimeEvent = useCallback((event: RealtimeEvent) => {
    console.log('[Live Sync]', event.event_type, event.data);

    // 1. Immediately mutate transaction state in memory
    setTransaction((prev: any) => {
      if (!prev) return prev;
      return {
        ...prev,
        status: event.data.status ?? prev.status,
        final_price: event.data.final_price !== undefined ? event.data.final_price : prev.final_price,
        buyer_approved: event.data.buyer_approved !== undefined ? event.data.buyer_approved : prev.buyer_approved,
        merchant_approved: event.data.merchant_approved !== undefined ? event.data.merchant_approved : prev.merchant_approved,
        agreed_quote_id: event.data.agreed_quote_id ?? prev.agreed_quote_id,
      };
    });

    // 2. Immediately update quotes state if quote was supplied
    if (event.data.quote) {
      const newOrUpdated = event.data.quote;
      setQuotes((prev) => {
        const idx = prev.findIndex((q) => q.id === newOrUpdated.id);
        if (idx >= 0) {
          const clone = [...prev];
          clone[idx] = newOrUpdated;
          return clone;
        }
        return [...prev, newOrUpdated];
      });
    }

    // 3. Re-sync full database state seamlessly in background
    fetchTransactionData();
  }, [fetchTransactionData]);

  // Connect WebSocket channel for this transaction
  const { status: wsStatus } = useTransactionRealtime(txId, {
    onEvent: handleRealtimeEvent,
    onReconnect: fetchTransactionData,
  });

  useEffect(() => {
    fetchTransactionData();
  }, [fetchTransactionData]);

  // Load upsell offer when agreed
  useEffect(() => {
    if ((transaction?.status === 'agreed' || transaction?.status === 'quote_agreed') && getRole() === 'buyer' && !upsellOffer && !upsellLoading) {
      setUpsellLoading(true);
      api.getUpsellOffer(txId)
        .then(offer => setUpsellOffer(offer))
        .catch(err => console.error("Failed to load upsell", err))
        .finally(() => setUpsellLoading(false));
    }
  }, [transaction?.status, txId]);

  // Dual Approval Handler
  const handleApprove = async () => {
    setApproveLoading(true);
    setError('');
    try {
      await api.approveTransaction(txId);
      await fetchTransactionData();
    } catch (err: any) {
      setError(err.message || 'Failed to approve transaction.');
    } finally {
      setApproveLoading(false);
    }
  };

  // Revised Quote: Propose
  const handleProposeRevision = async (e: React.FormEvent) => {
    e.preventDefault();
    const priceNum = parseFloat(revisedPrice);
    if (isNaN(priceNum) || priceNum <= 0) {
      setError('Please enter a valid positive quote price.');
      return;
    }

    setRevisionSubmitting(true);
    setError('');
    try {
      await api.proposeQuoteRevision(txId, {
        amount: priceNum,
        note: revisionNote.trim() || undefined,
      });
      setShowRevisionForm(false);
      setRevisedPrice('');
      setRevisionNote('');
      await fetchTransactionData();
    } catch (err: any) {
      setError(err.message || 'Failed to submit revised quote.');
    } finally {
      setRevisionSubmitting(false);
    }
  };

  // Revised Quote: Accept
  const handleAcceptQuote = async (quoteId: number) => {
    setQuoteActionLoading(true);
    setError('');
    try {
      await api.acceptQuote(txId, quoteId);
      await fetchTransactionData();
    } catch (err: any) {
      setError(err.message || 'Failed to accept revised quote.');
    } finally {
      setQuoteActionLoading(false);
    }
  };

  // Revised Quote: Reject
  const handleRejectQuote = async (quoteId: number) => {
    setQuoteActionLoading(true);
    setError('');
    try {
      await api.rejectQuote(txId, quoteId);
      await fetchTransactionData();
    } catch (err: any) {
      setError(err.message || 'Failed to reject revised quote.');
    } finally {
      setQuoteActionLoading(false);
    }
  };

  // Terminate Transaction (State 9)
  const [terminateLoading, setTerminateLoading] = useState(false);
  const handleTerminate = async () => {
    if (!confirm('Are you sure you want to terminate this negotiation session? This action is permanent.')) return;
    setTerminateLoading(true);
    setError('');
    try {
      await api.terminateTransaction(txId);
      await fetchTransactionData();
    } catch (err: any) {
      setError(err.message || 'Failed to terminate transaction.');
    } finally {
      setTerminateLoading(false);
    }
  };

  // Secure Settlement Flow (Razorpay Checkout)
  const handleCheckout = async () => {
    setCheckoutLoading(true);
    setError('');
    setCheckoutResult(null);

    try {
      // 1. Create or retrieve internal Order (reserves inventory)
      let order = activeOrder;
      if (!order || order.order_status === 'pending') {
        order = await api.createOrder(txId);
        setActiveOrder(order);
      }

      // 2. Initiate Razorpay Checkout configuration from backend
      const checkoutConfig = await api.initiateCheckout(order.id);

      // 3. Launch Razorpay Checkout modal
      if (typeof window !== 'undefined' && (window as any).Razorpay) {
        const options = {
          key: checkoutConfig.razorpay_key_id,
          amount: checkoutConfig.amount,
          currency: checkoutConfig.currency,
          name: checkoutConfig.merchant_name || 'Project Nexus',
          description: `Order #${checkoutConfig.order_id} - ${checkoutConfig.item_name} (${checkoutConfig.item_sku})`,
          order_id: checkoutConfig.razorpay_order_id,
          notes: {
            merchant_name: checkoutConfig.merchant_name,
            order_id: checkoutConfig.order_id.toString(),
            item_sku: checkoutConfig.item_sku,
          },
          handler: async function (response: any) {
            try {
              // 4. Server-Side Verification: Cryptographic verification of payment signature
              await api.verifyPayment({
                order_id: checkoutConfig.order_id,
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
              });

              setCheckoutResult({
                success: true,
                payment_id: response.razorpay_payment_id,
                order_id: checkoutConfig.order_id,
                merchant_name: checkoutConfig.merchant_name,
                message: 'Payment verified and confirmed by Razorpay. Inventory deducted and assigned to buyer account.',
              });

              await fetchTransactionData();
            } catch (err: any) {
              setError(err.message || 'Payment verification failed.');
            } finally {
              setCheckoutLoading(false);
            }
          },
          modal: {
            ondismiss: function () {
              setCheckoutLoading(false);
            },
          },
          theme: {
            color: '#012652',
          },
        };

        const rzp = new (window as any).Razorpay(options);
        rzp.on('payment.failed', function (response: any) {
          setError(response.error.description || 'Payment was declined or cancelled.');
          setCheckoutLoading(false);
        });
        rzp.open();
      } else {
        // Fallback for environment without live checkout script: run sandbox test
        const mockRes = await api.mockCheckout(order.id);
        await api.verifyPayment({
          order_id: order.id,
          razorpay_order_id: mockRes.razorpay_order_id,
          razorpay_payment_id: mockRes.razorpay_payment_id,
          razorpay_signature: mockRes.razorpay_signature,
        });

        setCheckoutResult({
          success: true,
          payment_id: mockRes.razorpay_payment_id,
          order_id: order.id,
          merchant_name: checkoutConfig.merchant_name,
          message: 'Sandbox Payment verified and captured. Inventory updated.',
        });

        await fetchTransactionData();
        setCheckoutLoading(false);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to initialize settlement.');
      setCheckoutLoading(false);
    }
  };

  // Tampering Simulation
  const handleTamperedCheckout = async () => {
    setCheckoutLoading(true);
    setError('');
    setCheckoutResult(null);
    try {
      const result = await api.mockTamperedCheckout(txId);
      setCheckoutResult(result);
    } catch (err: any) {
      setError(err.message || 'Checkout protocol failed: Cryptographic mandate mismatch (Tampering detected and blocked by Razorpay gatekeeper).');
      await fetchTransactionData();
    } finally {
      setCheckoutLoading(false);
    }
  };

  const role = getRole();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center font-mono text-xl text-[#012652]">
        Decrypting Negotiation Stream...
      </div>
    );
  }

  const isPaid = transaction?.status === 'paid' || transaction?.status === 'completed' || activeOrder?.payment_status === 'confirmed';
  
  // Revised quote proposed manually that is awaiting counter-party decision
  const activePendingRevision = quotes.find(q => q.status === 'pending' && q.source !== 'ai_negotiation');
  const isRevisionProposer = (activePendingRevision?.proposed_by === 'BUYER' && role === 'buyer') ||
                             (activePendingRevision?.proposed_by === 'MERCHANT' && role === 'merchant');

  // Independent party acceptances
  const buyerAccepted = transaction?.buyer_approved === 1;
  const merchantAccepted = transaction?.merchant_approved === 1;
  const isBothApproved = buyerAccepted && merchantAccepted;

  // The transaction moves to mutually approved ONLY when both parties have explicitly accepted
  const isMutuallyApproved = isBothApproved && (
    transaction?.status === 'mutually_approved' || 
    transaction?.status === 'approved' || 
    transaction?.status === 'quote_agreed'
  );

  // Ready to pay when mutually agreed AND no manual revised quote is pending AND not paid
  const isReadyToPay = isMutuallyApproved && !activePendingRevision && !isPaid;

  // Active agreed quote object
  const currentAgreedQuote = quotes.find(q => q.id === transaction?.agreed_quote_id);

  // Helper for rendering badges — muted semantic tokens matching dashboard palette
  const getStatusBadge = () => {
    if (isPaid) {
      return { text: 'PAID & COMPLETED', style: 'bg-emerald-50 text-emerald-700 border border-emerald-300' };
    }
    if (isMutuallyApproved) {
      return { text: 'MUTUALLY AGREED (READY TO PAY)', style: 'bg-emerald-50 text-emerald-700 border border-emerald-300' };
    }
    if (buyerAccepted && !merchantAccepted) {
      return { text: 'ACCEPTED BY BUYER (AWAITING MERCHANT)', style: 'bg-amber-50 text-amber-800 border border-amber-300' };
    }
    if (merchantAccepted && !buyerAccepted) {
      return { text: 'ACCEPTED BY MERCHANT (AWAITING BUYER)', style: 'bg-amber-50 text-amber-800 border border-amber-300' };
    }
    switch (transaction?.status) {
      case 'negotiating':
        return { text: 'AI NEGOTIATING', style: 'bg-blue-50 text-blue-700 border border-blue-300 animate-pulse' };
      case 'revision_pending':
        return { text: 'MANUAL REVISION IN PROGRESS', style: 'bg-amber-50 text-amber-800 border border-amber-300 animate-pulse' };
      case 'payment_initiated':
        return { text: 'PAYMENT IN PROGRESS', style: 'bg-blue-50 text-blue-700 border border-blue-300 animate-pulse' };
      case 'terminated':
      case 'failed':
      case 'verification_failed':
        return { text: 'TERMINATED', style: 'bg-red-50 text-red-700 border border-red-300' };
      case 'ai_negotiation_completed':
      case 'agreed':
      default:
        return { text: 'PENDING MUTUAL AGREEMENT', style: 'bg-amber-50 text-amber-800 border border-amber-300' };
    }
  };

  const statusBadge = getStatusBadge();

  return (
    <div className="min-h-screen p-6 md:p-8 max-w-5xl mx-auto">
      {/* Razorpay Checkout Script */}
      <Script src="https://checkout.razorpay.com/v1/checkout.js" />

      {/* Header */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-end border-b border-slate-200 pb-6 mb-8 gap-4">
        <div>
          <Link 
            href={role === 'merchant' ? '/merchant' : '/buyer'} 
            className="text-xs font-mono text-slate-500 hover:text-[#012652] transition-colors mb-2 inline-flex items-center min-h-[44px] py-2 px-1 -ml-1 touch-manipulation"
            aria-label="Return to Dashboard"
          >
            ← Return to Dashboard
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight text-[#012652]">
              Negotiation Session {transaction?.transaction_number || `#${txId}`}
            </h1>
            <span className="px-2.5 py-0.5 text-xs font-mono font-semibold bg-slate-100 text-[#012652] border border-slate-200 rounded-md">
              {role === 'merchant' ? 'Merchant View' : 'Buyer View'}
            </span>
            <div 
              role="status"
              aria-live="polite"
              aria-label={`Real-time sync status: ${wsStatus}`}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono bg-white border border-slate-200 shadow-xs"
            >
              <span className={`w-2 h-2 rounded-full shrink-0 ${
                wsStatus === 'connected' ? 'bg-emerald-500' :
                wsStatus === 'reconnecting' || wsStatus === 'connecting' ? 'bg-amber-400 animate-pulse' :
                'bg-slate-300'
              }`} />
              <span className={
                wsStatus === 'connected' ? 'text-emerald-700 font-semibold' :
                wsStatus === 'reconnecting' || wsStatus === 'connecting' ? 'text-amber-700 font-medium' :
                'text-slate-500'
              }>
                {wsStatus === 'connected' ? 'Live Sync Active' : wsStatus === 'reconnecting' ? 'Reconnecting...' : 'Offline'}
              </span>
            </div>
          </div>
          <p className="text-slate-500 font-mono text-xs mt-1">
            Fulfilling Merchant: <span className="font-bold text-[#012652]">{transaction?.merchant_name || 'Assigned Merchant'}</span>
          </p>
        </div>
        
        {transaction && (
          <div 
            role="status"
            aria-live="polite"
            aria-label={`Transaction status: ${statusBadge.text}`}
            className={`px-4 py-2 font-bold font-mono text-xs uppercase rounded-xl ${statusBadge.style}`}
          >
            Status: {statusBadge.text}
          </div>
        )}
      </header>

      {/* Error Banner */}
      {error && (
        <div className="mb-8 p-4 bg-red-50 border border-red-200 text-red-800 text-sm rounded-xl font-mono">
          <p className="font-bold mb-1">SYSTEM / VALIDATION NOTIFICATION:</p>
          {error}
        </div>
      )}

      {/* ACTIVE REVISED QUOTE PROPOSAL BANNER */}
      {activePendingRevision && (
        <div className="mb-8 p-6 bg-amber-50/60 border border-amber-300 rounded-2xl shadow-xs relative overflow-hidden">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
                <span className="text-xs font-mono font-bold uppercase tracking-wider text-[#012652]">
                  Active Revised Quote Proposal (#{activePendingRevision.id})
                </span>
                <span className="px-2 py-0.5 text-[10px] font-mono bg-slate-100 text-[#012652] border border-slate-200 rounded font-semibold">
                  Proposed by {activePendingRevision.proposed_by === 'BUYER' ? 'Buyer' : 'Merchant'}
                </span>
              </div>

              <div className="mt-2">
                <span className="text-2xl font-bold font-mono text-[#012652]">
                  ₹{activePendingRevision.amount.toLocaleString()}
                </span>
                <span className="text-xs text-slate-500 font-mono ml-2">
                  per unit (Total: ₹{(activePendingRevision.amount * (transaction?.quantity || 1)).toLocaleString()})
                </span>
              </div>

              {activePendingRevision.note && (
                <p className="text-xs font-mono text-slate-600 mt-2 bg-white p-2 rounded-lg border border-slate-200 inline-block">
                  &ldquo;{activePendingRevision.note}&rdquo;
                </p>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              {isRevisionProposer ? (
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-mono text-slate-600">
                  Waiting for the {role === 'buyer' ? 'Merchant' : 'Buyer'} to accept or reject your proposal.
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleAcceptQuote(activePendingRevision.id)}
                    disabled={quoteActionLoading}
                    className="px-5 py-2.5 bg-[#012652] hover:bg-[#012652]/90 text-white rounded-xl font-bold font-mono text-xs shadow-xs transition-all disabled:opacity-50"
                  >
                    {quoteActionLoading ? 'Processing...' : `Accept Quote (₹${activePendingRevision.amount.toLocaleString()})`}
                  </button>

                  <button
                    onClick={() => handleRejectQuote(activePendingRevision.id)}
                    disabled={quoteActionLoading}
                    className="px-4 py-2.5 bg-white hover:bg-slate-50 text-[#012652] border border-slate-300 rounded-xl font-bold font-mono text-xs transition-all disabled:opacity-50"
                  >
                    Reject
                  </button>

                  <button
                    onClick={() => {
                      setRevisedPrice(activePendingRevision.amount.toString());
                      setShowRevisionForm(true);
                    }}
                    className="px-4 py-2.5 bg-[#0D94FB] hover:bg-[#0D94FB]/90 text-white border border-[#0D94FB] rounded-xl font-bold font-mono text-xs transition-all"
                  >
                    Counter Quote
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Successful Settlement Banner */}
      {checkoutResult && (
        <div className="mb-8 p-6 bg-emerald-50/60 border border-emerald-300 text-[#012652] text-sm rounded-2xl relative overflow-hidden shadow-xs">
          <div className="absolute top-0 left-0 w-1 h-full bg-emerald-500"></div>
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <p className="font-bold uppercase tracking-wider text-[#012652] font-mono text-base">
              Razorpay Settlement Complete & Confirmed
            </p>
          </div>
          <p className="text-xs text-slate-600 mb-4">{checkoutResult.message}</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono bg-white p-3 rounded-xl border border-slate-200">
            <div>
              <p className="text-slate-400">Merchant Credited</p>
              <p className="font-bold text-[#012652]">{checkoutResult.merchant_name || transaction?.merchant_name}</p>
            </div>
            <div>
              <p className="text-slate-400">Nexus Order ID</p>
              <p className="font-bold text-[#012652]">#{checkoutResult.order_id || activeOrder?.id}</p>
            </div>
            <div>
              <p className="text-slate-400">Payment ID</p>
              <p className="font-bold text-[#012652] truncate">{checkoutResult.payment_id}</p>
            </div>
            <div>
              <p className="text-slate-400">Payment Gateway</p>
              <p className="font-bold text-[#012652]">Razorpay (Test Mode)</p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
        
        {/* Left: Transaction & Settlement Controls */}
        <div className="md:col-span-1 space-y-6">
          <div className="p-6 rounded-2xl border border-slate-200 bg-white">
            <h3 className="text-xs uppercase tracking-wider text-slate-400 font-mono mb-4 border-b border-slate-100 pb-2">
              Procurement Specifications
            </h3>
            
            <div className="space-y-4">
              <div>
                <p className="text-[10px] text-slate-400 uppercase font-mono">Wholesale Merchant</p>
                <p className="font-bold text-[#012652] text-base">
                  {transaction?.merchant_name || 'Assigned Wholesaler'}
                </p>
              </div>

              <div>
                <p className="text-[10px] text-slate-400 uppercase font-mono">Target Product</p>
                <p className="font-semibold text-[#012652]">
                  {transaction?.item_name || 'Component Listing'}
                </p>
                <p className="font-mono text-xs text-slate-500">{transaction?.sku}</p>
              </div>

              <div>
                <p className="text-[10px] text-slate-400 uppercase font-mono">Procurement Volume</p>
                <p className="font-mono text-[#012652] font-semibold">{transaction?.quantity} Units</p>
              </div>
              
              {transaction?.final_price && (
                <div className="pt-4 border-t border-slate-100">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-[10px] text-slate-400 uppercase font-mono">Currently Agreed Value</p>
                      <p className="font-mono text-2xl font-bold text-[#012652]">
                        ₹{(transaction.final_price * transaction.quantity).toLocaleString()}
                      </p>
                      <p className="font-mono text-xs text-slate-500">
                        @ ₹{transaction.final_price.toLocaleString()} / unit
                      </p>
                    </div>

                    {currentAgreedQuote && (
                      <span className={`px-2 py-1 text-[10px] font-mono rounded font-semibold uppercase ${
                        currentAgreedQuote.source === 'ai_negotiation' ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'bg-slate-100 text-[#012652] border border-slate-200'
                      }`}>
                        {currentAgreedQuote.source === 'ai_negotiation' ? 'AI Deal' : 'Revised'}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* REVISE QUOTE FORM (Collapsible) */}
            {showRevisionForm && !isPaid && (
              <div className="mt-6 pt-4 border-t border-slate-100">
                <form onSubmit={handleProposeRevision} className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-mono font-bold text-[#012652] uppercase">
                      Propose Revised Quote
                    </span>
                    <button
                      type="button"
                      onClick={() => setShowRevisionForm(false)}
                      className="text-xs text-slate-500 hover:text-[#012652] font-mono py-1 px-2 min-h-[36px] flex items-center"
                      aria-label="Cancel revision"
                    >
                      ✕ Cancel
                    </button>
                  </div>

                  <div>
                    <label htmlFor="revised-unit-price" className="text-[10px] font-mono text-slate-600 block mb-1 font-semibold">
                      New Unit Price (₹)
                    </label>
                    <input
                      id="revised-unit-price"
                      type="number"
                      step="0.01"
                      required
                      value={revisedPrice}
                      onChange={(e) => setRevisedPrice(e.target.value)}
                      placeholder="e.g. 21500"
                      className="w-full px-3 py-2 text-sm font-mono border border-slate-300 rounded-lg focus:outline-none focus:border-[#0D94FB] focus:ring-1 focus:ring-[#0D94FB] bg-white text-[#012652]"
                    />
                  </div>

                  <div>
                    <label htmlFor="revised-quote-note" className="text-[10px] font-mono text-slate-600 block mb-1 font-semibold">
                      Optional Note / Reason
                    </label>
                    <input
                      id="revised-quote-note"
                      type="text"
                      value={revisionNote}
                      onChange={(e) => setRevisionNote(e.target.value)}
                      placeholder="e.g. Agreed via phone call"
                      className="w-full px-3 py-2 text-xs font-mono border border-slate-300 rounded-lg focus:outline-none focus:border-[#0D94FB] focus:ring-1 focus:ring-[#0D94FB] bg-white text-[#012652]"
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={revisionSubmitting}
                    className="w-full py-2.5 bg-[#012652] hover:bg-[#012652]/90 text-white rounded-lg font-mono font-bold text-xs transition-all disabled:opacity-50"
                  >
                    {revisionSubmitting ? 'Submitting Proposal...' : 'Submit Revised Quote'}
                  </button>
                </form>
              </div>
            )}

            {/* DUAL-HUMAN APPROVAL CONTROLS */}
            {!isPaid && transaction?.status !== 'negotiating' && transaction?.status !== 'terminated' && transaction?.status !== 'failed' && (
              <div className="mt-6 pt-4 border-t border-slate-100 space-y-4">
                <div className="flex justify-between items-center">
                  <div className="text-xs font-mono font-bold uppercase text-slate-500">
                    Mutual Human Approval
                  </div>
                  <span className="text-[10px] font-mono text-slate-400">Independent Review</span>
                </div>

                {/* Approval Status Matrix */}
                <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                  <div className={`p-3 rounded-xl border text-center transition-all ${
                    buyerAccepted 
                      ? 'bg-emerald-50 border-emerald-300 text-emerald-700 font-bold' 
                      : 'bg-slate-50 border-slate-200 text-slate-500'
                  }`}>
                    <div className={`text-[10px] uppercase tracking-wider mb-0.5 ${buyerAccepted ? 'text-emerald-600' : 'text-slate-400'}`}>Buyer Acceptance</div>
                    <div className="text-xs">
                      {buyerAccepted ? 'Accepted by Buyer' : 'Pending Acceptance'}
                    </div>
                  </div>

                  <div className={`p-3 rounded-xl border text-center transition-all ${
                    merchantAccepted 
                      ? 'bg-emerald-50 border-emerald-300 text-emerald-700 font-bold' 
                      : 'bg-slate-50 border-slate-200 text-slate-500'
                  }`}>
                    <div className={`text-[10px] uppercase tracking-wider mb-0.5 ${merchantAccepted ? 'text-emerald-600' : 'text-slate-400'}`}>Merchant Acceptance</div>
                    <div className="text-xs">
                      {merchantAccepted ? 'Accepted by Merchant' : 'Pending Acceptance'}
                    </div>
                  </div>
                </div>

                {/* Case 1: When Mutual Agreement is still pending */}
                {!isMutuallyApproved && !activePendingRevision && (
                  <>
                    {((role === 'buyer' && !buyerAccepted) || (role === 'merchant' && !merchantAccepted)) ? (
                      <div className="space-y-2">
                        {((role === 'buyer' && merchantAccepted) || (role === 'merchant' && buyerAccepted)) && (
                          <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-center text-amber-800 font-mono text-xs">
                            <span className="font-bold">Notice:</span> {role === 'buyer' ? 'Merchant' : 'Buyer'} has already accepted ₹{transaction?.final_price?.toLocaleString()}. Your independent acceptance is required to finalize the deal.
                          </div>
                        )}
                        <button
                          onClick={handleApprove}
                          disabled={approveLoading}
                          className="w-full py-3.5 bg-[#0D94FB] hover:bg-[#0D94FB]/90 text-white rounded-xl font-bold font-mono tracking-wider uppercase text-xs transition-all shadow-xs disabled:opacity-50 flex items-center justify-center gap-2"
                        >
                          {approveLoading ? 'Recording Acceptance...' : `Accept & Agree to Price (₹${transaction.final_price?.toLocaleString()})`}
                        </button>
                        <p className="text-[10px] text-slate-400 text-center font-mono">
                          Acceptance is recorded independently. Both parties must accept the exact same price before checkout unlocks.
                        </p>
                      </div>
                    ) : (
                      <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-center font-mono text-xs">
                        <span className="font-bold text-[#012652] block text-sm mb-0.5">Accepted by {role === 'buyer' ? 'Buyer' : 'Merchant'}</span>
                        <p className="text-[11px] text-slate-600">
                          Your acceptance has been logged. Waiting for the {role === 'buyer' ? 'Merchant' : 'Buyer'} to independently accept.
                        </p>
                      </div>
                    )}
                  </>
                )}

                {/* Case 2: Mutually Approved Banner */}
                {isMutuallyApproved && (
                  <div className="p-4 bg-emerald-50 border border-emerald-300 rounded-xl text-center font-mono text-xs">
                    <span className="font-bold text-sm block mb-1 text-emerald-700">Mutually Agreed!</span>
                    <p className="text-[11px] text-emerald-600">
                      Both Buyer and Merchant have independently accepted ₹{transaction.final_price?.toLocaleString()} / unit. Price mandate locked.
                    </p>
                  </div>
                )}

                {/* Revision & Termination Action Bar */}
                {!activePendingRevision && !showRevisionForm && (
                  <div className="pt-2 border-t border-slate-100 flex gap-2">
                    <button
                      onClick={() => {
                        setRevisedPrice(transaction?.final_price?.toString() || '');
                        setShowRevisionForm(true);
                      }}
                      className="flex-1 py-2.5 bg-slate-50 hover:bg-slate-100 text-[#012652] border border-slate-200 rounded-xl font-bold font-mono text-xs transition-all flex items-center justify-center gap-1.5"
                    >
                      <span>✎</span> Revise Quote
                    </button>

                    <button
                      onClick={handleTerminate}
                      disabled={terminateLoading}
                      className="px-3 py-2.5 bg-white hover:bg-red-50 text-red-600 border border-red-200 rounded-xl font-bold font-mono text-xs transition-all"
                      title="Terminate negotiation session"
                    >
                      {terminateLoading ? '...' : '✕ Terminate'}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Revision Pending Notice when active quote exists */}
            {activePendingRevision && (
              <div className="mt-6 pt-4 border-t border-slate-200 bg-amber-50/60 p-3.5 rounded-xl text-xs font-mono text-amber-800 space-y-1">
                <div className="flex items-center gap-1.5 font-bold">
                  <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
                  Quote Revision in Progress
                </div>
                <p className="text-[11px] text-slate-600">
                  Payment is locked while revised quote #{activePendingRevision.id} is being evaluated.
                </p>
              </div>
            )}

            {/* Merchant-view Mutually Approved Notice */}
            {isMutuallyApproved && role === 'merchant' && !isPaid && (
              <div className="mt-6 pt-4 border-t border-slate-100 text-center">
                <div className="p-4 bg-emerald-50/60 border border-emerald-200 rounded-2xl">
                  <p className="font-mono font-bold text-xs uppercase tracking-wider text-emerald-700">
                    Ready for Buyer Payment
                  </p>
                  <p className="text-xs text-slate-600 mt-1 font-mono">
                    Mutual approval complete. Stock reservation is active for ₹{(transaction.final_price * transaction.quantity).toLocaleString()}.
                  </p>
                  <p className="text-[11px] text-slate-400 mt-2 font-mono">
                    Payment gateway is unlocked on the buyer portal.
                  </p>
                </div>
              </div>
            )}

            {/* Stage: Settlement via Razorpay */}
            {isReadyToPay && role === 'buyer' && (
              <div className="mt-8 pt-6 border-t border-slate-100 space-y-4">
                
                {/* AI Upsell Offer */}
                {upsellLoading && (
                  <div className="p-3 border border-slate-200 bg-slate-50 rounded-xl text-xs font-mono text-slate-600 animate-pulse">
                    AI Strategic Agent generating cross-sell for this merchant...
                  </div>
                )}
                
                {upsellOffer && (
                  <div className="p-4 border border-slate-200 bg-slate-50 rounded-xl relative">
                    <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-500">
                      Strategic Seller Recommendation
                    </span>
                    <p className="text-xs text-[#012652] mt-1 mb-2 font-medium">
                      {upsellOffer.pitch}
                    </p>
                    <div className="flex justify-between items-center bg-white p-2 rounded-lg border border-slate-200 text-xs font-mono mb-2">
                      <span className="text-[#012652] font-bold">{upsellOffer.recommended_sku}</span>
                      <span className="text-emerald-600 font-semibold">{upsellOffer.suggested_discount_percent}% bundle discount</span>
                    </div>
                  </div>
                )}

                <button
                  onClick={handleCheckout}
                  disabled={checkoutLoading}
                  className="w-full py-4 bg-[#0D94FB] hover:bg-[#0D94FB]/90 text-white rounded-xl font-bold tracking-wider uppercase text-xs transition-all shadow-sm disabled:opacity-50"
                >
                  {checkoutLoading ? 'Opening Razorpay Checkout...' : `Pay ₹${(transaction.final_price * transaction.quantity).toLocaleString()} with Razorpay`}
                </button>

                <button
                  onClick={handleTamperedCheckout}
                  disabled={checkoutLoading}
                  className="w-full py-3 bg-white hover:bg-slate-50 text-slate-600 border border-slate-300 rounded-xl font-bold tracking-wider uppercase text-xs transition-all"
                >
                  {checkoutLoading ? 'Verifying...' : 'Simulate Tampering (Graceful Failure)'}
                </button>

                <p className="text-[10px] text-slate-400 text-center font-mono">
                  Order amount = ₹{(transaction.final_price * transaction.quantity).toLocaleString()} (Negotiated Price). Binds inventory to Merchant &apos;{transaction?.merchant_name}&apos;.
                </p>
              </div>
            )}

            {isPaid && (
              <div className="mt-8 pt-6 border-t border-slate-100 text-center">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-600 mb-2 font-bold text-lg">
                  ✓
                </div>
                <h4 className="font-bold text-[#012652] text-sm">Settlement Complete</h4>
                <p className="text-xs text-slate-500 font-mono mt-1">
                  Payment processed via Razorpay. Stock captured and assigned.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Right: Audit Trail & Quote History Timeline */}
        <div className="md:col-span-2 space-y-6">
          {/* QUOTE HISTORY TIMELINE */}
          {quotes.length > 0 && (
            <div className="p-6 rounded-2xl border border-slate-200 bg-white">
              <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
                <h3 className="text-xs uppercase tracking-wider text-slate-400 font-mono">
                  Quote Negotiation Timeline ({quotes.length} proposal{quotes.length > 1 ? 's' : ''})
                </h3>
                <span className="text-[10px] font-mono text-slate-400 font-semibold">
                  Canonical Settlement Records
                </span>
              </div>

              <div className="space-y-3">
                {quotes.map((q, idx) => {
                  const isAcceptedByBoth = (q.status === 'accepted') || (q.buyer_accepted === true && q.merchant_accepted === true);
                  const isAcceptedByBuyerOnly = q.buyer_accepted === true && !q.merchant_accepted;
                  const isAcceptedByMerchantOnly = q.merchant_accepted === true && !q.buyer_accepted;
                  const isRejected = q.status === 'rejected';
                  const isSuperseded = q.status === 'superseded';

                  const isBuyer = q.proposed_by === 'BUYER';
                  const isMerchant = q.proposed_by === 'MERCHANT';
                  const isAi = q.source === 'ai_negotiation';

                  let cardBorder = 'bg-white border-slate-200';
                  if (isAcceptedByBoth) {
                    cardBorder = 'bg-emerald-50/50 border-emerald-300';
                  } else if (isAcceptedByBuyerOnly || isAcceptedByMerchantOnly) {
                    cardBorder = 'bg-amber-50/40 border-amber-200';
                  } else if (isRejected || isSuperseded) {
                    cardBorder = 'bg-slate-50/50 border-slate-200 opacity-60';
                  }

                  let badgeClass = 'bg-slate-100 text-[#012652] border border-slate-200';
                  if (isBuyer) {
                    badgeClass = 'bg-blue-50 text-blue-700 border border-blue-200';
                  } else if (isMerchant) {
                    badgeClass = 'bg-slate-100 text-[#012652] border border-slate-200';
                  } else if (isAi) {
                    badgeClass = 'bg-blue-50 text-blue-700 border border-blue-200';
                  }

                  let statusBadgeClass = 'bg-amber-50 text-amber-700 border border-amber-200';
                  if (isAcceptedByBoth) {
                    statusBadgeClass = 'bg-emerald-50 text-emerald-700 border border-emerald-200';
                  } else if (isAcceptedByBuyerOnly) {
                    statusBadgeClass = 'bg-amber-50 text-amber-700 border border-amber-200';
                  } else if (isAcceptedByMerchantOnly) {
                    statusBadgeClass = 'bg-amber-50 text-amber-700 border border-amber-200';
                  } else if (isRejected) {
                    statusBadgeClass = 'bg-red-50 text-red-600 border border-red-200';
                  } else if (isSuperseded) {
                    statusBadgeClass = 'bg-slate-100 text-slate-500 border border-slate-200';
                  }

                  return (
                    <div 
                      key={idx}
                      className={`p-3.5 rounded-xl border transition-all text-xs font-mono ${cardBorder}`}
                    >
                      <div className="flex justify-between items-center mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 text-[10px] rounded font-bold uppercase ${badgeClass}`}>
                            {isAi ? 'AI Consensus' :
                             isMerchant ? 'Merchant Proposal' :
                             'Buyer Proposal'}
                          </span>

                          <span className={`font-bold text-sm ${isRejected ? 'text-slate-400 line-through opacity-75' : 'text-[#012652]'}`}>
                            ₹{q.amount.toLocaleString()} / unit
                          </span>
                        </div>

                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${statusBadgeClass}`}>
                            {isAcceptedByBoth ? 'Mutually Agreed' :
                             isAcceptedByBuyerOnly ? 'Accepted by Buyer' :
                             isAcceptedByMerchantOnly ? 'Accepted by Merchant' :
                             isRejected ? 'Rejected' :
                             isSuperseded ? 'Superseded' :
                             'Pending Mutual Agreement'}
                          </span>
                          <span className="text-[10px] text-slate-400">
                            {new Date(q.created_at).toLocaleTimeString()}
                          </span>
                        </div>
                      </div>

                      {q.note && (
                        <p className="text-[11px] italic mt-1 text-slate-500">
                          Note: &ldquo;{q.note}&rdquo;
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* AUDIT TRAIL / AI NEGOTIATION ORCHESTRATION */}
          <div className="p-6 rounded-2xl min-h-[400px] border border-slate-200 bg-white">
            <div className="flex justify-between items-center mb-6 border-b border-slate-100 pb-3">
              <h3 className="text-xs uppercase tracking-wider text-slate-400 font-mono">
                AI Negotiation Orchestration
              </h3>
              <span className="text-[10px] font-mono text-slate-500 flex items-center gap-1.5 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                Live Event Log
              </span>
            </div>
            
            <div className="space-y-3">
              {logs.map((log, idx) => {
                const actorLower = log.actor.toLowerCase();
                const isBuyer = actorLower.includes('buyer');
                const isMerchant = actorLower.includes('merchant');
                const isSystem = actorLower.includes('system') || actorLower.includes('orchestrator') || actorLower.includes('gateway');
                
                let badgeClass = 'bg-slate-100 text-[#012652]';
                let borderClass = 'border-slate-200 bg-white';
                
                if (isBuyer) {
                  badgeClass = 'bg-blue-50 text-blue-700';
                  borderClass = 'border-slate-200 bg-white';
                } else if (isMerchant) {
                  badgeClass = 'bg-slate-100 text-[#012652]';
                  borderClass = 'border-slate-200 bg-white';
                } else if (isSystem) {
                  badgeClass = 'bg-slate-100 text-slate-600';
                  borderClass = 'border-slate-200 bg-slate-50/50';
                }

                return (
                  <div key={idx} className={`p-4 rounded-xl border ${borderClass}`}>
                    <div className="flex justify-between items-baseline mb-2">
                      <span className={`text-[11px] font-bold font-mono tracking-wider uppercase px-2 py-0.5 rounded ${badgeClass}`}>
                        {log.actor}
                      </span>
                      <span className="text-[10px] text-slate-400 font-mono">
                        {new Date(log.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-xs font-mono text-slate-700 whitespace-pre-wrap leading-relaxed">
                      {log.message}
                    </p>
                  </div>
                );
              })}
              
              {logs.length === 0 && (
                <div className="text-center p-12 text-xs text-slate-400 font-mono">
                  No negotiation messages exchanged yet.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
