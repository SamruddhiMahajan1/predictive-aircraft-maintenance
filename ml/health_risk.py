import pandas as pd


# Load training dataset
df = pd.read_csv("data/training_dataset.csv")


def calculate_health_score(row):

    # -----------------------------
    # 1. RUL-based health
    # -----------------------------
    rul_ratio = (
        row["rul_hours"] / row["life_limit_hours"]
    )

    rul_health = max(0, min(100, rul_ratio * 100))


    # -----------------------------
    # 2. Usage health
    # -----------------------------
    usage_health = 100 - (
        (
            row["hours_used_pct"]
            + row["cycles_used_pct"]
        ) / 2
    )

    usage_health = max(0, min(100, usage_health))


    # -----------------------------
    # 3. Maintenance health
    # -----------------------------
    maintenance_penalty = min(
        row["maintenance_count"] * 2,
        20
    )

    maintenance_health = 100 - maintenance_penalty


    # -----------------------------
    # 4. Snag health
    # -----------------------------
    snag_penalty = min(
        row["snag_count"] * 1.5,
        20
    )

    snag_health = 100 - snag_penalty


    # -----------------------------
    # Final weighted score
    # -----------------------------
    health_score = (
        0.50 * rul_health
        + 0.25 * usage_health
        + 0.15 * maintenance_health
        + 0.10 * snag_health
    )

    return round(
        max(0, min(100, health_score)),
        2
    )


# Calculate health score
df["health_score"] = df.apply(
    calculate_health_score,
    axis=1
)


# Risk classification
def classify_risk(score):

    if score >= 80:
        return "LOW"

    elif score >= 60:
        return "MEDIUM"

    elif score >= 40:
        return "HIGH"

    else:
        return "CRITICAL"


df["risk_level"] = df["health_score"].apply(
    classify_risk
)


# Save output
df.to_csv(
    "data/health_risk_dataset.csv",
    index=False
)


# Display results
print("\n===== HEALTH & RISK ANALYSIS =====")

print(
    df[
        [
            "component_id",
            "component_name",
            "rul_hours",
            "health_score",
            "risk_level"
        ]
    ].head(10)
)

print("\nRisk distribution:")

print(
    df["risk_level"].value_counts()
)

print("\nSaved to:")
print("data/health_risk_dataset.csv")

print("\n===================================")