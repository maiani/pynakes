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

    A skip or failure for which downloads were tried names each request's
    host, HTTP status, and content type, and the report ends with its counts.
    """
    lines: list[str] = []
    for item in report["fetched"]:
        lines.append(_fetched_line(item))
    for item in report["skipped"]:
        # A dry run files its planned work under ``skipped`` so the JSON shape
        # is the same either way, but "Skipped X (would fetch)" reads as two
        # contradictory claims. Say what the run would do instead.
        if item["reason"] == WOULD_FETCH:
            lines.append(f"Would fetch {item['key']}.")
        else:
            lines.append(f"{skipped_prefix} {item['key']} ({item['reason']}){_tried(item)}.")
    for item in report["failed"]:
        lines.append(f"{failed_prefix} {item['key']} ({item['error']}){_tried(item)}.")
    summary = report.get("summary")
    if summary and (report["skipped"] or report["failed"]):
        lines.append(_summary_line(summary))
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
