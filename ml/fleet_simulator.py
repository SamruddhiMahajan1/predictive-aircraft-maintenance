import pandas as pd


# -----------------------------
# Load datasets
# -----------------------------

aircraft = pd.read_csv(
    "data/aircraft.csv"
)

flight_ops = pd.read_csv(
    "data/flight_operations.csv"
)

maintenance_plans = pd.read_csv(
    "data/maintenance_plans.csv"
)


# -----------------------------
# Calculate current availability
# -----------------------------

availability = (
    flight_ops
    .groupby("aircraft_id")
    .agg(
        total_days_available=("days_available", "sum"),
        total_days_unavailable=("days_unavailable", "sum")
    )
    .reset_index()
)

availability["total_days"] = (
    availability["total_days_available"]
    + availability["total_days_unavailable"]
)

availability["current_availability_pct"] = (
    availability["total_days_available"]
    / availability["total_days"]
) * 100


# -----------------------------
# Calculate planned downtime
# -----------------------------

planned_downtime = (
    maintenance_plans
    .groupby("aircraft_id")
    .agg(
        planned_maintenance_days=(
            "agency_turnaround_days",
            "sum"
        ),
        maintenance_actions=(
            "component_id",
            "count"
        )
    )
    .reset_index()
)


# -----------------------------
# Merge
# -----------------------------

simulation = availability.merge(
    planned_downtime,
    on="aircraft_id",
    how="left"
)


# Aircraft without planned maintenance
simulation[
    "planned_maintenance_days"
] = simulation[
    "planned_maintenance_days"
].fillna(0)

simulation[
    "maintenance_actions"
] = simulation[
    "maintenance_actions"
].fillna(0)


# -----------------------------
# Simulate BEFORE vs AFTER
# -----------------------------

simulation["simulated_available_days"] = (
    simulation["total_days_available"]
)

simulation["simulated_unavailable_days"] = (
    simulation["total_days_unavailable"]
    + simulation["planned_maintenance_days"]
)


simulation["simulated_total_days"] = (
    simulation["simulated_available_days"]
    + simulation["simulated_unavailable_days"]
)


simulation["simulated_availability_pct"] = (
    simulation["simulated_available_days"]
    / simulation["simulated_total_days"]
) * 100


# -----------------------------
# Fleet-level metrics
# -----------------------------

fleet_current_availability = (
    simulation["total_days_available"].sum()
    /
    (
        simulation["total_days_available"].sum()
        +
        simulation["total_days_unavailable"].sum()
    )
) * 100


fleet_simulated_availability = (
    simulation["simulated_available_days"].sum()
    /
    simulation["simulated_total_days"].sum()
) * 100


# -----------------------------
# Save
# -----------------------------

simulation.to_csv(
    "data/fleet_simulation.csv",
    index=False
)


# -----------------------------
# Display
# -----------------------------

print("\n===== FLEET SIMULATOR =====")

print("\nFleet current availability:")
print(
    f"{fleet_current_availability:.2f}%"
)

print("\nFleet simulated availability:")
print(
    f"{fleet_simulated_availability:.2f}%"
)

print("\nAircraft requiring planned maintenance:")

print(
    simulation[
        simulation["maintenance_actions"] > 0
    ][
        [
            "aircraft_id",
            "current_availability_pct",
            "maintenance_actions",
            "planned_maintenance_days",
            "simulated_availability_pct"
        ]
    ].head(15)
)

print("\nSaved to:")
print("data/fleet_simulation.csv")

print("\n==========================")