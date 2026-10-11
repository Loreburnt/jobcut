"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  deleteApplication,
  getHealth,
  getShortlist,
  setStatus,
  type ScoreBasis,
  type Shortlist,
  type ShortlistItem,
} from "@/lib/api";
import JobCard from "@/components/JobCard";
import RunControls from "@/components/RunControls";
import { absoluteDay, relativeDay } from "@/lib/ui";
import { Icon } from "@/components/icons";
import { ErrorNote, SkeletonCards } from "@/components/States";

const MATCH_STEPS = [60, 70, 80, 90, 95];
const STATUS_LABEL: Record<string, string> = {
  saved: "Saved",
  applied: "Applied",
  screen: "Screening",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  no_response: "No response",
};

export default function HomePage() {
  const router = useRouter();
  const [data, setData] = useState<Shortlist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Restore the persisted match floor (a real "facet"); lazy init avoids a
  // setState-in-effect and reads localStorage only on the client.
  const [minScore, setMinScore] = useState<number>(() => {
    if (typeof window === "undefined") return 70;
    const saved = Number(window.localStorage.getItem("jp_min_score"));
    return saved >= 60 && saved <= 95 ? saved : 70;
  });
  const [q, setQ] = useState("");
  // Which score drives the list: Claude's review (default) or jobcut's automatic score.
  const [basis, setBasis] = useState<ScoreBasis>(() => {
    if (typeof window === "undefined") return "claude";
    try {
      return window.localStorage.getItem("jp_basis") === "auto" ? "auto" : "claude";
    } catch {
      return "claude";
    }
  });
  function changeBasis(b: ScoreBasis) {
    setBasis(b);
    try {
      window.localStorage.setItem("jp_basis", b);
    } catch {
      /* storage unavailable: keep in memory only */
    }
  }
  const [toast, setToast] = useState<{ jobId: string; label: string; prev: string | null } | null>(null);

  function changeMin(v: number) {
    setMinScore(v);
    if (typeof window !== "undefined") window.localStorage.setItem("jp_min_score", String(v));
  }

  // First run (no token, no jobs) → onboarding, unless dismissed for THIS install.
  // The "dismissed" flag is namespaced by data dir so a stale flag from another
  // install on the same localhost origin can't suppress onboarding for a fresh one.
  useEffect(() => {
    getHealth()
      .then((h) => {
        if (h.apify_token_set || h.jobs > 0) return;
        if (localStorage.getItem(`jp_onboarded:${h.data_dir}`)) return;
        router.push("/onboarding");
      })
      .catch(() => {});
  }, [router]);

  const load = useCallback(() => {
    setLoading(true);
    getShortlist({ min_score: minScore, basis, ...(q ? { q } : {}) })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }, [minScore, q, basis]);

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0); // debounce the search box
    return () => clearTimeout(t);
  }, [load, q]);

  // Applying (any status) excludes the job from the shortlist — drop it optimistically,
  // then reconcile in the background (fast now; the PUT already cleared the read cache).
  // A toast offers Undo so a mis-click never silently loses the card.
  const onApplied = useCallback(
    (jobId: string, next: string, prev: string | null) => {
      setData((d) =>
        d
          ? {
              ...d,
              today: d.today.filter((j) => j.job_id !== jobId),
              backlog: d.backlog.filter((j) => j.job_id !== jobId),
            }
          : d,
      );
      setToast({ jobId, label: STATUS_LABEL[next] ?? next, prev });
      load();
    },
    [load],
  );

  const undo = useCallback(async () => {
    if (!toast) return;
    const { jobId, prev } = toast;
    setToast(null);
    try {
      if (prev) await setStatus(jobId, prev);
      else await deleteApplication(jobId); // it had no application before — remove the one we just made
    } finally {
      load();
    }
  }, [toast, load]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  const newCount = data?.today.length ?? 0;
  const funnelCount = data?.meta.funnel_count ?? 0;
  const totallyEmpty = data && data.meta.db_count === 0;

  return (
    <div className="space-y-8">
      {/* header */}
      <header className="flex flex-col items-start justify-between gap-4 md:flex-row md:items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-on-surface">
            Your shortlist for today
          </h1>
          <p className="mt-1 text-lg text-on-surface-variant">
            {data
              ? `${newCount} new today · ${funnelCount} in your funnel`
              : "Loading your matches…"}
          </p>
          {data && (data.meta.last_pull || data.meta.last_scored) && (
            <p className="mt-1 flex items-center gap-1.5 text-sm text-on-surface-faint">
              <Icon name="calendar" size={14} className="shrink-0" />
              {data.meta.last_pull && (
                <span title={absoluteDay(data.meta.last_pull) ?? undefined}>
                  Jobs pulled {relativeDay(data.meta.last_pull)}
                </span>
              )}
              {data.meta.last_pull && data.meta.last_scored && <span aria-hidden>·</span>}
              {data.meta.last_scored && (
                <span title={absoluteDay(data.meta.last_scored) ?? undefined}>
                  scored {relativeDay(data.meta.last_scored)}
                </span>
              )}
            </p>
          )}
        </div>
        <RunControls onDone={load} />
      </header>

      {/* score basis tabs: Claude's review vs jobcut's automatic score */}
      <section aria-label="Score source">
        <div role="tablist" className="inline-flex gap-1 rounded-lg bg-surface-sunken p-1">
          {(
            [
              { key: "claude", label: "Claude's review", count: data?.meta.claude_count },
              { key: "auto", label: "Automatic score", count: undefined },
            ] as { key: ScoreBasis; label: string; count?: number }[]
          ).map((tab) => {
            const active = basis === tab.key;
            return (
              <button
                key={tab.key}
                role="tab"
                aria-selected={active}
                onClick={() => changeBasis(tab.key)}
                className={`rounded-md px-4 py-2 text-sm font-semibold transition-colors ${
                  active ? "bg-surface text-on-surface shadow-sm" : "text-on-surface-variant hover:text-on-surface"
                }`}
              >
                {tab.label}
                {tab.count != null && <span className="ml-1.5 font-normal text-on-surface-faint">{tab.count}</span>}
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-sm text-on-surface-variant">
          {basis === "claude"
            ? "Jobs Claude has read in full and judged against your profile, remote eligibility and company stability."
            : "jobcut's instant keyword score for every new job. Fast, but it can't read eligibility or company risk."}
        </p>
      </section>

      {/* filter row */}
      <section className="flex flex-col items-stretch gap-4 rounded-card border border-border/40 bg-surface p-4 shadow-card lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant">
            <Icon name="search" size={18} />
          </span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by title or company"
            className="w-full rounded-lg border border-border bg-bg py-2.5 pl-10 pr-3 text-on-surface outline-none transition-colors placeholder:text-on-surface-variant focus:border-primary focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="flex items-center gap-3 rounded-lg border border-border bg-bg px-4 py-2">
          <span className="whitespace-nowrap text-sm font-medium text-on-surface-variant">
            Minimum match
          </span>
          <div className="flex gap-1 rounded-lg bg-surface-sunken p-1">
            {MATCH_STEPS.map((v) => {
              const active = minScore === v;
              return (
                <button
                  key={v}
                  onClick={() => changeMin(v)}
                  className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                    active
                      ? "bg-surface text-on-surface shadow-sm"
                      : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  {v}%+
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {error && (
        <ErrorNote>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>We couldn&apos;t load your shortlist. Make sure jobcut is running, then try again.</span>
            <button
              onClick={load}
              className="shrink-0 rounded-lg border border-[color:var(--color-accent-red)]/40 px-3 py-1.5 text-sm font-semibold text-[color:var(--color-accent-red)] transition-colors hover:bg-[color:var(--color-accent-red)]/10"
            >
              Retry
            </button>
          </div>
        </ErrorNote>
      )}

      {loading && !data && <SkeletonCards count={4} />}

      {totallyEmpty ? (
        <EmptyState
          title="Let’s find your first matches"
          body="You don’t have any jobs yet. Run “Find new jobs” to pull your saved searches and score them against your profile."
        />
      ) : (
        data && (
          <div className="space-y-10">
            <Section icon="sparkles" title="Latest matches" count={data.today.length}>
              {data.today.length ? (
                <ProgressiveGrid items={data.today} onApplied={onApplied} />
              ) : basis === "claude" && !data.meta.claude_count ? (
                <EmptyState
                  title="Claude hasn't reviewed these jobs yet"
                  body="Ask Claude in your chat: “puntúa mis ofertas”. Meanwhile, the Automatic score tab shows every job."
                />
              ) : (
                <EmptyState
                  title="No matches at this level"
                  body="Lower the minimum match, clear the search, or find new jobs to widen the net."
                />
              )}
            </Section>

            <Section icon="calendar" title="Earlier" count={data.backlog.length}>
              {data.backlog.length ? (
                <ProgressiveGrid items={data.backlog} onApplied={onApplied} />
              ) : (
                <EmptyState
                  title="No earlier matches above this level"
                  body="Your backlog of strong matches from prior days will show up here."
                />
              )}
            </Section>
          </div>
        )
      )}

      {toast && (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-4 rounded-full border border-border bg-surface px-5 py-3 text-sm font-medium text-on-surface shadow-pop"
        >
          <span>Marked as {toast.label}</span>
          <button onClick={undo} className="font-semibold text-primary hover:underline">
            Undo
          </button>
        </div>
      )}
    </div>
  );
}

function Section({
  icon,
  title,
  count,
  children,
}: {
  icon: "sparkles" | "calendar";
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="mb-5 flex items-center gap-2 text-2xl font-semibold text-on-surface">
        <span className="text-primary">
          <Icon name={icon} size={22} />
        </span>
        {title}
        {count > 0 && <span className="text-base font-normal text-on-surface-faint">· {count}</span>}
      </h2>
      {children}
    </section>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">{children}</div>;
}

const PAGE = 24;

// The min-match slider is the real filter; the feed returns everything above the floor.
// We reveal cards progressively so a low floor (hundreds of matches) stays snappy.
function ProgressiveGrid({
  items,
  onApplied,
}: {
  items: ShortlistItem[];
  onApplied: (jobId: string, next: string, prev: string | null) => void;
}) {
  const [shown, setShown] = useState(PAGE);
  const visible = items.slice(0, shown);
  const left = items.length - visible.length;
  return (
    <>
      <Grid>
        {visible.map((j) => (
          <JobCard key={j.job_id} item={j} onApplied={onApplied} />
        ))}
      </Grid>
      {left > 0 && (
        <div className="mt-6 flex justify-center">
          <button
            onClick={() => setShown((n) => n + PAGE)}
            className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-semibold text-on-surface transition-colors hover:border-primary hover:text-primary"
          >
            Show {Math.min(PAGE, left)} more · {left} below this match level
          </button>
        </div>
      )}
    </>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-card border border-dashed border-border bg-surface/60 p-8 text-center">
      <p className="text-base font-medium text-on-surface">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-on-surface-variant">{body}</p>
    </div>
  );
}
