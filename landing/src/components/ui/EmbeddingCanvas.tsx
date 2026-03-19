import { useRef, useEffect, useState, useCallback } from "react";

interface Point {
  x: number;
  y: number;
  folder: string;
  title: string;
  cluster: number;
}

// Pre-baked demo data — simulates t-SNE projection of note embeddings
const FOLDER_COLORS: Record<string, string> = {
  Poems: "#bf5af2",
  Essays: "#0071e3",
  Journal: "#30d158",
  Ideas: "#ff9f0a",
  Drafts: "#ff375f",
  Recipes: "#ff6482",
  Products: "#64d2ff",
  Personal: "#ac8e68",
  Faith: "#5e5ce6",
  Travel: "#2aa198",
};

const CLUSTER_LABELS = [
  { x: 0.15, y: 0.2, label: "Nigerian Identity" },
  { x: 0.75, y: 0.15, label: "Creative Process" },
  { x: 0.5, y: 0.5, label: "Personal Reflection" },
  { x: 0.2, y: 0.75, label: "Faith & Doubt" },
  { x: 0.8, y: 0.7, label: "Startup Ideas" },
  { x: 0.45, y: 0.85, label: "Family & Home" },
  { x: 0.85, y: 0.4, label: "London Life" },
];

function generateDemoPoints(): Point[] {
  const points: Point[] = [];
  const folders = Object.keys(FOLDER_COLORS);
  const rng = (seed: number) => {
    let s = seed;
    return () => {
      s = (s * 16807 + 0) % 2147483647;
      return s / 2147483647;
    };
  };
  const rand = rng(42);

  // Generate clustered points
  const clusterCenters = [
    { x: 0.15, y: 0.2, folders: ["Essays", "Poems"] },
    { x: 0.75, y: 0.15, folders: ["Drafts", "Journal"] },
    { x: 0.5, y: 0.5, folders: ["Journal", "Personal"] },
    { x: 0.2, y: 0.75, folders: ["Poems", "Journal"] },
    { x: 0.8, y: 0.7, folders: ["Ideas", "Products"] },
    { x: 0.45, y: 0.85, folders: ["Personal", "Recipes"] },
    { x: 0.85, y: 0.4, folders: ["Essays", "Travel"] },
  ];

  const titles = [
    "On Leaving", "Vespers", "Code Switching", "Lagos Morning",
    "Hyphenated", "Third Culture", "Marketplace Idea", "Focus Timer",
    "Sunday Mornings", "Kitchen Notes", "Jollof Recipe", "Night Bus",
    "Workshop Draft", "New Poem", "Letter Home", "City Sounds",
    "Reading Notes", "Prayer", "Doubt", "Bridge Poem",
  ];

  for (let c = 0; c < clusterCenters.length; c++) {
    const center = clusterCenters[c];
    const numPoints = 20 + Math.floor(rand() * 15);
    for (let i = 0; i < numPoints; i++) {
      const angle = rand() * Math.PI * 2;
      const r = rand() * 0.12 + rand() * 0.04;
      points.push({
        x: Math.max(0.02, Math.min(0.98, center.x + Math.cos(angle) * r)),
        y: Math.max(0.02, Math.min(0.98, center.y + Math.sin(angle) * r)),
        folder: center.folders[Math.floor(rand() * center.folders.length)],
        title: titles[Math.floor(rand() * titles.length)],
        cluster: c,
      });
    }
  }

  return points;
}

const DEMO_POINTS = generateDemoPoints();

function isDarkMode(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export default function EmbeddingCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredPoint, setHoveredPoint] = useState<Point | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const animFrameRef = useRef<number>(0);
  const timeRef = useRef(0);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number, time: number) => {
      const dpr = window.devicePixelRatio || 1;
      const dark = isDarkMode();
      ctx.clearRect(0, 0, width * dpr, height * dpr);
      ctx.save();
      ctx.scale(dpr, dpr);

      const padding = 40;
      const w = width - padding * 2;
      const h = height - padding * 2;

      // Subtle grid
      ctx.strokeStyle = dark ? "rgba(255, 255, 255, 0.06)" : "rgba(210, 210, 215, 0.15)";
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 10; i++) {
        const gx = padding + (w / 10) * i;
        const gy = padding + (h / 10) * i;
        ctx.beginPath();
        ctx.moveTo(gx, padding);
        ctx.lineTo(gx, padding + h);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(padding, gy);
        ctx.lineTo(padding + w, gy);
        ctx.stroke();
      }

      // Draw points
      DEMO_POINTS.forEach((point, _idx) => {
        const px = padding + point.x * w;
        const py = padding + point.y * h;

        // Subtle idle drift
        const drift = Math.sin(time * 0.0005 + point.x * 10 + point.y * 7) * 1.5;
        const driftY = Math.cos(time * 0.0004 + point.y * 8 + point.x * 5) * 1.5;
        const finalX = px + drift;
        const finalY = py + driftY;

        const color = FOLDER_COLORS[point.folder] || "#6e6e73";
        const isHovered = hoveredPoint === point;
        const radius = isHovered ? 6 : 3.5;

        // Glow for hovered
        if (isHovered) {
          ctx.beginPath();
          ctx.arc(finalX, finalY, 14, 0, Math.PI * 2);
          ctx.fillStyle = color + "20";
          ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(finalX, finalY, radius, 0, Math.PI * 2);
        ctx.fillStyle = color + (isHovered ? "ff" : dark ? "dd" : "bb");
        ctx.fill();
      });

      // Cluster labels
      ctx.font = "600 11px system-ui, -apple-system, sans-serif";
      ctx.textAlign = "center";
      CLUSTER_LABELS.forEach((label) => {
        const lx = padding + label.x * w;
        const ly = padding + label.y * h - 55;
        ctx.fillStyle = dark ? "rgba(245, 245, 247, 0.3)" : "rgba(29, 29, 31, 0.35)";
        ctx.fillText(label.label, lx, ly);
      });

      ctx.restore();
    },
    [hoveredPoint],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      const rect = container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
    };

    resize();
    window.addEventListener("resize", resize);

    const animate = (timestamp: number) => {
      timeRef.current = timestamp;
      const rect = container.getBoundingClientRect();
      draw(ctx, rect.width, rect.height, timestamp);
      animFrameRef.current = requestAnimationFrame(animate);
    };

    animFrameRef.current = requestAnimationFrame(animate);

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animFrameRef.current);
    };
  }, [draw]);

  const handleMouseMove = (e: React.MouseEvent) => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const rect = container.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top });

    const padding = 40;
    const w = rect.width - padding * 2;
    const h = rect.height - padding * 2;

    let closest: Point | null = null;
    let closestDist = Infinity;

    DEMO_POINTS.forEach((point) => {
      const px = padding + point.x * w;
      const py = padding + point.y * h;
      const dist = Math.sqrt((mx - px) ** 2 + (my - py) ** 2);
      if (dist < closestDist && dist < 20) {
        closestDist = dist;
        closest = point;
      }
    });

    setHoveredPoint(closest);
  };

  return (
    <div className="relative">
      <div
        ref={containerRef}
        className="w-full aspect-[16/10] rounded-2xl bg-apple-card-solid/70 border border-apple-border/30 overflow-hidden cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredPoint(null)}
      >
        <canvas ref={canvasRef} className="w-full h-full" />

        {/* Tooltip */}
        {hoveredPoint && (
          <div
            className="absolute pointer-events-none z-10 px-3 py-2 rounded-lg bg-apple-code-bg text-apple-bg text-[13px] shadow-lg dark:bg-apple-bg-alt dark:text-apple-text"
            style={{
              left: mousePos.x + 12,
              top: mousePos.y - 40,
              transform: mousePos.x > 400 ? "translateX(-110%)" : "none",
            }}
          >
            <div className="font-semibold">{hoveredPoint.title}</div>
            <div className="text-[11px] opacity-60 flex items-center gap-1.5 mt-0.5">
              <span
                className="w-2 h-2 rounded-full inline-block"
                style={{
                  backgroundColor: FOLDER_COLORS[hoveredPoint.folder] || "#6e6e73",
                }}
              />
              {hoveredPoint.folder}
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 mt-4">
        {Object.entries(FOLDER_COLORS)
          .slice(0, 7)
          .map(([folder, color]) => (
            <div
              key={folder}
              className="flex items-center gap-1.5 text-[12px] text-apple-text-secondary"
            >
              <span
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: color }}
              />
              {folder}
            </div>
          ))}
      </div>
    </div>
  );
}
