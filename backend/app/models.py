from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import relationship
import datetime
from .database import Base


class UserRole(str):
    MERCHANT = "merchant"
    BUYER = "buyer"


class TransactionStatus(str):
    # Core 9-State Lifecycle Machine
    NEGOTIATING = "negotiating"                               # 1. AI Negotiating
    AI_NEGOTIATION_COMPLETED = "ai_negotiation_completed"     # 2. AI Negotiation Completed (AI concludes, awaiting human approvals)
    AWAITING_BUYER_APPROVAL = "awaiting_buyer_approval"       # 3. Awaiting Buyer Approval (Merchant approved)
    AWAITING_MERCHANT_APPROVAL = "awaiting_merchant_approval" # 4. Awaiting Merchant Approval (Buyer approved)
    MANUAL_REVISION_IN_PROGRESS = "revision_pending"          # 5. Manual Revision in Progress
    MUTUALLY_APPROVED = "mutually_approved"                   # 6. Mutually Approved (both agreed, price locked)
    PAYMENT_INITIATED = "payment_initiated"                   # 7. Payment Initiated (Order created, Razorpay open)
    COMPLETED = "paid"                                        # 8. Transaction Completed (Payment captured & verified)
    TERMINATED = "terminated"                                 # 9. Transaction Terminated (Failed / Cancelled)

    # Backward compatibility aliases
    AGREED = "ai_negotiation_completed"
    QUOTE_AGREED = "mutually_approved"
    APPROVED = "mutually_approved"
    PAID = "paid"
    FAILED = "terminated"
    REVISION_PENDING = "revision_pending"
    VERIFICATION_FAILED = "verification_failed"


class QuoteStatus(str):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class QuoteSource(str):
    AI_NEGOTIATION = "ai_negotiation"
    MANUAL_MERCHANT = "manual_merchant"
    MANUAL_BUYER = "manual_buyer"


class OrderStatus(str):
    PENDING = "pending"
    RAZORPAY_ORDER_CREATED = "razorpay_order_created"
    PAYMENT_INITIATED = "payment_initiated"
    PAYMENT_VERIFICATION_PENDING = "payment_verification_pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    VERIFICATION_FAILED = "verification_failed"
    EXPIRED = "expired"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # merchant or buyer
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # One-to-one relationship with MerchantProfile
    merchant_profile = relationship("MerchantProfile", back_populates="user", uselist=False)


class MerchantProfile(Base):
    """
    First-class merchant entity. Stores business metadata separately from auth.
    Adding a new merchant = creating a User(role='merchant') + MerchantProfile.
    No code changes needed for N merchants.
    """
    __tablename__ = "merchant_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    display_name = Column(String, nullable=False)  # e.g. "Nexus Global Tech"
    description = Column(String, nullable=True)  # e.g. "Premium B2B electronics wholesaler"
    contact_email = Column(String, nullable=True)
    business_category = Column(String, nullable=True)  # e.g. "Electronics", "Components"
    is_active = Column(Boolean, default=True)  # Soft-disable a merchant
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="merchant_profile")


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, index=True, nullable=False)  # NOT unique — same SKU allowed across merchants
    name = Column(String, nullable=False)
    current_stock = Column(Integer, nullable=False, default=0)
    reserved_stock = Column(Integer, nullable=False, default=0)  # Units reserved by unpaid orders
    base_price = Column(Float, nullable=False)
    minimum_margin_limit = Column(Float, nullable=False)  # Absolute minimum price merchant will accept
    demand_velocity = Column(Float, default=1.0)  # 1.0 = normal, >1.0 = high demand
    wholesaler_name = Column(String, nullable=False)  # Denormalized display label from MerchantProfile

    # True merchant ownership via FK
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    merchant = relationship("User")

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Same SKU allowed across merchants, but not duplicated within one merchant
    __table_args__ = (
        UniqueConstraint('sku', 'merchant_id', name='uq_sku_merchant'),
    )


class AccountInventory(Base):
    __tablename__ = "account_inventory"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    item_id = Column(String, nullable=False)  # SKU or item ID
    purchased_qty = Column(Integer, nullable=False)
    acquired_price = Column(Float, nullable=False)
    wholesaler_name = Column(String, nullable=False)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=True)  # Provenance to exact listing
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    account = relationship("User")
    inventory = relationship("Inventory")


class Transaction(Base):
    """Represents an AI negotiation session. Separate from the Order (payment record)."""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_number = Column(String, unique=True, index=True, nullable=True)
    sku = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    final_price = Column(Float, nullable=True)  # Agreed price per unit
    status = Column(String, default=TransactionStatus.NEGOTIATING)
    cryptographic_signature = Column(String, nullable=True)  # Agreed mandate signature
    razorpay_order_id = Column(String, nullable=True)  # Legacy — kept for backward compat

    buyer_id = Column(Integer, ForeignKey("users.id"))
    merchant_id = Column(Integer, ForeignKey("users.id"))
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=True)  # Exact merchant listing

    buyer_approved = Column(Integer, default=0)  # 0=False, 1=True
    merchant_approved = Column(Integer, default=0)  # 0=False, 1=True

    # Foreign key to currently agreed quote
    agreed_quote_id = Column(Integer, ForeignKey("quotes.id", name="fk_transaction_agreed_quote", use_alter=True), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    buyer = relationship("User", foreign_keys=[buyer_id])
    merchant = relationship("User", foreign_keys=[merchant_id])
    inventory = relationship("Inventory")
    quotes = relationship("Quote", back_populates="transaction", foreign_keys="Quote.transaction_id", order_by="Quote.created_at")
    agreed_quote = relationship("Quote", foreign_keys=[agreed_quote_id], post_update=True)


class Quote(Base):
    """
    Represents an offer / quote in the negotiation or revised quote lifecycle.
    Immutable record preserving complete negotiation audit history.
    """
    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    amount = Column(Float, nullable=False)  # Agreed or proposed per-unit price
    proposed_by = Column(String, nullable=False)  # "AI" | "MERCHANT" | "BUYER"
    source = Column(String, nullable=False)  # QuoteSource (ai_negotiation, manual_merchant, manual_buyer)
    merchant_accepted = Column(Boolean, nullable=True)  # True, False, or None
    buyer_accepted = Column(Boolean, nullable=True)     # True, False, or None
    status = Column(String, default=QuoteStatus.PENDING)  # QuoteStatus (pending, accepted, rejected, superseded)
    note = Column(Text, nullable=True)  # Optional rationale / comments
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    accepted_at = Column(DateTime, nullable=True)

    transaction = relationship("Transaction", back_populates="quotes", foreign_keys=[transaction_id])


class Order(Base):
    """
    Purchase/payment record. Created only after buyer accepts a negotiation.
    Merchant identity resolved dynamically from Inventory FK — never hardcoded.
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    negotiation_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)

    agreed_price = Column(Float, nullable=False)  # Per-unit negotiated price
    quantity = Column(Integer, nullable=False)
    total_amount = Column(Float, nullable=False)  # agreed_price × quantity
    currency = Column(String, default="INR")

    order_status = Column(String, default=OrderStatus.PENDING)
    payment_status = Column(String, default=OrderStatus.PENDING)

    razorpay_order_id = Column(String, nullable=True, unique=True)
    razorpay_payment_id = Column(String, nullable=True)
    razorpay_signature = Column(String, nullable=True)

    idempotency_key = Column(String, unique=True, nullable=False)  # hash(negotiation_id, buyer_id)
    cryptographic_signature = Column(String, nullable=True)  # Cart mandate from negotiation

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    buyer = relationship("User", foreign_keys=[buyer_id])
    merchant = relationship("User", foreign_keys=[merchant_id])
    inventory = relationship("Inventory")
    negotiation = relationship("Transaction")


class InventoryReservation(Base):
    """Tracks inventory reserved by unpaid orders. Released on payment failure or expiry."""
    __tablename__ = "inventory_reservations"

    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String, default="active")  # "active", "fulfilled", "released"
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    inventory = relationship("Inventory")
    order = relationship("Order")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    actor = Column(String, nullable=False)  # e.g. "Merchant Agent", "Buyer Agent", "System"
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    transaction = relationship("Transaction")
