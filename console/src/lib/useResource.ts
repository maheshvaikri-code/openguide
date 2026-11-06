import { useCallback, useEffect, useRef, useState } from "react";

export type Resource<T> =
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "ready"; data: T; refreshing: boolean; pollError: Error | null };

/**
 * Load async data with a loading / error / ready state machine.
 *
 * - A response that arrives after a newer request was started is dropped, so a slow
 *   earlier request can never overwrite fresher data (live tail, fast filter changes).
 * - Background polling keeps showing the last good data; a failed poll is reported in
 *   `pollError` instead of blanking the screen.
 */
export function useResource<T>(
  load: () => Promise<T>,
  deps: ReadonlyArray<unknown>,
  pollMs?: number,
): [Resource<T>, () => void, () => void] {
  const [state, setState] = useState<Resource<T>>({ status: "loading" });
  const seq = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const run = useCallback((silent: boolean) => {
    const mine = ++seq.current;
    if (!silent) setState({ status: "loading" });
    else setState((s) => (s.status === "ready" ? { ...s, refreshing: true } : s));
    loadRef.current().then(
      (data) => {
        if (mine === seq.current) setState({ status: "ready", data, refreshing: false, pollError: null });
      },
      (error: unknown) => {
        if (mine !== seq.current) return;
        const err = error instanceof Error ? error : new Error(String(error));
        setState((s) =>
          silent && s.status === "ready"
            ? { ...s, refreshing: false, pollError: err }
            : { status: "error", error: err },
        );
      },
    );
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => run(false), [run, ...deps]);

  useEffect(() => {
    if (!pollMs) return;
    // Don't poll a tab nobody is looking at: a 10 000-run fleet is megabytes per refresh.
    const id = setInterval(() => {
      if (typeof document === "undefined" || !document.hidden) run(true);
    }, pollMs);
    return () => clearInterval(id);
  }, [run, pollMs]);

  // invalidate in-flight requests on unmount
  useEffect(() => () => void ++seq.current, []);

  // reload() shows the loading state; refresh() refetches in the background and keeps what is on screen
  return [state, useCallback(() => run(false), [run]), useCallback(() => run(true), [run])];
}
