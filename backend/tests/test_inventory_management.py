import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
from fastapi import HTTPException

from app.database import Base
from app import models, schemas
from app.payment.razorpay_provider import payment_provider
from app.payment.service import PaymentService
from app.main import remove_inventory, delete_inventory

# In-memory SQLite database
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

@pytest.fixture
def merchant_and_listing(db):
    merchant = models.User(username="nexus_tech", hashed_password="pwd", role="merchant")
    other_merchant = models.User(username="apex_corp", hashed_password="pwd", role="merchant")
    buyer = models.User(username="buyer_alpha", hashed_password="pwd", role="buyer")
    db.add_all([merchant, other_merchant, buyer])
    db.commit()

    profile = models.MerchantProfile(user_id=merchant.id, display_name="Nexus Global Tech")
    other_profile = models.MerchantProfile(user_id=other_merchant.id, display_name="Apex Corp")
    db.add_all([profile, other_profile])
    db.commit()

    item = models.Inventory(
        sku="TEST-SKU-01",
        name="Industrial Sensor Node",
        current_stock=100,
        reserved_stock=0,
        base_price=5000.0,
        minimum_margin_limit=4000.0,
        wholesaler_name=profile.display_name,
        merchant_id=merchant.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return merchant, other_merchant, buyer, item


import asyncio

def test_merchant_remove_partial_inventory(db, merchant_and_listing):
    merchant, _, _, item = merchant_and_listing

    req = schemas.InventoryRemoveRequest(units_to_remove=30, delete_if_zero=False)
    resp = asyncio.run(remove_inventory(inventory_id=item.id, req=req, current_user=merchant, db=db))

    assert resp.current_stock == 70
    assert resp.available_stock == 70
    assert resp.reserved_stock == 0

    # Verify directly from DB
    updated = db.query(models.Inventory).filter(models.Inventory.id == item.id).first()
    assert updated.current_stock == 70


def test_merchant_remove_to_zero_out_of_stock(db, merchant_and_listing):
    merchant, _, _, item = merchant_and_listing

    # Remove all 100 units without deleting the listing
    req = schemas.InventoryRemoveRequest(units_to_remove=100, delete_if_zero=False)
    resp = asyncio.run(remove_inventory(inventory_id=item.id, req=req, current_user=merchant, db=db))

    assert resp.current_stock == 0
    assert resp.available_stock == 0

    # Ensure listing remains in DB marked as 0 stock (Out of Stock)
    updated = db.query(models.Inventory).filter(models.Inventory.id == item.id).first()
    assert updated is not None
    assert updated.current_stock == 0


def test_merchant_remove_with_delete_if_zero(db, merchant_and_listing):
    merchant, _, _, item = merchant_and_listing

    # Remove all 100 units with delete_if_zero=True
    req = schemas.InventoryRemoveRequest(units_to_remove=100, delete_if_zero=True)
    resp = asyncio.run(remove_inventory(inventory_id=item.id, req=req, current_user=merchant, db=db))

    assert resp["status"] == "deleted"

    # Ensure listing is removed from database
    deleted = db.query(models.Inventory).filter(models.Inventory.id == item.id).first()
    assert deleted is None


def test_cannot_remove_more_than_available(db, merchant_and_listing):
    merchant, _, _, item = merchant_and_listing

    # Simulate 25 units reserved by buyer orders (available is 75)
    item.reserved_stock = 25
    db.commit()

    # Attempt to remove 80 units
    req = schemas.InventoryRemoveRequest(units_to_remove=80, delete_if_zero=False)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(remove_inventory(inventory_id=item.id, req=req, current_user=merchant, db=db))

    assert excinfo.value.status_code == 400
    assert "Only 75 units are currently available" in excinfo.value.detail


def test_cross_merchant_ownership_protection(db, merchant_and_listing):
    _, other_merchant, _, item = merchant_and_listing

    req = schemas.InventoryRemoveRequest(units_to_remove=10, delete_if_zero=False)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(remove_inventory(inventory_id=item.id, req=req, current_user=other_merchant, db=db))

    assert excinfo.value.status_code == 403
    assert "You do not own this inventory listing" in excinfo.value.detail


def test_cannot_delete_listing_with_active_reservations(db, merchant_and_listing):
    merchant, _, _, item = merchant_and_listing

    item.reserved_stock = 10
    db.commit()

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(delete_inventory(inventory_id=item.id, current_user=merchant, db=db))

    assert excinfo.value.status_code == 400
    assert "reserved by active buyer orders" in excinfo.value.detail



def test_automatic_stock_deduction_on_successful_payment(db, merchant_and_listing):
    """
    Verifies that when an order is paid via verified Razorpay payment,
    the purchased quantity is deducted from product total stock and reservation fulfilled.
    """
    merchant, _, buyer, item = merchant_and_listing
    item.current_stock = 10
    item.reserved_stock = 0
    db.commit()

    # Create transaction for 3 units
    tx = models.Transaction(
        sku=item.sku,
        quantity=3,
        final_price=4500.0,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=item.id,
        status=models.TransactionStatus.AGREED,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    # Reserve inventory for order creation
    item.reserved_stock = 3
    order = models.Order(
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=item.id,
        negotiation_id=tx.id,
        agreed_price=4500.0,
        quantity=3,
        total_amount=13500.0,
        currency="INR",
        order_status=models.OrderStatus.PENDING,
        payment_status=models.OrderStatus.PENDING,
        razorpay_order_id="order_test_rzp_01",
        idempotency_key="idemp_test_01",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    reservation = models.InventoryReservation(
        inventory_id=item.id,
        order_id=order.id,
        quantity=3,
        status="active",
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.add(reservation)
    db.commit()

    # Generate mock payment credentials
    mock_payment = payment_provider.generate_mock_payment(order.razorpay_order_id)

    # Verify payment
    confirmed_order = PaymentService.verify_payment(
        order_id=order.id,
        razorpay_order_id=order.razorpay_order_id,
        razorpay_payment_id=mock_payment["razorpay_payment_id"],
        razorpay_signature=mock_payment["razorpay_signature"],
        buyer_id=buyer.id,
        db=db,
    )

    assert confirmed_order.payment_status == models.OrderStatus.CONFIRMED

    # Check inventory deduction: 10 units - 3 units = 7 units
    db.refresh(item)
    assert item.current_stock == 7
    assert item.reserved_stock == 0

    # Reservation fulfilled
    db.refresh(reservation)
    assert reservation.status == "fulfilled"

    # Provenance record created
    acct_inv = db.query(models.AccountInventory).filter(
        models.AccountInventory.account_id == buyer.id,
        models.AccountInventory.inventory_id == item.id,
    ).first()
    assert acct_inv is not None
    assert acct_inv.purchased_qty == 3


def test_idempotent_payment_verification_does_not_double_deduct(db, merchant_and_listing):
    """
    Verifies that calling verify_payment multiple times does NOT deduct inventory twice.
    """
    merchant, _, buyer, item = merchant_and_listing
    item.current_stock = 10
    item.reserved_stock = 2
    db.commit()

    tx = models.Transaction(
        sku=item.sku,
        quantity=2,
        final_price=4500.0,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=item.id,
        status=models.TransactionStatus.AGREED,
    )
    db.add(tx)
    db.commit()

    order = models.Order(
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=item.id,
        negotiation_id=tx.id,
        agreed_price=4500.0,
        quantity=2,
        total_amount=9000.0,
        currency="INR",
        order_status=models.OrderStatus.PENDING,
        payment_status=models.OrderStatus.PENDING,
        razorpay_order_id="order_test_rzp_02",
        idempotency_key="idemp_test_02",
    )
    db.add(order)
    db.commit()

    mock_payment = payment_provider.generate_mock_payment(order.razorpay_order_id)

    # First verification
    PaymentService.verify_payment(
        order_id=order.id,
        razorpay_order_id=order.razorpay_order_id,
        razorpay_payment_id=mock_payment["razorpay_payment_id"],
        razorpay_signature=mock_payment["razorpay_signature"],
        buyer_id=buyer.id,
        db=db,
    )

    db.refresh(item)
    assert item.current_stock == 8

    # Second verification (duplicate attempt)
    PaymentService.verify_payment(
        order_id=order.id,
        razorpay_order_id=order.razorpay_order_id,
        razorpay_payment_id=mock_payment["razorpay_payment_id"],
        razorpay_signature=mock_payment["razorpay_signature"],
        buyer_id=buyer.id,
        db=db,
    )

    db.refresh(item)
    # Stock must remain 8, not become 6
    assert item.current_stock == 8
