import pandas as pd
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import numpy as np

# Load dataset
df = pd.read_csv("data/training_dataset.csv")

# Features
features = [
    "operating_hours",
    "operating_cycles",
    "life_limit_hours",
    "life_limit_cycles",
    "hours_used_pct",
    "cycles_used_pct",
    "times_replaced",
    "maintenance_count",
    "total_downtime_hours",
    "total_maintenance_cost",
    "total_flight_hours",
    "total_sorties",
    "total_flight_cycles",
    "total_high_stress_sorties",
    "total_days_available",
    "total_days_unavailable",
    "snag_count",
    "aircraft_total_flight_hours",
    "aircraft_total_cycles"
]

# Target
target = "rul_hours"

X = df[features]
y = df[target]

# IMPORTANT:
# Use exactly the same split as Random Forest
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.20,
    random_state=42
)

# Create XGBoost model
model = XGBRegressor(
    n_estimators=200,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    objective="reg:squarederror",
    random_state=42,
    n_jobs=-1
)

# Train
print("Training XGBoost model...")

model.fit(X_train, y_train)

print("Training completed!")

# Predictions
predictions = model.predict(X_test)

# Evaluate
mae = mean_absolute_error(y_test, predictions)

rmse = np.sqrt(
    mean_squared_error(y_test, predictions)
)

r2 = r2_score(y_test, predictions)

print("\n===== XGBOOST EVALUATION =====")

print(f"\nMAE  : {mae:.2f} hours")
print(f"RMSE : {rmse:.2f} hours")
print(f"R²   : {r2:.4f}")

print("\nFirst 10 predictions:")

for actual, predicted in zip(
    y_test.iloc[:10],
    predictions[:10]
):
    print(
        f"Actual: {actual:.0f} hours | "
        f"Predicted: {predicted:.0f} hours"
    )

print("\n==============================")