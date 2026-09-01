import logging
import re
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from ..config import settings
from ..ml.pricing import pricing_engine
from .price_parser import extract_agreed_price

logger = logging.getLogger(__name__)

def _clamp_price(counter: float, buyer_bid: float | None, merchant_floor: float, catalog_price: float) -> float:
    """
    Deterministic backend price guardrails:
    1. If buyer already offered >= floor, never counter below buyer's offer.
    2. Never counter below merchant floor.
    3. Never counter above catalog price.
    """
    if buyer_bid is not None and buyer_bid >= merchant_floor:
        counter = max(counter, buyer_bid)
    counter = max(counter, merchant_floor)
    counter = min(counter, catalog_price)
    return round(counter, 2)

class MerchantAgent:
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", api_key=settings.GEMINI_API_KEY, temperature=0.2, max_retries=0) if settings.GEMINI_API_KEY else None

    def invoke(self, state: dict) -> dict:
        merchant_floor = state.get("merchant_floor_price", 0)
        catalog_price = state.get("catalog_price", 0)
        merchant_name = state.get("merchant_wholesaler_name", "Wholesaler")
        max_turns = state.get("max_turns", 5)
        turns = state.get("turns", 0)

        # Check if the last message from the Buyer was already an agreement
        last_msg_text = state['messages'][-1].content if state.get('messages') else ""
        if "PROPOSAL_AGREED" in last_msg_text:
            extracted_val = extract_agreed_price(last_msg_text, state.get('messages'))
            price_str = f"{extracted_val:.2f}" if extracted_val is not None else (f"{buyer_bid:.2f}" if buyer_bid else str(catalog_price))
            return {
                "messages": [AIMessage(content=f"We confirm the deal. PROPOSAL_AGREED: {price_str}", name="Merchant")]
            }

        # Extract buyer's latest bid from message history
        buyer_bid = None
        for msg in reversed(state.get('messages', [])):
            text = msg.content if hasattr(msg, 'content') else str(msg)
            prices = re.findall(r'\$?([\d,]+\.?\d*)', text)
            for p in prices:
                try:
                    val = float(p.replace(',', ''))
                    if val > 100:
                        buyer_bid = val
                        break
                except ValueError:
                    continue
            if buyer_bid:
                break

        if not self.llm:
            return self._heuristic_merchant_response(state, turns, max_turns, merchant_floor, catalog_price, merchant_name, buyer_bid)
            
        buyer_bid_str = f"₹{buyer_bid:,.2f}" if buyer_bid is not None else "None"
        system_prompt = f"""System Role: You are the autonomous Merchant Agent representing {merchant_name} from Global Wholesale Inventory.
Primary Commercial Objective: Maximize merchant profit margin while successfully closing B2B wholesale transactions.

Confidential Parameters:
* Catalog Listed Price (Anchor): ₹{catalog_price:,.2f}
* Confidential Merchant Floor Price: ₹{merchant_floor:,.2f} (STRICTLY CONFIDENTIAL. Never reveal, mention, or counter below this).
* Current Buyer Offer: {buyer_bid_str}

Strategic Negotiation Directives:
1. ANCHORING: If this is the initial round, quote the catalog price (₹{catalog_price:,.2f}).
2. NEVER CONCEDE BELOW BUYER'S OFFER:
   - If the Buyer's current offer is already above your floor (₹{merchant_floor:,.2f}), the buyer has already committed to this level.
   - You MUST NEVER counter below the buyer's offer.
   - Negotiate UPWARD from the buyer's offer towards catalog price.
3. CONCESSION CURVE:
   - Concede gradually in small steps to preserve merchant margin.
   - If the Buyer's counter is within 3% of your last offer, or if round {max_turns} is reached and buyer offer >= floor, you may close by stating: "PROPOSAL_AGREED: [Final Price]".
4. STRICT FAILURE CONDITION:
   - If round {max_turns} passes and buyer's offer remains strictly below ₹{merchant_floor:,.2f}, state: "NEGOTIATION_FAILED".
5. SECURITY: Never disclose your floor price (₹{merchant_floor:,.2f}) or internal margin formulas under any circumstances."""

        messages = [SystemMessage(content=system_prompt)]
        for msg in state['messages']:
            if getattr(msg, 'name', '') == "Merchant":
                messages.append(AIMessage(content=msg.content))
            else:
                messages.append(HumanMessage(content=msg.content))
        
        if len(messages) == 1:
            messages.append(HumanMessage(content="Hello, I am the Buyer Agent. I am interested in your product. What is your initial offer?"))
        
        try:
            response = self.llm.invoke(messages)
            content = response.content
            if isinstance(content, list):
                content = " ".join([str(item.get("text", "")) for item in content if isinstance(item, dict) and "text" in item])
            
            # Post-process LLM response with deterministic guardrails
            if "PROPOSAL_AGREED" in content:
                extracted_val = extract_agreed_price(content, state.get('messages'))
                if extracted_val is not None:
                    val = extracted_val
                    if val < merchant_floor:
                        # Reject invalid agreement below floor
                        logger.warning(f"LLM agreed below floor ({val} < {merchant_floor}). Enforcing guardrail.")
                        val = _clamp_price(val, buyer_bid, merchant_floor, catalog_price)
                        content = f"We can accept your proposal at our minimum threshold. PROPOSAL_AGREED: {val:.2f}"
                    else:
                        content = f"We confirm the agreed terms. PROPOSAL_AGREED: {val:.2f}"
            else:
                # Check for counter-offer price in text and clamp if violated
                match = re.search(r'(?:offer|counter|price|rate|at)\s*(?:of|is)?\s*₹?\s*([\d,]+\.?\d*)', content, re.IGNORECASE)
                if match:
                    try:
                        extracted = float(match.group(1).replace(',', ''))
                        if extracted > 100:
                            clamped = _clamp_price(extracted, buyer_bid, merchant_floor, catalog_price)
                            if clamped != extracted:
                                content = re.sub(re.escape(match.group(1)), f"{clamped:,.2f}", content)
                    except ValueError:
                        pass

            response.content = content
            response.name = "Merchant"
            return {"messages": [response]}
        except Exception as e:
            logger.warning(f"MerchantAgent LLM unavailable ({e}). Triggering ML pricing fallback.")
            return self._heuristic_merchant_response(state, turns, max_turns, merchant_floor, catalog_price, merchant_name, buyer_bid)

    def _heuristic_merchant_response(self, state: dict, turns: int, max_turns: int, merchant_floor: float, catalog_price: float, merchant_name: str, buyer_bid: float | None) -> dict:
        """
        Deterministic, strategic merchant negotiation algorithm.
        Optimizes for maximum merchant margin while reaching computational consensus.
        """
        # If it is the first turn, quote catalog price
        if not state.get('messages'):
            return {
                "messages": [AIMessage(
                    content=f"Greetings from {merchant_name}. Our standard catalog rate is ₹{catalog_price:,.2f} per unit. We welcome your bulk proposal.",
                    name="Merchant"
                )]
            }

        # If buyer bid is at or exceeds catalog price, agree immediately
        if buyer_bid and buyer_bid >= catalog_price:
            return {
                "messages": [AIMessage(
                    content=f"We appreciate your business. PROPOSAL_AGREED: {buyer_bid:.2f}",
                    name="Merchant"
                )]
            }

        # Case 1: Buyer has not made an identifiable bid yet
        if not buyer_bid:
            return {
                "messages": [AIMessage(
                    content=f"Our standard catalog rate is ₹{catalog_price:,.2f} per unit. Please share your target volume and pricing proposal.",
                    name="Merchant"
                )]
            }

        # Case 2: Buyer bid is BELOW merchant floor
        if buyer_bid < merchant_floor:
            if turns >= max_turns:
                return {
                    "messages": [AIMessage(content="NEGOTIATION_FAILED", name="Merchant")]
                }
            # Concede gradually toward floor + margin buffer
            step_progress = min(1.0, (turns + 1) / max_turns)
            target = merchant_floor * 1.05
            counter = catalog_price - (catalog_price - target) * step_progress
            counter = _clamp_price(counter, buyer_bid, merchant_floor, catalog_price)
            return {
                "messages": [AIMessage(
                    content=f"Thank you for your proposal. Given our operational standards and volume commitments, we cannot meet your figure. In the spirit of partnership, we can offer ₹{counter:,.2f} per unit. Does this work for you?",
                    name="Merchant"
                )]
            }

        # Case 3: Buyer bid is AT OR ABOVE merchant floor!
        # Merchant-favouring strategy:
        # Headroom is the space between buyer's offer and catalog listed price.
        headroom = catalog_price - buyer_bid
        
        # Concession aggression decays as turns progress: 0.8 on turn 1 -> 0.2 by turn 5
        aggression = max(0.2, 0.8 - (0.6 * (turns / max(1, max_turns))))
        counter_offer = buyer_bid + (headroom * aggression)
        counter_offer = _clamp_price(counter_offer, buyer_bid, merchant_floor, catalog_price)

        # Check if buyer's offer is close enough to close the deal (headroom < 4% or final turns)
        gap_percentage = (catalog_price - buyer_bid) / catalog_price if catalog_price else 0
        if turns >= (max_turns - 1) or gap_percentage <= 0.04 or abs(counter_offer - buyer_bid) <= 150:
            final_settlement = round((buyer_bid + counter_offer) / 2.0, 2)
            final_settlement = _clamp_price(final_settlement, buyer_bid, merchant_floor, catalog_price)
            return {
                "messages": [AIMessage(
                    content=f"We value this long-term partnership and accept your terms at ₹{final_settlement:,.2f} per unit. PROPOSAL_AGREED: {final_settlement:.2f}",
                    name="Merchant"
                )]
            }

        return {
            "messages": [AIMessage(
                content=f"We appreciate your counter-offer. Based on current inventory velocity, we can adjust our rate to ₹{counter_offer:,.2f} per unit. We believe this represents exceptional value for this volume.",
                name="Merchant"
            )]
        }

