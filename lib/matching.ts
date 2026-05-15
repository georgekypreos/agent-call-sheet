/** Helpers for matching Courted agents to FUB people. */

export function normalizePhone(input: string | null | undefined): string {
  if (!input) return "";
  // Strip everything except digits, keep last 10 (US format)
  const digits = String(input).replace(/\D/g, "");
  if (!digits) return "";
  return digits.length > 10 ? digits.slice(-10) : digits;
}

export function normalizeEmail(input: string | null | undefined): string {
  return (input ?? "").trim().toLowerCase();
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Returns true if the `dateStr` matches today's month-day (ignoring year). */
export function matchesToday(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  const s = String(dateStr).trim();
  const today = new Date();
  const mm = String(today.getMonth() + 1).padStart(2, "0");
  const dd = String(today.getDate()).padStart(2, "0");
  const target = `${mm}-${dd}`;
  // Try YYYY-MM-DD or YYYY/MM/DD
  let m = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/.exec(s);
  if (m) return `${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}` === target;
  // Try MM-DD-YYYY or MM/DD/YYYY
  m = /^(\d{1,2})[-/](\d{1,2})[-/]\d{4}/.exec(s);
  if (m) return `${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")}` === target;
  // Try MM-DD or MM/DD
  m = /^(\d{1,2})[-/](\d{1,2})$/.exec(s);
  if (m) return `${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")}` === target;
  return false;
}

/** Check if any of the tags identifies an SREG agent. Catches Signature/SREG prefixes. */
export function isSREGTagged(tags: string[] | null | undefined): boolean {
  if (!tags || tags.length === 0) return false;
  return tags.some((t) => {
    const lc = String(t).toLowerCase().trim();
    return lc.startsWith("signature") || lc.startsWith("sreg");
  });
}
