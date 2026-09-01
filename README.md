# Nexus B2B — Autonomous Multi-Agent AI Negotiation & Razorpay Settlement Platform

[![Production Deployment](https://img.shields.io/badge/Production-Live-emerald.svg)](https://nexus-b2b-xi.vercel.app)
[![FastAPI Backend](https://img.shields.io/badge/Backend-Render-0055FF.svg)](https://nexus-b2b-backend.onrender.com)
[![Razorpay Payment Engine](https://img.shields.io/badge/Payment-Razorpay%20Verified-0D94FB.svg)](https://razorpay.com)
[![LangGraph AI](https://img.shields.io/badge/Agents-LangGraph%20%2B%20Gemini-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Test Suite](https://img.shields.io/badge/Tests-41%2F41%20Passing-brightgreen.svg)]()

> **Nexus B2B** is an enterprise-grade autonomous negotiation and instant settlement exchange. It coordinates parallel, multi-agent AI procurement pipelines, enforces cryptographic price integrity, and automates multi-party payments via Razorpay.

---

## 🌐 Live Production Deployments & Demo Access

| Service | Environment URL | Description |
| :--- | :--- | :--- |
| **Frontend Web App** | [https://nexus-b2b-xi.vercel.app](https://nexus-b2b-xi.vercel.app) | Next.js 16 App Router, React 19, Tailwind CSS 4, Real-time WebSockets |
| **Backend REST & WS** | [https://nexus-b2b-backend.onrender.com](https://nexus-b2b-backend.onrender.com) | FastAPI, SQLAlchemy async ORM, LangGraph Agents, Razorpay Integration |
| **Interactive API Docs** | [https://nexus-b2b-backend.onrender.com/docs](https://nexus-b2b-backend.onrender.com/docs) | OpenAPI 3.0 interactive Swagger UI |

### 🔑 Pre-Configured Demo Credentials

| Role | Username | Password | Purpose |
| :--- | :--- | :--- | :--- |
| **Buyer (Procurement)** | `retail_purchaser` | `retail_purchaser` | Launch parallel AI auctions, set budget ceilings, review quotes, checkout via Razorpay |
| **Merchant (Wholesaler)** | `tech_distributor` | `tech_distributor` | Manage catalog inventory, configure floor pricing, review live deals, submit revised quotes |

---

## ⚡ Key Innovations & Core Features

### 1. Autonomous Multi-Agent Negotiation (LangGraph + Gemini)
- **Buyer Procurement Agent**: Concedes strategically along an algorithmic concession curve, bidding up from 75% of catalog value without ever exceeding the buyer's maximum budget ceiling.
- **Merchant Wholesaler Agent**: Dynamically evaluates inventory velocity, order volume, and minimum price floors to calculate optimal counter-offers.
- **Strategic Upsell Agent**: Analyzes past order patterns and catalog pairings to generate targeted cross-sell pitches and volume bundle discounts upon deal finalization.
- **Orchestrator Agent**: Manages state transitions across turns, detects price convergence, enforces merchant floor constraints, and cryptographically signs agreed settlement quotes.

### 2. Razorpay Smart Payment & Settlement Pipeline
- **Cryptographic Cart Mandate**: HMAC-SHA256 signatures seal the negotiated price and merchant routing ID, mathematically preventing price tampering on client devices.
- **Idempotent Order Creation**: Guaranteed safe retries with zero duplicate charge risk on high-concurrency procurement bursts.
- **Stock Reservation with Expiry**: Locks inventory atomically during payment review and auto-releases stock upon payment expiry or failure.
- **Multi-Merchant Route Splitting**: Native support for splitting multi-vendor procurement orders into vendor-specific accounts with dynamic commission retention.

### 3. Real-Time Streaming & Resilience Engine
- **Bidirectional WebSockets**: Instant updates for counter-offers, proposal revisions, mutual human approvals, and payment confirmation.
- **Zero-Jitter Token Auto-Refresh**: WebSocket connection automatically performs silent background JWT rotation upon expiration (4401 handling), ensuring 100% active stream uptime without page reloads.
- **Human-in-the-Loop Counter-Quotes**: Either party can propose revised quotes, counter-offers, or cancellations with instant mutual state sync.

---

## 🏗️ Architecture & Component Layout

```
                                  ┌─────────────────────────────┐
                                  │   Buyer Procurement Node    │
                                  │  (Next.js / Realtime Hook)  │
                                  └──────────────┬──────────────┘
                                                 │ HTTPS / WSS
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   FASTAPI APPLICATION CORE                                     │
│                                                                                                │
│  ┌─────────────────────────┐   ┌───────────────────────────┐   ┌────────────────────────────┐  │
│  │   Auth & JWT Security   │   │    WebSocket Manager      │   │    Rate Limiter & Locks    │  │
│  │  (BCrypt + Auto-Refresh)│   │  (Zero-Jitter Reconnect)  │   │  (Brute-Force Protection)  │  │
│  └─────────────────────────┘   └───────────────────────────┘   └────────────────────────────┘  │
│                                                │                                               │
│  ┌─────────────────────────────────────────────┴────────────────────────────────────────────┐  │
│  │                              LANGGRAPH MULTI-AGENT RUNTIME                              │  │
│  │                                                                                          │  │
│  │   ┌─────────────────────┐    Bid / Counter    ┌──────────────────────┐                  │  │
│  │   │   Buyer Agent       │ ◄─────────────────► │    Merchant Agent    │                  │  │
│  │   │ (Budget Ceiling)    │                     │  (Floor Protection)  │                  │  │
│  │   └──────────┬──────────┘                     └──────────┬───────────┘                  │  │
│  │              │                                           │                              │  │
│  │              └────────────────────┬──────────────────────┘                              │  │
│  │                                   ▼                                                     │  │
│  │                     ┌───────────────────────────┐                                       │  │
│  │                     │    Orchestrator Agent     │                                       │  │
│  │                     │ (HMAC Signature Mandate)  │                                       │  │
│  │                     └─────────────┬─────────────┘                                       │  │
│  └───────────────────────────────────┼─────────────────────────────────────────────────────┘  │
│                                      │                                                         │
│                                      ▼                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                               RAZORPAY PAYMENT ENGINE                                    │  │
│  │   - HMAC Cart Validation       - Razorpay Standard Checkout     - Webhook Verification   │  │
│  │   - Idempotent Orders          - Route Split Transfer           - Stock Capture Engine   │  │
│  └──────────────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Structure

```
├── frontend/                  # Next.js 16 App Router Frontend
│   ├── app/
│   │   ├── auth/              # Role-based login & registration (Buyer / Merchant)
│   │   ├── buyer/             # Buyer dashboard, multi-agent procurement & auction cards
│   │   ├── merchant/          # Merchant inventory management, floor controls & quote revisions
│   │   ├── transaction/[id]/  # Canonical transaction view, approvals & Razorpay checkout
│   │   └── users/             # User directory & active profile switcher
│   ├── components/ui/         # Enterprise UI design system & particle backdrop
│   └── lib/                   # API clients, silent auth refresh, useRealtime WebSocket hook
│
└── backend/                   # FastAPI Backend Application
    ├── app/
    │   ├── agents/            # LangGraph multi-agent systems (Buyer, Merchant, Upsell, Orchestrator)
    │   ├── ml/                # Dynamic ML pricing models & concession curves
    │   ├── payment/           # Razorpay provider, HMAC signatures & route split settlement
    │   ├── auth.py            # JWT token authentication, password hashing & refresh routes
    │   ├── config.py          # Environment settings & validation
    │   ├── database.py        # SQLAlchemy session management & connection pool
    │   ├── models.py          # SQLAlchemy models (User, Inventory, Transaction, Quote, Order)
    │   ├── schemas.py         # Pydantic validation schemas
    │   ├── realtime.py        # WebSocket channel & room manager
    │   ├── rate_limit.py      # SlowAPI rate limiting & account lockout manager
    │   └── main.py            # FastAPI main application & API route handlers
    └── tests/                 # Comprehensive test suite (41/41 unit & integration tests)
```

---

## 🛠️ Local Development Setup

### Prerequisites
- Node.js 18+ and npm
- Python 3.11+ (Python 3.13 recommended)

### 1. Backend Setup

```bash
cd backend

# Create virtual environment & install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Fill in your GEMINI_API_KEY, RAZORPAY_KEY_ID, and RAZORPAY_KEY_SECRET

# Start FastAPI development server
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Configure environment variables
cp .env.example .env.local
# Set NEXT_PUBLIC_API_URL=http://localhost:8000/api

# Start Next.js development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🧪 Automated Testing Suite

All 41 test cases pass with full test isolation across SQLite and PostgreSQL:

```bash
cd backend
python3 -m pytest backend/tests -v
```

### Test Coverage Highlights:
- **`test_auth_security.py`**: Rate limiting, brute-force lockout, token expiration & password hashing.
- **`test_quote_workflow.py`**: 9-state quote lifecycle, merchant revised quote submission, buyer decision & floor price validation.
- **`test_price_logic.py`**: Negotiation price authority, concession curve validation, and multi-merchant quote isolation.
- **`test_multi_merchant_payment.py`**: Razorpay order creation, HMAC signature verification, stock reservation, and tamper prevention.
- **`test_realtime.py`**: WebSocket broadcast channels, heartbeat pings, and dashboard event dispatching.

---

## 📄 License & Acknowledgements

Built for the **Razorpay Buildathon 2026**. Designed and developed by **Maharshi Pandya**.
Distributed under the MIT License.
