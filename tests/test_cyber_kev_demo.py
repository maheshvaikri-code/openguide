"""Corporate CISA KEV reference demo over CISA-shaped data."""
import importlib.util
import os
import sys

EX = os.path.join(os.path.dirname(__file__), "..", "examples", "cyber-kev", "run.py")


def _load():
    spec = importlib.util.spec_from_file_location("cyber_kev_demo", EX)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _catalog():
    return {
        "title": "CISA Catalog of Known Exploited Vulnerabilities",
        "catalogVersion": "2026.06.25",
        "dateReleased": "2026-06-25T19:03:21Z",
        "count": 4,
        "vulnerabilities": [
            {
                "cveID": "CVE-2026-10001",
                "vendorProject": "Microsoft",
                "product": "SharePoint Server",
                "vulnerabilityName": "Microsoft SharePoint Code Execution Vulnerability",
                "dateAdded": "2026-06-25",
                "shortDescription": "A test vulnerability under active exploitation.",
                "requiredAction": "Apply mitigations per vendor instructions.",
                "dueDate": "2026-07-16",
                "knownRansomwareCampaignUse": "Known",
            },
            {
                "cveID": "CVE-2026-10002",
                "vendorProject": "Apple",
                "product": "iOS",
                "vulnerabilityName": "Apple iOS Memory Corruption Vulnerability",
                "dateAdded": "2026-06-20",
                "shortDescription": "A mobile vulnerability under active exploitation.",
                "requiredAction": "Apply updates per vendor instructions.",
                "dueDate": "2026-07-11",
                "knownRansomwareCampaignUse": "Unknown",
            },
            {
                "cveID": "CVE-2024-9999",
                "vendorProject": "Acme",
                "product": "Widget",
                "vulnerabilityName": "Acme Widget Vulnerability",
                "dateAdded": "2024-01-01",
                "shortDescription": "Out of demo scope.",
                "requiredAction": "Patch.",
                "dueDate": "2024-01-22",
                "knownRansomwareCampaignUse": "Unknown",
            },
        ],
    }


def _fetcher(url):
    assert "known_exploited_vulnerabilities.json" in url
    return _catalog()


def test_select_entries_filters_vendors_and_orders_recent_first():
    mod = _load()
    entries = mod.select_entries(_catalog(), ["Microsoft", "Apple"], limit=5)

    assert [entry.cve_id for entry in entries] == ["CVE-2026-10001", "CVE-2026-10002"]
    assert entries[0].ransomware_known is True
    assert entries[1].vendor == "Apple"


def test_cyber_kev_demo_allows_siem_and_blocks_edr_with_trace(tmp_path):
    mod = _load()
    result = mod.run_demo(("Microsoft", "Apple"), refresh=True, cache_dir=tmp_path, fetcher=_fetcher)

    assert [entry.cve_id for entry in result["entries"]] == ["CVE-2026-10001", "CVE-2026-10002"]
    assert result["allowed"].status_code == 200
    assert result["allowed"].headers["x-openguide-tool-decision"] == "allow"
    assert result["blocked"].status_code == 403
    assert result["blocked"].json()["reason"] == "approval_required:edr.isolate_host"

    session = result["session"]
    assert session["turns"] == 2
    assert session["trace_verified"] is True
    assert result["trace"]["verified"] is True
    assert result["trace"]["event_counts"]["TOOL_POLICY"] == 2

    run = result["store"].get_run("corporate-cyber-kev-reference")
    trace = result["store"].get_trace(run.trace_cas_key)
    policy_events = [rec for rec in trace.records if rec.get("ev") == "TOOL_POLICY"]
    assert [event["decision"] for event in policy_events] == ["allow", "deny"]
    assert policy_events[-1]["reason"] == "approval_required:edr.isolate_host"
