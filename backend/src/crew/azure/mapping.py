"""Azure DevOps MCP JSON -> contract models. Pure functions, tested with recorded payloads.

Everything that comes out of Azure is untrusted third-party text. Here we only *normalise* it (strip the
server's UNTRUSTED markers, HTML -> Markdown); fencing it as data inside prompts is the agents' job.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

from markdownify import markdownify

from ..contracts import WorkItemDetail, WorkItemSummary

F_ID = "System.Id"
F_TITLE = "System.Title"
F_TYPE = "System.WorkItemType"
F_STATE = "System.State"
F_ITERATION = "System.IterationPath"
F_DESCRIPTION = "System.Description"
F_CRITERIA = "Microsoft.VSTS.Common.AcceptanceCriteria"
F_REPRO = "Microsoft.VSTS.TCM.ReproSteps"

SUMMARY_FIELDS = [F_ID, F_TITLE, F_TYPE, F_STATE]

# `<<abc123>>` / `<</abc123>>` fences and the `[UNTRUSTED AZURE DEVOPS ... CONTENT]` banner.
# Deliberately tolerant: the exact wording changes between server releases.
_FENCE = re.compile(r"<</?[^<>\s]{1,80}>>")
_BANNER = re.compile(r"\[\s*UNTRUSTED[^\]\n]*\]", re.IGNORECASE)
_DANGEROUS_BLOCKS = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


class AzureMappingError(ValueError):
    """The payload does not look like what the server documents."""


def strip_untrusted_markers(text: str) -> str:
    return _BANNER.sub("", _FENCE.sub("", text)).strip()


def parse_tool_text(text: str) -> Any:
    """``CallToolResult.content[0].text`` -> JSON value (markers removed, tolerant of surrounding prose)."""
    cleaned = strip_untrusted_markers(text)
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    # last resort: the outermost JSON object/array inside whatever the server wrapped around it
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if starts:
        start = min(starts)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except ValueError:
                pass
    raise AzureMappingError(f"resposta do MCP não é JSON: {cleaned[:120]!r}")


# ---------------------------------------------------------------------------------------------- HTML


def html_to_markdown(html: str | None) -> str:
    if not html or not html.strip():
        return ""
    safe = _DANGEROUS_BLOCKS.sub("", html)
    md = markdownify(safe, heading_style="ATX", bullets="-", escape_underscores=False)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


class _ListItems(HTMLParser):
    """Collects the text of each ``<li>`` (nested lists are flattened, parent text first)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[str] = []
        self._buf: list[str] = []
        self._skip = 0

    def flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        if text:
            self.items.append(text)
        self._buf = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "li":
            self.flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "li":
            self.flush()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)


_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def split_criteria(html: str | None) -> list[str]:
    """Acceptance criteria HTML -> one item per ``<li>``; without a list, one item per line/paragraph."""
    if not html or not html.strip():
        return []
    if re.search(r"<li[\s>]", html, re.IGNORECASE):
        p = _ListItems()
        p.feed(html)
        p.close()
        p.flush()
        return p.items
    lines = html_to_markdown(html).splitlines()
    return [_BULLET.sub("", ln).strip() for ln in lines if ln.strip()]


# -------------------------------------------------------------------------------------------- items


def _items(data: Any) -> list[dict[str, Any]]:
    """Find the work item objects in a batch/get/WIQL response (shapes vary between server releases)."""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for key in ("value", "workItems", "work_items", "items", "results"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [d for d in inner if isinstance(d, dict)]
        if "id" in data or "fields" in data:
            return [data]
    raise AzureMappingError("formato de resposta de work items não reconhecido")


def _fields(item: dict[str, Any]) -> dict[str, Any]:
    f = item.get("fields")
    return f if isinstance(f, dict) else item


def _text(fields: dict[str, Any], key: str, default: str = "") -> str:
    v = fields.get(key)
    if isinstance(v, dict):  # identity-like objects: {"displayName": ...}
        v = v.get("displayName") or v.get("name")
    return str(v).strip() if v is not None else default


def _work_item_id(item: dict[str, Any]) -> int:
    raw = item.get("id", _fields(item).get(F_ID))
    try:
        return int(str(raw))
    except (TypeError, ValueError) as e:
        raise AzureMappingError(f"work item sem id válido: {raw!r}") from e


def ids_from_wiql(data: Any) -> list[int]:
    return [_work_item_id(i) for i in _items(data)]


def to_summary(item: dict[str, Any]) -> WorkItemSummary:
    f = _fields(item)
    return WorkItemSummary(
        id=_work_item_id(item),
        type=_text(f, F_TYPE, "Work Item"),
        title=_text(f, F_TITLE, "(sem título)"),
        state=_text(f, F_STATE, "?"),
    )


def summaries(data: Any) -> list[WorkItemSummary]:
    return [to_summary(i) for i in _items(data)]


def to_detail(item: dict[str, Any], *, organization: str, project: str) -> WorkItemDetail:
    f = _fields(item)
    summary = to_summary(item)
    description = html_to_markdown(_text(f, F_DESCRIPTION))
    repro = html_to_markdown(_text(f, F_REPRO))
    if repro:
        description = f"{description}\n\n## Passos para reproduzir\n\n{repro}".strip()
    links = item.get("_links")
    html_link = links.get("html", {}).get("href") if isinstance(links, dict) else None
    url = (
        html_link
        if isinstance(html_link, str) and html_link.startswith("https://")
        else f"https://dev.azure.com/{organization}/{project}/_workitems/edit/{summary.id}"
    )
    return WorkItemDetail(
        **summary.model_dump(),
        description=description,
        acceptance_criteria=split_criteria(_text(f, F_CRITERIA)),
        iteration_path=_text(f, F_ITERATION) or None,
        url=url,
    )


def detail_from_tool_data(data: Any, *, organization: str, project: str) -> WorkItemDetail:
    items = _items(data)
    if not items:
        raise AzureMappingError("work item não encontrado")
    return to_detail(items[0], organization=organization, project=project)
