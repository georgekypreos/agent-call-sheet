/** Display helpers shared across components. */

export function fmtMoney(n: number | null | undefined): string {
  const v = n ?? 0;
  if (!v) return "$0";
  if (v >= 1_000_000) return "$" + (v / 1_000_000).toFixed(v >= 10_000_000 ? 0 : 1).replace(/\.0$/, "") + "M";
  if (v >= 1_000) return "$" + Math.round(v / 1_000) + "k";
  return "$" + v;
}

export function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  // YYYY-MM-DD → "Jan 5, 1985" style
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(s);
  if (m) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${months[+m[2] - 1]} ${+m[3]}, ${m[1]}`;
  }
  return s;
}

export function fmtAnniversary(s: string | null | undefined): string {
  if (!s) return "—";
  const base = fmtDate(s);
  const m = /^(\d{4})/.exec(s);
  if (m) {
    const yrs = new Date().getFullYear() - parseInt(m[1], 10);
    if (yrs >= 0) return `${base} (${yrs} yr${yrs === 1 ? "" : "s"})`;
  }
  return base;
}

export function displayName(a: { firstName?: string; lastName?: string; email?: string; rank?: number }): string {
  const f = (a.firstName ?? "").trim();
  const l = (a.lastName ?? "").trim();
  const full = `${f} ${l}`.trim();
  return full || a.email || `Agent #${a.rank ?? "?"}`;
}

export function initials(a: { firstName?: string; lastName?: string; email?: string }): string {
  const f = (a.firstName ?? "").trim();
  const l = (a.lastName ?? "").trim();
  const i = (f[0] ?? "") + (l[0] ?? "");
  return i.toUpperCase() || (a.email ? a.email[0].toUpperCase() : "?");
}

export function fmtTrend(cur: number, prev: number): { pctText: string; klass: string; arrow: string } {
  if (!prev || prev <= 0) return { pctText: "", klass: "text-muted", arrow: "" };
  const pct = ((cur - prev) / prev) * 100;
  const rounded = Math.round(pct);
  if (rounded > 0) return { pctText: `+${rounded}%`, klass: "text-success", arrow: "↑" };
  if (rounded < 0) return { pctText: `${rounded}%`, klass: "text-danger", arrow: "↓" };
  return { pctText: "0%", klass: "text-muted", arrow: "→" };
}
