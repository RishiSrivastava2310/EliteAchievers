"""Canonical request contract. All labs use explicitly documented units."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Wide sparse rows: each non-null value is an observation, never an imputed zero.
RANGES = {
    "creatinine": (0.1, 30),
    "bun": (0, 250),
    "potassium": (1, 12),
    "bicarbonate": (2, 60),
    "lactate": (0, 40),
    "sodium": (90, 200),
    "glucose": (10, 1500),
    "hemoglobin": (2, 25),
    "wbc": (0, 200),
    "map": (20, 200),
    "heart_rate": (15, 260),
    "spo2": (40, 100),
    "respiratory_rate": (2, 80),
    "temperature": (25, 45),
    "weight_kg": (20, 350),
    "urine_output_ml": (0, 5000),
    "fluid_input_ml": (0, 10000),
    "ventilation": (0, 1),
    "vasopressor": (0, 1),
    "diuretic": (0, 1),
    "nephrotoxic_drug": (0, 1),
    "rrt": (0, 1),
    "dialysis_history": (0, 1),
}
UNITS = {
    "creatinine": "mg/dL",
    "bun": "mg/dL",
    "potassium": "mmol/L",
    "bicarbonate": "mmol/L",
    "lactate": "mmol/L",
    "sodium": "mmol/L",
    "glucose": "mg/dL",
    "hemoglobin": "g/dL",
    "wbc": "10^9/L",
    "map": "mmHg",
    "heart_rate": "bpm",
    "spo2": "%",
    "respiratory_rate": "/min",
    "temperature": "C",
    "weight_kg": "kg",
    "urine_output_ml": "mL per specified interval",
    "fluid_input_ml": "mL",
    "ventilation": "0/1",
    "vasopressor": "0/1",
    "diuretic": "0/1",
    "nephrotoxic_drug": "0/1",
    "rrt": "0/1",
    "dialysis_history": "0/1",
}


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    hour: float = Field(
        ge=-168,
        le=8760,
        description="Measurement time, hours relative to ICU admission",
    )
    available_hour: float | None = Field(default=None, ge=-168, le=9000)
    creatinine: float | None = None
    bun: float | None = None
    potassium: float | None = None
    bicarbonate: float | None = None
    lactate: float | None = None
    sodium: float | None = None
    glucose: float | None = None
    hemoglobin: float | None = None
    wbc: float | None = None
    map: float | None = None
    heart_rate: float | None = None
    spo2: float | None = None
    respiratory_rate: float | None = None
    temperature: float | None = None
    weight_kg: float | None = None
    urine_output_ml: float | None = None
    urine_interval_hours: float | None = Field(default=None, gt=0, le=24)
    fluid_input_ml: float | None = None
    ventilation: float | None = None
    vasopressor: float | None = None
    diuretic: float | None = None
    nephrotoxic_drug: float | None = None
    rrt: float | None = None
    dialysis_history: float | None = None

    @model_validator(mode="after")
    def validate_measurements(self):
        if self.available_hour is None:
            self.available_hour = self.hour
        if self.available_hour < self.hour:
            raise ValueError("available_hour cannot precede the measurement hour")
        present = 0
        for key, (low, high) in RANGES.items():
            value = getattr(self, key)
            if value is not None:
                present += 1
                if not low <= value <= high:
                    raise ValueError(
                        f"{key} must be between {low} and {high} {UNITS[key]}"
                    )
                if key in (
                    "ventilation",
                    "vasopressor",
                    "diuretic",
                    "nephrotoxic_drug",
                    "rrt",
                    "dialysis_history",
                ) and value not in (0, 1):
                    raise ValueError(f"{key} must be 0 or 1")
        if not present:
            raise ValueError("A reading must contain at least one measurement")
        if self.urine_interval_hours is not None and self.urine_output_ml is None:
            raise ValueError("urine_interval_hours requires urine_output_ml")
        return self


class Patient(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    age: float = Field(ge=18, le=110)
    sex: Literal["male", "female", "unknown"] = "unknown"
    weight_kg: float | None = Field(default=None, ge=20, le=350)
    admission_type: Literal["emergency", "elective", "urgent", "other", "unknown"] = (
        "unknown"
    )
    baseline_creatinine: float | None = Field(default=None, ge=0.1, le=30)
    baseline_hour: float | None = Field(default=None, ge=-168, le=8760)
    chronic_kidney_disease: bool | None = None
    diabetes: bool | None = None
    hypertension: bool | None = None
    heart_failure: bool | None = None
    chronic_dialysis: bool = False

    @model_validator(mode="after")
    def validate_baseline(self):
        if (self.baseline_creatinine is None) != (self.baseline_hour is None):
            raise ValueError(
                "Provide baseline_creatinine and its baseline_hour together"
            )
        return self


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    patient: Patient
    at_hour: float = Field(ge=0, le=8760)
    readings: list[Reading] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def validate_times(self):
        if any(
            r.hour > self.at_hour or r.available_hour > self.at_hour
            for r in self.readings
        ):
            raise ValueError(
                "Future or not-yet-available readings are not allowed in a prediction request"
            )
        if (
            self.patient.baseline_hour is not None
            and self.patient.baseline_hour > self.at_hour
        ):
            raise ValueError("Baseline must be known by prediction time")
        for row in self.readings:
            if (
                self.patient.baseline_hour is not None
                and row.hour == self.patient.baseline_hour
                and row.creatinine is not None
                and row.creatinine != self.patient.baseline_creatinine
            ):
                raise ValueError(
                    "Provided baseline conflicts with a creatinine reading at the same hour"
                )
        # Same variable at one measurement time must not have conflicting values.
        seen = {}
        urine_intervals = {}
        for row in self.readings:
            if row.urine_output_ml is not None and row.urine_interval_hours is not None:
                identity = (row.hour, row.available_hour)
                if (
                    identity in urine_intervals
                    and urine_intervals[identity] != row.urine_interval_hours
                ):
                    raise ValueError(
                        "Conflicting urine collection intervals at the same measurement and availability time"
                    )
                urine_intervals[identity] = row.urine_interval_hours
            for key in RANGES:
                value = getattr(row, key)
                if value is not None:
                    identity = (row.hour, row.available_hour, key)
                    if identity in seen and seen[identity] != value:
                        raise ValueError(
                            f"Conflicting {key} observations at hour {row.hour}"
                        )
                    seen[identity] = value
        return self


class ModelContribution(BaseModel):
    measurement: str
    contribution_percentage_points: float
    direction: Literal["increases_model_risk", "decreases_model_risk"]


class PredictionResponse(BaseModel):
    at_hour: float
    target: str
    horizon_hours: int
    status: Literal[
        "predicted",
        "aki_already_observed",
        "outside_new_aki_cohort",
        "insufficient_data",
    ]
    predicted_risk: float | None = Field(ge=0, le=1)
    predicted_risk_percent: float | None = Field(ge=0, le=100)
    risk_category: Literal["low", "moderate", "high"] | None
    alert: bool
    alert_options: dict = Field(default_factory=dict)
    alert_threshold: float = Field(ge=0, le=1)
    clinical_assessment: dict
    clinical_summary: dict = Field(default_factory=dict)
    data_quality: dict
    model_contributions: list[ModelContribution]
    input_sensitivity: dict | None = None
    model: dict
    notice: str
    lead_time_note: str


class StoredPredictionResponse(PredictionResponse):
    stay_id: str
    source: Literal["mimic", "eicu"]


class BatchPredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests: list[PredictionRequest] = Field(min_length=1, max_length=25)


class StoredBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stay_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=25
    )
    at_hour: float = Field(ge=0, le=8760)

    @model_validator(mode="after")
    def unique_stays(self):
        if len(set(self.stay_ids)) != len(self.stay_ids):
            raise ValueError("stay_ids must be unique")
        return self
