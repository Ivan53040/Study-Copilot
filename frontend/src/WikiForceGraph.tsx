// Obsidian-style force-directed graph for the wiki: canvas + d3-force with
// draggable nodes, hover highlighting of neighbours, and a floating panel of
// filter / display / force controls.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type ForceCollide,
  type ForceLink,
  type ForceManyBody,
  type ForceX,
  type ForceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { WikiGraph, WikiGraphNode } from "./types";

interface SimNode extends SimulationNodeDatum, WikiGraphNode {}
interface SimLink extends SimulationLinkDatum<SimNode> {
  weight: number;
}

const TYPE_COLORS: Record<string, string> = {
  map: "#fb7185",
  concept: "#7dd3fc",
  entity: "#c4b5fd",
  source: "#fcd34d",
};

function communityColor(community: number): string {
  return `hsl(${(community * 67) % 360}, 55%, 60%)`;
}

// Golden-angle spacing keeps neighbouring course colors clearly distinct.
function indexColor(index: number): string {
  return `hsl(${(40 + index * 137) % 360}, 52%, 58%)`;
}

const DEFAULTS = {
  showConcepts: true,
  showEntities: true,
  showSources: true,
  showMaps: true,
  showOrphans: true,
  separateByCourse: false,
  colorByCommunity: true,
  textFade: 1.0,
  nodeSize: 1.0,
  linkThickness: 1.0,
  centerForce: 0.4,
  repelForce: 1.0,
  linkForce: 0.7,
  linkDistance: 80,
};

const SETTINGS_KEY = "study-copilot.wiki-graph.settings.v1";

function savedOptions(): typeof DEFAULTS {
  if (typeof window === "undefined") return { ...DEFAULTS };
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<typeof DEFAULTS>;
    const next = { ...DEFAULTS };
    for (const key of Object.keys(DEFAULTS) as (keyof typeof DEFAULTS)[]) {
      if (typeof parsed[key] === typeof DEFAULTS[key]) {
        (next[key] as boolean | number) = parsed[key] as boolean & number;
      }
    }
    return next;
  } catch {
    return { ...DEFAULTS };
  }
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="wgp-row">
      <span>{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        className={`wgp-switch ${value ? "on" : ""}`}
        onClick={() => onChange(!value)}
      >
        <span className="wgp-knob" />
      </button>
    </div>
  );
}

function Slider({
  label,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="wgp-slider">
      <span>{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="wgp-section">
      <button type="button" className="wgp-section-head" onClick={() => setOpen(!open)}>
        <span className={`wgp-chevron ${open ? "open" : ""}`}>▸</span>
        {title}
      </button>
      {open && children}
    </div>
  );
}

export function WikiForceGraph({
  graph,
  onOpenPage,
}: {
  graph: WikiGraph;
  onOpenPage: (path: string) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const linksRef = useRef<SimLink[]>([]);
  // World positions survive filter changes so the layout doesn't reshuffle.
  const savedPositions = useRef<Map<string, { x: number; y: number }>>(new Map());
  const transformRef = useRef({ x: 0, y: 0, k: 1 });
  const hoverRef = useRef<SimNode | null>(null);
  const dragRef = useRef<SimNode | null>(null);
  const panRef = useRef<{ startX: number; startY: number; tx: number; ty: number } | null>(null);
  const drawRef = useRef<() => void>(() => {});
  const centeredRef = useRef(false);

  const [search, setSearch] = useState("");
  const [opts, setOpts] = useState(savedOptions);
  const [panelOpen, setPanelOpen] = useState(true);
  const [hoverTitle, setHoverTitle] = useState<string | null>(null);
  const set = (patch: Partial<typeof DEFAULTS>) => setOpts((o) => ({ ...o, ...patch }));

  useEffect(() => {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(opts));
  }, [opts]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let nodes = graph.nodes.filter(
      (n) =>
        (n.type !== "concept" || opts.showConcepts) &&
        (n.type !== "entity" || opts.showEntities) &&
        (n.type !== "source" || opts.showSources) &&
        (n.type !== "map" || opts.showMaps) &&
        (!q || n.title.toLowerCase().includes(q)),
    );
    let ids = new Set(nodes.map((n) => n.id));
    const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    if (!opts.showOrphans) {
      const connected = new Set<string>();
      for (const e of edges) {
        connected.add(e.source);
        connected.add(e.target);
      }
      nodes = nodes.filter((n) => connected.has(n.id));
      ids = new Set(nodes.map((n) => n.id));
    }
    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }
    return { nodes, edges, degree };
  }, [
    graph,
    search,
    opts.showConcepts,
    opts.showEntities,
    opts.showSources,
    opts.showMaps,
    opts.showOrphans,
    opts.separateByCourse,
  ]);

  const radiusOf = useCallback(
    (node: SimNode) =>
      (3.5 + Math.sqrt((filtered.degree.get(node.id) ?? 0) + 1) * 2.2) * opts.nodeSize,
    [filtered, opts.nodeSize],
  );

  // Course colors remain distinct, while a shared center lets cross-course
  // concept links pull related course clusters toward each other.
  const courses = useMemo(
    () => [...new Set(filtered.nodes.map((n) => n.course ?? ""))].sort(),
    [filtered],
  );
  const multiCourse = courses.length > 1;
  const anchors = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    if (!opts.separateByCourse || !multiCourse) {
      for (const course of courses) map.set(course, { x: 0, y: 0 });
      return map;
    }
    const ring = Math.max(240, 55 * Math.sqrt(filtered.nodes.length) + 40 * courses.length);
    courses.forEach((course, index) => {
      const angle = (index / courses.length) * Math.PI * 2 - Math.PI / 2;
      map.set(course, { x: ring * Math.cos(angle), y: ring * Math.sin(angle) });
    });
    return map;
  }, [courses, filtered.nodes.length, multiCourse, opts.separateByCourse]);
  const anchorOf = useCallback(
    (node: SimNode) => anchors.get(node.course ?? "") ?? { x: 0, y: 0 },
    [anchors],
  );
  const courseColorOf = useCallback(
    (course: string | null) => indexColor(Math.max(0, courses.indexOf(course ?? ""))),
    [courses],
  );

  // ---- drawing ----
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const dpr = window.devicePixelRatio || 1;
    const { width, height } = wrap.getBoundingClientRect();
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const t = transformRef.current;
    const rootStyle = getComputedStyle(document.documentElement);
    const textColor = rootStyle.getPropertyValue("--text").trim() || "#e5e7eb";
    const mutedColor = rootStyle.getPropertyValue("--muted").trim() || "#8b93a7";
    const accent = rootStyle.getPropertyValue("--accent").trim() || "#8b5cf6";

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.translate(t.x, t.y);
    ctx.scale(t.k, t.k);

    const hover = hoverRef.current;
    const neighborIds = new Set<string>();
    if (hover) {
      neighborIds.add(hover.id);
      for (const l of linksRef.current) {
        const s = l.source as SimNode;
        const d = l.target as SimNode;
        if (s.id === hover.id) neighborIds.add(d.id);
        if (d.id === hover.id) neighborIds.add(s.id);
      }
    }

    // Course labels beneath each cluster (All-courses mode).
    if (multiCourse) {
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = `600 ${22 / t.k}px Inter, system-ui, sans-serif`;
      const byCourse = new Map<string, { x: number; y: number; n: number }>();
      for (const n of nodesRef.current) {
        if (n.x == null || n.y == null) continue;
        const key = n.course ?? "";
        const acc = byCourse.get(key) ?? { x: 0, y: 0, n: 0 };
        acc.x += n.x;
        acc.y += n.y;
        acc.n += 1;
        byCourse.set(key, acc);
      }
      for (const [key, acc] of byCourse) {
        ctx.fillStyle = courseColorOf(key);
        ctx.globalAlpha = hover ? 0.12 : 0.35;
        ctx.fillText(key || "(no course)", acc.x / acc.n, acc.y / acc.n);
      }
      ctx.globalAlpha = 1;
    }

    // Edges.
    for (const l of linksRef.current) {
      const s = l.source as SimNode;
      const d = l.target as SimNode;
      if (s.x == null || d.x == null) continue;
      const active = hover && (s.id === hover.id || d.id === hover.id);
      ctx.beginPath();
      ctx.moveTo(s.x!, s.y!);
      ctx.lineTo(d.x!, d.y!);
      ctx.lineWidth = ((0.4 + l.weight * 0.18) * opts.linkThickness) / t.k;
      ctx.strokeStyle = active ? accent : mutedColor;
      ctx.globalAlpha = hover ? (active ? 0.9 : 0.04) : Math.min(0.5, 0.1 + l.weight * 0.05);
      ctx.stroke();
    }

    // Nodes.
    for (const n of nodesRef.current) {
      if (n.x == null || n.y == null) continue;
      const r = radiusOf(n);
      const dimmed = hover ? !neighborIds.has(n.id) : false;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle =
        hover && n.id === hover.id
          ? accent
          : opts.colorByCommunity
            ? multiCourse
              ? courseColorOf(n.course)
              : communityColor(n.community)
            : TYPE_COLORS[n.type] ?? mutedColor;
      ctx.globalAlpha = dimmed ? 0.08 : 0.9;
      ctx.fill();
      if (n.flagged && !dimmed) {
        ctx.setLineDash([3 / t.k, 3 / t.k]);
        ctx.lineWidth = 1.4 / t.k;
        ctx.strokeStyle = mutedColor;
        ctx.globalAlpha = 0.8;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 2.5 / t.k, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Labels: fade in with zoom (threshold slider), always visible on hover set.
    const zoomAlpha = Math.max(0, Math.min(1, (t.k - opts.textFade * 0.6) / 0.5));
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const n of nodesRef.current) {
      if (n.x == null || n.y == null) continue;
      const inHover = hover && neighborIds.has(n.id);
      const alpha = inHover ? 1 : hover ? 0 : zoomAlpha;
      if (alpha <= 0.02) continue;
      ctx.font = `${11 / t.k}px Inter, system-ui, sans-serif`;
      ctx.fillStyle = inHover ? textColor : mutedColor;
      ctx.globalAlpha = alpha;
      ctx.fillText(n.title, n.x, n.y + radiusOf(n) + 3 / t.k);
    }
    ctx.globalAlpha = 1;
  }, [opts.colorByCommunity, opts.linkThickness, opts.textFade, radiusOf, multiCourse, courseColorOf]);

  useEffect(() => {
    drawRef.current = draw;
    draw();
  }, [draw]);

  useEffect(() => {
    centeredRef.current = false;
    savedPositions.current.clear();
  }, [graph, opts.separateByCourse]);

  // ---- simulation (rebuilt when the filtered node/edge set changes) ----
  useEffect(() => {
    const nodes: SimNode[] = filtered.nodes.map((n) => {
      const saved = savedPositions.current.get(n.id);
      return { ...n, x: saved?.x, y: saved?.y };
    });
    const links: SimLink[] = filtered.edges.map((e) => ({
      source: e.source,
      target: e.target,
      weight: e.weight,
    }));
    nodesRef.current = nodes;
    linksRef.current = links;

    const anchorStrength = (
      multiCourse ? (opts.separateByCourse ? 0.14 : 0.025) : 0.08
    ) * opts.centerForce;
    const sim = forceSimulation<SimNode>(nodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance(opts.linkDistance)
          .strength((l) => Math.min(1, (l.weight / 8) * opts.linkForce + 0.05)),
      )
      .force("charge", forceManyBody<SimNode>().strength(-60 * opts.repelForce))
      // Collision packs each cluster into a tidy circular blob.
      .force("collide", forceCollide<SimNode>((d) => radiusOf(d) + 3))
      .force("x", forceX<SimNode>((d) => anchorOf(d).x).strength(anchorStrength))
      .force("y", forceY<SimNode>((d) => anchorOf(d).y).strength(anchorStrength))
      .on("tick", () => {
        for (const n of nodes) {
          if (n.x != null && n.y != null) savedPositions.current.set(n.id, { x: n.x, y: n.y });
        }
        drawRef.current();
      });
    simRef.current = sim;

    // Warm the layout synchronously so the graph appears settled immediately
    // (manual tick() does not dispatch tick events, so save/draw by hand).
    sim.stop();
    const warm = Math.min(
      300,
      Math.ceil(Math.log(sim.alphaMin()) / Math.log(1 - sim.alphaDecay())),
    );
    sim.tick(warm);
    for (const n of nodes) {
      if (n.x != null && n.y != null) savedPositions.current.set(n.id, { x: n.x, y: n.y });
    }
    // Fit the settled graph into the viewport on first load. Large all-course
    // graphs can span several thousand world pixels even with a shared center.
    if (!centeredRef.current && wrapRef.current && nodes.length > 0) {
      const positioned = nodes.filter((n) => n.x != null && n.y != null);
      const xs = positioned.map((n) => n.x!);
      const ys = positioned.map((n) => n.y!);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      const { width, height } = wrapRef.current.getBoundingClientRect();
      const padding = 48;
      const scale = Math.min(
        1,
        (width - padding * 2) / Math.max(1, maxX - minX),
        (height - padding * 2) / Math.max(1, maxY - minY),
      );
      transformRef.current = {
        x: width / 2 - ((minX + maxX) / 2) * scale,
        y: height / 2 - ((minY + maxY) / 2) * scale,
        k: scale,
      };
      centeredRef.current = true;
    }
    drawRef.current();

    return () => {
      sim.stop();
      simRef.current = null;
    };
    // Force parameters are applied live by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered]);

  // ---- live force updates from the sliders ----
  const forcesTouched = useRef(false);
  useEffect(() => {
    if (!forcesTouched.current) {
      // Skip the mount run: the fresh simulation already has these values.
      forcesTouched.current = true;
      return;
    }
    const sim = simRef.current;
    if (!sim) return;
    const anchorStrength = (
      multiCourse ? (opts.separateByCourse ? 0.14 : 0.025) : 0.08
    ) * opts.centerForce;
    (sim.force("link") as ForceLink<SimNode, SimLink>)
      .distance(opts.linkDistance)
      .strength((l) => Math.min(1, (l.weight / 8) * opts.linkForce + 0.05));
    (sim.force("charge") as ForceManyBody<SimNode>).strength(-60 * opts.repelForce);
    (sim.force("x") as ForceX<SimNode>).strength(anchorStrength);
    (sim.force("y") as ForceY<SimNode>).strength(anchorStrength);
    sim.alpha(0.4).restart();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.centerForce, opts.repelForce, opts.linkForce, opts.linkDistance, opts.separateByCourse]);

  // Node-size slider also changes collision radii; refresh without a full rebuild.
  const sizeTouched = useRef(false);
  useEffect(() => {
    if (!sizeTouched.current) {
      sizeTouched.current = true;
      return;
    }
    const sim = simRef.current;
    if (!sim) return;
    const collide = sim.force("collide") as ForceCollide<SimNode> | undefined;
    collide?.radius((d) => radiusOf(d) + 3);
    sim.alpha(0.2).restart();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.nodeSize]);

  // ---- pointer interaction ----
  const toWorld = (clientX: number, clientY: number) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const t = transformRef.current;
    return {
      x: (clientX - rect.left - t.x) / t.k,
      y: (clientY - rect.top - t.y) / t.k,
    };
  };

  const hitTest = (clientX: number, clientY: number): SimNode | null => {
    const p = toWorld(clientX, clientY);
    let best: SimNode | null = null;
    let bestDist = Infinity;
    for (const n of nodesRef.current) {
      if (n.x == null || n.y == null) continue;
      const r = radiusOf(n) + 4 / transformRef.current.k;
      const dx = p.x - n.x;
      const dy = p.y - n.y;
      const dist = dx * dx + dy * dy;
      if (dist <= r * r && dist < bestDist) {
        best = n;
        bestDist = dist;
      }
    }
    return best;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    canvasRef.current?.setPointerCapture(e.pointerId);
    const node = hitTest(e.clientX, e.clientY);
    if (node) {
      dragRef.current = node;
      const p = toWorld(e.clientX, e.clientY);
      node.fx = p.x;
      node.fy = p.y;
      simRef.current?.alphaTarget(0.3).restart();
    } else {
      const t = transformRef.current;
      panRef.current = { startX: e.clientX, startY: e.clientY, tx: t.x, ty: t.y };
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (dragRef.current) {
      const p = toWorld(e.clientX, e.clientY);
      const node = dragRef.current;
      node.fx = p.x;
      node.fy = p.y;
      // Move immediately too, so dragging stays responsive even when the
      // simulation timer is throttled (background window).
      node.x = p.x;
      node.y = p.y;
      drawRef.current();
      return;
    }
    if (panRef.current) {
      const pan = panRef.current;
      transformRef.current.x = pan.tx + (e.clientX - pan.startX);
      transformRef.current.y = pan.ty + (e.clientY - pan.startY);
      drawRef.current();
      return;
    }
    const node = hitTest(e.clientX, e.clientY);
    if (node !== hoverRef.current) {
      hoverRef.current = node;
      setHoverTitle(node?.title ?? null);
      if (canvasRef.current) canvasRef.current.style.cursor = node ? "grab" : "default";
      drawRef.current();
    }
  };

  const endPointer = (e: React.PointerEvent) => {
    canvasRef.current?.releasePointerCapture(e.pointerId);
    if (dragRef.current) {
      dragRef.current.fx = null;
      dragRef.current.fy = null;
      dragRef.current = null;
      simRef.current?.alphaTarget(0);
    }
    panRef.current = null;
  };

  const onWheel = (e: React.WheelEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const t = transformRef.current;
    const factor = Math.exp(-e.deltaY * 0.0012);
    const k = Math.max(0.08, Math.min(6, t.k * factor));
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    // Keep the point under the cursor fixed while zooming.
    t.x = mx - ((mx - t.x) / t.k) * k;
    t.y = my - ((my - t.y) / t.k) * k;
    t.k = k;
    drawRef.current();
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    const node = hitTest(e.clientX, e.clientY);
    if (node) onOpenPage(node.id);
  };

  // Redraw on container resize.
  useEffect(() => {
    if (!wrapRef.current) return;
    const observer = new ResizeObserver(() => drawRef.current());
    observer.observe(wrapRef.current);
    return () => observer.disconnect();
  }, []);

  const flaggedCount = graph.communities.filter((c) => c.flagged).length;

  return (
    <div className="wiki-force-wrap" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        className="wiki-force-canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPointer}
        onPointerLeave={endPointer}
        onWheel={onWheel}
        onDoubleClick={onDoubleClick}
      />
      <div className="wiki-graph-hud muted small">
        {filtered.nodes.length} pages · {filtered.edges.length} links ·{" "}
        {graph.stats.communities} clusters
        {flaggedCount > 0 && <> · {flaggedCount} sparse</>}
        {hoverTitle && <> · {hoverTitle}</>}
      </div>
      {!panelOpen && (
        <button className="wgp-open" onClick={() => setPanelOpen(true)}>
          Options
        </button>
      )}
      {panelOpen && (
        <div className="wiki-graph-panel">
          <div className="wgp-header">
            <span>Filters</span>
            <div className="grow" />
            <button
              className="wgp-icon"
              title="Reset to defaults"
              onClick={() => {
                window.localStorage.removeItem(SETTINGS_KEY);
                setOpts({ ...DEFAULTS });
                setSearch("");
              }}
            >
              ↺
            </button>
            <button className="wgp-icon" title="Close" onClick={() => setPanelOpen(false)}>
              ✕
            </button>
          </div>
          <input
            className="wgp-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search pages…"
          />
          <Toggle label="Concepts" value={opts.showConcepts} onChange={(v) => set({ showConcepts: v })} />
          <Toggle label="Entities" value={opts.showEntities} onChange={(v) => set({ showEntities: v })} />
          <Toggle label="Sources" value={opts.showSources} onChange={(v) => set({ showSources: v })} />
          <Toggle label="Course maps" value={opts.showMaps} onChange={(v) => set({ showMaps: v })} />
          <Toggle label="Orphans" value={opts.showOrphans} onChange={(v) => set({ showOrphans: v })} />
          <Toggle
            label="Separate by course"
            value={opts.separateByCourse}
            onChange={(v) => set({ separateByCourse: v })}
          />

          <Section title="Display">
            <Toggle
              label="Color by cluster"
              value={opts.colorByCommunity}
              onChange={(v) => set({ colorByCommunity: v })}
            />
            <Slider label="Text fade threshold" min={0} max={3} step={0.05} value={opts.textFade} onChange={(v) => set({ textFade: v })} />
            <Slider label="Node size" min={0.4} max={2.5} step={0.05} value={opts.nodeSize} onChange={(v) => set({ nodeSize: v })} />
            <Slider label="Link thickness" min={0.2} max={3} step={0.05} value={opts.linkThickness} onChange={(v) => set({ linkThickness: v })} />
          </Section>

          <Section title="Forces">
            <Slider label="Center force" min={0} max={1} step={0.02} value={opts.centerForce} onChange={(v) => set({ centerForce: v })} />
            <Slider label="Repel force" min={0} max={4} step={0.05} value={opts.repelForce} onChange={(v) => set({ repelForce: v })} />
            <Slider label="Link force" min={0} max={1} step={0.02} value={opts.linkForce} onChange={(v) => set({ linkForce: v })} />
            <Slider label="Link distance" min={20} max={300} step={5} value={opts.linkDistance} onChange={(v) => set({ linkDistance: v })} />
          </Section>
        </div>
      )}
    </div>
  );
}
