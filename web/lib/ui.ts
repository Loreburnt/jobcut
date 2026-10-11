// Shared visual helpers. Colors come from the D1 theme tokens (Stitch),
// tuned for legibility on the light (#f8f9ff / white) surfaces.

export const CATEGORY_COLOR: Record<string, string> = {
  Interview: "#16a34a",
  Screen: "#0891b2",
  Active: "#2563eb",
  Reviewing: "#7c3aed",
  Applied: "#64748b",
  Offer: "#9333ea",
  "No response": "#94a3b8",
  Closed: "#64748b",
  Withdrawn: "#d97706",
  Rejected: "#dc2626",
  Saved: "#6366f1",
  Other: "#64748b",
};

// Match-score scale: high green / mid amber / low gray (--color-score-*).
export function scoreColor(score: number | null): string {
  if (score == null) return "#6e7b6c";
  if (score >= 75) return "#16a34a";   // high
  if (score >= 50) return "#d97706";   // mid
  return "#6e7b6c";                    // low
}

// Friendly label for the scoring backend that produced a score (db `scores.backend`).
// Returns null when unknown/empty so the UI can skip the badge.
// `local` and `llm_api` are no longer offered, but scores produced by them before they
// were removed still sit in the db — keep labelling those rows instead of leaking the id.
const SCORER_LABELS: Record<string, string> = {
  rule_based: "Rule-based",
  claude_skills: "Claude",
  local: "Local AI",
  llm_api: "API",
};
export function scorerLabel(backend: string | null | undefined): string | null {
  if (!backend) return null;
  return SCORER_LABELS[backend] ?? backend;
}

// Parse a stored ISO timestamp for display (B-19). New timestamps are UTC-aware
// (`…+00:00`); legacy rows are naive but were stamped in UTC — so a naive datetime
// means UTC, not local. Append `Z` when a datetime carries no offset so the browser
// localizes both forms identically (fixes the "2h behind" notes). Date-only strings
// ("YYYY-MM-DD") are left untouched.
export function isoToLocal(iso: string): Date {
  const needsUtc = iso.includes("T") && !/([zZ]|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(needsUtc ? `${iso}Z` : iso);
}

// Build a LOCAL-midnight Date from a "YYYY-MM-DD" head, or null if the value isn't a
// real date. `posted_date` can be junk (Apify sometimes gives non-ISO text), so callers
// get null and skip rendering rather than showing garbage.
function dayOnly(value: string | null | undefined): Date | null {
  if (!value) return null;
  const head = value.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(head)) return null;
  const [y, m, d] = head.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

// A short, friendly age: "today", "yesterday", "3d ago", "2w ago", then an absolute
// date ("Jul 18") beyond a month or for future dates. Null for blanks/unparseable.
export function relativeDay(value: string | null | undefined): string | null {
  const d = dayOnly(value);
  if (!d) return null;
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((start.getTime() - d.getTime()) / 86_400_000);
  if (days < 0) return absoluteDay(value);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return absoluteDay(value);
}

// Absolute short date for tooltips/fallback: "Jul 18" (this year) or "Jul 18, 2025".
export function absoluteDay(value: string | null | undefined): string | null {
  const d = dayOnly(value);
  if (!d) return null;
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, sameYear
    ? { month: "short", day: "numeric" }
    : { month: "short", day: "numeric", year: "numeric" });
}

export function offerLink(item: {
  linkedin_url: string | null;
  apply_url: string | null;
  easy_apply_url: string | null;
}): string | null {
  return item.linkedin_url || item.apply_url || item.easy_apply_url || null;
}


// "10/10/26" (dd/mm/yy) for a "YYYY-MM-DD…" value, or null if it isn't a real date.
export function shortDate(value: string | null | undefined): string | null {
  const d = dayOnly(value);
  if (!d) return null;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yy = String(d.getFullYear()).slice(-2);
  return `${dd}/${mm}/${yy}`;
}

// Always-relative age: "today", "yesterday", "5d ago", "3w ago", "2mo ago".
export function ageLabel(value: string | null | undefined): string | null {
  const d = dayOnly(value);
  if (!d) return null;
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((start.getTime() - d.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 60) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}
