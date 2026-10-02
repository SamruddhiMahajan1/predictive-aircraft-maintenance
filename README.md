# Predictive Aircraft Maintenance & Fleet Availability

### SIH 2026 — Problem Statement 26249

> An AI-powered predictive maintenance system designed to anticipate
> aircraft component degradation, estimate Remaining Useful Life (RUL),
> prioritize maintenance actions, and support fleet availability.

---

## Problem

Aircraft maintenance can become reactive when component degradation
is identified only after significant performance deterioration.

This can lead to:

- Unexpected aircraft downtime
- Unplanned maintenance
- Reduced fleet availability
- Inefficient maintenance scheduling
- Difficulty prioritizing limited maintenance resources

The challenge is to move from **reactive maintenance** toward
**predictive and data-driven fleet readiness**.

---

## Our Solution

We propose an AI-driven predictive maintenance and fleet
availability platform.

The system processes aircraft health and telemetry data to:

1. Estimate component health
2. Predict Remaining Useful Life (RUL)
3. Identify aircraft at risk
4. Prioritize maintenance actions
5. Estimate the impact of maintenance on fleet availability

### Core Workflow

```text
Aircraft Health Data
        ↓
Data Preprocessing
        ↓
Feature Engineering
        ↓
AI / ML Prediction
        ↓
Health Score + RUL
        ↓
Risk Assessment
        ↓
Maintenance Recommendation
        ↓
Fleet Availability Dashboard
```

---

## Key Features

### 1. Aircraft Health Monitoring

Monitor aircraft/engine health parameters and identify degradation
trends over time.

### 2. Remaining Useful Life Prediction

Estimate the remaining operational life of a component using
machine-learning models.

### 3. Risk Assessment

Classify aircraft/component health into:

- Low Risk
- Medium Risk
- High Risk

### 4. Predictive Maintenance Recommendation

Generate maintenance priorities based on predicted degradation,
health condition, and remaining useful life.

### 5. Fleet Availability Monitoring

Provide a fleet-level view of:

- Operational aircraft
- Aircraft requiring maintenance
- High-risk aircraft
- Overall fleet availability

### 6. Maintenance Impact Simulation

Estimate how planned maintenance actions can affect overall
fleet availability.

---

## Key Innovation

The system goes beyond simply predicting component degradation.

It connects:

**Health Prediction → Risk Assessment → Maintenance Priority → Fleet Availability**

Instead of only identifying an unhealthy aircraft, the system aims
to determine which maintenance action should be prioritized to support
overall fleet readiness.

### Innovation Layers

- AI-based Remaining Useful Life prediction
- Component-level health scoring
- Risk-based maintenance prioritization
- Fleet-level availability monitoring
- Maintenance impact simulation

---

## AI/ML Approach

The prototype uses NASA C-MAPSS aircraft-engine prognostics data
to develop and evaluate a predictive-maintenance pipeline.

The modelling pipeline includes:

- Data preprocessing
- Time-series feature engineering
- RUL estimation
- Health-score generation
- Risk classification
- Model evaluation

Multiple machine-learning approaches can be evaluated, with the model
selected based on validation performance and suitability for the
prototype.

---

## Data

The prototype uses **NASA C-MAPSS aircraft-engine prognostics data**
for development and demonstration.

The dataset provides aircraft-engine sensor measurements and degradation
trajectories that can be used to develop and evaluate Remaining Useful
Life (RUL) prediction models.

Operational military aircraft telemetry is not publicly available.
Therefore, NASA C-MAPSS is used as a benchmark dataset to demonstrate
the proposed predictive-maintenance architecture.

The system is designed so that authorized aircraft health telemetry
can be integrated in a future deployment environment.

### Dataset Usage

The benchmark data is used to demonstrate:

```text
Engine Sensor Data
        ↓
Degradation Analysis
        ↓
RUL Prediction
        ↓
Health Assessment
        ↓
Risk Identification
```

---

## System Architecture

```text
                 AIRCRAFT HEALTH DATA
                         │
                         ▼
              ┌──────────────────────┐
              │  Data Preprocessing   │
              │ & Feature Engineering│
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │     AI/ML ENGINE     │
              │  Health + RUL Model  │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │     RISK ENGINE      │
              │  Low / Medium / High │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  MAINTENANCE ENGINE  │
              │    Priority + Action │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   FLEET READINESS    │
              │    & AVAILABILITY    │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │    WEB DASHBOARD     │
              └──────────────────────┘
```

---

## Technology Stack

### Machine Learning

- Python
- Pandas
- NumPy
- Scikit-learn
- XGBoost

### Backend

- FastAPI
- Python

### Frontend

- React / Next.js
- JavaScript
- Tailwind CSS

### Development

- Git
- GitHub

---

## Project Structure

```text
predictive-aircraft-maintenance/
│
├── backend/
│   ├── main.py
│   ├── model/
│   └── services/
│
├── ml/
│   ├── preprocessing.py
│   ├── train.py
│   ├── predict.py
│   └── evaluation.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── sample/
│
├── models/
│
├── frontend/
│
├── docs/
│   ├── architecture.png
│   ├── system-design.png
│   └── screenshots/
│
├── demo/
│   ├── demo-script.md
│   └── screenshots/
│
├── tests/
│
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Prototype Status

### Development Progress

- [ ] Dataset preprocessing
- [ ] RUL prediction model
- [ ] Health-score generation
- [ ] Risk classification
- [ ] Maintenance recommendation engine
- [ ] Fleet availability calculation
- [ ] Backend API
- [ ] Interactive dashboard
- [ ] End-to-end prototype
- [ ] Demo video

> **Note:** This checklist will be updated as the prototype progresses.

---

## Planned Prototype Capabilities

The prototype is planned to demonstrate:

- Aircraft/engine health monitoring
- Remaining Useful Life (RUL) prediction
- Component risk assessment
- Predictive maintenance prioritization
- Fleet availability monitoring
- Maintenance impact simulation
- Interactive fleet dashboard

---

## Current Limitations

- The prototype uses benchmark aircraft-engine data rather than
  operational military aircraft telemetry.
- Fleet-level scenarios are simulated for demonstration purposes.
- Maintenance recommendations are intended as decision-support outputs
  and not as operational maintenance instructions.
- Real-world deployment would require integration with authorized
  aircraft health-monitoring and maintenance systems.

---

## Team

**Team Name:** Konsors
**SIH 2026 — Problem Statement:** 26249

| Role | Member |
|---|---|
| Team Leader | Samruddhi Mahajan |
| Team Member | Aashutosh Barhate |
| Team Member | Aditi Kudekar |
| Team Member | Atharva Pardeshi |
| Team Member | Nitish Singh |
| Team Member | Shubham Palmate |

---

## Disclaimer

This is a student prototype developed for SIH 2026.

The prototype does not use classified, restricted, or operational
military aircraft data.

The prototype uses **NASA C-MAPSS aircraft-engine prognostics data**
for development and demonstration.

The benchmark data is used to demonstrate the predictive-maintenance
pipeline and does not represent the actual operational condition of
Indian military aircraft.

The proposed architecture is designed to support integration with
authorized aircraft health and telemetry data in a real deployment
environment.

---

## Future Scope

The system can be extended with:

- Integration with authorized real-time aircraft telemetry
- Edge/IoT-based health data acquisition
- Advanced time-series and deep-learning models
- Digital aircraft/component health twins
- Automated maintenance scheduling
- Fleet-wide resource optimization
- Integration with existing maintenance information systems
- Real-time fleet readiness monitoring

---

## Current Development Focus

Our immediate goal is to build an end-to-end working prototype:

**Aircraft Health Data → AI/RUL Prediction → Risk Assessment → Maintenance Recommendation → Fleet Availability**

---

## Results

### RUL Prediction Performance

| Metric | Value |
|---|---:|
| MAE | TBD |
| RMSE | TBD |

### Prototype Fleet Scenario

| Metric | Value |
|---|---:|
| Fleet Availability | TBD |
| High-Risk Aircraft | TBD |
| Maintenance Recommendations | TBD |

> Results will be updated after model training and prototype evaluation.

---

## Prototype Demo

The prototype will demonstrate:

1. Aircraft health data ingestion
2. RUL prediction
3. Aircraft risk identification
4. Maintenance prioritization
5. Fleet availability monitoring
6. Maintenance impact simulation

### Demo Video

Coming soon.
