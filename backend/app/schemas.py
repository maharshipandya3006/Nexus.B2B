from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from datetime import datetime
import re


# --- User Schemas ---

class UserBase(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        description="Alphanumeric and underscore characters only (3-30 chars)",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        cleaned = v.strip()
        if not re.match(r"^[a-zA-Z0-9_]{3,30}$", cleaned):
            raise ValueError("Username must be 3-30 characters and contain only alphanumeric letters and underscores.")
        return cleaned

class UserCreate(UserBase):
    password: str = Field(
        ...,
        min_length=6,
        max_length=72,
        description="Password must be between 6 and 72 characters",
    )
    role: Literal["buyer", "merchant"] = Field(
        ...,
        description="Role must strictly be either 'buyer' or 'merchant'",
    )

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters long.")
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password exceeds maximum length allowed (72 bytes).")
        return v

class UserUpdate(BaseModel):
    role: Optional[Literal["buyer", "merchant"]] = None
    password: Optional[str] = Field(
        default=None,
        min_length=6,
        max_length=72,
    )

    @field_validator("password")
    @classmethod
    def validate_update_password(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if len(v) < 6:
                raise ValueError("Password must be at least 6 characters long.")
            if len(v.encode("utf-8")) > 72:
                raise ValueError("Password exceeds maximum length allowed (72 bytes).")
        return v

class UserResponse(UserBase):
    id: int
    role: str
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    username: str

class TokenData(BaseModel):
    username: Optional[str] = None


# --- Merchant Profile Schemas ---

class MerchantProfileCreate(BaseModel):
    display_name: str
    description: Optional[str] = None
    contact_email: Optional[str] = None
    business_category: Optional[str] = None

class MerchantProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    contact_email: Optional[str] = None
    business_category: Optional[str] = None

class MerchantProfileResponse(BaseModel):
    id: int
    user_id: int
    display_name: str
    description: Optional[str] = None
    contact_email: Optional[str] = None
    business_category: Optional[str] = None
    is_active: bool
    username: Optional[str] = None  # Populated from User join
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Inventory Schemas ---

class InventoryBase(BaseModel):
    sku: str
    name: str
    current_stock: int
    base_price: float
    minimum_margin_limit: float
    demand_velocity: float

class InventoryCreate(InventoryBase):
    """Merchant-created inventory. wholesaler_name auto-populated from MerchantProfile."""
    pass

class InventoryRemoveRequest(BaseModel):
    """Merchant request to remove units or delete stock from an existing listing."""
    units_to_remove: int = Field(gt=0, description="Quantity to remove from listing stock")
    delete_if_zero: Optional[bool] = Field(default=False, description="If true and remaining stock reaches 0, delete the listing")

class InventoryResponse(InventoryBase):
    id: int
    merchant_id: int
    merchant_name: str = ""  # From MerchantProfile.display_name
    wholesaler_name: str = ""
    reserved_stock: int = 0
    available_stock: int = 0  # current_stock - reserved_stock
    created_at: datetime

    class Config:
        from_attributes = True


# --- Account Inventory Schemas ---

class AccountInventoryBase(BaseModel):
    item_id: str
    purchased_qty: int
    acquired_price: float
    wholesaler_name: str

class AccountInventoryResponse(AccountInventoryBase):
    id: int
    account_id: int
    inventory_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


# --- Transaction / Negotiation Schemas ---

class TransactionBase(BaseModel):
    sku: str
    quantity: int

class TransactionCreate(TransactionBase):
    buyer_id: int
    merchant_id: int
    inventory_id: Optional[int] = None

class QuoteResponse(BaseModel):
    id: int
    transaction_id: int
    amount: float
    proposed_by: str
    source: str
    merchant_accepted: Optional[bool] = None
    buyer_accepted: Optional[bool] = None
    status: str
    note: Optional[str] = None
    created_at: datetime
    accepted_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class QuoteCreateRequest(BaseModel):
    amount: float
    note: Optional[str] = None

class QuoteActionResponse(BaseModel):
    status: str
    quote: Optional[QuoteResponse] = None
    message: Optional[str] = None

class TransactionResponse(BaseModel):
    id: int
    transaction_number: Optional[str] = None
    sku: str
    quantity: int
    final_price: Optional[float] = None
    status: str
    cryptographic_signature: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    buyer_id: int
    merchant_id: int
    inventory_id: Optional[int] = None
    buyer_approved: int
    merchant_approved: int
    buyer_accepted: Optional[bool] = None
    merchant_accepted: Optional[bool] = None
    agreed_quote_id: Optional[int] = None
    quotes: Optional[List[QuoteResponse]] = None
    active_quote: Optional[QuoteResponse] = None
    merchant_name: Optional[str] = None  # From MerchantProfile
    item_name: Optional[str] = None  # From Inventory
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AuditLogResponse(BaseModel):
    id: int
    transaction_id: Optional[int] = None
    actor: str
    message: str
    timestamp: datetime

    class Config:
        from_attributes = True


# --- Negotiation Request/Response Schemas ---

class NegotiationRequest(BaseModel):
    sku: str
    quantity: int
    buyer_max_budget: float
    inventory_id: int  # Required — identifies the exact merchant listing

class NegotiationStatusResponse(BaseModel):
    transaction_id: int
    transaction_number: Optional[str] = None
    status: str
    final_price: Optional[float] = None
    logs: List[AuditLogResponse]

class MultiNegotiationRequest(BaseModel):
    """Triggers parallel negotiation across all merchants offering this SKU."""
    sku: str
    quantity: int
    buyer_max_budget: float

class MerchantOfferResponse(BaseModel):
    merchant_id: int
    merchant_name: str
    inventory_id: int
    transaction_id: int
    transaction_number: Optional[str] = None
    status: str
    final_price: Optional[float] = None
    available_stock: int = 0
    logs: List[AuditLogResponse] = []

class MultiNegotiationResponse(BaseModel):
    sku: str
    offers: List[MerchantOfferResponse]
    best_offer_transaction_id: Optional[int] = None


# --- Order Schemas ---

class OrderCreateRequest(BaseModel):
    """Buyer accepts a negotiation → creates an Order + reserves inventory."""
    negotiation_id: int

class OrderResponse(BaseModel):
    id: int
    buyer_id: int
    merchant_id: int
    inventory_id: int
    negotiation_id: int
    agreed_price: float
    quantity: int
    total_amount: float
    currency: str
    order_status: str
    payment_status: str
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    merchant_name: Optional[str] = None  # From MerchantProfile
    item_name: Optional[str] = None  # From Inventory
    item_sku: Optional[str] = None  # From Inventory
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Payment / Checkout Schemas ---

class CheckoutInitResponse(BaseModel):
    """Everything the frontend needs to open Razorpay Checkout. Key comes from backend."""
    order_id: int
    razorpay_order_id: str
    razorpay_key_id: str  # Public key only — NOT the secret
    amount: int  # In paise
    currency: str
    merchant_name: str
    item_name: str
    item_sku: str

class PaymentVerifyRequest(BaseModel):
    order_id: int
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# --- Upsell Schemas ---

class UpsellOfferResponse(BaseModel):
    recommended_sku: str
    pitch: str
    suggested_discount_percent: float
