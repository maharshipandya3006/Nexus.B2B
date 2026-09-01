import logging
import re
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from ..config import settings
from .price_parser import extract_agreed_price

logger = logging.getLogger(__name__)

class BuyerAgent:
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            api_key=settings.GEMINI_API_KEY,
            temperature=0.2,
            max_retries=0,
            timeout=5.0
        ) if settings.GEMINI_API_KEY else None

    def invoke(self, state: dict) -> dict:
        current_turns = state.get("turns", 0) + 1
        max_turns = state.get("max_turns", 5)
        buyer_budget = state.get("buyer_max_budget", 0)
        catalog_price = state.get("catalog_price", 0)

        # Check if the last message from the Merchant was already an agreement
        last_msg_text = state['messages'][-1].content if state.get('messages') else ""
        if "PROPOSAL_AGREED" in last_msg_text:
            extracted_val = extract_agreed_price(last_msg_text, state.get('messages'))
            price_str = f"{extracted_val:.2f}" if extracted_val is not None else (f"{buyer_budget:.2f}" if buyer_budget else str(catalog_price))
            return {
                "messages": [AIMessage(content=f"Thank you for working with us. PROPOSAL_AGREED: {price_str}", name="Buyer")],
                "turns": current_turns
            }

        if not self.llm:
            return self._heuristic_buyer_response(state, current_turns, max_turns, buyer_budget, catalog_price)
            
        system_prompt = f"""System Role: You are the autonomous Buyer Agent. Your objective is to secure the lowest possible price for {state['item_name']} without causing the negotiation to fail.
Context: You are negotiating directly with the Merchant Agent. You have a maximum budget of {buyer_budget}. You do not know the merchant's minimum price.
Directives:
* Start with a low but respectful initial offer (around 75-80% of catalog price).
* Analyze the Merchant Agent's counter-offers. Adjust your bids incrementally upward towards your maximum budget.
* If the Merchant Agent's offer falls at or below your maximum budget ({buyer_budget}), state: "PROPOSAL_AGREED: [Final Price]".
* If you cannot reach an agreement below your budget after {max_turns} rounds, state: "NEGOTIATION_FAILED".
* Never reveal your maximum budget to the Merchant Agent."""

        messages = [SystemMessage(content=system_prompt)]
        for msg in state['messages']:
            if getattr(msg, 'name', '') == "Buyer":
                messages.append(AIMessage(content=msg.content))
            else:
                messages.append(HumanMessage(content=msg.content))
                
        if len(messages) == 1:
            messages.append(HumanMessage(content="Hello, I am the Merchant. Please make your initial offer."))
        
        try:
            response = self.llm.invoke(messages)
            content = response.content
            if isinstance(content, list):
                content = " ".join([str(item.get("text", "")) for item in content if isinstance(item, dict) and "text" in item])
            response.content = content
            response.name = "Buyer"
            return {"messages": [response], "turns": current_turns}
        except Exception as e:
            logger.warning(f"BuyerAgent LLM unavailable ({e}). Triggering autonomous strategic fallback.")
            return self._heuristic_buyer_response(state, current_turns, max_turns, buyer_budget, catalog_price)

    def _heuristic_buyer_response(self, state: dict, current_turns: int, max_turns: int, buyer_budget: float, catalog_price: float) -> dict:
        """
        Deterministic, strategic procurement algorithm when LLM quota/rate limit is reached.
        Ensures negotiations never fail due to API rate limits.
        """
        # Extract the last quoted merchant price from messages
        merchant_price = None
        for msg in reversed(state.get('messages', [])):
            text = msg.content if hasattr(msg, 'content') else str(msg)
            prices = re.findall(r'\$?([\d,]+\.?\d*)', text)
            for p in prices:
                try:
                    val = float(p.replace(',', ''))
                    if val > 100:  # Avoid matching low numbers like quantities
                        merchant_price = val
                        break
                except ValueError:
                    continue
            if merchant_price:
                break

        if not merchant_price:
            merchant_price = catalog_price

        # If the merchant's price is already within our budget, ACCEPT!
        if merchant_price <= buyer_budget:
            return {
                "messages": [AIMessage(
                    content=f"That price is acceptable and aligns with our procurement parameters. PROPOSAL_AGREED: {merchant_price:.2f}",
                    name="Buyer"
                )],
                "turns": current_turns
            }

        # If max turns reached and merchant still exceeds budget
        if current_turns >= max_turns:
            return {
                "messages": [AIMessage(content="NEGOTIATION_FAILED", name="Buyer")],
                "turns": current_turns
            }

        # Offer an incremental step towards our max budget
        step_progress = min(1.0, current_turns / max_turns)
        initial_bid = min(buyer_budget * 0.85, catalog_price * 0.75)
        current_bid = round(initial_bid + (buyer_budget - initial_bid) * step_progress, 2)

        return {
            "messages": [AIMessage(
                content=f"We appreciate your counter-proposal. Based on our volume commitment and market benchmark analysis, we can increase our offer to ₹{current_bid:,.2f} per unit. Can we meet at this level?",
                name="Buyer"
            )],
            "turns": current_turns
        }
