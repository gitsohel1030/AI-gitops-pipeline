"""
Model loading logic — Week 4 version.
 
Priority order:
1. Load model.pkl baked into the Docker image (from CI training) — fastest, no network call
2. Fall back to S3 if model.pkl isn't present
3. Fall back to training fresh (dev/testing only)
"""
 
import os
import boto3
import joblib
import logging
import numpy as np
import tempfile
 
logger = logging.getLogger(__name__)
 
_model = None
model_loaded = False
 
 
def load_model():
    global _model, model_loaded
 
    local_model_path = "model.pkl"
 
    # Priority 1 — baked-in model from CI pipeline
    if os.path.exists(local_model_path):
        logger.info(f"Loading model from local file: {local_model_path}")
        _model = joblib.load(local_model_path)
        model_loaded = True
        logger.info("Model loaded from local artifact (CI-built image)")
        return
 
    # Priority 2 — S3
    s3_bucket  = os.getenv("MODEL_S3_BUCKET", "mlflow-artifacts-608827180555")
    model_path = os.getenv("MODEL_S3_KEY", "")
 
    if model_path:
        try:
            logger.info(f"Downloading model from s3://{s3_bucket}/{model_path}")
            s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "ap-south-1"))
            with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
                s3.download_fileobj(s3_bucket, model_path, tmp)
                tmp_path = tmp.name
            _model = joblib.load(tmp_path)
            os.unlink(tmp_path)
            model_loaded = True
            logger.info("Model loaded from S3 successfully")
            return
        except Exception as e:
            logger.error(f"Failed to load model from S3: {e}")
 
    # Priority 3 — fallback training (dev only)
    logger.warning("No model.pkl or S3 key found — training fallback model for dev/test")
    _model = _train_fallback_model()
    model_loaded = True
 
 
def predict(features: list) -> tuple[int, float]:
    if _model is None:
        raise RuntimeError("Model not loaded")
    X = np.array(features).reshape(1, -1)
    prediction = int(_model.predict(X)[0])
    probabilities = _model.predict_proba(X)[0]
    confidence = float(probabilities[prediction])
    return prediction, confidence
 
 
def _train_fallback_model():
    from sklearn.ensemble import RandomForestClassifier
    import pandas as pd
 
    np.random.seed(42)
    n = 2000
    distance = np.random.uniform(0.5, 15.0, n)
    items    = np.random.randint(1, 10, n)
    hour     = np.random.randint(0, 24, n)
    weather  = np.random.choice([0, 1, 2], n, p=[0.6, 0.3, 0.1])
    rating   = np.random.uniform(2.0, 5.0, n)
    day      = np.random.randint(0, 7, n)
 
    X = np.column_stack([distance, items, hour, weather, rating, day])
    delay_prob = (
        (distance / 15.0) * 0.3 + (weather / 2.0) * 0.3 +
        (((hour >= 12) & (hour <= 14)) | ((hour >= 19) & (hour <= 21))).astype(int) * 0.2 +
        (items / 10.0) * 0.1 + np.random.uniform(0, 0.1, n)
    )
    y = (delay_prob > 0.4).astype(int)
 
    model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
    model.fit(X, y)
    return model
