import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

from app.database import Base
from app import models, schemas
from app.payment.razorpay_provider import payment_provider
from app.payment.service import PaymentService
from app.agents.orchestrator import NegotiationOrchestrator, generate_cart_mandate, verify_cart_mandate

# In-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_multi_merchant_inventory_isolation(db):
    """
    Verifies that multiple merchants can hold listings with the SAME SKU
    without collisions, and each listing maintains distinct merchant ownership, stock, and pricing.
    """
    # Create two merchants
    merchant_a = models.User(username="merchant_nexus", hashed_password="pwd", role="merchant")
    merchant_b = models.User(username="merchant_apex", hashed_password="pwd", role="merchant")
    db.add_all([merchant_a, merchant_b])
    db.commit()

    # Create Merchant Profiles
    profile_a = models.MerchantProfile(user_id=merchant_a.id, display_name="Nexus Global Tech")
    profile_b = models.MerchantProfile(user_id=merchant_b.id, display_name="Apex Distributor")
    db.add_all([profile_a, profile_b])
    db.commit()

    # Both merchants stock the exact same SKU "CHIP-M4"
    inv_a = models.Inventory(
        sku="CHIP-M4",
        name="Apple M4 Chip",
        current_stock=100,
        base_price=24000.0,
        minimum_margin_limit=20000.0,
        wholesaler_name=profile_a.display_name,
        merchant_id=merchant_a.id,
    )
    inv_b = models.Inventory(
        sku="CHIP-M4",
        name="Apple M4 Chip",
        current_stock=50,
        base_price=23000.0,
        minimum_margin_limit=19000.0,
        wholesaler_name=profile_b.display_name,
        merchant_id=merchant_b.id,
    )
    db.add_all([inv_a, inv_b])
    db.commit()

    # Query listings
    listings = db.query(models.Inventory).filter(models.Inventory.sku == "CHIP-M4").all()
    assert len(listings) == 2
    assert {l.merchant_id for l in listings} == {merchant_a.id, merchant_b.id}

    # Verify duplicate SKU under SAME merchant is prevented by unique constraint
    with pytest.raises(Exception):
        dup_inv = models.Inventory(
            sku="CHIP-M4",
            name="Duplicate Listing",
            current_stock=10,
            base_price=24000.0,
            minimum_margin_limit=20000.0,
            wholesaler_name=profile_a.display_name,
            merchant_id=merchant_a.id,
        )
        db.add(dup_inv)
        db.commit()
    db.rollback()

def test_order_creation_and_inventory_reservation(db):
    """
    Tests that accepting a negotiation creates an Order and reserves inventory (not immediate deduction).
    """
    buyer = models.User(username="buyer_1", hashed_password="pwd", role="buyer")
    merchant = models.User(username="merchant_1", hashed_password="pwd", role="merchant")
    db.add_all([buyer, merchant])
    db.commit()

    profile = models.MerchantProfile(user_id=merchant.id, display_name="Nexus Tech")
    db.add(profile)

    inv = models.Inventory(
        sku="RAM-32G",
        name="32GB RAM",
        current_stock=100,
        reserved_stock=0,
        base_price=6000.0,
        minimum_margin_limit=5000.0,
        wholesaler_name="Nexus Tech",
        merchant_id=merchant.id,
    )
    db.add(inv)
    db.commit()

    # Create approved negotiation
    agreed_price = 5500.0
    quantity = 10
    mandate = generate_cart_mandate("RAM-32G", quantity, agreed_price, merchant_id=merchant.id, inventory_id=inv.id)

    negotiation = models.Transaction(
        sku="RAM-32G",
        quantity=quantity,
        final_price=agreed_price,
        status=models.TransactionStatus.APPROVED,
        cryptographic_signature=mandate,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=inv.id,
        buyer_approved=1,
        merchant_approved=1,
    )
    db.add(negotiation)
    db.commit()

    # Step 1: Create Order via PaymentService
    order = PaymentService.create_order(negotiation.id, buyer.id, db)

    assert order.id is not None
    assert order.merchant_id == merchant.id
    assert order.inventory_id == inv.id
    assert order.total_amount == agreed_price * quantity  # 55,000 INR
    assert order.order_status == models.OrderStatus.PENDING

    # Verify inventory reservation (reserved_stock increased, current_stock not deducted yet)
    db.refresh(inv)
    assert inv.reserved_stock == 10
    assert inv.current_stock == 100

    # Verify reservation record created
    res = db.query(models.InventoryReservation).filter(models.InventoryReservation.order_id == order.id).first()
    assert res is not None
    assert res.quantity == 10
    assert res.status == "active"

def test_razorpay_checkout_and_verification_lifecycle(db):
    """
    Tests the complete end-to-end payment lifecycle:
    Order -> Initiate Razorpay Checkout (dynamic notes) -> Signature Verification -> Stock deduction.
    """
    buyer = models.User(username="buyer_test", hashed_password="pwd", role="buyer")
    merchant = models.User(username="merchant_apex", hashed_password="pwd", role="merchant")
    db.add_all([buyer, merchant])
    db.commit()

    profile = models.MerchantProfile(user_id=merchant.id, display_name="Apex Wholesale")
    db.add(profile)

    inv = models.Inventory(
        sku="SSD-1TB",
        name="1TB NVMe",
        current_stock=50,
        reserved_stock=0,
        base_price=4000.0,
        minimum_margin_limit=3500.0,
        wholesaler_name="Apex Wholesale",
        merchant_id=merchant.id,
    )
    db.add(inv)
    db.commit()

    agreed_price = 3700.0
    qty = 5
    mandate = generate_cart_mandate("SSD-1TB", qty, agreed_price, merchant_id=merchant.id, inventory_id=inv.id)

    negotiation = models.Transaction(
        sku="SSD-1TB",
        quantity=qty,
        final_price=agreed_price,
        status=models.TransactionStatus.APPROVED,
        cryptographic_signature=mandate,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=inv.id,
        buyer_approved=1,
        merchant_approved=1,
    )
    db.add(negotiation)
    db.commit()

    # 1. Create order
    order = PaymentService.create_order(negotiation.id, buyer.id, db)

    # 2. Initiate checkout
    checkout_res = PaymentService.initiate_checkout(order.id, buyer.id, db)
    assert checkout_res.amount == int(3700.0 * 5 * 100)  # In paise: 1850000
    assert checkout_res.merchant_name == "Apex Wholesale"
    assert checkout_res.razorpay_order_id.startswith("order_")

    # 3. Simulate payment via payment_provider
    mock_payment = payment_provider.generate_mock_payment(checkout_res.razorpay_order_id)

    # 4. Server-side verification
    confirmed_order = PaymentService.verify_payment(
        order_id=order.id,
        razorpay_order_id=checkout_res.razorpay_order_id,
        razorpay_payment_id=mock_payment["razorpay_payment_id"],
        razorpay_signature=mock_payment["razorpay_signature"],
        buyer_id=buyer.id,
        db=db,
    )

    assert confirmed_order.payment_status == models.OrderStatus.CONFIRMED
    assert confirmed_order.razorpay_payment_id == mock_payment["razorpay_payment_id"]

    # 5. Verify stock permanently deducted and reservation cleared
    db.refresh(inv)
    assert inv.current_stock == 45  # 50 - 5
    assert inv.reserved_stock == 0  # 5 reserved released

    # 6. Verify buyer account inventory recorded with provenance
    account_inv = db.query(models.AccountInventory).filter(
        models.AccountInventory.account_id == buyer.id,
        models.AccountInventory.item_id == "SSD-1TB"
    ).first()
    assert account_inv is not None
    assert account_inv.purchased_qty == 5
    assert account_inv.acquired_price == 3700.0
    assert account_inv.wholesaler_name == "Apex Wholesale"

def test_idempotent_order_creation(db):
    """
    Verifies that calling create_order multiple times for the same negotiation
    does not reserve inventory twice or create duplicate orders.
    """
    buyer = models.User(username="buyer_idem", hashed_password="pwd", role="buyer")
    merchant = models.User(username="merchant_idem", hashed_password="pwd", role="merchant")
    db.add_all([buyer, merchant])
    db.commit()

    inv = models.Inventory(
        sku="TEST-SKU",
        name="Test Item",
        current_stock=20,
        reserved_stock=0,
        base_price=100.0,
        minimum_margin_limit=80.0,
        wholesaler_name="Idem Merchant",
        merchant_id=merchant.id,
    )
    db.add(inv)
    db.commit()

    negotiation = models.Transaction(
        sku="TEST-SKU",
        quantity=5,
        final_price=90.0,
        status=models.TransactionStatus.APPROVED,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=inv.id,
        buyer_approved=1,
        merchant_approved=1,
    )
    db.add(negotiation)
    db.commit()

    order1 = PaymentService.create_order(negotiation.id, buyer.id, db)
    order2 = PaymentService.create_order(negotiation.id, buyer.id, db)

    assert order1.id == order2.id
    db.refresh(inv)
    assert inv.reserved_stock == 5  # Only reserved ONCE
