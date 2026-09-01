import logging
from google import genai
from google.genai import types
from ..config import settings
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class UpsellAgent:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None

    def generate_upsell_offer(self, purchased_sku: str, purchased_name: str, available_inventory: List[Dict], merchant_id: int = None) -> Optional[dict]:
        """
        Analyzes the purchased item and recommends a cross-sell/upsell product from the catalog.
        If merchant_id is provided, only recommends items from the same merchant.
        """
        # Filter out the item they already bought, and optionally scope to same merchant
        other_items = [
            item for item in available_inventory
            if item['sku'] != purchased_sku
            and item['current_stock'] > 0
            and (merchant_id is None or item.get('merchant_id') == merchant_id)
        ]
        
        if not other_items:
            return None

        # Deterministic fallback if API key is invalid or client fails
        if not self.client:
            return self._deterministic_upsell(purchased_name, other_items)

        system_instruction = f"""
        You are a brilliant AI B2B Sales Representative for Project Nexus.
        The buyer has just successfully negotiated the purchase of: '{purchased_name}' (SKU: {purchased_sku}).
        
        Your goal is to suggest ONE highly complementary product from our available inventory to add to their order.
        You must pick the most logical pairing.
        Generate a persuasive, short 1-2 sentence pitch explaining why they need this with their order, and offer a slight bundle discount (e.g. 5-10%).
        
        Return ONLY valid JSON matching this schema:
        {{
            "recommended_sku": "<string: the exact SKU of the chosen product>",
            "pitch": "<string: your short, persuasive sales pitch>",
            "suggested_discount_percent": <float: discount percentage, e.g. 5.0>
        }}
        """

        catalog_str = "\n".join([f"- {item['name']} (SKU: {item['sku']}, Base Price: {item['base_price']} INR)" for item in other_items])
        
        prompt = f"""
        Available Catalog for Cross-Sell:
        {catalog_str}
        
        Generate the JSON recommendation.
        """

        try:
            response = self.client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.4
                )
            )
            import json
            result = json.loads(response.text.strip())
            
            # Validate that they actually picked a real SKU
            valid_skus = [i['sku'] for i in other_items]
            if result.get('recommended_sku') not in valid_skus:
                logger.warning(f"Upsell Agent hallucinated SKU {result.get('recommended_sku')}. Overriding.")
                return self._deterministic_upsell(purchased_name, other_items)
                
            return {
                "recommended_sku": result["recommended_sku"],
                "pitch": result.get("pitch", "We highly recommend adding this item to your order!"),
                "suggested_discount_percent": float(result.get("suggested_discount_percent", 5.0))
            }
            
        except Exception as e:
            logger.error(f"Error calling Gemini in UpsellAgent: {str(e)}. Falling back to deterministic.")
            return self._deterministic_upsell(purchased_name, other_items)

    def _deterministic_upsell(self, purchased_name: str, other_items: List[Dict]) -> dict:
        # Just pick the first available item
        target = other_items[0]
        return {
            "recommended_sku": target["sku"],
            "pitch": f"Did you know {target['name']} pairs perfectly with your new {purchased_name}? Add it to your cart for a 5% bundle discount!",
            "suggested_discount_percent": 5.0
        }
