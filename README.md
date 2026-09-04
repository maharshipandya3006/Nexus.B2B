# Nexus B2B

## Autonomous AI Negotiation and Secure B2B Settlement Platform

Nexus B2B is an AI powered wholesale procurement platform where **AI agents negotiate prices between buyers and merchants, while deterministic systems verify, approve, and settle the final transaction**.

The platform combines autonomous multi-agent negotiation, real-time communication, cryptographic price verification, inventory reservation, human approval, and Razorpay payments into a single B2B transaction workflow.

> **The AI negotiates. The system verifies. Humans approve. Razorpay settles.**

Two AI agents can negotiate a deal in real time, but the final monetary transaction is never based on trust alone. Every negotiated price is validated, protected against tampering, and explicitly approved before payment.

Built for the **Razorpay Buildathon 2026**.

---

## Live Demo

| Service           | URL                                         | Description                                 |
| ----------------- | ------------------------------------------- | ------------------------------------------- |
| Frontend          | https://nexus-b2b-xi.vercel.app             | Next.js web application                     |
| Backend API       | https://nexus-b2b-backend.onrender.com      | FastAPI backend                             |
| API Documentation | https://nexus-b2b-backend.onrender.com/docs | Interactive OpenAPI / Swagger documentation |

### Demo Accounts

| Role     | Username           | Password           | Capabilities                                                            |
| -------- | ------------------ | ------------------ | ----------------------------------------------------------------------- |
| Buyer    | `retail_purchaser` | `retail_purchaser` | Browse inventory, launch procurement, negotiate, review quotes and pay  |
| Merchant | `tech_distributor` | `tech_distributor` | Manage inventory, configure pricing floors, negotiate and revise quotes |

---

# What Problem Does Nexus B2B Solve?

Traditional B2B procurement is heavily dependent on manual negotiation.

A typical transaction looks like:

```text
Buyer finds supplier
        ↓
Buyer requests quotation
        ↓
Merchant responds
        ↓
Buyer negotiates
        ↓
Merchant counters
        ↓
More messages / calls / emails
        ↓
Both parties agree
        ↓
Manual payment
        ↓
Inventory reconciliation
```

This process becomes increasingly inefficient when:

* multiple products are being purchased
* multiple merchants are involved
* prices need to be negotiated dynamically
* inventory changes during negotiation
* procurement teams operate at scale
* payment integrity matters
* every participant needs an auditable transaction state

Nexus B2B turns this into an automated transaction pipeline:

```text
Buyer Requirement
       ↓
AI Procurement Agent
       ↓
AI Merchant Agent
       ↓
Multi-Turn Negotiation
       ↓
Price Convergence
       ↓
Cryptographic Price Verification
       ↓
Human Approval
       ↓
Inventory Reservation
       ↓
Razorpay Checkout
       ↓
Webhook Verification
       ↓
Settlement
```

---

# Core Idea

Nexus B2B is not designed around unrestricted AI autonomy.

Instead, it separates **decision-making** from **financial authority**.

### AI handles

* price negotiation
* strategic concessions
* merchant counter-offers
* budget-aware bidding
* inventory-aware pricing
* cross-selling opportunities
* negotiation orchestration

### Deterministic backend handles

* price validation
* merchant floor enforcement
* authentication
* inventory locking
* transaction state
* payment verification
* HMAC signatures
* webhook validation
* idempotency

### Humans handle

* final approval
* revised quotes
* cancellation
* payment authorization

This creates a controlled autonomy model:

```text
             AI
      Negotiates the Deal
              │
              ▼
      Deterministic System
       Verifies the Deal
              │
              ▼
            Human
       Approves the Deal
              │
              ▼
          Razorpay
       Settles the Deal
```

---

# Key Features

## 1. Autonomous Multi-Agent Negotiation

Nexus B2B uses a LangGraph-based multi-agent architecture with Gemini-powered agents.

### Buyer Procurement Agent

The buyer agent negotiates within a strict budget boundary.

It:

* starts from a strategic opening bid
* follows a concession curve
* increases its offer over multiple rounds
* never exceeds the buyer's maximum budget
* reacts to merchant counter-offers
* evaluates whether a deal is economically acceptable

The buyer's maximum budget acts as a hard constraint rather than a suggestion.

---

### Merchant Wholesaler Agent

The merchant agent protects the economics of the seller.

It evaluates factors such as:

* catalog price
* inventory velocity
* order quantity
* minimum acceptable price
* negotiation history
* commercial opportunity

The merchant agent can dynamically generate counter-offers while respecting the configured floor price.

---

### Orchestrator Agent

The orchestrator coordinates the negotiation state.

Its responsibilities include:

* managing agent turns
* maintaining negotiation state
* detecting price convergence
* enforcing negotiation constraints
* determining when a deal can progress
* generating the final settlement quote
* signing the agreed settlement information

This prevents individual agents from independently controlling the complete transaction lifecycle.

---

### Strategic Upsell Agent

Once a deal reaches finalization, the upsell agent can analyze:

* previous order patterns
* related catalog products
* product pairings
* volume opportunities

It can then generate:

* cross-sell recommendations
* bundle opportunities
* volume discounts

---

# 2. Human-in-the-Loop Approval

Nexus B2B deliberately does not allow an AI agent to independently authorize a financial transaction.

After negotiation, both sides must explicitly approve the final quote.

```text
AI Negotiation
      ↓
Final Negotiated Price
      ↓
Buyer Approval ─────┐
                    ├──→ Transaction Approved
Merchant Approval ──┘
      ↓
Razorpay Payment
```

If either party rejects the proposal, the transaction does not proceed automatically.

Both buyers and merchants can also submit revised quotes manually after the AI negotiation has completed.

This provides a practical balance between:

**automation + control + accountability**

---

# 3. Cryptographically Protected Pricing

One of the most important design decisions in Nexus B2B is that the negotiated price is not trusted simply because it came from the frontend.

The backend generates an HMAC-SHA256 signature over critical transaction information.

Conceptually:

```text
Negotiated Price
Merchant Route
Cart Parameters
       ↓
   HMAC-SHA256
       ↓
Signed Settlement Mandate
       ↓
Razorpay Order Creation
```

This protects the transaction from client-side price manipulation.

If a user attempts to modify the price after negotiation, the cryptographic validation fails.

The system therefore treats the backend as the authoritative source of monetary state.

---

# 4. Razorpay Payment & Settlement

Nexus B2B integrates Razorpay into the transaction lifecycle.

The payment pipeline includes:

* Razorpay Standard Checkout
* server-side order creation
* HMAC validation
* webhook verification
* idempotent order handling
* inventory reservation
* payment confirmation
* merchant routing
* settlement tracking

The payment system is designed so that the negotiated price is carried through the transaction rather than being independently reconstructed by the client.

---

# 5. Inventory Reservation

Inventory is protected during the payment process.

When a transaction reaches the payment stage:

```text
Available Inventory
        ↓
Temporary Reservation
        ↓
Payment Window
        ↓
   ┌────┴────┐
   ↓         ↓
Success    Failure/Expiry
   ↓         ↓
Capture    Release
```

This prevents multiple procurement attempts from consuming the same inventory during concurrent transactions.

Expired or failed payments release the reserved stock.

---

# 6. Multi-Merchant Procurement

Nexus B2B is designed around wholesale procurement where an order can involve multiple merchants.

The system tracks merchant-specific transaction information and supports vendor-specific payment routing.

Conceptually:

```text
                 Buyer Order
                     │
          ┌──────────┼──────────┐
          ↓          ↓          ↓
      Merchant A  Merchant B  Merchant C
          │          │          │
       Quote A    Quote B    Quote C
          │          │          │
          └──────────┼──────────┘
                     ↓
              Payment Engine
                     ↓
          Vendor-specific settlement
```

This architecture makes the platform suitable for marketplace-style B2B procurement rather than a single-vendor checkout system.

---

# 7. Real-Time Negotiation

Negotiations are streamed in real time using WebSockets.

The frontend receives live events for:

* buyer bids
* merchant counter-offers
* AI negotiation progress
* revised quotes
* approval state changes
* cancellations
* payment updates
* transaction events

The goal is to eliminate the need for users to repeatedly refresh the dashboard to see negotiation changes.

---

# 8. Resilient WebSocket Authentication

The WebSocket layer supports automatic authentication refresh.

When a JWT expires, the connection can perform a silent refresh and reconnect without requiring the user to manually reload the application.

The system also handles connection lifecycle events and heartbeat communication.

This is particularly important during long-running AI negotiations where a user should not lose their active session simply because an access token expires.

---

# 9. Secure Authentication

The backend implements:

* JWT authentication
* password hashing
* token expiration
* token refresh
* rate limiting
* brute-force protection
* account lockout mechanisms

Authentication is shared across the buyer and merchant applications while maintaining role-specific access.

---

# 10. Quote State Management

Negotiation is represented as a controlled transaction state machine rather than a collection of loosely connected UI states.

The quote workflow handles:

* AI-generated offers
* counter-offers
* price convergence
* merchant floor validation
* buyer decisions
* merchant decisions
* manual revised quotes
* cancellation
* final approval
* payment progression

This makes the state of a transaction deterministic and testable.

---

# Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                        NEXUS B2B                             │
└──────────────────────────────────────────────────────────────┘

                    BUYER APPLICATION
                Next.js / React / WebSocket
                         │
                         │ HTTPS / WSS
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                       FASTAPI CORE                           │
│                                                              │
│   ┌───────────────┐    ┌────────────────┐                    │
│   │ Authentication│    │ WebSocket      │                    │
│   │ JWT / BCrypt  │    │ Manager        │                    │
│   └───────────────┘    └────────────────┘                    │
│                                                              │
│   ┌───────────────┐    ┌────────────────┐                    │
│   │ Rate Limiter  │    │ Transaction    │                    │
│   │ / Lockout     │    │ State Manager  │                    │
│   └───────────────┘    └────────────────┘                    │
│                         │                                    │
│                         ▼                                    │
│              LANGGRAPH AGENT RUNTIME                         │
│                                                              │
│       ┌──────────────────┐    ┌──────────────────┐           │
│       │   Buyer Agent    │◄──►│ Merchant Agent   │           │
│       │ Budget Ceiling   │    │ Floor Protection │           │
│       └────────┬─────────┘    └────────┬─────────┘           │ 
│                │                       │                     │
│                └───────────┬───────────┘                     │
│                            ▼                                 │
│                  ┌──────────────────┐                        │
│                  │  Orchestrator    │                        │
│                  │  Agent           │                        │
│                  └────────┬─────────┘                        │
│                           │                                  │
│                           ▼                                  │
│                  Settlement Mandate                          │
│                           │                                  │
│                           ▼                                  │
│                  HMAC-SHA256 Validation                      │
│                           │                                  │
└───────────────────────────┼──────────────────────────────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │       RAZORPAY       │
                 │                      │
                 │ Standard Checkout    │
                 │ Order Creation       │
                 │ HMAC Verification    │
                 │ Webhooks             │
                 │ Route Splitting      │
                 │ Settlement           │
                 └──────────────────────┘
```

---

# Technology Stack

## Frontend

* Next.js 16
* React 19
* App Router
* Tailwind CSS 4
* WebSockets
* TypeScript
* Custom enterprise UI components

## Backend

* Python 3.11+
* FastAPI
* SQLAlchemy
* Pydantic
* Async database operations
* WebSockets
* JWT authentication
* BCrypt password hashing
* SlowAPI rate limiting

## AI / Agentic Layer

* LangGraph
* Gemini
* Multi-agent orchestration
* Concession-based negotiation
* Dynamic pricing logic
* Strategic upselling

## Payments

* Razorpay
* Razorpay Standard Checkout
* HMAC-SHA256
* Webhook verification
* Idempotent order creation
* Route splitting

## Database

* SQLAlchemy ORM
* SQLite for isolated testing
* PostgreSQL support for production environments

## Deployment

* Vercel for frontend
* Render for backend

---

# Repository Structure

```text
nexus-b2b/
│
├── frontend/
│   ├── app/
│   │   ├── auth/
│   │   │   └── # Buyer / Merchant authentication
│   │   │
│   │   ├── buyer/
│   │   │   └── # Buyer procurement dashboard
│   │   │
│   │   ├── merchant/
│   │   │   └── # Merchant inventory and deal management
│   │   │
│   │   ├── transaction/
│   │   │   └── [id]/
│   │   │       └── # Transaction, approvals and payment
│   │   │
│   │   └── users/
│   │       └── # User directory and profile switching
│   │
│   ├── components/
│   │   └── ui/
│   │       └── # Shared UI system
│   │
│   └── lib/
│       ├── API clients
│       ├── authentication refresh
│       └── WebSocket realtime hooks
│
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── buyer
│   │   │   ├── merchant
│   │   │   ├── upsell
│   │   │   └── orchestrator
│   │   │
│   │   ├── ml/
│   │   │   └── # Pricing and concession logic
│   │   │
│   │   ├── payment/
│   │   │   └── # Razorpay integration
│   │   │
│   │   ├── auth.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── realtime.py
│   │   ├── rate_limit.py
│   │   └── main.py
│   │
│   └── tests/
│       ├── test_auth_security.py
│       ├── test_quote_workflow.py
│       ├── test_price_logic.py
│       ├── test_multi_merchant_payment.py
│       └── test_realtime.py
│
└── README.md
```

---

# Transaction Lifecycle

A complete Nexus B2B transaction follows this lifecycle:

### 1. Product Discovery

The buyer browses merchant inventory and selects the required products and quantities.

### 2. Procurement Configuration

The buyer defines the maximum amount they are willing to pay.

### 3. AI Negotiation

The Buyer Agent begins negotiating with the Merchant Agent.

Both agents operate under their respective constraints.

### 4. Counter-Offers

Agents exchange offers until:

* a mutually acceptable price is reached
* negotiation constraints prevent further movement
* the negotiation is terminated

### 5. Final Quote

The Orchestrator determines the negotiated settlement price.

### 6. Human Approval

The buyer and merchant independently approve the final quote.

### 7. Cryptographic Validation

The backend signs the transaction parameters and protects the settlement price with HMAC-SHA256.

### 8. Inventory Reservation

Required inventory is temporarily locked.

### 9. Razorpay Checkout

The buyer completes payment through Razorpay.

### 10. Webhook Verification

The backend verifies the payment event.

### 11. Settlement

The transaction is finalized and the appropriate merchant routing and inventory updates are performed.

---

# Example Negotiation

Suppose a product is listed for:

```text
Catalog Price: ₹4,500
```

The buyer sets:

```text
Maximum Budget: ₹4,200
```

The negotiation can proceed:

```text
Buyer Agent
₹3,375
    ↓
Merchant Agent
₹4,450
    ↓
Buyer Agent
₹3,650
    ↓
Merchant Agent
₹4,250
    ↓
Buyer Agent
₹3,950
    ↓
Merchant Agent
₹4,100
    ↓
Negotiation Converges
```

The final price is then passed into the controlled approval and payment pipeline.

The key principle is that **the frontend does not get to redefine the negotiated price after agreement**.

---

# Security Model

Nexus B2B treats financial state as security-critical.

### Price Integrity

HMAC-SHA256 protects the negotiated settlement parameters.

### Authentication

JWT-based authentication protects API and real-time communication.

### Password Security

Passwords are hashed rather than stored as plaintext.

### Brute-Force Protection

Rate limiting and account lockout reduce credential attack risk.

### Payment Integrity

Razorpay payment verification and webhook validation prevent the frontend from declaring a transaction successful by itself.

### Idempotency

Payment operations are designed to safely handle retries without creating duplicate charges.

### Inventory Integrity

Atomic stock reservation prevents overselling during the payment window.

---

# Testing

Nexus B2B includes an automated backend test suite covering authentication, negotiation, payment, pricing, inventory, and real-time functionality.

Current test status:

```text
41 / 41 tests passing
```

Run the test suite:

```bash
cd backend
python3 -m pytest backend/tests -v
```

## Test Coverage

### `test_auth_security.py`

Tests:

* rate limiting
* brute-force protection
* account lockout
* token expiration
* password hashing

### `test_quote_workflow.py`

Tests:

* quote lifecycle
* merchant revised quotes
* buyer decisions
* merchant decisions
* floor-price validation

### `test_price_logic.py`

Tests:

* negotiation price authority
* concession curve behavior
* multi-merchant quote isolation

### `test_multi_merchant_payment.py`

Tests:

* Razorpay order creation
* HMAC verification
* stock reservation
* payment tamper prevention

### `test_realtime.py`

Tests:

* WebSocket broadcasts
* heartbeat handling
* dashboard event dispatching

---

# Local Development

## Prerequisites

* Node.js 18+
* npm
* Python 3.11+
* Python 3.13 recommended

---

## Backend

```bash
cd backend

python3 -m venv venv

source venv/bin/activate

pip install -r requirements.txt
```

Create the environment file:

```bash
cp .env.example .env
```

Configure the required environment variables:

```env
GEMINI_API_KEY=your_gemini_api_key

RAZORPAY_KEY_ID=your_razorpay_key_id
RAZORPAY_KEY_SECRET=your_razorpay_key_secret
```

Start the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

Backend:

```text
http://localhost:8000
```

Swagger documentation:

```text
http://localhost:8000/docs
```

---

# Frontend

```bash
cd frontend

npm install
```

Create the environment file:

```bash
cp .env.example .env.local
```

Configure:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

Start the frontend:

```bash
npm run dev
```

Open:

```text
http://localhost:3000
```

---

# Design Principles

Nexus B2B is built around several architectural principles.

## 1. Autonomy With Constraints

AI agents are allowed to make decisions, but only within explicitly defined financial and business constraints.

## 2. AI Is Not the Source of Financial Truth

The backend determines authoritative transaction state.

## 3. Human Approval for Money Movement

AI can negotiate a deal but does not independently authorize the final payment.

## 4. Cryptographic Verification

Critical financial parameters are cryptographically protected.

## 5. Real-Time by Default

Negotiation and transaction state should propagate immediately rather than depend on page refreshes.

## 6. Failure-Aware Architecture

Retries, expired payments, disconnected clients, duplicate requests and invalid transactions are treated as expected system conditions rather than exceptional afterthoughts.

---

# Why Nexus B2B?

Most AI commerce concepts stop at:

```text
AI → Recommendation
```

Nexus B2B goes further:

```text
AI
 ↓
Negotiation
 ↓
Agreement
 ↓
Verification
 ↓
Human Approval
 ↓
Payment
 ↓
Settlement
```

The important innovation is not simply putting an LLM into a procurement workflow.

It is connecting **agentic decision-making to a controlled financial execution layer**.

That creates a system where autonomous agents can negotiate commercially meaningful transactions without giving an LLM unrestricted authority over money.

---

# Project Highlights

| Capability                | Nexus B2B     |
| ------------------------- | ------------- |
| AI Negotiation            | Yes           |
| Multi-Agent Architecture  | Yes           |
| Buyer Agent               | Yes           |
| Merchant Agent            | Yes           |
| Orchestrator Agent        | Yes           |
| Strategic Upselling       | Yes           |
| Real-Time WebSockets      | Yes           |
| Human Approval            | Yes           |
| Manual Revised Quotes     | Yes           |
| Dynamic Pricing Logic     | Yes           |
| Merchant Floor Protection | Yes           |
| HMAC Price Protection     | Yes           |
| Razorpay Integration      | Yes           |
| Webhook Verification      | Yes           |
| Idempotent Payments       | Yes           |
| Inventory Reservation     | Yes           |
| Multi-Merchant Routing    | Yes           |
| JWT Authentication        | Yes           |
| Rate Limiting             | Yes           |
| Automated Tests           | 41/41 Passing |
| Production Deployment     | Yes           |

---

# Production Architecture

```text
                         INTERNET
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
        VERCEL FRONTEND             RENDER BACKEND
         Next.js 16                  FastAPI
              │                           │
              │ HTTPS / WSS               │
              └─────────────┬─────────────┘
                            │
                            ▼
                    APPLICATION CORE
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
       Auth             WebSocket          Agents
          │                 │                 │
          │                 │          ┌──────┴──────┐
          │                 │          │             │
          │                 │       Buyer        Merchant
          │                 │          │             │
          │                 │          └──────┬──────┘
          │                 │                 │
          │                 │                 ▼
          │                 │           Orchestrator
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                            ▼
                     Price Verification
                            │
                            ▼
                     Razorpay Checkout
                            │
                            ▼
                     Payment Webhooks
                            │
                            ▼
                       Settlement
```

---

# Roadmap

Potential future extensions include:

* richer merchant discovery and matching
* advanced procurement analytics
* historical negotiation intelligence
* supplier performance scoring
* larger multi-merchant procurement baskets
* more sophisticated pricing models
* expanded payment routing
* deeper ERP and inventory-system integrations
* enterprise procurement workflows
* negotiation analytics and reporting

---

# Buildathon

Nexus B2B was built for the **Razorpay Buildathon 2026** with the goal of exploring what happens when autonomous AI agents are connected directly to a secure financial execution layer.

The project focuses on a simple question:

> **What if AI could negotiate a B2B deal end-to-end, without being trusted blindly with the money?**

Nexus B2B is our answer.

---

# Author

**Maharshi Pandya**

Designed and developed for Razorpay Buildathon 2026.

---

# License

Distributed under the MIT License.
