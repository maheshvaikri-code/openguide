"""Corporate EDGAR reference demo over SEC-shaped data."""
import importlib.util
import os
import sys

EX = os.path.join(os.path.dirname(__file__), "..", "examples", "corporate-edgar", "run.py")


def _load():
    spec = importlib.util.spec_from_file_location("corporate_edgar_demo", EX)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _company(entity, revenue_2023, revenue_2024, income_2024):
    return {
        "entityName": entity,
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2023,
                                "end": "2023-09-30",
                                "filed": "2023-11-03",
                                "val": revenue_2023,
                            },
                            {
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2024,
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": revenue_2024,
                            },
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2024,
                                "end": "2024-09-28",
                                "filed": "2024-11-01",
                                "val": income_2024,
                            }
                        ]
                    }
                },
            }
        },
    }


def _fetcher(url):
    if "CIK0000320193" in url:
        return _company("Apple Inc.", 383_285_000_000, 391_035_000_000, 93_736_000_000)
    if "CIK0000789019" in url:
        return _company("Microsoft Corporation", 211_915_000_000, 245_122_000_000, 88_136_000_000)
    raise AssertionError(url)


def test_company_snapshot_extracts_latest_annual_sec_facts():
    mod = _load()
    snap = mod.company_snapshot_from_sec_facts(
        "AAPL", "0000320193", _company("Apple Inc.", 383_285_000_000, 391_035_000_000, 93_736_000_000)
    )

    assert snap.entity_name == "Apple Inc."
    assert snap.revenue.fiscal_year == 2024
    assert snap.revenue.value == 391_035_000_000
    assert round(snap.revenue_growth, 4) == 0.0202
    assert round(snap.net_margin, 4) == 0.2397


def test_corporate_edgar_demo_allows_crm_and_blocks_erp_with_trace(tmp_path):
    mod = _load()
    result = mod.run_demo(("AAPL", "MSFT"), refresh=True, cache_dir=tmp_path, fetcher=_fetcher)

    assert [s.ticker for s in result["snapshots"]] == ["AAPL", "MSFT"]
    assert result["allowed"].status_code == 200
    assert result["allowed"].headers["x-openguide-tool-decision"] == "allow"
    assert result["blocked"].status_code == 403
    assert result["blocked"].json()["reason"] == "approval_required:erp.update_vendor_risk"

    session = result["session"]
    assert session["turns"] == 2
    assert session["trace_verified"] is True
    assert result["trace"]["verified"] is True
    assert result["trace"]["event_counts"]["TOOL_POLICY"] == 2

    run = result["store"].get_run("corporate-edgar-reference")
    trace = result["store"].get_trace(run.trace_cas_key)
    policy_events = [rec for rec in trace.records if rec.get("ev") == "TOOL_POLICY"]
    assert [event["decision"] for event in policy_events] == ["allow", "deny"]
    assert policy_events[-1]["reason"] == "approval_required:erp.update_vendor_risk"
