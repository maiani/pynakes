"""Human-readable formatting for Pinax fetch reports."""


def fetch_report_lines(
    report: dict,
    *,
    skipped_prefix: str = "Skipped",
    failed_prefix: str = "Failed",
) -> list[str]:
    """Return concise human-readable lines for a ``fetch_materials`` report."""
    lines: list[str] = []
    for item in report["fetched"]:
        lines.append(_fetched_line(item))
    for item in report["skipped"]:
        lines.append(f"{skipped_prefix} {item['key']} ({item['reason']}).")
    for item in report["failed"]:
        lines.append(f"{failed_prefix} {item['key']} ({item['error']}).")
    return lines


def _fetched_line(item: dict) -> str:
    parts = []
    if item["pdf_path"]:
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
