"""5-signal knowledge graph over wiki pages, with community detection.

Edge relevance combines four signals (weights from llm_wiki):
  direct wikilink x3.0, shared-source Jaccard x4.0, Adamic-Adar x1.5 (capped),
  cross-course title match x3.0, same page type x1.0. Communities come from deterministic weighted label
  propagation — pure Python, no graph library needed at wiki scale.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from app.config.settings import Settings
from app.vault.service import extract_links
from app.wiki import store

_LINK_WEIGHT = 3.0
_SOURCE_WEIGHT = 4.0
_ADAMIC_WEIGHT = 1.5
_TITLE_WEIGHT = 3.0
_TYPE_WEIGHT = 1.0
_MAX_SWEEPS = 20


def _shared_concept_key(title: str) -> tuple[str, ...] | None:
    """High-precision key for equivalent concepts named across courses."""
    without_alias = re.sub(r"\([^)]*\)", "", title.lower())
    words = re.findall(r"[a-z0-9]+", without_alias)
    normalized = [word[:-1] if len(word) > 4 and word.endswith("s") else word for word in words]
    if not normalized or normalized[0] == "assignment":
        return None
    compact = re.sub(r"[^A-Za-z0-9]", "", title)
    is_acronym = 2 <= len(compact) <= 8 and compact.isupper()
    if len(normalized) < 2 and not is_acronym:
        return None
    # Token order does not change identity for names such as
    # "Semantic HTML Structure" and "HTML Semantic Structure".
    return tuple(sorted(set(normalized)))


def build_wiki_graph(settings: Settings, course: str | None) -> dict:
    pages = store.list_wiki_pages(course, settings)
    by_path = {page["path"]: page for page in pages}
    ids = sorted(by_path)
    # Titles can repeat across courses; prefer a same-course target when
    # resolving wikilinks so cross-course links only form deliberately.
    by_title: dict[str, list[str]] = defaultdict(list)
    by_stem: dict[str, list[str]] = defaultdict(list)
    for pid in ids:
        by_title[by_path[pid]["title"].lower()].append(pid)
        by_stem[Path(pid).stem.lower()].append(pid)

    def resolve(target: str, source_page: dict) -> str | None:
        clean = target.strip().replace("\\", "/").strip("/")
        # Full vault-relative links make deliberate cross-course targets
        # unambiguous, while ordinary title/stem links keep same-course priority.
        for exact in (clean, f"{clean}.md"):
            if exact in by_path:
                return exact
        key = Path(clean).stem.lower()
        candidates = by_title.get(key) or by_stem.get(key)
        if not candidates:
            return None
        same_course = [
            p for p in candidates
            if by_path[p].get("course") == source_page.get("course")
        ]
        return (same_course or candidates)[0]

    # Undirected wikilink adjacency, resolved by title within this wiki.
    neighbors: dict[str, set[str]] = {pid: set() for pid in ids}
    for page in pages:
        for target in extract_links(page["body"]):
            target_path = resolve(target, page)
            if target_path and target_path != page["path"]:
                neighbors[page["path"]].add(target_path)
                neighbors[target_path].add(page["path"])

    # Candidate pairs: directly linked, or sharing at least one source.
    candidates: set[tuple[str, str]] = set()
    for pid in ids:
        for other in neighbors[pid]:
            candidates.add(tuple(sorted((pid, other))))
    source_map: dict[str, set[str]] = defaultdict(set)
    for page in pages:
        for src in page["sources"]:
            source_map[src].add(page["path"])
    for members in source_map.values():
        for pair in combinations(sorted(members), 2):
            candidates.add(pair)

    # Equivalent concept/entity titles are explicit bridges between courses.
    title_groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for page in pages:
        if page["type"] not in {"concept", "entity"}:
            continue
        key = _shared_concept_key(page["title"])
        if key:
            title_groups[key].append(page["path"])
    title_pairs: set[tuple[str, str]] = set()
    for members in title_groups.values():
        for a, b in combinations(sorted(members), 2):
            if by_path[a].get("course") != by_path[b].get("course"):
                pair = (a, b)
                title_pairs.add(pair)
                candidates.add(pair)

    edges = []
    weights: dict[tuple[str, str], float] = {}
    for a, b in sorted(candidates):
        pa, pb = by_path[a], by_path[b]
        link = _LINK_WEIGHT if b in neighbors[a] else 0.0
        sa, sb = set(pa["sources"]), set(pb["sources"])
        union = sa | sb
        source = _SOURCE_WEIGHT * (len(sa & sb) / len(union)) if union else 0.0
        aa = sum(
            1.0 / math.log(len(neighbors[w]))
            for w in neighbors[a] & neighbors[b]
            if len(neighbors[w]) >= 2
        )
        adamic = _ADAMIC_WEIGHT * min(1.0, aa / 2.0)
        title = _TITLE_WEIGHT if (a, b) in title_pairs else 0.0
        affinity = _TYPE_WEIGHT if pa["type"] == pb["type"] else 0.0
        weight = link + source + adamic + title + affinity
        if weight <= 0:
            continue
        weights[(a, b)] = weight
        edges.append(
            {
                "source": a,
                "target": b,
                "weight": round(weight, 3),
                "signals": {
                    "link": round(link, 3),
                    "source": round(source, 3),
                    "adamic": round(adamic, 3),
                    "title": round(title, 3),
                    "type": round(affinity, 3),
                },
            }
        )

    labels = _label_propagation(ids, weights)
    communities = _communities(ids, weights, labels, settings.wiki.min_cohesion)
    community_of = {
        pid: cid for cid, info in communities.items() for pid in info["members"]
    }

    nodes = [
        {
            "id": pid,
            "title": by_path[pid]["title"],
            "type": by_path[pid]["type"],
            "course": by_path[pid].get("course"),
            "community": community_of[pid],
            "degree": len(neighbors[pid]),
            "flagged": communities[community_of[pid]]["flagged"],
        }
        for pid in ids
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "communities": [
            {
                "id": cid,
                "size": len(info["members"]),
                "cohesion": round(info["cohesion"], 3),
                "flagged": info["flagged"],
            }
            for cid, info in sorted(communities.items())
        ],
        "stats": {
            "pages": len(nodes),
            "edges": len(edges),
            "communities": len(communities),
            "cross_course_edges": sum(
                1
                for edge in edges
                if by_path[edge["source"]].get("course")
                != by_path[edge["target"]].get("course")
            ),
        },
    }


def _label_propagation(
    ids: list[str], weights: dict[tuple[str, str], float]
) -> dict[str, int]:
    """Deterministic weighted label propagation (sorted order, tie -> min)."""
    adjacency: dict[str, dict[str, float]] = {pid: {} for pid in ids}
    for (a, b), w in weights.items():
        adjacency[a][b] = w
        adjacency[b][a] = w
    labels = {pid: i for i, pid in enumerate(ids)}
    for _ in range(_MAX_SWEEPS):
        changed = False
        for pid in ids:
            if not adjacency[pid]:
                continue
            tally: dict[int, float] = defaultdict(float)
            for other, w in adjacency[pid].items():
                tally[labels[other]] += w
            best = max(tally.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if best != labels[pid]:
                labels[pid] = best
                changed = True
        if not changed:
            break
    return labels


def _communities(
    ids: list[str],
    weights: dict[tuple[str, str], float],
    labels: dict[str, int],
    min_cohesion: float,
) -> dict[int, dict]:
    groups: dict[int, list[str]] = defaultdict(list)
    for pid in ids:
        groups[labels[pid]].append(pid)
    # Relabel to consecutive ids, largest community first.
    ordered = sorted(groups.values(), key=lambda members: (-len(members), members[0]))

    strength: dict[str, float] = defaultdict(float)
    for (a, b), w in weights.items():
        strength[a] += w
        strength[b] += w

    result: dict[int, dict] = {}
    for cid, members in enumerate(ordered):
        member_set = set(members)
        internal = sum(
            w for (a, b), w in weights.items() if a in member_set and b in member_set
        )
        total_strength = sum(strength[pid] for pid in members)
        cohesion = (2.0 * internal / total_strength) if total_strength > 0 else 0.0
        result[cid] = {
            "members": members,
            "cohesion": cohesion,
            "flagged": cohesion < min_cohesion or len(members) < 2,
        }
    return result
