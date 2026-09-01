# Nexus B2B — Autonomous Multi-Agent AI Negotiation & Payment Settlement Platform

Nexus B2B is a real-time autonomous negotiation platform powered by multi-agent AI systems (LangGraph + Google Gemini) and integrated with Razorpay for automated escrow, invoice splitting, and multi-merchant payment settlement.

---

## 🚀 Architecture Overview

- **Frontend**: Next.js 16 (App Router), React 19, Tailwind CSS 4, Framer Motion, Real-time WebSockets.
- **Backend**: FastAPI (Python 3.13), SQLAlchemy async ORM, LangGraph Agent Workflow, Google Gemini AI.
- **Payment & Settlement**: Razorpay Payment Gateway, Razorpay Route / Multi-party split settlement, Webhook verification.
- **Real-time Engine**: WebSocket connection manager with live counter-offer streaming, dynamic charts, and auto-settlement notifications.

---

## 📁 Repository Structure

```
├── frontend/                  # Next.js App Router Frontend
│   ├── app/
│   │   ├── auth/              # Role-based login & registration (Buyer / Merchant)
│   │   ├── buyer/             # Buyer dashboard, negotiation interface & quote creation
│   │   ├── merchant/          # Merchant inventory management, discount controls & orders
│   │   ├── transaction/[id]/  # Transaction status & payment settlement view
│   │   └── users/             # User directory & active role switcher
│   ├── components/ui/         # UI components & particle animations
│   └── lib/                   # API clients & WebSocket hook (useRealtime.ts)
│
└── backend/                   # FastAPI Backend
    ├── app/
    │   ├── agents/            # LangGraph Negotiation Agents (Buyer, Merchant, Upsell, Orchestrator)
    │   ├── ml/                # Dynamic ML pricing models
    │   ├── payment/           # Razorpay provider & payment splitting services
    │   ├── auth.py            # JWT token authentication & password hashing
    │   ├── config.py          # Environment settings
    │   ├── database.py        # Database session management
    │   ├── models.py          # SQLAlchemy models
    │   ├── schemas.py         # Pydantic validation schemas
    │   ├── realtime.py        # WebSocket connection manager
    │   ├── rate_limit.py      # Request rate limiting
    │   └── main.py            # FastAPI main application
    └── tests/                 # Comprehensive test suite
```

---

## 🛠️ Local Development Setup

### 1. Backend (FastAPI)

```bash
cd backend

# Install dependencies (using uv or pip)
uv sync
# or: pip install -e .

# Configure environment variables
cp .env.example .env
# Edit .env with your Razorpay Keys and Gemini API Key

# Start the backend server
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend (Next.js)

```bash
cd frontend

# Install dependencies
npm install

# Start Next.js development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🧪 Testing

Run backend tests:

```bash
cd backend
pytest -v
```

---

## 🔒 Security & Environment Variables

Make sure never to commit your `.env` files. Copy `.env.example` and fill in:
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `GEMINI_API_KEY`
