import { useEffect, useState } from "react";

export type PageName = "fleet" | "run" | "trajectory" | "contracts" | "packs" | "audit";
export interface Route {
  page: PageName;
  param: string | null;
}

const PAGES: PageName[] = ["fleet", "run", "trajectory", "contracts", "packs", "audit"];

/** "#/run/abc%2F1" -> {page:"run", param:"abc/1"}. Unknown pages fall back to the fleet. */
export function parseHash(hash: string): Route {
  const path = hash.replace(/^#\/?/, "").split("?")[0] ?? "";
  const [first, ...rest] = path.split("/");
  const page = PAGES.find((p) => p === first) ?? "fleet";
  const raw = rest.join("/");
  let param: string | null = null;
  if (raw) {
    try {
      param = decodeURIComponent(raw);
    } catch {
      param = raw;
    }
  }
  return { page, param };
}

export function hrefFor(page: PageName, param?: string | null): string {
  return `#/${page}${param ? `/${encodeURIComponent(param)}` : ""}`;
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
