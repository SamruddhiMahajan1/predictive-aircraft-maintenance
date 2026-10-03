import pandas as pd
from sklearn.model_selection import train_test_split

# Load training dataset
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

# Create X and y
X = df[features]
y = df[target]

# Split dataset
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.20,
    random_state=42
)

print("\nDataset preparation completed!")

print("\nTotal samples:", len(df))
print("Training samples:", len(X_train))
print("Testing samples:", len(X_test))

print("\nNumber of features:", X.shape[1])

print("\nTraining feature shape:", X_train.shape)
print("Testing feature shape:", X_test.shape)

print("\nTarget:")
print(target)

print("\nFirst training sample:")
print(X_train.iloc[0])

print("\nCorresponding target:")
print(y_train.iloc[0])