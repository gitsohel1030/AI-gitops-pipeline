"""
FoodRush Order Delay Predictor — Inference API
Week 3 - Model Serving
 
Real-world pattern: This is exactly how companies serve ML models.
A FastAPI container runs in Kubernetes, receives prediction requests
from other services, and returns results in milliseconds.
 
In FoodRush's case: the order-service would call this API before
confirming an order to warn customers about potential delays.
 
Author: Sohel Mubarak Mujawar
"""
 
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import uvicorn
import logging
import time
import os
from model import load_model, predict
 
# ── Logging setup ─────────────────────────────────────────
# Structured logging — every log line has timestamp + level
# In production these go to Loki via Promtail
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)
 
 
# ── Request schema ────────────────────────────────────────
# Pydantic validates every incoming request automatically
# If a field is missing or wrong type → 422 error returned
# No manual validation code needed — this is why FastAPI is preferred
class OrderFeatures(BaseModel):
    distance_km: float = Field(
        ...,
        ge=0.1,
        le=50.0,
        description="Distance from restaurant to customer in km"
    )
    items_count: int = Field(
        ...,
        ge=1,
        le=50,
        description="Number of items in the order"
    )
    order_hour: int = Field(
        ...,
        ge=0,
        le=23,
        description="Hour of day the order was placed (0-23)"
    )
    weather_condition: int = Field(
        ...,
        ge=0,
        le=2,
        description="0=clear, 1=rainy, 2=heavy rain"
    )
    restaurant_rating: float = Field(
        ...,
        ge=1.0,
        le=5.0,
        description="Restaurant rating (1.0 to 5.0)"
    )
    day_of_week: int = Field(
        ...,
        ge=0,
        le=6,
        description="Day of week (0=Monday, 6=Sunday)"
    )
 
    # Example shown in auto-generated API docs at /docs
    class Config:
        json_schema_extra = {
            "example": {
                "distance_km": 8.5,
                "items_count": 4,
                "order_hour": 20,
                "weather_condition": 1,
                "restaurant_rating": 3.8,
                "day_of_week": 5
            }
        }
 
 
# ── Response schema ───────────────────────────────────────
class PredictionResponse(BaseModel):
    prediction: int
    label: str
    confidence: float
    model_version: str
    latency_ms: float
 
 
# ── App lifespan ──────────────────────────────────────────
# Lifespan loads model ONCE at startup — not on every request
# Loading a model on every request = 500ms+ latency per call
# Loading once at startup = 2ms latency per call
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FoodRush Delay Predictor API...")
    logger.info("Loading model from MLflow...")
    load_model()
    logger.info("Model loaded successfully. API ready.")
    yield
    logger.info("Shutting down API...")
 
 
# ── FastAPI app ───────────────────────────────────────────
app = FastAPI(
    title="FoodRush Order Delay Predictor",
    description="""
    Predicts whether a FoodRush delivery order will be delayed.
    Used by the order-service to warn customers before order confirmation.
 
    Part of the AI in DevOps portfolio project.
    """,
    version="1.0.0",
    lifespan=lifespan
)
 
 
# ── Health check endpoint ─────────────────────────────────
# Kubernetes liveness probe hits this every 10 seconds
# If it returns non-200 → pod gets restarted
@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "foodrush-delay-predictor",
        "version": "1.0.0"
    }
 
 
# ── Readiness check endpoint ──────────────────────────────
# Kubernetes readiness probe hits this before sending traffic
# Returns 503 if model not loaded yet — prevents cold-start errors
@app.get("/ready")
def ready():
    from model import model_loaded
    if not model_loaded:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded yet"
        )
    return {"status": "ready"}
 
 
# ── Prediction endpoint ───────────────────────────────────
@app.post("/predict", response_model=PredictionResponse)
def predict_delay(order: OrderFeatures):
    """
    Predict whether an order will be delayed.
 
    Returns:
    - prediction: 0 (on time) or 1 (delayed)
    - label: ON_TIME or DELAYED
    - confidence: probability of the predicted class (0.0 to 1.0)
    - model_version: which model version made the prediction
    - latency_ms: how long the prediction took
    """
    start_time = time.time()
 
    try:
        features = [
            order.distance_km,
            order.items_count,
            order.order_hour,
            order.weather_condition,
            order.restaurant_rating,
            order.day_of_week
        ]
 
        prediction, confidence = predict(features)
        latency_ms = (time.time() - start_time) * 1000
 
        label = "DELAYED" if prediction == 1 else "ON_TIME"
 
        logger.info(
            f"Prediction: {label} | "
            f"Confidence: {confidence:.3f} | "
            f"Latency: {latency_ms:.1f}ms | "
            f"Distance: {order.distance_km}km | "
            f"Hour: {order.order_hour}"
        )
 
        return PredictionResponse(
            prediction=prediction,
            label=label,
            confidence=round(confidence, 4),
            model_version=os.getenv("MODEL_VERSION", "v2"),
            latency_ms=round(latency_ms, 2)
        )
 
    except Exception as e:
        logger.error(f"Prediction failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
 
 
# ── Model info endpoint ───────────────────────────────────
@app.get("/model-info")
def model_info():
    """Returns metadata about the loaded model."""
    return {
        "model_name": "foodrush-delay-predictor",
        "model_version": os.getenv("MODEL_VERSION", "v2"),
        "algorithm": "RandomForestClassifier",
        "features": [
            "distance_km",
            "items_count",
            "order_hour",
            "weather_condition",
            "restaurant_rating",
            "day_of_week"
        ],
        "accuracy": 0.94,
        "f1_score": 0.9268,
        "trained_on": "FoodRush synthetic order data (2000 samples)"
    }
 
 
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )
