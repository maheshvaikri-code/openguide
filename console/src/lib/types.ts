// Shapes returned by the proxy's /v1/openguide/* API (see proxy/app.py, proxy/console_api.py).

export interface Run {
  run_id: string;
  contract_hash: string;
  model: string;
  tier: string;
  turns: number;
  max_drift: number;
  recoveries: number;
  halted: boolean;
  verified: boolean;
  trace_hash: string;
  trace_cas_key: string;
  created: string;
}

export interface InvariantReading {
  reading: number | null;      // null = sensor gap
  floor: number | null;
  violated: boolean;
  determinism?: string;
}

/** One behavioural-state record (ev === "STATE"), as appended by the Reconciler. */
export interface StateRecord {
  ev: "STATE";
  prev?: string;
  turn: number;
  tier_active: string;
  invariants: Record<string, InvariantReading>;
  drift: number;
  signals_active: Record<string, number>;
  recovery_fired: string | null;
  validation_failures: string[];
  sensor_gaps: string[];
  reanchored: boolean;
}

/** What was said on one turn. Present only when the proxy ran with content capture on (off by default). */
export interface TurnRecord {
  ev: "TURN";
  turn: number;
  user: string;
  output: string;
  /** The re-anchor sent to the model with this turn's request, or null. */
  restated: string | null;
  truncated: boolean;
}

export interface ChainReport {
  ok: boolean;
  checked: number;
  /** Index of the first record whose link fails; the chain verified up to here. */
  break_at: number | null;
  reason: string | null;
}

export interface TraceResponse {
  manifest: Record<string, unknown>;
  head: string;
  verified: boolean;
  chain?: ChainReport;
  cas_key: string | null;
  records?: Array<Record<string, unknown>>;
  metadata_only?: boolean;
  record_count?: number;
  event_counts?: Record<string, number>;
}

export interface ContractSummary {
  hash: string;
  name: string | null;
  version: string | null;
  enforcement_floor: string;
  invariants: number;
}

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

export interface Pack {
  name: string;
  model_id: string;
  pack_hash: string;
  signals: string[];
  layers: number;
  dim: number;
  status: string;
  note?: string;
  evals: {
    mmlu_delta_at_gain?: Record<string, number | null>;
    gsm8k_delta_at_gain?: Record<string, number | null>;
    coherence_ok?: boolean | null;
  };
}

export interface RunFilter {
  contract?: string;
  min_drift?: number;
  halted?: boolean;
  has_trace?: boolean;
  limit?: number;
}
