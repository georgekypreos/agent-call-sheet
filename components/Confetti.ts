/** Confetti trigger. Uses canvas-confetti from CDN if available, falls back to a CSS-based version. */

declare global {
  // canvas-confetti attaches `confetti` to window when loaded
  interface Window {
    confetti?: (opts: Record<string, unknown>) => void;
  }
}

export function fireConfetti(): void {
  const colors = ["#4f46e5", "#7c3aed", "#06b6d4", "#10b981", "#22d3ee", "#f59e0b", "#f43f5e", "#ec4899", "#84cc16"];
  if (typeof window !== "undefined" && typeof window.confetti === "function") {
    const c = window.confetti;
    const duration = 4000;
    const end = Date.now() + duration;
    (function frame() {
      c!({ particleCount: 8, angle: 60, spread: 75, origin: { x: 0, y: 0.75 }, colors, startVelocity: 55, scalar: 1.1 });
      c!({ particleCount: 8, angle: 120, spread: 75, origin: { x: 1, y: 0.75 }, colors, startVelocity: 55, scalar: 1.1 });
      if (Date.now() < end) requestAnimationFrame(frame);
    })();
    c({ particleCount: 250, spread: 110, origin: { x: 0.5, y: 0.55 }, colors, scalar: 1.25, startVelocity: 60 });
    setTimeout(() => c({ particleCount: 200, spread: 130, origin: { x: 0.25, y: 0.5 }, colors, scalar: 1.15 }), 350);
    setTimeout(() => c({ particleCount: 200, spread: 130, origin: { x: 0.75, y: 0.5 }, colors, scalar: 1.15 }), 700);
    return;
  }
  fallbackConfetti(colors);
}

function fallbackConfetti(colors: string[]) {
  const container = document.createElement("div");
  container.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:9999;overflow:hidden;";
  document.body.appendChild(container);
  const N = 400;
  for (let i = 0; i < N; i++) {
    const piece = document.createElement("div");
    const size = 6 + Math.random() * 10;
    const color = colors[Math.floor(Math.random() * colors.length)];
    const left = Math.random() * 100;
    const delay = Math.random() * 1.2;
    const dur = 2.2 + Math.random() * 2.2;
    const rot = ((Math.random() * 1080 - 540) | 0);
    const drift = ((Math.random() * 300 - 150) | 0);
    piece.style.cssText = `position:absolute;top:-20px;left:${left}vw;width:${size}px;height:${size * 0.4}px;background:${color};border-radius:2px;opacity:0.95;transform:rotate(${rot}deg);animation:cfall ${dur}s ${delay}s cubic-bezier(0.25,0.45,0.6,1) forwards;--drift:${drift}px;`;
    container.appendChild(piece);
  }
  setTimeout(() => container.remove(), 5000);
}
