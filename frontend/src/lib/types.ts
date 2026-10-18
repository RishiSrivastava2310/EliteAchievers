export type Role = 'doctor' | 'researcher' | 'admin';
export type Source = 'MIMIC-IV' | 'eICU-CRD' | 'Manual' | 'CSV';
export type RiskCategory = 'Low' | 'Moderate' | 'High' | 'Unavailable';
export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
}
export interface Session {
  user: User;
  token: string;
  mode: 'synthetic' | 'backend';
}
export interface SignInRequest {
  email: string;
  password: string;
}
export interface SignUpRequest extends SignInRequest {
  name: string;
}
export interface ReadingsRequest {
  readings: Reading[];
}
export interface FeatureContribution {
  feature: string;
  value: number;
  method: string;
}
export const measurementKeys = [
  'creatinine',
  'bun',
  'urineOutput',
  'map',
  'heartRate',
  'spo2',
  'potassium',
  'bicarbonate',
  'lactate',
] as const;
export type MeasurementKey = (typeof measurementKeys)[number];
export interface Reading {
  id: string;
  at: string;
  availableAt: string;
  key: MeasurementKey;
  value: number;
  intervalHours?: number;
}
export interface Forecast {
  at: string;
  availableAt: string;
  probability: number;
  horizonHours: 24;
  synthetic: boolean;
  modelVersion: string;
  contributions?: FeatureContribution[];
}
export interface IcuOutcome {
  status: 'died' | 'discharged_alive';
  at: string;
  availableAt: string;
}
export interface OutcomeUpdate {
  patientId: string;
  outcome: IcuOutcome;
}
export interface Patient {
  id: string;
  age: number;
  sex: 'Female' | 'Male' | 'Unknown';
  source: Source;
  unit: string;
  admission: string;
  admittedAt: string;
  durationHours: number;
  weightKg?: number;
  esrd: boolean;
  chronicDialysis: boolean;
  rrtAt?: string;
  readings: Reading[];
  forecasts: Forecast[];
  outcome?: IcuOutcome;
  synthetic: boolean;
}
export interface Recognition {
  status: 'Observed AKI' | 'No AKI observed' | 'Insufficient data';
  stage: number;
  onsetAt?: string;
  evidence: string[];
  urineAvailable: boolean;
}
export interface PatientSnapshot {
  patient: Patient;
  readings: Reading[];
  recognition: Recognition;
  forecast?: Forecast;
  probability?: number;
  risk: RiskCategory;
  eligibility: string | null;
  completeness: number;
  latestAt?: string;
}
export interface ResearchAlert {
  id: string;
  patientId: string;
  at: string;
  title: string;
  detail: string;
  severity: 'critical' | 'warning' | 'info';
  synthetic: boolean;
}
export interface Metric {
  name: string;
  value: number;
  lower?: number;
  upper?: number;
}
export interface Evaluation {
  id: string;
  name: string;
  trainSource: string;
  testSource: string;
  cohortSize: number;
  metrics: Metric[];
  roc?: { x: number; y: number }[];
  precisionRecall?: { x: number; y: number }[];
  calibration?: { x: number; y: number }[];
  falseAlertsPerPatientDay?: number;
  medianLeadTimeHours?: number;
  contributions?: FeatureContribution[];
}
export interface ModelStatus {
  state: 'unavailable' | 'ready';
  version?: string;
  description: string;
}
export interface PlatformData {
  patients: Patient[];
  evaluations: Evaluation[];
  model: ModelStatus;
  provenance: string;
}
export interface HealthResponse {
  status: 'ok';
  service: string;
}
export interface ApiErrorBody {
  detail?: string;
}
