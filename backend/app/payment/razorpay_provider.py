import hmac
import hashlib
import time
import uuid
import logging
from typing import Dict, Any, Optional
from ..config import settings

logger = logging.getLogger(__name__)

# Try to import razorpay if available, otherwise catch and run in mock only
try:
    import razorpay
    RAZORPAY_AVAILABLE = True
except ImportError:
    RAZORPAY_AVAILABLE = False

class RazorpayProvider:
    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID
        self.key_secret = settings.RAZORPAY_KEY_SECRET
        self.webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        self.is_mock = not (self.key_id and self.key_secret and RAZORPAY_AVAILABLE)
        
        if not self.is_mock:
            self.client = razorpay.Client(auth=(self.key_id, self.key_secret))
            logger.info("Razorpay Client initialized in LIVE TEST mode.")
        else:
            self.client = None
            if not RAZORPAY_AVAILABLE:
                logger.warning("Razorpay SDK not installed. Running in MOCK mode.")
            elif not (self.key_id and self.key_secret):
                logger.warning("Razorpay credentials not configured. Running in MOCK mode.")
            else:
                logger.info("Razorpay Client initialized in MOCK/SANDBOX mode.")

    def create_order(
        self, amount: float, currency: str = "INR",
        receipt: Optional[str] = None, notes: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Creates a Razorpay order. Amount is passed in INR (e.g. 500.00).
        Converts to paise (50000) for Razorpay.
        notes dict dynamically carries merchant_id, merchant_name, etc.
        """
        amount_in_paise = int(amount * 100)
        
        if self.is_mock:
            mock_order_id = f"order_{uuid.uuid4().hex[:14]}"
            return {
                "id": mock_order_id,
                "entity": "order",
                "amount": amount_in_paise,
                "amount_paid": 0,
                "amount_due": amount_in_paise,
                "currency": currency,
                "receipt": receipt or f"receipt_{int(time.time())}",
                "status": "created",
                "attempts": 0,
                "created_at": int(time.time()),
                "notes": notes or {"mode": "sandbox"}
            }
        else:
            try:
                data = {
                    "amount": amount_in_paise,
                    "currency": currency,
                    "receipt": receipt or f"receipt_{int(time.time())}",
                    "payment_capture": 1,  # Auto capture
                    "notes": notes or {}
                }
                order = self.client.order.create(data=data)
                return order
            except Exception as e:
                logger.error(f"Error creating Razorpay order: {str(e)}")
                raise ValueError(f"Razorpay order creation failed: {str(e)}")

    def verify_payment(
        self, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str
    ) -> bool:
        """Verifies the payment signature using Razorpay SDK or mock HMAC."""
        if self.is_mock:
            msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
            expected_signature = hmac.new(
                settings.SECRET_KEY.encode('utf-8'),
                msg,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_signature, razorpay_signature)
        else:
            try:
                params_dict = {
                    'razorpay_order_id': razorpay_order_id,
                    'razorpay_payment_id': razorpay_payment_id,
                    'razorpay_signature': razorpay_signature
                }
                self.client.utility.verify_payment_signature(params_dict)
                return True
            except Exception as e:
                logger.error(f"Razorpay payment signature verification failed: {str(e)}")
                return False

    def verify_webhook_signature(self, payload_body: bytes, signature: str) -> bool:
        """
        Verifies Razorpay webhook signature using the webhook secret.
        Razorpay signs webhooks with HMAC-SHA256 using the webhook secret.
        """
        secret = self.webhook_secret or self.key_secret
        if not secret:
            logger.error("No webhook secret or key secret configured for verification.")
            return False

        if self.is_mock:
            # In mock mode, just accept — we won't receive real webhooks
            return True

        try:
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload_body,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Webhook signature verification error: {str(e)}")
            return False

    def fetch_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves payment details from Razorpay for reconciliation."""
        if self.is_mock:
            return {
                "id": payment_id,
                "entity": "payment",
                "amount": 0,
                "currency": "INR",
                "status": "captured",
                "method": "mock",
            }
        try:
            return self.client.payment.fetch(payment_id)
        except Exception as e:
            logger.error(f"Error fetching payment {payment_id}: {str(e)}")
            return None

    def generate_mock_payment(self, razorpay_order_id: str) -> Dict[str, str]:
        """Generates mock payment details and valid mock signatures for testing checkout."""
        payment_id = f"pay_{uuid.uuid4().hex[:14]}"
        msg = f"{razorpay_order_id}|{payment_id}".encode('utf-8')
        secret = self.key_secret or settings.SECRET_KEY
        signature = hmac.new(
            secret.encode('utf-8'),
            msg,
            hashlib.sha256
        ).hexdigest()
        
        return {
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        }


payment_provider = RazorpayProvider()
