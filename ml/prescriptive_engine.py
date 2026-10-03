import pandas as pd


# Load health and risk dataset
df = pd.read_csv("data/health_risk_dataset.csv")


def generate_recommendation(row):

    risk = row["risk_level"]
    rul = row["rul_hours"]
    health = row["health_score"]

    # Critical
    if risk == "CRITICAL":

        action = "Immediate maintenance assessment"
        urgency = "CRITICAL"

    # High risk
    elif risk == "HIGH":

        action = "Schedule maintenance inspection"
        urgency = "HIGH"

    # Medium risk
    elif risk == "MEDIUM":

        action = "Plan preventive maintenance"
        urgency = "MEDIUM"

    # Low risk
    else:

        action = "Continue monitoring"
        urgency = "LOW"

    # Explanation
    if rul < 1000:

        reason = (
            "Low remaining useful life"
        )

    elif health < 60:

        reason = (
            "Reduced component health"
        )

    elif row["maintenance_count"] >= 3:

        reason = (
            "Repeated maintenance history"
        )

    elif row["snag_count"] >= 8:

        reason = (
            "Frequent snag reports"
        )

    else:

        reason = (
            "Routine condition monitoring"
        )

    return pd.Series(
        [
            action,
            urgency,
            reason
        ]
    )


# Generate recommendations
df[
    [
        "recommended_action",
        "maintenance_urgency",
        "recommendation_reason"
    ]
] = df.apply(
    generate_recommendation,
    axis=1
)


# Save output
df.to_csv(
    "data/prescriptive_output.csv",
    index=False
)


# Display results
print("\n===== PRESCRIPTIVE ENGINE =====")

print(
    df[
        [
            "component_id",
            "component_name",
            "health_score",
            "risk_level",
            "rul_hours",
            "recommended_action",
            "maintenance_urgency",
            "recommendation_reason"
        ]
    ].head(15)
)

print("\nMaintenance urgency distribution:")

print(
    df["maintenance_urgency"].value_counts()
)

print("\nSaved to:")
print("data/prescriptive_output.csv")

print("\n==============================")