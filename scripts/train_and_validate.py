"""
CI Training Script — Week 4
Trains the model fresh, validates accuracy against a minimum threshold,
and saves the model artifact for the Docker build step.
 
This runs inside GitHub Actions — no MLflow server dependency,
no AWS credentials needed for this step (S3 upload happens separately if needed).
 
Author: Sohel Mubarak Mujawar
"""
 
import sys
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score
 
# The accuracy gate — pipeline fails below this
MINIMUM_ACCURACY = 0.90
 
 
def generate_foodrush_data(n_samples=2000):
    """Same synthetic data generation as Week 2 — reproducible with seed=42."""
    np.random.seed(42)
 
    df = pd.DataFrame({
        'distance_km': np.random.uniform(0.5, 15.0, n_samples),
        'items_count': np.random.randint(1, 10, n_samples),
        'order_hour': np.random.randint(0, 24, n_samples),
        'weather_condition': np.random.choice([0, 1, 2], n_samples, p=[0.6, 0.3, 0.1]),
        'restaurant_rating': np.random.uniform(2.0, 5.0, n_samples),
        'day_of_week': np.random.randint(0, 7, n_samples),
    })
 
    delay_probability = (
        (df['distance_km'] / 15.0) * 0.3 +
        (df['weather_condition'] / 2.0) * 0.3 +
        ((df['order_hour'].between(12, 14) | df['order_hour'].between(19, 21)).astype(int)) * 0.2 +
        (df['items_count'] / 10.0) * 0.1 +
        np.random.uniform(0, 0.1, n_samples)
    )
    df['was_delayed'] = (delay_probability > 0.4).astype(int)
    return df
 
 
def main():
    print("=" * 55)
    print("  CI Training + Validation Pipeline")
    print("=" * 55)
 
    df = generate_foodrush_data()
    features = ['distance_km', 'items_count', 'order_hour',
                'weather_condition', 'restaurant_rating', 'day_of_week']
    X = df[features]
    y = df['was_delayed']
 
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
 
    # Best config found in Week 2 experiments
    model = RandomForestClassifier(
        n_estimators=100, max_depth=10, random_state=42, n_jobs=-1
    )
    model.fit(X_train, y_train)
 
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
 
    print(f"  Accuracy: {accuracy:.4f}")
    print(f"  F1 Score: {f1:.4f}")
    print(f"  Minimum required: {MINIMUM_ACCURACY}")
 
    # ── The accuracy gate ──────────────────────────────
    if accuracy < MINIMUM_ACCURACY:
        print(f"\n  ❌ FAILED — accuracy {accuracy:.4f} below threshold {MINIMUM_ACCURACY}")
        print("  Pipeline stopping. Model will NOT be deployed.")
        sys.exit(1)   # non-zero exit code = GitHub Actions marks this step failed
 
    print(f"\n  ✅ PASSED — accuracy meets threshold")
 
    # Save model artifact — this gets baked into the Docker image next
    joblib.dump(model, "model.pkl")
    print("  Model saved to model.pkl")
 
    # Write metrics to a file GitHub Actions can read for the job summary
    with open("metrics.txt", "w") as f:
        f.write(f"accuracy={accuracy:.4f}\n")
        f.write(f"f1_score={f1:.4f}\n")
 
 
if __name__ == "__main__":
    main()
