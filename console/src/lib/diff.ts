import type { Json } from "./types";

export interface DiffEntry {
  path: string;
  kind: "added" | "removed" | "changed";
  before?: Json;
  after?: Json;
}

const isObj = (v: Json | undefined): v is { [k: string]: Json } =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Structural diff of two JSON values. Arrays are compared by index. Paths look like a.b[2].c */
export function diffJson(a: Json | undefined, b: Json | undefined, path = ""): DiffEntry[] {
  if (a === undefined && b === undefined) return [];
  if (a === undefined) return [{ path: path || "(root)", kind: "added", after: b }];
  if (b === undefined) return [{ path: path || "(root)", kind: "removed", before: a }];

  if (Array.isArray(a) && Array.isArray(b)) {
    const out: DiffEntry[] = [];
    for (let i = 0; i < Math.max(a.length, b.length); i++) out.push(...diffJson(a[i], b[i], `${path}[${i}]`));
    return out;
  }
  if (isObj(a) && isObj(b)) {
    const out: DiffEntry[] = [];
    for (const k of [...new Set([...Object.keys(a), ...Object.keys(b)])].sort()) {
      out.push(...diffJson(a[k], b[k], path ? `${path}.${k}` : k));
    }
    return out;
  }
  return JSON.stringify(a) === JSON.stringify(b)
    ? []
    : [{ path: path || "(root)", kind: "changed", before: a, after: b }];
}
