"""Compare retrieval against manually labelled source pages."""

from __future__ import annotations

import json
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.retrieval.service import search
from app.retrieval.types import MetadataFilter
from evals.page_metrics import score_pages


def _page_key(path: str, page: int, root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        path_text = resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        path_text = resolved.as_posix()
    return f"{path_text}#page={page}"


def run_page_benchmark(
    dataset: dict, *, settings: Settings | None = None, k: int = 5
) -> dict:
    settings = settings or get_settings()
    rows = []
    for item in dataset["queries"]:
        relevance = {
            _page_key(str(settings.vault.root / entry["path"]), entry["page"], settings.vault.root): entry["grade"]
            for entry in item["relevant_pages"]
        }
        if not relevance:
            raise ValueError(f"Query {item['id']} has no labelled relevant pages")
        results = search(
            item["query"],
            settings=settings,
            flt=MetadataFilter(course=item.get("course")),
            final_limit=max(k * 4, 20),
        )
        ranked = list(dict.fromkeys(
            _page_key(hit.path, hit.page_number, settings.vault.root)
            for hit in results.hits if hit.page_number is not None
        ))[:k]
        scores = score_pages(ranked, relevance, k)
        rows.append({"id": item["id"], "ranked_pages": ranked, **scores})
    metric_names = ("recall", "mrr", "map", "ndcg")
    return {
        "k": k,
        "count": len(rows),
        **{name: round(sum(row[name] for row in rows) / len(rows), 4) if rows else 0.0 for name in metric_names},
        "queries": rows,
    }


def load_page_dataset(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
