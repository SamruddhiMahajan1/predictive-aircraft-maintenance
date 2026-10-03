import pandas as pd
import joblib

# Load dataset
df = pd.read_csv("data/training_dataset.csv")

# Load saved model
model = joblib.load("models/rul_random_forest.pkl")

# Load feature list
features = joblib.load("models/rul_features.pkl")

# Select one component
component = df.iloc[0]

# Prepare input
X_new = component[features].to_frame().T

# Predict RUL
predicted_rul = model.predict(X_new)[0]

# Actual derived RUL
actual_rul = component["rul_hours"]

print("\n===== SAVED MODEL TEST =====")

print(f"\nComponent ID : {component['component_id']}")
print(f"Component    : {component['component_name']}")
print(f"Aircraft     : {component['aircraft_id']}")

print(f"\nDerived RUL   : {actual_rul:.0f} hours")
print(f"Predicted RUL : {predicted_rul:.0f} hours")

print(
    f"Difference   : "
    f"{abs(actual_rul - predicted_rul):.0f} hours"
)

print("\n============================")