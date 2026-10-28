import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
from fastapi.testclient import TestClient
from main import app

ORDER = {"distance_km": 12.5, "items_count": 6, "order_hour": 20,
         "weather_condition": 2, "restaurant_rating": 3.2, "day_of_week": 5}

def test_metrics_exposed_after_prediction():
    with TestClient(app) as c:
        assert c.post("/predict", json=ORDER).status_code == 200
        m = c.get("/metrics")
        assert m.status_code == 200
        assert m.headers["content-type"].startswith("text/plain")
        assert 'delay_predictor_predictions_total{outcome="' in m.text
        assert "delay_predictor_prediction_latency_seconds_bucket" in m.text
        assert "delay_predictor_prediction_confidence_count" in m.text

def test_invalid_input_is_422_and_not_counted_as_error():
    with TestClient(app) as c:
        assert c.post("/predict", json={**ORDER, "order_hour": 99}).status_code == 422
        assert "delay_predictor_prediction_errors_total 0.0" in c.get("/metrics").text
