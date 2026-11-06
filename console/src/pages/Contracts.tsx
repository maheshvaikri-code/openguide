import { useMemo, useRef, useState } from "react";
import type { ValidateResult } from "../lib/api";
import { diffJson } from "../lib/diff";
import { hrefFor } from "../lib/router";
import type { Json } from "../lib/types";
import { useResource } from "../lib/useResource";
import { useApi } from "../ui/ApiContext";
import { StateView } from "../ui/StateView";
import { shortHash } from "../ui/format";

export function ContractsPage({ selected }: { selected: string | null }) {
  const api = useApi();
  const [res, reload, refresh] = useResource(() => api.contracts(), []);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Contracts</h1>
          <p>A contract declares how an agent must behave. Its hash is its identity: change one value and you have a different contract.</p>
        </div>
      </div>
      <StateView
        resource={res}
        reload={reload}
        label="Loading contracts"
        isEmpty={(d) => d.length === 0}
        empty={{ title: "No contracts registered", body: "Load contracts from a directory with OPENGUIDE_CONTRACTS_DIR, or register one by POSTing it to /v1/openguide/contracts." }}
      >
        {(list) => (
          <div className="split contracts">
            <section className="panel" aria-label="Registered contracts">
              <header><h2>{list.length} registered</h2></header>
              <table>
                <thead><tr><th>Contract</th><th>Floor</th><th className="r">Invariants</th></tr></thead>
                <tbody>
                  {list.map((c) => (
                    <tr key={c.hash} data-active={c.hash === selected}>
                      <td>
                        <a href={hrefFor("contracts", c.hash)} aria-current={c.hash === selected ? "true" : undefined}>
                          {c.name ?? "Unnamed contract"} <span className="muted">{c.version ?? ""}</span>
                        </a>
                        <div className="mono muted">{shortHash(c.hash, 12)}</div>
                      </td>
                      <td>{c.enforcement_floor.toUpperCase()}</td>
                      <td className="r num">{c.invariants}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            {selected ? (
              <Editor key={selected} hash={selected} others={list.filter((c) => c.hash !== selected)} onRegistered={refresh} />
            ) : (
              <div className="panel state"><span className="glyph" aria-hidden="true">§</span><h2>Select a contract</h2><p>Choose one on the left to read it, edit a copy, compare it with another, or copy the header that activates it.</p></div>
            )}
          </div>
        )}
      </StateView>
    </>
  );
}

type Others = Array<{ hash: string; name: string | null; version: string | null }>;

/** Loads the contract, then mounts the editor with its text already in place (no empty-editor flash). */
function Editor({ hash, others, onRegistered }: { hash: string; others: Others; onRegistered: () => void }) {
  const api = useApi();
  const [res, reload] = useResource(() => api.contract(hash), [hash]);
  return (
    <StateView resource={res} reload={reload} label="Loading contract" empty={{ title: "Contract not found", body: "It may have been removed from this proxy." }}>
      {(d) => <EditorBody key={hash} hash={hash} contract={d.contract} others={others} onRegistered={onRegistered} />}
    </StateView>
  );
}

function EditorBody({ hash, contract, others, onRegistered }: { hash: string; contract: Json; others: Others; onRegistered: () => void }) {
  const api = useApi();
  const [text, setText] = useState(() => JSON.stringify(contract, null, 2));
  const [check, setCheck] = useState<ValidateResult | { pending: true } | { error: string } | null>(null);
  const [cmp, setCmp] = useState("");
  const [copied, setCopied] = useState<"idle" | "ok" | "failed">("idle");
  const checkSeq = useRef(0); // a slow check must not overwrite the result for text that has since changed
  const [registered, setRegistered] = useState<string | null>(null);

  const parsed = useMemo<{ ok: true; value: Json } | { ok: false; error: string }>(() => {
    try {
      return { ok: true, value: JSON.parse(text) as Json };
    } catch (e) {
      return { ok: false, error: (e as Error).message };
    }
  }, [text]);

  const [other] = useResource<{ hash: string; contract: Json } | null>(
    async () => (cmp ? await api.contract(cmp) : null),
    [cmp],
  );
  const changes = useMemo(() => {
    if (other.status !== "ready" || !other.data) return null;
    return diffJson(other.data.contract, contract);
  }, [contract, other]);

  const runCheck = async () => {
    if (!parsed.ok) return;
    const mine = ++checkSeq.current;
    setCheck({ pending: true });
    try {
      const r = await api.validate(parsed.value);
      if (mine === checkSeq.current) setCheck(r);
    } catch (e) {
      if (mine === checkSeq.current) setCheck({ error: (e as Error).message });
    }
  };
  const register = async () => {
    if (!parsed.ok) return;
    try {
      const r = await api.register(parsed.value);
      setRegistered(r.contract_hash);
      onRegistered();
    } catch (e) {
      setCheck({ error: (e as Error).message });
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`X-OpenGuide-Contract: ${hash}`);
      setCopied("ok");
    } catch {
      setCopied("failed"); // e.g. a non-secure page or denied permission: say so, the header is selectable above
    }
    setTimeout(() => setCopied("idle"), 2500);
  };

  return (
    <div className="stack">
      <section className="panel" aria-label="Activate this contract">
        <header><h2>Use this contract</h2></header>
        <div className="body stack">
          <p className="muted">Send this header with any request to the proxy to govern it with this contract.</p>
          <div className="controls">
            <code className="chip" style={{ fontSize: 13, margin: 0 }}>X-OpenGuide-Contract: {hash}</code>
            <button className="btn" onClick={copy}>{copied === "ok" ? "Copied" : "Copy header"}</button>
            {copied === "failed" && <span className="muted" role="status">Couldn't copy. Select the header text and copy it by hand.</span>}
          </div>
        </div>
      </section>

      <section className="panel" aria-label="Contract editor">
        <header><h2>Contract body</h2><span className="muted">JSON, as the proxy stores it</span></header>
        <div className="body stack">
          <label className="field">
            <span className="sr-only">Contract JSON</span>
            <textarea
              className="editor"
              value={text}
              spellCheck={false}
              aria-invalid={!parsed.ok}
              aria-describedby="editor-status"
              onChange={(e) => { checkSeq.current += 1; setText(e.target.value); setCheck(null); setRegistered(null); }}
            />
          </label>
          <div id="editor-status" aria-live="polite" className="stack">
            {!parsed.ok && <p className="notice bad">This isn't valid JSON yet: {parsed.error}</p>}
            {check && "pending" in check && <p className="muted">Checking…</p>}
            {check && "error" in check && <p className="notice bad">{check.error}</p>}
            {check && "ok" in check && check.ok === false && <p className="notice bad">The proxy rejected this contract: {check.error}</p>}
            {check && "ok" in check && check.ok === true && (
              <p className="notice">
                Valid. {check.hash === hash
                  ? "Same hash as the stored contract, so nothing has changed."
                  : <>This would be a different contract: <span className="mono">{shortHash(check.hash, 16)}</span> instead of <span className="mono">{shortHash(hash, 16)}</span>.</>}
              </p>
            )}
            {registered && <p className="notice">Registered as <a className="mono" href={hrefFor("contracts", registered)}>{shortHash(registered, 16)}</a>.</p>}
          </div>
          <div className="controls">
            <button className="btn primary" disabled={!parsed.ok} onClick={runCheck}>Check contract</button>
            <button className="btn" disabled={!(check && "ok" in check && check.ok && check.hash !== hash)} onClick={register}
              title="Adds the edited contract to this proxy under its new hash">
              Register as a new contract
            </button>
          </div>
        </div>
      </section>

      <section className="panel" aria-label="Compare contracts">
        <header>
          <h2>Compare</h2>
          <span className="grow" />
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            Compare against
            <select value={cmp} onChange={(e) => setCmp(e.target.value)}>
              <option value="">Choose a contract</option>
              {others.map((o) => <option key={o.hash} value={o.hash}>{o.name ?? "Unnamed contract"} {o.version ?? ""}</option>)}
            </select>
          </label>
        </header>
        {!cmp ? (
          <div className="state"><p>Pick another contract to see exactly what differs.</p></div>
        ) : other.status === "loading" ? (
          <div className="state" role="status"><div className="skeleton" style={{ width: 200 }} /></div>
        ) : other.status === "error" ? (
          <div className="state" role="alert"><p>{other.error.message}</p></div>
        ) : changes && changes.length === 0 ? (
          <div className="state"><p>These two contracts are identical.</p></div>
        ) : (
          <table className="fixed">
            <colgroup><col style={{ width: "24%" }} /><col style={{ width: "12%" }} /><col style={{ width: "32%" }} /><col style={{ width: "32%" }} /></colgroup>
            <thead><tr><th>Where</th><th>Change</th><th>Other contract</th><th>This contract</th></tr></thead>
            <tbody>
              {(changes ?? []).map((c) => (
                <tr key={c.path}>
                  <td className="pathcell">{c.path}</td>
                  <td className={c.kind === "added" ? "diff-add" : c.kind === "removed" ? "diff-del" : "diff-chg"}>
                    {c.kind === "added" ? "+ added here" : c.kind === "removed" ? "− missing here" : "~ changed"}
                  </td>
                  <td className="mono">{c.before === undefined ? "" : JSON.stringify(c.before)}</td>
                  <td className="mono">{c.after === undefined ? "" : JSON.stringify(c.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
