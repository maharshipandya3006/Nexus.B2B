function getNormalizedApiUrl(): string {
  let url = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').trim();
  // Strip trailing slashes
  url = url.replace(/\/+$/, '');
  // If it does not end in /api, append it
  if (!url.endsWith('/api')) {
    url = `${url}/api`;
  }
  return url;
}

const API_URL = getNormalizedApiUrl();

export class ApiError extends Error {
  status: number;
  data: any;

  constructor(status: number, message: string, data?: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

let refreshPromise: Promise<string | null> | null = null;

export async function silentRefreshToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  const currentToken = localStorage.getItem('token');
  if (!currentToken) return null;

  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${currentToken}`,
        },
        body: JSON.stringify({ token: currentToken }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.access_token) {
          localStorage.setItem('token', data.access_token);
          if (data.role) {
            localStorage.setItem('role', data.role);
          }
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('auth:token_refreshed', { detail: { token: data.access_token } }));
          }
          return data.access_token;
        }
      }
      return null;
    } catch (e) {
      console.warn('[Silent Refresh] Network failure during refresh attempt:', e);
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

async function fetchWithAuth(endpoint: string, options: RequestInit = {}, isRetry: boolean = false): Promise<any> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    // If 401 Unauthorized and not already retrying, attempt automatic silent background token refresh
    if (response.status === 401 && !isRetry && endpoint !== '/auth/token' && endpoint !== '/auth/refresh') {
      const newToken = await silentRefreshToken();
      if (newToken) {
        return fetchWithAuth(endpoint, options, true);
      }
    }

    let errorData;
    try {
      errorData = await response.json();
    } catch (e) {
      errorData = { detail: response.statusText };
    }
    throw new ApiError(response.status, errorData.detail || 'API Error', errorData);
  }

  return response.json();
}

export interface Quote {
  id: number;
  transaction_id: number;
  amount: number;
  proposed_by: 'AI' | 'MERCHANT' | 'BUYER';
  source: 'ai_negotiation' | 'manual_merchant' | 'manual_buyer';
  merchant_accepted: boolean | null;
  buyer_accepted: boolean | null;
  status: 'pending' | 'accepted' | 'rejected' | 'superseded' | 'expired';
  note?: string;
  created_at: string;
  accepted_at?: string;
}

export interface Transaction {
  id: number;
  transaction_number?: string;
  sku: string;
  quantity: number;
  final_price: number | null;
  status: string;
  cryptographic_signature?: string | null;
  razorpay_order_id?: string | null;
  buyer_id: number;
  merchant_id: number;
  inventory_id?: number | null;
  buyer_approved: number;
  merchant_approved: number;
  buyer_accepted?: boolean;
  merchant_accepted?: boolean;
  agreed_quote_id?: number | null;
  quotes?: Quote[];
  active_quote?: Quote | null;
  merchant_name?: string | null;
  item_name?: string | null;
  merchant_minimum_price?: number | null;
  catalog_price?: number | null;
  created_at: string;
  updated_at: string;
}

export const api = {
  checkHealth: async (): Promise<boolean> => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 6000);
      const res = await fetch(`${API_URL}/health`, { signal: controller.signal });
      clearTimeout(timeoutId);
      return res.ok;
    } catch {
      return false;
    }
  },

  // Auth
  login: async (data: FormData) => {
    let response: Response;
    try {
      response = await fetch(`${API_URL}/auth/token`, {
        method: 'POST',
        body: data, // FastAPI OAuth2PasswordRequestForm expects form data
      });
    } catch (networkErr: any) {
      throw new ApiError(
        0,
        'Cannot reach backend server. If Render was idle, it may take 30–50 seconds to wake up. Please retry shortly.'
      );
    }
    
    if (!response.ok) {
      let errorDetail = 'Login failed';
      try {
        const errorData = await response.json();
        errorDetail = errorData.detail || errorDetail;
      } catch (parseErr) {
        if (response.status === 502 || response.status === 503 || response.status === 504) {
          errorDetail = 'Backend server is waking up from idle state. Please wait 15–30 seconds and click Sign In again.';
        } else {
          errorDetail = `Server returned status ${response.status} (${response.statusText || 'Error'})`;
        }
      }
      throw new ApiError(response.status, errorDetail);
    }
    return response.json();
  },
  
  register: (data: { username: string; password: string; role: string }) =>
    fetchWithAuth('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  
  getMe: () => fetchWithAuth('/auth/me'),
  
  refreshToken: () => silentRefreshToken(),

  logout: () => {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('token');
      localStorage.removeItem('role');
      window.location.href = '/auth';
    }
  },

  isAuthenticated: () => {
    if (typeof window !== 'undefined') {
      return Boolean(localStorage.getItem('token'));
    }
    return false;
  },
  
  // User Management
  getUsers: () => fetchWithAuth('/users'),
  
  updateUser: (id: number, data: { role?: string; password?: string }) => 
    fetchWithAuth(`/users/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
    
  deleteUser: (id: number) => 
    fetchWithAuth(`/users/${id}`, {
      method: 'DELETE',
    }),

  // Merchants (Dynamic Entities)
  getMerchants: () => fetchWithAuth('/merchants'),

  getMerchantProfile: (merchantId: number) => fetchWithAuth(`/merchants/${merchantId}`),

  updateMerchantProfile: (data: {
    display_name: string;
    description?: string;
    contact_email?: string;
    business_category?: string;
  }) =>
    fetchWithAuth('/merchants/profile', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  
  // Inventory (Merchant-scoped)
  getInventory: () => fetchWithAuth('/inventory'),
  
  addInventory: (data: {
    sku: string;
    name: string;
    current_stock: number;
    base_price: number;
    minimum_margin_limit: number;
    demand_velocity: number;
  }) => 
    fetchWithAuth('/inventory', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  removeInventory: (id: number, data: { units_to_remove: number; delete_if_zero?: boolean }) =>
    fetchWithAuth(`/inventory/${id}/remove`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  deleteInventory: (id: number) =>
    fetchWithAuth(`/inventory/${id}`, {
      method: 'DELETE',
    }),
    
  // Negotiation: Single-Merchant (Targeted Listing)
  initiateNegotiation: (data: {
    sku: string;
    quantity: number;
    buyer_max_budget: number;
    inventory_id: number;
  }) =>
    fetchWithAuth('/negotiate', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Negotiation: Multi-Merchant Parallel Bidding
  initiateMultiNegotiation: (data: {
    sku: string;
    quantity: number;
    buyer_max_budget: number;
  }) =>
    fetchWithAuth('/negotiate/multi', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
    
  // Transactions
  getTransactions: () => fetchWithAuth('/transactions'),

  getTransaction: (id: number) => fetchWithAuth(`/transactions/${id}`),
  
  getTransactionLogs: (id: number) => fetchWithAuth(`/transactions/${id}/logs`),
  
  approveTransaction: (id: number) => fetchWithAuth(`/transactions/${id}/approve`, {
    method: 'POST'
  }),

  // Revised Quote Workflow
  proposeQuoteRevision: (transactionId: number, data: { amount: number; note?: string }) =>
    fetchWithAuth(`/transactions/${transactionId}/quotes`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  acceptQuote: (transactionId: number, quoteId: number) =>
    fetchWithAuth(`/transactions/${transactionId}/quotes/${quoteId}/accept`, {
      method: 'POST',
    }),

  rejectQuote: (transactionId: number, quoteId: number) =>
    fetchWithAuth(`/transactions/${transactionId}/quotes/${quoteId}/reject`, {
      method: 'POST',
    }),

  getQuoteHistory: (transactionId: number) =>
    fetchWithAuth(`/transactions/${transactionId}/quotes`),

  terminateTransaction: (id: number) =>
    fetchWithAuth(`/transactions/${id}/terminate`, {
      method: 'POST',
    }),
  
  getUpsellOffer: (id: number) => fetchWithAuth(`/transactions/${id}/upsell`),

  // Orders (Production Lifecycle)
  createOrder: (negotiationId: number) =>
    fetchWithAuth('/orders', {
      method: 'POST',
      body: JSON.stringify({ negotiation_id: negotiationId }),
    }),

  getOrders: () => fetchWithAuth('/orders'),

  getOrder: (id: number) => fetchWithAuth(`/orders/${id}`),

  // Razorpay Payment Flow
  initiateCheckout: (orderId: number) =>
    fetchWithAuth(`/payment/checkout?order_id=${orderId}`, {
      method: 'POST',
    }),

  verifyPayment: (data: {
    order_id: number;
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
  }) =>
    fetchWithAuth('/payment/verify', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  mockCheckout: (orderId: number) => 
    fetchWithAuth(`/payment/mock-checkout?order_id=${orderId}`, {
      method: 'POST',
    }),

  // Admin Payments View
  getAdminPayments: (merchantId?: number) => {
    const query = merchantId ? `?merchant_id=${merchantId}` : '';
    return fetchWithAuth(`/admin/payments${query}`);
  },
    
  // Tampering Simulation (Graceful Failure testing)
  mockTamperedCheckout: (transactionId: number) => {
    const fakePayload = JSON.stringify({
      sku: "TAMPERED-SKU",
      quantity: 9999,
      price: 1.0,
      timestamp: new Date().toISOString()
    });
    const fakeToken = `${fakePayload}.invalid_cryptographic_signature_12345`;
    
    return fetchWithAuth(`/payment/create-order?transaction_id=${transactionId}&mandate_token=${fakeToken}`, {
      method: 'POST',
    });
  },

  // Legacy createOrder fallback
  createOrderLegacy: (transaction_id: number, mandate_token: string) =>
    fetchWithAuth(`/payment/create-order?transaction_id=${transaction_id}&mandate_token=${mandate_token}`, {
      method: 'POST',
    }),
};
