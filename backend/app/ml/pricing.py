import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
import logging

logger = logging.getLogger(__name__)

class PricingEngine:
    def __init__(self):
        self.model = LinearRegression()
        self.is_trained = False
        self._bootstrap_model()

    def _bootstrap_model(self):
        """
        Generates synthetic historical B2B wholesale transactions and trains a dynamic
        pricing model. Features: [quantity, stock_ratio, demand_velocity]
        Target: discount_ratio (e.g. 0.05 for 5% discount)
        """
        try:
            logger.info("Bootstrapping ML Pricing Engine...")
            np.random.seed(42)
            
            # Generate 1000 synthetic transaction records
            n_samples = 1000
            
            # 1. Quantity: larger volume -> higher discount (up to 20%)
            quantity = np.random.randint(10, 1000, n_samples)
            
            # 2. Stock Ratio (current stock / average inventory level): lower stock -> lower discount
            stock_ratio = np.random.uniform(0.1, 2.0, n_samples)
            
            # 3. Demand Velocity: higher velocity -> lower discount (sellers market)
            demand_velocity = np.random.uniform(0.5, 2.5, n_samples)
            
            # Formula for synthetic discount target (with some noise)
            # base discount starts positive with quantity, decreases when stock is low, decreases when demand is hot.
            base_discount = 0.05 + (quantity / 5000.0) - (0.05 / stock_ratio) - (0.03 * demand_velocity)
            noise = np.random.normal(0, 0.02, n_samples)
            
            discount = base_discount + noise
            # Clip discount between 0% and 30%
            discount = np.clip(discount, 0.0, 0.30)
            
            df = pd.DataFrame({
                "quantity": quantity,
                "stock_ratio": stock_ratio,
                "demand_velocity": demand_velocity,
                "discount": discount
            })
            
            X = df[["quantity", "stock_ratio", "demand_velocity"]]
            y = df["discount"]
            
            self.model.fit(X, y)
            self.is_trained = True
            logger.info("ML Pricing Engine successfully trained.")
        except Exception as e:
            logger.error(f"Failed to bootstrap pricing engine: {str(e)}")
            self.is_trained = False

    def predict_wholesale_price(self, base_price: float, quantity: int, current_stock: int, demand_velocity: float) -> float:
        """
        Predicts the optimal price for a bulk order dynamically.
        """
        # Determine current stock ratio (assume average replenishment level is 1000 units)
        stock_ratio = max(0.1, current_stock / 1000.0)
        
        if self.is_trained:
            try:
                features = np.array([[quantity, stock_ratio, demand_velocity]])
                discount_pred = self.model.predict(features)[0]
                discount_pred = float(np.clip(discount_pred, 0.0, 0.30)) # Cap at 30% max discount
            except Exception as e:
                logger.error(f"Error predicting price via ML model: {str(e)}. Falling back to formula.")
                discount_pred = self._formula_fallback(quantity, stock_ratio, demand_velocity)
        else:
            discount_pred = self._formula_fallback(quantity, stock_ratio, demand_velocity)
            
        final_price = base_price * (1 - discount_pred)
        return round(final_price, 2)

    def _formula_fallback(self, quantity: int, stock_ratio: float, demand_velocity: float) -> float:
        # Fallback formula: simple proportional logic
        qty_factor = min(0.15, quantity / 6000.0)
        stock_factor = 0.05 if stock_ratio < 0.3 else 0.0
        velocity_factor = min(0.08, (demand_velocity - 1.0) * 0.05) if demand_velocity > 1.0 else 0.0
        
        discount = 0.05 + qty_factor - stock_factor - velocity_factor
        return max(0.0, min(0.30, discount))

pricing_engine = PricingEngine()
