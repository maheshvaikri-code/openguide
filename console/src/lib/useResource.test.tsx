import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useResource } from "./useResource";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useResource", () => {
  it("goes loading -> ready", async () => {
    const { result } = renderHook(() => useResource(() => Promise.resolve(42), []));
    expect(result.current[0].status).toBe("loading");
    await waitFor(() => expect(result.current[0]).toMatchObject({ status: "ready", data: 42 }));
  });

  it("goes loading -> error with the thrown error", async () => {
    const { result } = renderHook(() => useResource(() => Promise.reject(new Error("boom")), []));
    await waitFor(() => expect(result.current[0]).toMatchObject({ status: "error" }));
    expect((result.current[0] as { error: Error }).error.message).toBe("boom");
  });

  it("drops a stale response that arrives after a newer request", async () => {
    const slow = deferred<string>();
    const fast = deferred<string>();
    let which = "slow";
    const { result, rerender } = renderHook(({ k }) => useResource(() => (k === "slow" ? slow.promise : fast.promise), [k]), {
      initialProps: { k: which },
    });
    which = "fast";
    rerender({ k: which });
    await act(async () => fast.resolve("fresh"));
    await waitFor(() => expect(result.current[0]).toMatchObject({ status: "ready", data: "fresh" }));
    await act(async () => slow.resolve("stale"));
    expect(result.current[0]).toMatchObject({ status: "ready", data: "fresh" }); // not overwritten
  });

  it("keeps showing data when a background poll fails", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const { result } = renderHook(() =>
      useResource(() => (++calls === 1 ? Promise.resolve("ok") : Promise.reject(new Error("offline"))), [], 1000),
    );
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    expect(result.current[0]).toMatchObject({ status: "ready", data: "ok" });
    await act(async () => void (await vi.advanceTimersByTimeAsync(1000)));
    expect(result.current[0]).toMatchObject({ status: "ready", data: "ok" });
    expect((result.current[0] as { pollError: Error | null }).pollError?.message).toBe("offline");
    vi.useRealTimers();
  });

  it("does not poll while the tab is hidden, and resumes when it is shown", async () => {
    vi.useFakeTimers();
    let hidden = true;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    const load = vi.fn().mockResolvedValue("x");
    renderHook(() => useResource(load, [], 1000));
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    expect(load).toHaveBeenCalledTimes(1);                                   // the initial load
    await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));
    expect(load).toHaveBeenCalledTimes(1);                                   // hidden: no polling
    hidden = false;
    await act(async () => void (await vi.advanceTimersByTimeAsync(1000)));
    expect(load).toHaveBeenCalledTimes(2);                                   // visible again: polls
    vi.useRealTimers();
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
  });

  it("refresh() refetches in the background without dropping what is on screen", async () => {
    const d = deferred<string>();
    const load = vi.fn().mockResolvedValueOnce("first").mockReturnValueOnce(d.promise);
    const { result } = renderHook(() => useResource(load, []));
    await waitFor(() => expect(result.current[0]).toMatchObject({ status: "ready", data: "first" }));
    act(() => result.current[2]());                                          // refresh
    expect(result.current[0]).toMatchObject({ status: "ready", data: "first", refreshing: true });   // not "loading"
    await act(async () => d.resolve("second"));
    expect(result.current[0]).toMatchObject({ status: "ready", data: "second", refreshing: false });
  });
});
