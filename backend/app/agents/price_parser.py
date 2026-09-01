import re
import logging
from typing import Optional, Sequence, Any

logger = logging.getLogger(__name__)

def extract_agreed_price(text: str, fallback_messages: Optional[Sequence[Any]] = None) -> Optional[float]:
    """
    Robustly extracts the exact negotiated price from a message or negotiation transcript.
    Supports all currency notations (₹, Rs, Rs., INR, $, commas, decimals, bracketed expressions, unit indicators).
    Never defaults to catalog price if an actual negotiated bid/counter exists in the dialogue.
    """
    if not text:
        return None

    # Strategy 1: Explicit PROPOSAL_AGREED tag with price
    # e.g., "PROPOSAL_AGREED: 58000", "PROPOSAL_AGREED: ₹58,000", "PROPOSAL_AGREED: [₹58,000]", "PROPOSAL_AGREED: Rs. 58,000.00 / unit"
    match = re.search(
        r'PROPOSAL_AGREED\s*[:=\-]?\s*\[?\s*(?:₹|Rs\.?|INR|\$)?\s*([\d,]+(?:\.\d+)?)\s*(?:INR|Rs\.?|₹|\$)?\s*\]?',
        text,
        re.IGNORECASE
    )
    if match:
        try:
            val = float(match.group(1).replace(',', ''))
            if val > 0:
                return round(val, 2)
        except ValueError:
            pass

    # Strategy 2: If PROPOSAL_AGREED exists in text, extract first numerical price after the tag
    if "PROPOSAL_AGREED" in text:
        after_tag = text.split("PROPOSAL_AGREED", 1)[1]
        num_match = re.search(r'([\d,]+(?:\.\d+)?)', after_tag)
        if num_match:
            try:
                val = float(num_match.group(1).replace(',', ''))
                if val > 0:
                    return round(val, 2)
            except ValueError:
                pass

    # Strategy 3: Explicit acceptance phrases in text
    # e.g. "We accept your offer of ₹58,000", "deal confirmed at 58000", "agreed to terms at ₹58,000"
    agree_match = re.search(
        r'(?:accept|agreed?|deal at|settle at|close at|terms at|confirm.*?deal at)\s*(?:your offer of|the offer of|price of|rate of|at)?\s*[:=\-]?\s*\[?\s*(?:₹|Rs\.?|INR|\$)?\s*([\d,]+(?:\.\d+)?)',
        text,
        re.IGNORECASE
    )
    if agree_match:
        try:
            val = float(agree_match.group(1).replace(',', ''))
            if val > 0:
                return round(val, 2)
        except ValueError:
            pass

    # Strategy 4: Fallback to recent message history if PROPOSAL_AGREED was stated without inline number
    if fallback_messages:
        for msg in reversed(fallback_messages):
            msg_text = msg.content if hasattr(msg, "content") else str(msg)
            # Find quoted unit prices > 50 (ignoring small integer counters like turns/units)
            prices = re.findall(r'(?:₹|Rs\.?|INR|\$)?\s*([\d,]+(?:\.\d+)?)\s*(?:per unit|INR|Rs\.?|₹|\$|/-)?', msg_text)
            for p in prices:
                try:
                    val = float(p.replace(',', ''))
                    if val > 50:
                        return round(val, 2)
                except ValueError:
                    continue

    return None
