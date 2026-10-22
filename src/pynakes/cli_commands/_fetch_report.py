"""Human-readable formatting for Pinax fetch reports."""

from pynakes._fetch_attempts import describe_attempts
from pynakes.fetch_progress import WOULD_FETCH


def fetch_report_lines(
    report: dict,
    *,
    skipped_prefix: str = "Skipped",
    failed_prefix: str = "Failed",
) -> list[str]:
    """Return concise human-readable lines for a ``fetch_materials`` report.

    Entries skipped (or, in a dry run, planned) for the same reason share one
    line that counts and names them. A skip or failure for which downloads
    were tried keeps its own line naming each request's host, HTTP status, and
    content type. The report ends with its counts and, when PDFs are still
    missing, their coverage grouped by reason.
    """
    lines: list[str] = []
    named: set[str] = set()
    for item in report["fetched"]:
        lines.append(_fetched_line(item))
    # Skips that tried nothing differ only by key, so each reason gets one
    # line naming its keys; a skip that tried downloads keeps its own line.
    groups: dict[str, list[str]] = {}
    for item in report["skipped"]:
        if item.get("attempts"):
            lines.append(f"{skipped_prefix} {item['key']} ({item['reason']}){_tried(item)}.")
        else:
            groups.setdefault(item["reason"], []).append(item["key"])
        named.add(item["key"])
    for reason, keys in groups.items():
        lines.append(_skip_group_line(reason, keys, skipped_prefix))
    for item in report["failed"]:
        lines.append(f"{failed_prefix} {item['key']} ({item['error']}){_tried(item)}.")
        named.add(item["key"])
    for item in report.get("discovered", ()):
        lines.append(_discovered_line(item))
    summary = report.get("summary")
    if summary and (report["skipped"] or report["failed"]):
        lines.append(_summary_line(summary))
    coverage = report.get("coverage")
    if coverage and coverage["missing"]:
        lines.extend(_coverage_lines(coverage, named))
    return lines


def _skip_group_line(reason: str, keys: list[str], skipped_prefix: str) -> str:
    # A dry run files its planned work under ``skipped`` so the JSON shape
    # is the same either way, but "Skipped X (would fetch)" reads as two
    # contradictory claims. Say what the run would do instead.
    if reason == WOULD_FETCH:
        if len(keys) == 1:
            return f"Would fetch {keys[0]}."
        return f"Would fetch {len(keys)} entries: {', '.join(keys)}."
    if len(keys) == 1:
        return f"{skipped_prefix} {keys[0]} ({reason})."
    return f"{skipped_prefix} {len(keys)} entries ({reason}): {', '.join(keys)}."


def _discovered_line(item: dict) -> str:
    if item["status"] == "linked":
        written = f"; recorded {', '.join(item['written'])}" if item.get("written") else ""
        return (
            f"Found arXiv:{item['arxiv_id']} for {item['key']} "
            f"(confirmed by {str(item.get('verified_by', '')).replace('_', ' ')}{written})."
        )
    detail = f": {item['message']}" if item.get("message") else ""
    return f"arXiv id lookup for {item['key']}: {item['status'].replace('_', ' ')}{detail}."


def _coverage_lines(coverage: dict, named: set[str]) -> list[str]:
    """Count the entries still missing a PDF by reason; name only keys no line above named."""
    groups: dict[str, list[str]] = {}
    for item in coverage["missing"]:
        groups.setdefault(item["reason"], []).append(item["key"])
    counts = ", ".join(f"{len(keys)} {reason}" for reason, keys in groups.items())
    lines = [
        f"Coverage: {coverage['with_pdf']} of {coverage['entries']} entries have a PDF; "
        f"{len(coverage['missing'])} still missing what was requested ({counts})."
    ]
    for reason, keys in groups.items():
        unnamed = [key for key in keys if key not in named]
        if unnamed:
            lines.append(f"  {reason}: {', '.join(unnamed)}.")
    return lines


def _tried(item: dict) -> str:
    attempts = item.get("attempts")
    return f"; tried {describe_attempts(attempts)}" if attempts else ""


def _summary_line(summary: dict) -> str:
    parts = [
        f"{summary.get(name, 0)} {label}"
        for name, label in (
            ("fetched", "fetched"),
            ("already_present", "already present"),
            ("unavailable", "unavailable"),
            ("failed", "failed"),
            ("planned", "planned"),
        )
        if summary.get(name) or name in {"fetched", "failed"}
    ]
    return f"Summary: {summary.get('requested', 0)} requested; {', '.join(parts)}."


def _fetched_line(item: dict) -> str:
    parts = []
    if item.get("artifact") == "supplement_pdf" and item["pdf_path"]:
        parts.append("supplement PDF")
    elif item["pdf_path"]:
        parts.append("PDF")
    if item["source_path"]:
        parts.append("source")
    label = "+".join(parts) if parts else "materials"

    if item.get("arxiv_id"):
        source = f"arXiv:{item['arxiv_id']}"
    elif item.get("doi"):
        source = f"DOI:{item['doi']}"
    else:
        source = ""

    suffix = f" ({source})" if source else ""
    return f"Fetched {label} for {item['key']}{suffix}."
