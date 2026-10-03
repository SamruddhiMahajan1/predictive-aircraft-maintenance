import pandas as pd

# -----------------------------
# 1. Load datasets
# -----------------------------

components = pd.read_csv("data/components_with_rul.csv")
flights = pd.read_csv("data/flight_operations.csv")
maintenance = pd.read_csv("data/maintenance_records.csv")
snags = pd.read_csv("data/snag_logs.csv")
aircraft = pd.read_csv("data/aircraft.csv")


# -----------------------------
# 2. Aggregate flight history
# One row per aircraft
# -----------------------------

flight_summary = (
    flights.groupby("aircraft_id")
    .agg(
        total_flight_hours=("flight_hours", "sum"),
        total_sorties=("sorties", "sum"),
        total_flight_cycles=("flight_cycles", "sum"),
        total_high_stress_sorties=("high_stress_sorties", "sum"),
        total_days_available=("days_available", "sum"),
        total_days_unavailable=("days_unavailable", "sum")
    )
    .reset_index()
)


# -----------------------------
# 3. Aggregate maintenance history
# One row per component
# -----------------------------

maintenance_summary = (
    maintenance.groupby("component_id")
    .agg(
        maintenance_count=("maintenance_id", "count"),
        total_downtime_hours=("downtime_hours", "sum"),
        total_maintenance_cost=("cost_inr", "sum")
    )
    .reset_index()
)


# -----------------------------
# 4. Aggregate snag history
# One row per aircraft
# -----------------------------

snag_summary = (
    snags.groupby("aircraft_id")
    .agg(
        snag_count=("snag_id", "count")
    )
    .reset_index()
)


# -----------------------------
# 5. Select aircraft features
# -----------------------------

aircraft_features = aircraft[
    [
        "aircraft_id",
        "total_flight_hours",
        "total_cycles",
        "current_status"
    ]
].copy()


# -----------------------------
# 6. Rename duplicate aircraft
# fields from aircraft table
# -----------------------------

aircraft_features = aircraft_features.rename(
    columns={
        "total_flight_hours": "aircraft_total_flight_hours",
        "total_cycles": "aircraft_total_cycles",
        "current_status": "aircraft_status"
    }
)


# -----------------------------
# 7. Start with components
# -----------------------------

training = components.copy()


# -----------------------------
# 8. Merge maintenance history
# -----------------------------

training = training.merge(
    maintenance_summary,
    on="component_id",
    how="left"
)


# -----------------------------
# 9. Merge aircraft flight history
# -----------------------------

training = training.merge(
    flight_summary,
    on="aircraft_id",
    how="left"
)


# -----------------------------
# 10. Merge snag history
# -----------------------------

training = training.merge(
    snag_summary,
    on="aircraft_id",
    how="left"
)


# -----------------------------
# 11. Merge aircraft information
# -----------------------------

training = training.merge(
    aircraft_features,
    on="aircraft_id",
    how="left"
)


# -----------------------------
# 12. Fill missing history
# -----------------------------

numeric_columns = training.select_dtypes(
    include="number"
).columns

training[numeric_columns] = training[numeric_columns].fillna(0)


# -----------------------------
# 13. Save training dataset
# -----------------------------

training.to_csv(
    "data/training_dataset.csv",
    index=False
)


# -----------------------------
# 14. Display results
# -----------------------------

print("\nTraining dataset created successfully!\n")

print("Shape:", training.shape)

print("\nColumns:")
for column in training.columns:
    print("-", column)

print("\nFirst 5 rows:")
print(training.head())

print("\nSaved to:")
print("data/training_dataset.csv")