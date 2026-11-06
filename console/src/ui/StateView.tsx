import { useState, type ReactNode } from "react";
import { ApiError, token } from "../lib/api";
import type { Resource } from "../lib/useResource";

export interface EmptyCopy {
  title: string;
  body: string;
  action?: ReactNode;
}

/**
 * The five states every surface must handle (docs: skills/ui.md):
 * loading, error, empty, partial (success with a notice) and success.
 */
export function StateView<T>({
  resource,
  reload,
  isEmpty,
  empty,
  children,
  label = "Loading",
}: {
  resource: Resource<T>;
  reload: () => void;
  isEmpty?: (data: T) => boolean;
  empty: EmptyCopy;
  children: (data: T) => ReactNode;
  label?: string;
}) {
  if (resource.status === "loading") {
    return (
      <div className="panel state" role="status" aria-live="polite">
        <span className="sr-only">{label}…</span>
        <div className="skeleton" style={{ width: 220 }} />
        <div className="skeleton" style={{ width: 320 }} />
        <div className="skeleton" style={{ width: 160 }} />
      </div>
    );
  }
  if (resource.status === "error") return <ErrorState error={resource.error} reload={reload} />;

  const { data, pollError } = resource;
  if (isEmpty?.(data)) {
    return (
      <div className="panel state">
        <span className="glyph" aria-hidden="true">○</span>
        <h2>{empty.title}</h2>
        <p>{empty.body}</p>
        {empty.action}
      </div>
    );
  }
  return (
    <>
      {pollError && (
        <div className="notice" role="status">
          Live updates paused: {pollError.message} Showing the last data received.
        </div>
      )}
      {children(data)}
    </>
  );
}

export function ErrorState({ error, reload }: { error: Error; reload: () => void }) {
  const needsToken = error instanceof ApiError && error.needsToken;
  const [value, setValue] = useState("");
  return (
    <div className="panel state error" role="alert">
      <span className="glyph" aria-hidden="true">!</span>
      <h2>{needsToken ? "Enter the admin token" : "Couldn't load this view"}</h2>
      <p>{error.message}</p>
      {needsToken ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            token.set(value.trim() || null);
            // Reload the whole page: other panels on this screen (filters, badges) may have
            // swallowed the same 401 and would otherwise stay empty until a manual refresh.
            window.location.reload();
          }}
          className="controls"
        >
          <label className="field">
            Admin token
            <input type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
          </label>
          <button className="btn primary" type="submit">Use token</button>
        </form>
      ) : (
        <button className="btn" onClick={reload}>Try again</button>
      )}
      {needsToken && <p>The token stays in this tab only and is cleared when you close it.</p>}
    </div>
  );
}
