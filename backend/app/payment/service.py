"""
PaymentService: Encapsulates all payment business logic.
Merchant identity is always resolved dynamically via FKs — never hardcoded.
"""
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..schemas import CheckoutInitResponse, OrderResponse
from .razorpay_provider import payment_provider
from ..agents.orchestrator import verify_cart_mandate

logger = logging.getLogger(__name__)


class PaymentService:

    # ------------------------------------------------------------------ #
    # 1. CREATE ORDER (Buyer accepts a negotiation)
    # ------------------------------------------------------------------ #
    @staticmethod
    def create_order(negotiation_id: int, buyer_id: int, db: Session) -> models.Order:
        """
        Creates an Order from an accepted negotiation.
        Reserves inventory. Merchant resolved from Inventory FK.
        """
        # 1. Load and validate negotiation
        negotiation = db.query(models.Transaction).filter(
            models.Transaction.id == negotiation_id
        ).first()
        if not negotiation:
            raise ValueError("Negotiation not found.")
        PAYABLE_STATUSES = (
            models.TransactionStatus.MUTUALLY_APPROVED,
            models.TransactionStatus.APPROVED,
            models.TransactionStatus.QUOTE_AGREED,
            models.TransactionStatus.PAYMENT_INITIATED,
            "mutually_approved",
            "quote_agreed",
            "approved",
        )
        if negotiation.status not in PAYABLE_STATUSES:
            raise ValueError(f"Negotiation is not ready for payment. Current status: {negotiation.status}")
        if negotiation.buyer_id != buyer_id:
            raise ValueError("This negotiation does not belong to the current buyer.")
        if negotiation.buyer_approved != 1 or negotiation.merchant_approved != 1:
            raise ValueError("Payment requires explicit mutual approval from both Buyer and Merchant.")

        # Check if an open revised quote is in flight
        pending_quote = db.query(models.Quote).filter(
            models.Quote.transaction_id == negotiation.id,
            models.Quote.source != models.QuoteSource.AI_NEGOTIATION,
            models.Quote.status == models.QuoteStatus.PENDING,
        ).first()
        if pending_quote:
            raise ValueError("A revised quote is currently pending. Both parties must resolve it before initiating payment.")

        # Derive settlement price strictly from agreed quote
        if negotiation.agreed_quote_id:
            agreed_quote = db.query(models.Quote).filter(models.Quote.id == negotiation.agreed_quote_id).first()
            if not agreed_quote or agreed_quote.status != models.QuoteStatus.ACCEPTED:
                raise ValueError("Agreed quote is not in accepted status.")
            settlement_price = agreed_quote.amount
        else:
            settlement_price = negotiation.final_price

        if settlement_price is None or settlement_price <= 0:
            raise ValueError("Negotiation has no valid agreed settlement price.")

        # 2. Load inventory and validate merchant ownership
        inventory = db.query(models.Inventory).filter(
            models.Inventory.id == negotiation.inventory_id
        ).first()
        if not inventory:
            raise ValueError("Inventory item not found.")
        if inventory.merchant_id != negotiation.merchant_id:
            raise ValueError("Inventory merchant does not match negotiation merchant. Possible tampering.")

        # 3. Idempotency — prevent duplicate orders for the same negotiation
        idempotency_key = hashlib.sha256(
            f"{negotiation_id}:{buyer_id}".encode()
        ).hexdigest()

        existing_order = db.query(models.Order).filter(
            models.Order.idempotency_key == idempotency_key
        ).first()
        if existing_order:
            logger.info(f"Duplicate order creation blocked. Returning existing order {existing_order.id}.")
            return existing_order

        # 4. Check available stock
        available = inventory.current_stock - inventory.reserved_stock
        if available < negotiation.quantity:
            raise ValueError(
                f"Insufficient stock. Available: {available}, Requested: {negotiation.quantity}"
            )

        # 5. Verify cart mandate cryptographic signature
        if negotiation.cryptographic_signature:
            if not verify_cart_mandate(negotiation.cryptographic_signature):
                raise ValueError("Cryptographic cart mandate verification failed. Possible tampering.")

        # 6. Reserve inventory
        inventory.reserved_stock += negotiation.quantity

        reservation = models.InventoryReservation(
            inventory_id=inventory.id,
            order_id=0,  # Will update after order creation
            quantity=negotiation.quantity,
            status="active",
            expires_at=datetime.utcnow() + timedelta(minutes=settings.RESERVATION_EXPIRY_MINUTES)
        )
        db.add(reservation)
        db.flush()  # Get reservation ID

        # 7. Create Order
        total_amount = settlement_price * negotiation.quantity
        order = models.Order(
            buyer_id=buyer_id,
            merchant_id=negotiation.merchant_id,  # Dynamic — from negotiation/inventory FK
            inventory_id=inventory.id,
            negotiation_id=negotiation.id,
            agreed_price=settlement_price,
            quantity=negotiation.quantity,
            total_amount=total_amount,
            currency="INR",
            order_status=models.OrderStatus.PENDING,
            payment_status=models.OrderStatus.PENDING,
            idempotency_key=idempotency_key,
            cryptographic_signature=negotiation.cryptographic_signature,
        )
        db.add(order)
        db.flush()

        # Update reservation with order_id
        reservation.order_id = order.id

        # Lock negotiation in PAYMENT_INITIATED state
        negotiation.status = models.TransactionStatus.PAYMENT_INITIATED

        # 8. Audit log
        merchant_profile = db.query(models.MerchantProfile).filter(
            models.MerchantProfile.user_id == negotiation.merchant_id
        ).first()
        merchant_display = merchant_profile.display_name if merchant_profile else f"Merchant#{negotiation.merchant_id}"

        log = models.AuditLog(
            transaction_id=negotiation.id,
            actor="System Payment Gateway",
            message=(
                f"Order #{order.id} created for merchant '{merchant_display}'. "
                f"Amount: ₹{total_amount:,.2f} ({negotiation.quantity} × ₹{negotiation.final_price:,.2f}). "
                f"Inventory reserved. Awaiting payment."
            )
        )
        db.add(log)
        db.commit()
        db.refresh(order)

        logger.info(f"Order {order.id} created. Merchant: {merchant_display}. Total: {total_amount}")
        return order

    # ------------------------------------------------------------------ #
    # 2. INITIATE CHECKOUT (Create Razorpay Order)
    # ------------------------------------------------------------------ #
    @staticmethod
    def initiate_checkout(order_id: int, buyer_id: int, db: Session) -> CheckoutInitResponse:
        """
        Creates a Razorpay order for an existing internal Order.
        Razorpay notes include dynamic merchant metadata.
        """
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise ValueError("Order not found.")
        if order.buyer_id != buyer_id:
            raise ValueError("This order does not belong to the current buyer.")
        if order.order_status not in (models.OrderStatus.PENDING, models.OrderStatus.RAZORPAY_ORDER_CREATED):
            raise ValueError(f"Cannot initiate checkout. Order status: {order.order_status}")

        # If already has a Razorpay order, return it (idempotent)
        if order.razorpay_order_id and order.order_status == models.OrderStatus.RAZORPAY_ORDER_CREATED:
            inventory = order.inventory
            merchant_profile = db.query(models.MerchantProfile).filter(
                models.MerchantProfile.user_id == order.merchant_id
            ).first()
            return CheckoutInitResponse(
                order_id=order.id,
                razorpay_order_id=order.razorpay_order_id,
                razorpay_key_id=settings.RAZORPAY_KEY_ID or "rzp_mock_key",
                amount=int(order.total_amount * 100),
                currency=order.currency,
                merchant_name=merchant_profile.display_name if merchant_profile else "Unknown",
                item_name=inventory.name if inventory else "Unknown",
                item_sku=inventory.sku if inventory else "Unknown",
            )

        # Load merchant profile for dynamic notes
        merchant_profile = db.query(models.MerchantProfile).filter(
            models.MerchantProfile.user_id == order.merchant_id
        ).first()
        merchant_name = merchant_profile.display_name if merchant_profile else f"Merchant#{order.merchant_id}"

        inventory = db.query(models.Inventory).filter(
            models.Inventory.id == order.inventory_id
        ).first()

        # Dynamic notes — no hardcoded merchant names
        notes = {
            "merchant_id": str(order.merchant_id),
            "merchant_name": merchant_name,
            "inventory_id": str(order.inventory_id),
            "order_id": str(order.id),
            "item_sku": inventory.sku if inventory else "unknown",
            "platform": "Project Nexus",
        }

        # Create Razorpay order
        rzp_order = payment_provider.create_order(
            amount=order.total_amount,
            currency=order.currency,
            receipt=f"nexus_order_{order.id}",
            notes=notes,
        )

        # Update order
        order.razorpay_order_id = rzp_order["id"]
        order.order_status = models.OrderStatus.RAZORPAY_ORDER_CREATED
        order.payment_status = models.OrderStatus.RAZORPAY_ORDER_CREATED

        log = models.AuditLog(
            transaction_id=order.negotiation_id,
            actor="System Payment Gateway",
            message=(
                f"Razorpay order {rzp_order['id']} created for merchant '{merchant_name}'. "
                f"Amount: {rzp_order['amount']} paise. Ready for checkout."
            )
        )
        db.add(log)
        db.commit()

        return CheckoutInitResponse(
            order_id=order.id,
            razorpay_order_id=rzp_order["id"],
            razorpay_key_id=settings.RAZORPAY_KEY_ID or "rzp_mock_key",
            amount=rzp_order["amount"],
            currency=rzp_order.get("currency", "INR"),
            merchant_name=merchant_name,
            item_name=inventory.name if inventory else "Unknown",
            item_sku=inventory.sku if inventory else "Unknown",
        )

    # ------------------------------------------------------------------ #
    # 3. VERIFY PAYMENT (Server-side signature check)
    # ------------------------------------------------------------------ #
    @staticmethod
    def verify_payment(
        order_id: int,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
        buyer_id: int,
        db: Session,
    ) -> models.Order:
        """
        Verifies Razorpay payment signature server-side.
        On success: confirms order, deducts inventory, creates AccountInventory.
        On failure: marks order failed, releases reservation.
        """
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise ValueError("Order not found.")
        if order.buyer_id != buyer_id:
            raise ValueError("This order does not belong to the current buyer.")
        if order.razorpay_order_id != razorpay_order_id:
            raise ValueError("Razorpay order ID mismatch.")

        # Prevent duplicate processing
        if order.payment_status == models.OrderStatus.CONFIRMED:
            logger.info(f"Order {order_id} already confirmed. Skipping duplicate verification.")
            return order

        # Verify signature
        verified = payment_provider.verify_payment(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
        )

        if verified:
            PaymentService._confirm_order(order, razorpay_payment_id, razorpay_signature, db)
        else:
            PaymentService._fail_order(order, "Payment signature verification failed.", db)

        db.commit()
        db.refresh(order)
        return order

    # ------------------------------------------------------------------ #
    # 4. WEBHOOK HANDLER (Idempotent)
    # ------------------------------------------------------------------ #
    @staticmethod
    def handle_webhook(event_type: str, payload: dict, db: Session) -> None:
        """
        Processes Razorpay webhook events idempotently.
        Maps back to merchant via Order.merchant_id → MerchantProfile.
        """
        try:
            payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
            rzp_order_id = payment_entity.get("order_id")
            rzp_payment_id = payment_entity.get("id")

            if not rzp_order_id:
                logger.warning(f"Webhook {event_type}: No order_id in payload. Skipping.")
                return

            order = db.query(models.Order).filter(
                models.Order.razorpay_order_id == rzp_order_id
            ).first()
            if not order:
                logger.warning(f"Webhook {event_type}: No order found for {rzp_order_id}. Skipping.")
                return

            # Idempotency: skip if already in terminal state
            if order.payment_status in (
                models.OrderStatus.CONFIRMED,
                models.OrderStatus.FAILED,
                models.OrderStatus.VERIFICATION_FAILED,
            ):
                logger.info(f"Webhook {event_type}: Order {order.id} already in terminal state. No-op.")
                return

            if event_type == "payment.captured":
                PaymentService._confirm_order(order, rzp_payment_id, None, db)
            elif event_type == "payment.failed":
                reason = payment_entity.get("error_description", "Payment failed via webhook")
                PaymentService._fail_order(order, reason, db)
            else:
                logger.info(f"Webhook {event_type}: Unhandled event type. Skipping.")
                return

            db.commit()
            logger.info(f"Webhook {event_type} processed for order {order.id}.")

        except Exception as e:
            logger.error(f"Webhook processing error: {str(e)}")
            raise

    # ------------------------------------------------------------------ #
    # 5. RELEASE EXPIRED RESERVATIONS
    # ------------------------------------------------------------------ #
    @staticmethod
    def release_expired_reservations(db: Session) -> int:
        """Releases inventory reservations that have expired (unpaid orders)."""
        now = datetime.utcnow()
        expired = db.query(models.InventoryReservation).filter(
            models.InventoryReservation.status == "active",
            models.InventoryReservation.expires_at < now,
        ).all()

        released_count = 0
        for reservation in expired:
            # Release stock
            inventory = db.query(models.Inventory).filter(
                models.Inventory.id == reservation.inventory_id
            ).first()
            if inventory:
                inventory.reserved_stock = max(0, inventory.reserved_stock - reservation.quantity)

            reservation.status = "released"

            # Update order status
            order = db.query(models.Order).filter(
                models.Order.id == reservation.order_id
            ).first()
            if order and order.payment_status not in (
                models.OrderStatus.CONFIRMED,
                models.OrderStatus.FAILED,
            ):
                order.order_status = models.OrderStatus.EXPIRED
                order.payment_status = models.OrderStatus.EXPIRED

            released_count += 1

        if released_count > 0:
            db.commit()
            logger.info(f"Released {released_count} expired inventory reservations.")

        return released_count

    # ------------------------------------------------------------------ #
    # INTERNAL HELPERS
    # ------------------------------------------------------------------ #
    @staticmethod
    def _confirm_order(
        order: models.Order, payment_id: Optional[str],
        signature: Optional[str], db: Session
    ) -> Optional[models.Inventory]:
        """Confirms an order: deducts inventory, creates AccountInventory. Idempotent."""
        if order.payment_status == models.OrderStatus.CONFIRMED:
            logger.info(f"Order #{order.id} is already CONFIRMED. Skipping duplicate inventory deduction.")
            return db.query(models.Inventory).filter(models.Inventory.id == order.inventory_id).first()

        order.payment_status = models.OrderStatus.CONFIRMED
        order.order_status = models.OrderStatus.CONFIRMED
        if payment_id:
            order.razorpay_payment_id = payment_id
        if signature:
            order.razorpay_signature = signature
        order.updated_at = datetime.utcnow()

        # Atomic lock on inventory row during deduction
        try:
            inventory = db.query(models.Inventory).filter(
                models.Inventory.id == order.inventory_id
            ).with_for_update().first()
        except Exception:
            inventory = db.query(models.Inventory).filter(
                models.Inventory.id == order.inventory_id
            ).first()

        if inventory:
            # Permanent deduction: subtract quantity from total current_stock & reserved_stock
            inventory.current_stock = max(0, inventory.current_stock - order.quantity)
            inventory.reserved_stock = max(0, inventory.reserved_stock - order.quantity)

        # Fulfill reservation
        reservation = db.query(models.InventoryReservation).filter(
            models.InventoryReservation.order_id == order.id,
            models.InventoryReservation.status == "active",
        ).first()
        if reservation:
            reservation.status = "fulfilled"


        # Create AccountInventory for provenance
        account_inv = models.AccountInventory(
            account_id=order.buyer_id,
            item_id=inventory.sku if inventory else "unknown",
            purchased_qty=order.quantity,
            acquired_price=order.agreed_price,
            wholesaler_name=inventory.wholesaler_name if inventory else "unknown",
            inventory_id=order.inventory_id,
        )
        db.add(account_inv)

        # Complete transaction status
        if order.negotiation:
            order.negotiation.status = models.TransactionStatus.COMPLETED

        # Audit log
        merchant_profile = db.query(models.MerchantProfile).filter(
            models.MerchantProfile.user_id == order.merchant_id
        ).first()
        merchant_name = merchant_profile.display_name if merchant_profile else f"Merchant#{order.merchant_id}"

        log = models.AuditLog(
            transaction_id=order.negotiation_id,
            actor="System Payment Gateway",
            message=(
                f"✅ Payment confirmed for merchant '{merchant_name}'. "
                f"Payment ID: {payment_id}. "
                f"₹{order.total_amount:,.2f} settled. Inventory deducted."
            )
        )
        db.add(log)
        logger.info(f"Order {order.id} confirmed. Merchant: {merchant_name}. Payment: {payment_id}")

    @staticmethod
    def _fail_order(order: models.Order, reason: str, db: Session):
        """Fails an order and releases the inventory reservation."""
        order.payment_status = models.OrderStatus.FAILED
        order.order_status = models.OrderStatus.FAILED
        order.updated_at = datetime.utcnow()

        # Release reservation
        inventory = db.query(models.Inventory).filter(
            models.Inventory.id == order.inventory_id
        ).first()

        reservation = db.query(models.InventoryReservation).filter(
            models.InventoryReservation.order_id == order.id,
            models.InventoryReservation.status == "active",
        ).first()
        if reservation:
            if inventory:
                inventory.reserved_stock = max(0, inventory.reserved_stock - reservation.quantity)
            reservation.status = "released"

        log = models.AuditLog(
            transaction_id=order.negotiation_id,
            actor="System Payment Gateway",
            message=f"❌ Payment failed. Reason: {reason}. Inventory reservation released."
        )
        db.add(log)
        logger.warning(f"Order {order.id} failed: {reason}")
