export interface Parameter {
  name: string;
  label: string;
  value: number;
  unit: string;
}
export interface Feature {
  id: string;
  name: string;
  op: string;
  args: Record<string, unknown>;
}
export interface Design {
  name: string;
  parameters: Parameter[];
  features: Feature[];
}
export interface Metrics {
  size: number[];
  bounds: number[];
  volume: number;
  area: number;
  solids: number;
  valid: boolean;
  dimensions?: { label: string; value: number; unit: string }[];
}
export interface Step {
  index: number;
  feature: Feature;
  file: string;
  metrics: Metrics;
  elapsed: number;
  url?: string;
}
export interface Result {
  steps: Step[];
  metrics: Metrics;
  elapsed: number;
  total_seconds: number;
  source: string;
  attempts: number;
  artifact_base: string;
  changes?: {
    parameters: {
      name: string;
      label: string;
      before: number | null;
      after: number | null;
    }[];
    added: string[];
    removed: string[];
    modified: string[];
  };
  mesh: { watertight: boolean; vertices: number; faces: number };
}
export interface Revision {
  id: string;
  parent: string | null;
  design: Design;
  result: Result;
  created: string;
}
export interface Job {
  id: string;
  status: string;
  error: string | null;
}
export interface Project {
  id: string;
  name: string;
  current_revision: string | null;
  created: string;
  messages: { id: number; role: string; content: string; created: string }[];
  revisions: { id: string; created: string; parent: string | null }[];
  revision: Revision | null;
  jobs: Job[];
}
export interface JobEvent {
  id: number;
  type: string;
  data: Record<string, any>;
}
export interface Example {
  id: string;
  name: string;
  prompt: string;
  features: number;
}
export interface Health {
  model_exists: boolean;
  model_loaded: boolean;
  model_name: string;
  active_model?: string | null;
  ram_available_gb: number;
  runtime: string;
}
