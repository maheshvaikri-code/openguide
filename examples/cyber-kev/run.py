"""Cyber KEV reference demo: real CISA exploited-vulnerability data.

The demo pulls CISA's Known Exploited Vulnerabilities (KEV) catalog, selects
recent high-priority entries, then routes a scripted security operations agent
through the OpenGuide proxy:

  1. allowed action: create a SIEM case
  2. blocked action: isolate a production asset without approval

The blocked action is recorded as a TOOL_POLICY event in the hash-chained trace.

Run with live data:

    python examples/cyber-kev/run.py --refresh --vendors Microsoft Apple
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient  # noqa: E402

from guidancegrid.sensors import ExternalMeasure, MeasureRegistry, StructuralMeasure  # noqa: E402
from guidancegrid.store import Store  # noqa: E402
from proxy.app import create_app  # noqa: E402
from proxy.registry import ContractRegistry  # noqa: E402
from proxy.tool_policy import ToolPolicy  # noqa: E402
from proxy.upstream import MockUpstream  # noqa: E402

CISA_KEV_JSON = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
DEFAULT_VENDORS = ("Microsoft", "Apple")
CONTRACT = Path(__file__).with_name("cyber-governance.toml")


@dataclass(frozen=True)
class KEVEntry:
    cve_id: str
    vendor: str
    product: str
    vulnerability_name: str
    date_added: str
    due_date: str
    required_action: str
    known_ransomware: str
    short_description: str

    @property
    def ransomware_known(self) -> bool:
        return self.known_ransomware.lower() == "known"


FetchJSON = Callable[[str], dict[str, Any]]


def fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenGuide cyber-kev-demo"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_kev_entries(
    vendors: list[str],
    *,
    refresh: bool = False,
    cache_dir: Path | None = None,
    fetcher: FetchJSON = fetch_json,
    limit: int = 6,
) -> list[KEVEntry]:
    cache_dir = cache_dir or Path(__file__).with_name(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "known_exploited_vulnerabilities.json"
    if refresh or not cache_file.exists():
        data = fetcher(CISA_KEV_JSON)
        cache_file.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    else:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    return select_entries(data, vendors, limit=limit)


def select_entries(data: dict[str, Any], vendors: list[str], *, limit: int = 6) -> list[KEVEntry]:
    needles = [v.lower() for v in vendors]
    entries: list[KEVEntry] = []
    for raw in data.get("vulnerabilities", []):
        vendor = str(raw.get("vendorProject") or "")
        if needles and not any(n in vendor.lower() for n in needles):
            continue
        entries.append(
            KEVEntry(
                cve_id=str(raw.get("cveID") or ""),
                vendor=vendor,
                product=str(raw.get("product") or ""),
                vulnerability_name=str(raw.get("vulnerabilityName") or ""),
                date_added=str(raw.get("dateAdded") or ""),
                due_date=str(raw.get("dueDate") or ""),
                required_action=str(raw.get("requiredAction") or ""),
                known_ransomware=str(raw.get("knownRansomwareCampaignUse") or "Unknown"),
                short_description=str(raw.get("shortDescription") or ""),
            )
        )
    entries.sort(key=lambda e: (e.date_added, e.cve_id), reverse=True)
    if not entries:
        raise ValueError(f"no CISA KEV entries matched vendors: {', '.join(vendors)}")
    return entries[:limit]


def build_cyber_app(entries: list[KEVEntry]) -> tuple[TestClient, Store, str]:
    measures = MeasureRegistry()
    measures.register(StructuralMeasure("structural:kev_catalog_present", _kev_catalog_present))
    measures.register(ExternalMeasure("external:kev_grounding", _kev_grounding(entries)))
    measures.register(ExternalMeasure("external:security_action_scope", _security_action_scope))

    registry = ContractRegistry(measures=measures)
    contract_hash = registry.load_file(str(CONTRACT))
    store = Store()
    app = create_app(
        registry=registry,
        upstream=MockUpstream(_agent_responder(entries)),
        store=store,
        tool_policy=ToolPolicy(
            allow=["cisa.kev.lookup", "siem.create_case"],
            require_approval=["edr.isolate_host", "firewall.block_ip", "iam.disable_user"],
        ),
    )
    return TestClient(app), store, contract_hash


def run_demo(
    vendors: tuple[str, ...] = DEFAULT_VENDORS,
    *,
    refresh: bool = False,
    cache_dir: Path | None = None,
    fetcher: FetchJSON = fetch_json,
) -> dict[str, Any]:
    entries = load_kev_entries(list(vendors), refresh=refresh, cache_dir=cache_dir, fetcher=fetcher)
    client, store, contract_hash = build_cyber_app(entries)
    session_id = "corporate-cyber-kev-reference"
    headers = {"X-OpenGuide-Contract": contract_hash, "X-OpenGuide-Session": session_id}

    allowed = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "openai:gpt-4o",
            "messages": [{"role": "user", "content": _prompt(entries, action="siem_case")}],
        },
    )
    blocked = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "openai:gpt-4o",
            "messages": [{"role": "user", "content": _prompt(entries, action="isolate_prod_host")}],
        },
    )
    session = client.get(f"/v1/openguide/sessions/{session_id}").json()
    trace = client.get(f"/v1/openguide/runs/{session_id}/trace", params={"metadata_only": "true"}).json()
    return {
        "entries": entries,
        "allowed": allowed,
        "blocked": blocked,
        "session": session,
        "trace": trace,
        "store": store,
        "contract_hash": contract_hash,
    }


def _prompt(entries: list[KEVEntry], *, action: str) -> str:
    lines = [
        "source=CISA Known Exploited Vulnerabilities catalog",
        f"requested_action={action}",
        "Review these actively exploited vulnerabilities and propose only the requested security action.",
    ]
    for entry in entries:
        lines.append(
            f"{entry.cve_id} vendor={entry.vendor} product={entry.product} "
            f"date_added={entry.date_added} due={entry.due_date} ransomware={entry.known_ransomware}"
        )
    return "\n".join(lines)


def _agent_responder(entries: list[KEVEntry]):
    def responder(body: dict[str, Any]) -> dict[str, Any]:
        user = body.get("messages", [{}])[-1].get("content", "")
        action = "isolate_prod_host" if "requested_action=isolate_prod_host" in user else "siem_case"
        tool_name = "edr.isolate_host" if action == "isolate_prod_host" else "siem.create_case"
        content = _brief(entries, action)
        return _completion(content, tool_name, _tool_arguments(entries, action))

    return responder


def _brief(entries: list[KEVEntry], action: str) -> str:
    lines = ["CISA Known Exploited Vulnerabilities triage brief:"]
    for entry in entries:
        ransom = "ransomware observed" if entry.ransomware_known else "ransomware not marked known"
        lines.append(
            f"- {entry.cve_id}: {entry.vendor} {entry.product}; added {entry.date_added}; "
            f"due {entry.due_date}; {ransom}; action: {entry.required_action}"
        )
    lines.append(
        "Requested corporate action: "
        + ("create SIEM case" if action == "siem_case" else "isolate production host")
    )
    return "\n".join(lines)


def _tool_arguments(entries: list[KEVEntry], action: str) -> str:
    return json.dumps(
        {
            "action": action,
            "source": "CISA KEV catalog",
            "cves": [entry.cve_id for entry in entries],
            "vendors": sorted({entry.vendor for entry in entries}),
        },
        sort_keys=True,
    )


def _completion(content: str, tool_name: str, arguments: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-cyber-kev",
        "object": "chat.completion",
        "model": "mock:security-agent",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": [{
                    "id": "call_security_action",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": arguments},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _kev_catalog_present(ctx: dict[str, Any]) -> bool:
    text = _ctx_text(ctx)
    return "CISA Known Exploited Vulnerabilities" in text and "CVE-" in text


def _kev_grounding(entries: list[KEVEntry]):
    expected = [(entry.cve_id, entry.vendor, entry.product) for entry in entries]

    def scorer(ctx: dict[str, Any]) -> float:
        text = _ctx_text(ctx)
        hits = sum(1 for parts in expected for part in parts if part in text)
        return hits / max(len(expected) * 3, 1)

    return scorer


def _security_action_scope(ctx: dict[str, Any]) -> float:
    tools = ctx.get("tool_calls") or []
    names = [str((tc.get("function") or {}).get("name") or "") for tc in tools]
    allowed_prefixes = ("siem.", "edr.", "firewall.", "iam.", "cisa.")
    return 1.0 if all(name.startswith(allowed_prefixes) for name in names) else 0.0


def _ctx_text(ctx: dict[str, Any]) -> str:
    parts = [str(ctx.get("output", ""))]
    for msg in ctx.get("messages", []):
        parts.append(str(msg.get("content", "")))
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the corporate CISA KEV OpenGuide reference demo.")
    parser.add_argument("--vendors", nargs="+", default=list(DEFAULT_VENDORS))
    parser.add_argument("--refresh", action="store_true", help="fetch fresh CISA KEV JSON")
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args()

    result = run_demo(tuple(args.vendors), refresh=args.refresh, cache_dir=args.cache_dir)
    print("OpenGuide cyber KEV reference demo")
    print("source: CISA Known Exploited Vulnerabilities catalog")
    print()
    for entry in result["entries"]:
        print(
            f"{entry.cve_id:<18} {entry.vendor:<18} {entry.product:<28} "
            f"added={entry.date_added} due={entry.due_date}"
        )
    print()
    print(f"allowed SIEM action: HTTP {result['allowed'].status_code} "
          f"decision={result['allowed'].headers.get('x-openguide-tool-decision')}")
    print(f"blocked EDR action: HTTP {result['blocked'].status_code} "
          f"reason={result['blocked'].json().get('reason')}")
    print(f"trace verified: {result['trace']['verified']} "
          f"events={result['trace']['event_counts']} head={result['trace']['head']}")


if __name__ == "__main__":
    main()
