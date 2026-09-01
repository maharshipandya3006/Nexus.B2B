import hmac
import hashlib
import json
import logging
import operator
import re
from datetime import datetime, timedelta
from typing import TypedDict, Annotated, Sequence
from sqlalchemy.orm import Session
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END

from .. import models
from .buyer import BuyerAgent
from .merchant import MerchantAgent
from .price_parser import extract_agreed_price
from ..config import settings

logger = logging.getLogger(__name__)

def generate_cart_mandate(sku: str, quantity: int, price: float, merchant_id: int = 0, inventory_id: int = 0) -> str:
    """
    Generates a cryptographically signed cart mandate.
    Includes merchant_id and inventory_id to prevent cross-merchant tampering.
    """
    payload = {
        "sku": sku,
        "quantity": quantity,
        "price": price,
        "merchant_id": merchant_id,
        "inventory_id": inventory_id,
        "timestamp": datetime.utcnow().isoformat()
    }
    payload_str = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        payload_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"{payload_str}.{signature}"

def verify_cart_mandate(mandate_token: str) -> bool:
    try:
        parts = mandate_token.rsplit(".", 1)
        if len(parts) != 2:
            return False
        payload_str, signature = parts
        expected_signature = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            payload_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected_signature, signature)
    except Exception:
        return False

class NegotiationState(TypedDict):
    transaction_id: int
    messages: Annotated[Sequence[BaseMessage], operator.add]
    sku: str
    item_name: str
    catalog_price: float
    buyer_max_budget: float
    merchant_floor_price: float
    merchant_wholesaler_name: str
    merchant_id: int       # Dynamic merchant identity
    inventory_id: int      # Exact listing being negotiated
    max_turns: int
    turns: int

class NegotiationOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.buyer_agent = BuyerAgent()
        self.merchant_agent = MerchantAgent()

        workflow = StateGraph(NegotiationState)
        workflow.add_node("merchant_node", self._run_merchant)
        workflow.add_node("buyer_node", self._run_buyer)
        
        workflow.set_entry_point("merchant_node")
        
        workflow.add_conditional_edges(
            "merchant_node",
            self._check_status,
            {
                "continue": "buyer_node",
                "agreed": END,
                "failed": END
            }
        )

        workflow.add_conditional_edges(
            "buyer_node",
            self._check_status,
            {
                "continue": "merchant_node",
                "agreed": END,
                "failed": END
            }
        )
        
        self.graph = workflow.compile()

    def _run_merchant(self, state: dict):
        result = self.merchant_agent.invoke(state)
        msg_content = result["messages"][0].content
        log = models.AuditLog(
            transaction_id=state['transaction_id'],
            actor="Merchant Agent",
            message=msg_content
        )
        self.db.add(log)
        self.db.commit()
        return result

    def _run_buyer(self, state: dict):
        result = self.buyer_agent.invoke(state)
        msg_content = result["messages"][0].content
        log = models.AuditLog(
            transaction_id=state['transaction_id'],
            actor="Buyer Agent",
            message=msg_content
        )
        self.db.add(log)
        self.db.commit()
        return result

    def _check_status(self, state: dict):
        last_message = state["messages"][-1].content
        if "PROPOSAL_AGREED" in last_message:
            return "agreed"
        if "NEGOTIATION_FAILED" in last_message:
            return "failed"
        if state.get("turns", 0) >= state.get("max_turns", 5):
            return "failed"
        return "continue"

    def run_negotiation(self, transaction_id: int, buyer_max_budget: float) -> dict:
        transaction = self.db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
        if not transaction:
            raise ValueError("Transaction not found")

        # Look up by inventory_id for merchant-specific pricing (not by SKU!)
        if transaction.inventory_id:
            item = self.db.query(models.Inventory).filter(
                models.Inventory.id == transaction.inventory_id
            ).first()
        else:
            # Fallback for legacy transactions without inventory_id
            item = self.db.query(models.Inventory).filter(
                models.Inventory.sku == transaction.sku
            ).first()

        if not item:
            transaction.status = models.TransactionStatus.FAILED
            self.db.commit()
            return {"status": "failed", "reason": "SKU not found in catalog"}

        # Resolve merchant display name dynamically
        merchant_profile = self.db.query(models.MerchantProfile).filter(
            models.MerchantProfile.user_id == item.merchant_id
        ).first()
        merchant_display = merchant_profile.display_name if merchant_profile else item.wholesaler_name

        # ----------------------------------------------------
        # 1. TRACK 2 CROSSOVER: AI Anomaly & Fraud Risk Gating
        # ----------------------------------------------------
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        past_txs = self.db.query(models.Transaction).filter(
            models.Transaction.buyer_id == transaction.buyer_id,
            models.Transaction.status == models.TransactionStatus.PAID,
            models.Transaction.created_at >= thirty_days_ago
        ).all()
        
        if len(past_txs) >= 3:
            avg_qty = sum(tx.quantity for tx in past_txs) / len(past_txs)
            anomaly_threshold = avg_qty * 10.0 # 10x multiplier
            if transaction.quantity > anomaly_threshold:
                transaction.status = models.TransactionStatus.FAILED
                log = models.AuditLog(
                    transaction_id=transaction.id,
                    actor="System Anomaly Guard",
                    message=f"CRITICAL: Transaction flagged. Requested quantity ({transaction.quantity}) is {transaction.quantity/avg_qty:.1f}x the 30-day average. Blocked for potential merchant inventory draining."
                )
                self.db.add(log)
                self.db.commit()
                return {"status": "failed", "reason": "Anomaly Block: Order quantity exceeds safety threshold limit."}

        # ----------------------------------------------------
        # 2. Main Negotiation Loop (LangGraph StateMachine)
        # ----------------------------------------------------
        start_log = models.AuditLog(
            transaction_id=transaction.id,
            actor="System Orchestrator",
            message=f"Negotiation initiated for {transaction.quantity} units of '{item.name}' with merchant '{merchant_display}'. Base Price: {item.base_price} INR."
        )
        self.db.add(start_log)
        self.db.commit()
        
        initial_state = {
            "transaction_id": transaction.id,
            "messages": [],
            "sku": item.sku,
            "item_name": item.name,
            "catalog_price": item.base_price,
            "buyer_max_budget": buyer_max_budget,
            "merchant_floor_price": item.minimum_margin_limit,
            "merchant_wholesaler_name": merchant_display,
            "merchant_id": item.merchant_id,
            "inventory_id": item.id,
            "max_turns": 5,
            "turns": 0
        }

        # Run the graph synchronously
        try:
            final_state = self.graph.invoke(initial_state)
        except Exception as e:
            logger.error(f"LangGraph execution error: {e}")
            transaction.status = models.TransactionStatus.FAILED
            self.db.commit()
            return {"status": "failed", "reason": "Graph execution failed"}

        # Search messages in reverse order for agreed proposal
        agreed_price = None
        for msg in reversed(final_state.get("messages", [])):
            text = msg.content if hasattr(msg, "content") else str(msg)
            if "PROPOSAL_AGREED" in text or "agree" in text.lower() or "accept" in text.lower():
                agreed_price = extract_agreed_price(text, final_state.get("messages", []))
                if agreed_price is not None:
                    break

        if agreed_price is not None:
            # Deterministic backend safety validation
            if agreed_price < item.minimum_margin_limit:
                logger.warning(f"Agreed price {agreed_price} was below minimum floor {item.minimum_margin_limit}. Clamping to floor.")
                agreed_price = item.minimum_margin_limit

            # 1. Create canonical AI Quote (concluded by AI, pending independent human approvals)
            ai_quote = models.Quote(
                transaction_id=transaction.id,
                amount=agreed_price,
                proposed_by="AI",
                source=models.QuoteSource.AI_NEGOTIATION,
                merchant_accepted=None,
                buyer_accepted=None,
                status=models.QuoteStatus.PENDING,
                note="Autonomous AI consensus reached during multi-turn negotiation. Awaiting mutual human approval.",
                created_at=datetime.utcnow()
            )
            self.db.add(ai_quote)
            self.db.flush()

            # 2. Link quote to transaction - State 2: AI_NEGOTIATION_COMPLETED
            transaction.status = models.TransactionStatus.AI_NEGOTIATION_COMPLETED
            transaction.agreed_quote_id = ai_quote.id
            transaction.final_price = agreed_price
            transaction.buyer_approved = 0
            transaction.merchant_approved = 0
            transaction.cryptographic_signature = generate_cart_mandate(
                transaction.sku, transaction.quantity, agreed_price,
                merchant_id=item.merchant_id,
                inventory_id=item.id
            )
            self.db.commit()
            
            log = models.AuditLog(
                transaction_id=transaction.id,
                actor="System Orchestrator",
                message=(
                    f"AI negotiation completed with merchant '{merchant_display}' at ₹{agreed_price:,.2f} (Quote #{ai_quote.id}). "
                    f"AI negotiation ends. Awaiting independent mutual approval from Buyer and Merchant."
                )
            )
            self.db.add(log)
            self.db.commit()
            
            return {
                "status": "ai_negotiation_completed",
                "final_price": agreed_price,
                "quote_id": ai_quote.id,
                "signature": transaction.cryptographic_signature
            }
        else:
            transaction.status = models.TransactionStatus.TERMINATED
            self.db.commit()
            log = models.AuditLog(
                transaction_id=transaction.id,
                actor="System Orchestrator",
                message=f"Negotiation with merchant '{merchant_display}' failed to reach consensus. Final status: TERMINATED."
            )
            self.db.add(log)
            self.db.commit()
            return {"status": "failed", "reason": "No agreement reached."}
