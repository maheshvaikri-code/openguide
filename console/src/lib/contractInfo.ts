import type { Json, Run, StateRecord } from "./types";

/** One rule (invariant) of a contract, as the contract states it. Anything unstated is null. */
export interface Rule {
  id: string;
  measure: string | null;
  floor: number | null;
  weight: number | null;
  hard: boolean;
}

/** One rung of the recovery ladder. `gate: null` means "fires at the contract's drift threshold". */
export interface Rung {
  action: string;
  gate: number | null;
}

export interface ContractInfo {
  rules: Record<string, Rule>;
  boundaries: string[];
  persona: string | null;
  ladder: Rung[];
  threshold: number | null;
}

const isObj = (v: unknown): v is { [k: string]: Json } => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Read the parts of a stored contract the Console explains. Never throws, never guesses. */
export function parseContractInfo(contract: Json | null | undefined): ContractInfo {
  const info: ContractInfo = { rules: {}, boundaries: [], persona: null, ladder: [], threshold: null };
  if (!isObj(contract)) return info;

  const invs = contract["invariants"];
  if (Array.isArray(invs)) {
    for (const raw of invs) {
      if (!isObj(raw) || typeof raw["id"] !== "string") continue;
      info.rules[raw["id"]] = {
        id: raw["id"],
        measure: typeof raw["measure"] === "string" ? raw["measure"] : null,
        floor: num(raw["floor"]),
        // the OBC schema defaults a rule's weight to 1.0 when the contract doesn't state one
        weight: num(raw["weight"]) ?? 1,
        hard: raw["hard"] === true,
      };
    }
  }
  const ident = contract["identity"];
  if (isObj(ident)) {
    if (typeof ident["persona"] === "string") info.persona = ident["persona"];
    if (Array.isArray(ident["boundaries"])) info.boundaries = ident["boundaries"].filter((b): b is string => typeof b === "string");
  }
  const rec = contract["recovery"];
  if (isObj(rec)) {
    info.threshold = num(rec["drift_threshold"]);
    if (Array.isArray(rec["actions"])) {
      for (const a of rec["actions"]) {
        if (typeof a !== "string") continue;
        const [action, gate] = a.split("@");
        if (action) info.ladder.push({ action, gate: gate === undefined ? null : num(Number(gate)) });
      }
    }
  }
  return info;
}

export function measureKind(ref: string | null): string | null {
  if (ref === null) return null;
  const kind = ref.split(":", 1)[0];
  const names: Record<string, string> = {
    structural: "deterministic check", judge: "LLM judge", probe: "activation probe", external: "external signal",
  };
  return (kind && names[kind]) || "custom measure";
}

/** What each recovery action does, in plain words. Unknown actions are not given a made-up meaning. */
export const ACTION_MEANING: Record<string, string> = {
  re_anchor: "Restate the contract's persona and boundaries to the model with its next request.",
  escalate: "Recorded as an escalation and handled like a re-anchor. No hand-off to a person happens by itself.",
  halt: "Marks the run as halted in the record. The proxy does not itself stop later requests.",
};

export type RuleStatus = "met" | "missed" | "no-reading" | "not-scored" | "not-checked";

export interface DetectionRow {
  id: string;
  measure: string | null;
  kind: string | null;
  reading: number | null;
  floor: number | null;
  weight: number | null;
  hard: boolean;
  status: RuleStatus;
  /** How far below its floor the reading fell (0 when met). Null if there is no reading or floor. */
  shortfall: number | null;
  /** What this rule added to the turn's drift: weight x shortfall. Null when it can't be stated. */
  contribution: number | null;
}

/**
 * One row per rule for a turn. The trace (STATE record) is the source of truth for readings and
 * floors; the contract adds weights and measure kinds when it can be read. This mirrors the
 * reconciler: drift = sum over soft rules of weight x max(0, floor - reading), clipped to [0, 1];
 * a rule with no reading adds nothing; a hard rule counts only through its validation result.
 */
export function detectionRows(state: StateRecord, info: ContractInfo): DetectionRow[] {
  return Object.entries(state.invariants).map(([id, inv]) => {
    const rule = info.rules[id];
    const hard = rule?.hard ?? false;
    const floor = inv.floor ?? rule?.floor ?? null;
    const weight = rule?.weight ?? null;
    let status: RuleStatus;
    if (hard) {
      // Only deterministic (structural) hard rules are validated. A hard rule with no reading, or one the
      // validator never runs, must not read as passed.
      if (rule?.measure && !rule.measure.startsWith("structural:")) status = "not-checked";
      else if (state.validation_failures.includes(id)) status = "missed";
      else status = inv.reading === null ? "no-reading" : "met";
    } else if (inv.reading === null) status = "no-reading";
    else if (floor === null || floor <= 0) status = "not-scored";
    else status = inv.reading >= floor ? "met" : "missed";

    const scored = !hard && inv.reading !== null && floor !== null && floor > 0;
    const shortfall = scored ? Math.max(0, floor - (inv.reading as number)) : null;
    const contribution = shortfall !== null && weight !== null ? weight * shortfall : null;
    return {
      id, measure: rule?.measure ?? null, kind: measureKind(rule?.measure ?? null), reading: inv.reading, floor,
      weight, hard, status, shortfall, contribution,
    };
  });
}

/** The drift the rows add up to, or null if any scored rule's weight is unknown (so we can't claim it). */
export function explainedDrift(rows: readonly DetectionRow[]): number | null {
  let total = 0;
  for (const r of rows) {
    if (r.shortfall !== null && r.shortfall > 0 && r.contribution === null) return null;
    total += r.contribution ?? 0;
  }
  return Math.min(Math.max(total, 0), 1);
}

export interface LadderStep {
  action: string;
  gate: number | null;      // resolved: the contract's threshold when the rung has none of its own
  reached: boolean;
  defaulted: boolean;       // the gate is the compiler's default (1.0): the contract states none
  fired: boolean;           // this is the step whose action was recorded for the turn
}

/** The compiler's drift_threshold when a contract states none (guidancegrid/compiler/compile.py). */
const DEFAULT_THRESHOLD = 1;

/**
 * Each rung with its resolved gate and whether this drift reached it (at or above, as the reconciler does).
 * Several rungs can be reached at once; the reconciler records the LAST reached rung in list order, so that
 * is the one marked `fired` (matched to the action actually recorded, if given).
 */
export function ladderSteps(info: ContractInfo, drift: number, recorded: string | null = null): LadderStep[] {
  const steps = info.ladder.map((r) => {
    const stated = r.gate ?? info.threshold;
    const gate = stated ?? DEFAULT_THRESHOLD;
    return { action: r.action, gate, reached: drift >= gate, defaulted: stated === null, fired: false };
  });
  let last = -1;
  steps.forEach((s, i) => {
    if (s.reached && (recorded === null || s.action === recorded)) last = i;
  });
  if (last >= 0 && recorded !== null) steps[last]!.fired = true;
  return steps;
}

/** The drift at which this contract's first response step starts (its own gate, else its threshold). */
export function responseGate(info: ContractInfo): number | null {
  return info.ladder[0] ? (info.ladder[0].gate ?? info.threshold) : info.threshold;
}

/** One plain-language summary of a run, for the Fleet. Makes no threshold claim unless one is known. */
export function describeRun(run: Run, threshold: number | null): string {
  const peak = `Peaked at ${run.max_drift.toFixed(2)} drift`;
  const vs = threshold === null
    ? ""
    : run.max_drift >= threshold
      ? `, at or above this contract's threshold of ${threshold}`
      : `, below this contract's threshold of ${threshold}`;
  const fixes = run.recoveries === 0
    ? "No correction fired."
    : `${run.recoveries} ${run.recoveries === 1 ? "correction" : "corrections"} fired.`;
  return `${peak}${vs}. ${fixes}${run.halted ? " The run was flagged halted in the record." : ""}`;
}
