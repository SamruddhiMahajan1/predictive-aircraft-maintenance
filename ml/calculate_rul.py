import pandas as pd

# Load components dataset
df = pd.read_csv("data/components.csv")

# Calculate remaining useful life
df["rul_hours"] = (
    df["life_limit_hours"] - df["operating_hours"]
)

df["rul_cycles"] = (
    df["life_limit_cycles"] - df["operating_cycles"]
)

# Calculate percentage of life already used
df["hours_used_pct"] = (
    df["operating_hours"] / df["life_limit_hours"]
) * 100

df["cycles_used_pct"] = (
    df["operating_cycles"] / df["life_limit_cycles"]
) * 100

# Save processed dataset
df.to_csv("data/components_with_rul.csv", index=False)

# Display important columns
print("\nRUL calculation completed!\n")

print(
    df[
        [
            "component_id",
            "component_name",
            "operating_hours",
            "life_limit_hours",
            "rul_hours",
            "operating_cycles",
            "life_limit_cycles",
            "rul_cycles",
            "hours_used_pct",
            "cycles_used_pct"
        ]
    ].head(10)
)

print("\nSaved to: data/components_with_rul.csv")