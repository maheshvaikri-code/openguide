"""Corporate EDGAR reference demo: real public-company data, governed action.

The demo pulls public company facts from the SEC EDGAR JSON API, builds a small
finance/risk brief, then routes a scripted corporate agent through the
OpenGuide proxy:

  1. allowed action: create a CRM account note
  2. blocked action: update ERP risk scoring without approval

The blocked action is recorded as a TOOL_POLICY event in the hash-chained trace.

Run with live data:

    python examples/corporate-edgar/run.py --refresh --tickers AAPL MSFT

Set SEC_USER_AGENT to your company/contact for production-like runs.
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

SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_TICKERS = ("AAPL", "MSFT")
DEFAULT_CIKS = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "AMZN": "0001018724",
    "NVDA": "0001045810",
}
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
NET_INCOME_TAGS = ("NetIncomeLoss",)
CONTRACT = Path(__file__).with_name("corporate-governance.toml")


@dataclass(frozen=True)
class FactPoint:
    tag: str
    value: float
    fiscal_year: int
    end: str
    filed: str
    form: str


@dataclass(frozen=True)
class CompanySnapshot:
    ticker: str
    cik: str
    entity_name: str
    revenue: FactPoint
    previous_revenue: FactPoint | None
    net_income: FactPoint

    @property
    def revenue_growth(self) -> float | None:
        if self.previous_revenue is None or self.previous_revenue.value == 0:
            return None
        return (self.revenue.value - self.previous_revenue.value) / abs(self.previous_revenue.value)

    @property
    def net_margin(self) -> float:
        if self.revenue.value == 0:
            return 0.0
        return self.net_income.value / self.revenue.value


FetchJSON = Callable[[str], dict[str, Any]]


def _sec_user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "OpenGuide corporate-edgar-demo contact@example.com")


def fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": _sec_user_agent()})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_snapshots(
    tickers: list[str],
    *,
    refresh: bool = False,
    cache_dir: Path | None = None,
    fetcher: FetchJSON = fetch_json,
) -> list[CompanySnapshot]:
    cache_dir = cache_dir or Path(__file__).with_name(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    snapshots: list[CompanySnapshot] = []
    for ticker in [t.upper() for t in tickers]:
        cik = DEFAULT_CIKS.get(ticker)
        if cik is None:
            raise ValueError(f"ticker {ticker!r} is not in DEFAULT_CIKS; add its SEC CIK first")
        cache_file = cache_dir / f"{ticker}-companyfacts.json"
        if refresh or not cache_file.exists():
            data = fetcher(SEC_COMPANYFACTS.format(cik=cik))
            cache_file.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        else:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        snapshots.append(company_snapshot_from_sec_facts(ticker, cik, data))
    return snapshots


def company_snapshot_from_sec_facts(ticker: str, cik: str, data: dict[str, Any]) -> CompanySnapshot:
    facts = data.get("facts", {}).get("us-gaap", {})
    revenues = _annual_points(facts, REVENUE_TAGS)
    net_income = _annual_points(facts, NET_INCOME_TAGS)
    if not revenues or not net_income:
        raise ValueError(f"missing annual revenue or net income facts for {ticker}")
    return CompanySnapshot(
        ticker=ticker,
        cik=cik,
        entity_name=str(data.get("entityName") or ticker),
        revenue=revenues[-1],
        previous_revenue=revenues[-2] if len(revenues) > 1 else None,
        net_income=net_income[-1],
    )


def _annual_points(facts: dict[str, Any], tags: tuple[str, ...]) -> list[FactPoint]:
    points: list[FactPoint] = []
    for tag in tags:
        for unit in facts.get(tag, {}).get("units", {}).get("USD", []):
            if unit.get("form") != "10-K" or unit.get("fp") != "FY":
                continue
            if unit.get("val") is None or unit.get("fy") is None:
                continue
            points.append(
                FactPoint(
                    tag=tag,
                    value=float(unit["val"]),
                    fiscal_year=int(unit["fy"]),
                    end=str(unit.get("end") or ""),
                    filed=str(unit.get("filed") or ""),
                    form=str(unit.get("form") or ""),
                )
            )
    points.sort(key=lambda p: (p.fiscal_year, p.end, p.filed, p.tag))
    return points


def build_corporate_app(snapshots: list[CompanySnapshot]) -> tuple[TestClient, Store, str]:
    measures = MeasureRegistry()
    measures.register(StructuralMeasure("structural:sec_facts_present", _sec_facts_present))
    measures.register(ExternalMeasure("external:financial_grounding", _financial_grounding(snapshots)))
    measures.register(ExternalMeasure("external:action_scope", _action_scope))

    registry = ContractRegistry(measures=measures)
    contract_hash = registry.load_file(str(CONTRACT))
    store = Store()
    app = create_app(
        registry=registry,
        upstream=MockUpstream(_agent_responder(snapshots)),
        store=store,
        tool_policy=ToolPolicy(
            allow=["sec.companyfacts.lookup", "crm.create_account_note"],
            require_approval=["erp.update_vendor_risk", "payments.*"],
        ),
    )
    return TestClient(app), store, contract_hash


def run_demo(
    tickers: tuple[str, ...] = DEFAULT_TICKERS,
    *,
    refresh: bool = False,
    cache_dir: Path | None = None,
    fetcher: FetchJSON = fetch_json,
) -> dict[str, Any]:
    snapshots = load_snapshots(list(tickers), refresh=refresh, cache_dir=cache_dir, fetcher=fetcher)
    client, store, contract_hash = build_corporate_app(snapshots)
    session_id = "corporate-edgar-reference"
    headers = {"X-OpenGuide-Contract": contract_hash, "X-OpenGuide-Session": session_id}

    allowed = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "openai:gpt-4o",
            "messages": [{"role": "user", "content": _prompt(snapshots, action="crm_note")}],
        },
    )
    blocked = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "openai:gpt-4o",
            "messages": [{"role": "user", "content": _prompt(snapshots, action="erp_risk_update")}],
        },
    )
    session = client.get(f"/v1/openguide/sessions/{session_id}").json()
    trace = client.get(f"/v1/openguide/runs/{session_id}/trace", params={"metadata_only": "true"}).json()
    return {
        "snapshots": snapshots,
        "allowed": allowed,
        "blocked": blocked,
        "session": session,
        "trace": trace,
        "store": store,
        "contract_hash": contract_hash,
    }


def _prompt(snapshots: list[CompanySnapshot], *, action: str) -> str:
    lines = [
        "source=SEC EDGAR companyfacts",
        f"requested_action={action}",
        "Review these public-company facts and propose only the requested corporate action.",
    ]
    for s in snapshots:
        lines.append(
            f"{s.ticker} {s.entity_name}: FY{s.revenue.fiscal_year} revenue={int(s.revenue.value)} "
            f"net_income={int(s.net_income.value)} filed={s.revenue.filed} form={s.revenue.form}"
        )
    return "\n".join(lines)


def _agent_responder(snapshots: list[CompanySnapshot]):
    def responder(body: dict[str, Any]) -> dict[str, Any]:
        user = body.get("messages", [{}])[-1].get("content", "")
        action = "erp_risk_update" if "requested_action=erp_risk_update" in user else "crm_note"
        tool_name = "erp.update_vendor_risk" if action == "erp_risk_update" else "crm.create_account_note"
        content = _brief(snapshots, action)
        return _completion(content, tool_name, _tool_arguments(snapshots, action))

    return responder


def _brief(snapshots: list[CompanySnapshot], action: str) -> str:
    lines = ["SEC EDGAR companyfacts corporate finance brief:"]
    for s in snapshots:
        growth = "n/a" if s.revenue_growth is None else f"{s.revenue_growth * 100:.1f}%"
        lines.append(
            f"- {s.ticker}: FY{s.revenue.fiscal_year} revenue {_money(s.revenue.value)}, "
            f"net income {_money(s.net_income.value)}, net margin {s.net_margin * 100:.1f}%, "
            f"revenue growth {growth}; source SEC EDGAR companyfacts, "
            f"{s.revenue.form} filed {s.revenue.filed}."
        )
    lines.append(
        "Requested corporate action: "
        + ("create CRM account note" if action == "crm_note" else "update ERP vendor risk score")
    )
    return "\n".join(lines)


def _tool_arguments(snapshots: list[CompanySnapshot], action: str) -> str:
    return json.dumps(
        {
            "action": action,
            "source": "SEC EDGAR companyfacts",
            "tickers": [s.ticker for s in snapshots],
            "metrics": [
                {
                    "ticker": s.ticker,
                    "fy": s.revenue.fiscal_year,
                    "revenue": int(s.revenue.value),
                    "net_income": int(s.net_income.value),
                    "filed": s.revenue.filed,
                }
                for s in snapshots
            ],
        },
        sort_keys=True,
    )


def _completion(content: str, tool_name: str, arguments: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-corporate-edgar",
        "object": "chat.completion",
        "model": "mock:corporate-agent",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": [{
                    "id": "call_corporate_action",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": arguments},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _sec_facts_present(ctx: dict[str, Any]) -> bool:
    text = _ctx_text(ctx)
    return "SEC EDGAR companyfacts" in text and "filed=" in text


def _financial_grounding(snapshots: list[CompanySnapshot]):
    expected = [(s.ticker, str(int(s.revenue.value)), str(int(s.net_income.value))) for s in snapshots]

    def scorer(ctx: dict[str, Any]) -> float:
        text = _ctx_text(ctx)
        hits = sum(1 for parts in expected for part in parts if part in text)
        return hits / max(len(expected) * 3, 1)

    return scorer


def _action_scope(ctx: dict[str, Any]) -> float:
    tools = ctx.get("tool_calls") or []
    names = [str((tc.get("function") or {}).get("name") or "") for tc in tools]
    return 1.0 if all(name.startswith(("crm.", "erp.", "sec.")) for name in names) else 0.0


def _ctx_text(ctx: dict[str, Any]) -> str:
    parts = [str(ctx.get("output", ""))]
    for msg in ctx.get("messages", []):
        parts.append(str(msg.get("content", "")))
    return "\n".join(parts)


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    return f"{sign}${value:,.0f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the corporate EDGAR OpenGuide reference demo.")
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS))
    parser.add_argument("--refresh", action="store_true", help="fetch fresh SEC companyfacts JSON")
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args()

    result = run_demo(tuple(args.tickers), refresh=args.refresh, cache_dir=args.cache_dir)
    print("OpenGuide corporate EDGAR reference demo")
    print("source: SEC EDGAR companyfacts API")
    print()
    for s in result["snapshots"]:
        growth = "n/a" if s.revenue_growth is None else f"{s.revenue_growth * 100:.1f}%"
        print(
            f"{s.ticker:<5} FY{s.revenue.fiscal_year} revenue={_money(s.revenue.value):>9} "
            f"net_income={_money(s.net_income.value):>9} margin={s.net_margin * 100:>5.1f}% "
            f"growth={growth:>7} filed={s.revenue.filed}"
        )
    print()
    print(f"allowed CRM action: HTTP {result['allowed'].status_code} "
          f"decision={result['allowed'].headers.get('x-openguide-tool-decision')}")
    print(f"blocked ERP action: HTTP {result['blocked'].status_code} "
          f"reason={result['blocked'].json().get('reason')}")
    print(f"trace verified: {result['trace']['verified']} "
          f"events={result['trace']['event_counts']} head={result['trace']['head']}")


if __name__ == "__main__":
    main()
