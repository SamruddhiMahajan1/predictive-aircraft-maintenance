import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor

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

# Same split as Step 8
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.20,
    random_state=42
)

# Create Random Forest model
model = RandomForestRegressor(
    n_estimators=200,
    random_state=42,
    n_jobs=-1
)

# Train
print("Training Random Forest model...")

model.fit(X_train, y_train)

print("Training completed!")

# Make predictions
predictions = model.predict(X_test)

print("\nFirst 10 predictions:")

for actual, predicted in zip(
    y_test.iloc[:10],
    predictions[:10]
):
    print(
        f"Actual: {actual:.0f} hours | "
        f"Predicted: {predicted:.0f} hours"
    )