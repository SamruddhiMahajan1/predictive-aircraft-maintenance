import pandas as pd


# -----------------------------
# Load datasets
# -----------------------------

prescriptive = pd.read_csv(
    "data/prescriptive_output.csv"
)

parts = pd.read_csv(
    "data/spare_parts.csv"
)

agencies = pd.read_csv(
    "data/maintenance_agencies.csv"
)


# -----------------------------
# Create maintenance plan
# -----------------------------

plans = []


for _, row in prescriptive.iterrows():

    # Only plan maintenance for
    # HIGH or CRITICAL components
    if row["maintenance_urgency"] not in [
        "HIGH",
        "CRITICAL"
    ]:
        continue

    component_id = row["component_id"]
    component_name = row["component_name"]

    # -------------------------
    # Find compatible part
    # -------------------------

    matching_parts = parts[
        parts["component_id"] == component_id
    ]

    # If exact component ID is unavailable,
    # try matching component name
    if matching_parts.empty:

        matching_parts = parts[
            parts["component_name"] == component_name
        ]

    if matching_parts.empty:

        part_id = "PART_NOT_FOUND"
        part_name = "No compatible part found"
        quantity = 0
        lead_time = None

    else:

        part = matching_parts.iloc[0]

        part_id = part["part_id"]
        part_name = part["part_name"]
        quantity = part["quantity_available"]
        lead_time = part["lead_time_days"]


    # -------------------------
    # Find suitable agency
    # -------------------------

    # First try matching component name
    suitable_agencies = agencies[
        agencies["specialisation"].str.contains(
            component_name,
            case=False,
            na=False
        )
    ]

    # If no exact specialization match,
    # use all agencies and choose the fastest
    if suitable_agencies.empty:
        suitable_agencies = agencies.copy()

    agency = suitable_agencies.sort_values(
        "average_turnaround_days"
    ).iloc[0]


    # -------------------------
    # Create plan
    # -------------------------

    plans.append({

        "component_id": component_id,

        "component_name": component_name,

        "aircraft_id": row["aircraft_id"],

        "risk_level": row["risk_level"],

        "maintenance_urgency":
            row["maintenance_urgency"],

        "rul_hours": row["rul_hours"],

        "recommended_action":
            row["recommended_action"],

        "part_id": part_id,

        "part_name": part_name,

        "part_quantity_available": quantity,

        "part_lead_time_days": lead_time,

        "agency_id": agency["agency_id"],

        "agency_name": agency["agency_name"],

        "agency_specialisation":
            agency["specialisation"],

        "agency_turnaround_days":
            agency["average_turnaround_days"],

        "estimated_duration_hours":
            agency["average_turnaround_days"] * 24

    })


# -----------------------------
# Convert to DataFrame
# -----------------------------

planner_df = pd.DataFrame(plans)


# -----------------------------
# Save
# -----------------------------

planner_df.to_csv(
    "data/maintenance_plans.csv",
    index=False
)


# -----------------------------
# Display
# -----------------------------

print("\n===== MAINTENANCE PLANNER =====")

print(
    planner_df[
        [
            "component_id",
            "component_name",
            "aircraft_id",
            "risk_level",
            "part_id",
            "part_name",
            "part_quantity_available",
            "agency_name",
            "agency_turnaround_days"
        ]
    ].head(15)
)

print("\nTotal maintenance plans:")

print(len(planner_df))

print("\nSaved to:")
print("data/maintenance_plans.csv")

print("\n===============================")