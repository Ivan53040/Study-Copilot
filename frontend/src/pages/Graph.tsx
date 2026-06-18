import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { VaultGraph } from "../types";

interface Sim {
  id: string;
  title: string;
  folder: string;
  degree: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

function hue(folder: string): string {
  let h = 0;
  for (const ch of folder) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h}, 60%, 60%)`;
}

export function GraphPage({ onOpen }: { onOpen: (path: string) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [graph, setGraph] = useState<VaultGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const state = useRef({ offsetX: 0, offsetY: 0, scale: 1, nodes: [] as Sim[] });

  useEffect(() => {
    api.vaultGraph().then(setGraph).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (!graph) return;
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    const resize = () => {
      canvas.width = canvas.clientWidth;
      canvas.height = canvas.clientHeight;
    };
    resize();

    const byId = new Map<string, Sim>();
    const nodes: Sim[] = graph.nodes.map((n, i) => {
      const a = (i / graph.nodes.length) * Math.PI * 2;
      const s: Sim = {
        ...n,
        x: Math.cos(a) * 300 + (Math.random() - 0.5) * 40,
        y: Math.sin(a) * 300 + (Math.random() - 0.5) * 40,
        vx: 0,
        vy: 0,
      };
      byId.set(n.id, s);
      return s;
    });
    state.current.nodes = nodes;
    state.current.offsetX = canvas.width / 2;
    state.current.offsetY = canvas.height / 2;
    const edges = graph.edges
      .map((e) => [byId.get(e.source), byId.get(e.target)] as const)
      .filter(([a, b]) => a && b) as [Sim, Sim][];

    const radius = (n: Sim) => 3 + Math.sqrt(n.degree) * 1.6;

    const draw = () => {
      const { offsetX, offsetY, scale } = state.current;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.lineWidth = 0.5;
      ctx.strokeStyle = "rgba(150,160,180,0.25)";
      for (const [a, b] of edges) {
        ctx.beginPath();
        ctx.moveTo(a.x * scale + offsetX, a.y * scale + offsetY);
        ctx.lineTo(b.x * scale + offsetX, b.y * scale + offsetY);
        ctx.stroke();
      }
      for (const n of nodes) {
        const sx = n.x * scale + offsetX;
        const sy = n.y * scale + offsetY;
        ctx.beginPath();
        ctx.fillStyle = hue(n.folder);
        ctx.arc(sx, sy, radius(n) * scale, 0, Math.PI * 2);
        ctx.fill();
        if (n.degree >= 8 && scale > 0.5) {
          ctx.fillStyle = "rgba(230,232,238,0.9)";
          ctx.font = "11px sans-serif";
          ctx.fillText(n.title.slice(0, 24), sx + radius(n) * scale + 2, sy + 3);
        }
      }
    };

    let alpha = 1;
    let raf = 0;
    const tick = () => {
      // Repulsion (O(n^2); fine for a few hundred notes).
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let d2 = dx * dx + dy * dy || 0.01;
          const f = (2500 * alpha) / d2;
          const d = Math.sqrt(d2);
          const fx = (dx / d) * f;
          const fy = (dy / d) * f;
          a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
        }
      }
      // Springs along edges.
      for (const [a, b] of edges) {
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const f = (d - 60) * 0.02 * alpha;
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
      // Centering + integrate + damping.
      for (const n of nodes) {
        n.vx += -n.x * 0.002 * alpha;
        n.vy += -n.y * 0.002 * alpha;
        n.x += n.vx; n.y += n.vy;
        n.vx *= 0.85; n.vy *= 0.85;
      }
      alpha *= 0.985;
      draw();
      if (alpha > 0.03) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    // --- interaction ---
    let dragging = false;
    let moved = false;
    let lastX = 0, lastY = 0;
    const toWorld = (mx: number, my: number) => ({
      x: (mx - state.current.offsetX) / state.current.scale,
      y: (my - state.current.offsetY) / state.current.scale,
    });
    const hit = (mx: number, my: number) => {
      const w = toWorld(mx, my);
      for (const n of nodes) {
        const r = radius(n) + 4;
        if ((n.x - w.x) ** 2 + (n.y - w.y) ** 2 <= r * r) return n;
      }
      return null;
    };
    const onDown = (e: MouseEvent) => { dragging = true; moved = false; lastX = e.offsetX; lastY = e.offsetY; };
    const onMove = (e: MouseEvent) => {
      if (!dragging) return;
      moved = true;
      state.current.offsetX += e.offsetX - lastX;
      state.current.offsetY += e.offsetY - lastY;
      lastX = e.offsetX; lastY = e.offsetY;
      draw();
    };
    const onUp = (e: MouseEvent) => {
      dragging = false;
      if (!moved) {
        const n = hit(e.offsetX, e.offsetY);
        if (n) onOpen(n.id);
      }
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 0.9;
      state.current.scale *= factor;
      draw();
    };
    canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("resize", resize);

    return () => {
      cancelAnimationFrame(raf);
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("wheel", onWheel);
      window.removeEventListener("resize", resize);
    };
  }, [graph, onOpen]);

  return (
    <div>
      <h1 className="page-title">Graph</h1>
      <p className="page-sub">
        Your notes linked by [[wikilinks]]. Drag to pan, scroll to zoom, click a
        node to open it.
        {graph && (
          <> {" "}· {graph.stats.notes} notes, {graph.stats.links} links</>
        )}
      </p>
      {error && <div className="warn-banner">{error}</div>}
      <canvas
        ref={canvasRef}
        style={{
          width: "100%",
          height: "calc(100vh - 150px)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          background: "var(--panel)",
          cursor: "grab",
        }}
      />
    </div>
  );
}
