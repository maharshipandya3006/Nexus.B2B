import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app import models
from app.ml.pricing import pricing_engine
from app.agents.orchestrator import NegotiationOrchestrator, generate_cart_mandate, verify_cart_mandate
from app.payment.razorpay_provider import payment_provider
import time

# Create memory database for testing
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

def test_ml_pricing_engine():
    # Verify price is discounted for bulk quantity
    base_price = 100.0
    price_10 = pricing_engine.predict_wholesale_price(base_price, quantity=10, current_stock=1000, demand_velocity=1.0)
    price_500 = pricing_engine.predict_wholesale_price(base_price, quantity=500, current_stock=1000, demand_velocity=1.0)
    
    # 500 units should get a lower unit price (bulk discount) than 10 units
    assert price_500 <= price_10
    # Final price should not be lower than 30% discount limit (70.0)
    assert price_500 >= 70.0

def test_cart_mandate_cryptographic_verification():
    sku = "TEST-SKU"
    qty = 50
    price = 85.50
    
    mandate = generate_cart_mandate(sku, qty, price)
    
    # Valid mandate passes
    assert verify_cart_mandate(mandate) is True
    
    # Tampered mandate fails
    tampered_mandate = mandate.replace("85.5", "10.0") # Change price to 10.00
    assert verify_cart_mandate(tampered_mandate) is False

def test_fraud_anomaly_guard(db):
    # Register buyer and merchant
    buyer = models.User(username="test_buyer", hashed_password="pwd", role="buyer")
    merchant = models.User(username="test_merchant", hashed_password="pwd", role="merchant")
    db.add_all([buyer, merchant])
    db.commit()
    
    # Register inventory item
    item = models.Inventory(
        sku="TEST-ANOMALY",
        name="Anomaly Chipset",
        current_stock=1000,
        base_price=1000.0,
        minimum_margin_limit=800.0,
        demand_velocity=1.0,
        wholesaler_name="Test Merchant",
        merchant_id=merchant.id,
    )
    db.add(item)
    db.commit()
    
    # Add 3 historical transactions with average qty = 10
    for i in range(3):
        tx = models.Transaction(
            sku="TEST-ANOMALY",
            quantity=10,
            final_price=900.0,
            status=models.TransactionStatus.PAID,
            buyer_id=buyer.id,
            merchant_id=merchant.id
        )
        db.add(tx)
    db.commit()
    
    # Request a massive transaction (150 units, which is 15x avg)
    new_tx = models.Transaction(
        sku="TEST-ANOMALY",
        quantity=150,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        status=models.TransactionStatus.NEGOTIATING
    )
    db.add(new_tx)
    db.commit()
    
    # Trigger negotiation, should be blocked by system anomaly guard
    orchestrator = NegotiationOrchestrator(db)
    result = orchestrator.run_negotiation(new_tx.id, buyer_max_budget=950.0)
    
    assert result["status"] == "failed"
    assert "Anomaly Block" in result["reason"]
    
    # Ensure audit log is created
    log = db.query(models.AuditLog).filter(models.AuditLog.transaction_id == new_tx.id).first()
    assert log is not None
    assert "System Anomaly Guard" in log.actor

def test_razorpay_provider_signature_verification():
    order_id = "order_abc123"
    # Generate signature using mock generator
    payment_details = payment_provider.generate_mock_payment(order_id)
    
    assert payment_provider.verify_payment(
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_details["razorpay_payment_id"],
        razorpay_signature=payment_details["razorpay_signature"]
    ) is True
    
    # Verify verification fails with tampered signature
    assert payment_provider.verify_payment(
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_details["razorpay_payment_id"],
        razorpay_signature="tampered_sig"
    ) is False
