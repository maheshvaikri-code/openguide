import type { ContractSummary, Json, Pack, Run, RunFilter, TraceResponse } from "./types";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
  get needsToken(): boolean {
    return this.status === 401;
  }
}

export type ValidateResult =
  | { ok: true; hash: string; name: string | null; version: string | null; enforcement_floor: string; invariants: number }
  | { ok: false; error: string };

export interface ApiOptions {
  fetchImpl?: typeof fetch;
  getToken?: () => string | null;
  base?: string;
}

export interface Api {
  health(): Promise<boolean>;
  status(): Promise<{ auth_required: boolean } | null>;
  runs(filter?: RunFilter): Promise<Run[]>;
  run(id: string): Promise<Run>;
  trace(id: string): Promise<TraceResponse>;
  contracts(): Promise<ContractSummary[]>;
  contract(hash: string): Promise<{ hash: string; contract: Json }>;
  validate(body: unknown): Promise<ValidateResult>;
  register(body: unknown): Promise<{ contract_hash: string }>;
  packs(): Promise<{ packs: Pack[]; skipped: string[] }>;
}

async function readError(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  try {
    const j = JSON.parse(text) as { error?: unknown };
    if (typeof j.error === "string") return j.error;
  } catch {
    /* not JSON */
  }
  const snippet = text.replace(/\s+/g, " ").trim().slice(0, 120);
  return snippet || `Request failed (${res.status})`;
}

export function createApi(opts: ApiOptions = {}): Api {
  const base = opts.base ?? "";
  const doFetch: typeof fetch = opts.fetchImpl ?? ((...a) => fetch(...a));

  async function call(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    const token = opts.getToken?.();
    if (token) headers.set("authorization", `Bearer ${token}`);
    try {
      return await doFetch(base + path, { ...init, headers });
    } catch {
      throw new ApiError(0, "Couldn't reach the proxy. Check that it is running and try again.");
    }
  }

  async function getJson<T>(path: string): Promise<T> {
    const res = await call(path);
    if (res.status === 401) throw new ApiError(401, "This proxy needs an admin token.");
    if (!res.ok) throw new ApiError(res.status, await readError(res));
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError(res.status, "The proxy returned a response the Console couldn't read.");
    }
  }

  const q = (f: RunFilter = {}) => {
    const p = new URLSearchParams();
    if (f.contract) p.set("contract", f.contract);
    if (f.min_drift !== undefined) p.set("min_drift", String(f.min_drift));
    if (f.halted !== undefined) p.set("halted", String(f.halted));
    if (f.has_trace !== undefined) p.set("has_trace", String(f.has_trace));
    p.set("limit", String(f.limit ?? 10000));
    return p.toString();
  };

  return {
    async health() {
      try {
        return (await call("/healthz")).ok;
      } catch {
        return false;
      }
    },
    async status() {
      try {
        const res = await call("/v1/openguide/status");
        return res.ok ? ((await res.json()) as { auth_required: boolean }) : null;
      } catch {
        return null;
      }
    },
    async runs(filter) {
      return (await getJson<{ runs: Run[] }>(`/v1/openguide/runs?${q(filter)}`)).runs;
    },
    run: (id) => getJson<Run>(`/v1/openguide/runs/${encodeURIComponent(id)}`),
    trace: (id) => getJson<TraceResponse>(`/v1/openguide/runs/${encodeURIComponent(id)}/trace`),
    async contracts() {
      return (await getJson<{ contracts: ContractSummary[] }>("/v1/openguide/contracts")).contracts;
    },
    contract: (hash) => getJson(`/v1/openguide/contracts/${encodeURIComponent(hash)}`),
    async validate(body) {
      const res = await call("/v1/openguide/contracts/validate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 401) throw new ApiError(401, "This proxy needs an admin token.");
      if (res.status === 422) return { ok: false, error: await readError(res) };
      if (!res.ok) throw new ApiError(res.status, await readError(res));
      return (await res.json()) as ValidateResult;
    },
    async register(body) {
      const res = await call("/v1/openguide/contracts", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 401) throw new ApiError(401, "This proxy needs an admin token.");
      if (!res.ok) throw new ApiError(res.status, await readError(res));
      return (await res.json()) as { contract_hash: string };
    },
    packs: () => getJson("/v1/openguide/packs"),
  };
}

// Admin token: per tab only, never persisted beyond the session.
const KEY = "openguide.admin-token";
export const token = {
  get(): string | null {
    try {
      return sessionStorage.getItem(KEY);
    } catch {
      return null;
    }
  },
  set(v: string | null): void {
    try {
      if (v) sessionStorage.setItem(KEY, v);
      else sessionStorage.removeItem(KEY);
    } catch {
      /* storage unavailable: the token lives only until reload */
    }
  },
};
