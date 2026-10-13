"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addEvent,
  advanceProcess,
  getDocuments,
  getEvents,
  getJob,
  getProcessTiming,
  patchApplication,
  setProcess,
  setStatus,
  suggestProcess,
  type ApplicationFields,
  type AppDocument,
  type AppEvent,
  type JobDetail,
  type ProcessTiming,
  type SalaryEstimate,
} from "@/lib/api";
import DocumentViewer from "@/components/DocumentViewer";
import JobDescription from "@/components/JobDescription";
import ScoreRing from "@/components/ScoreRing";
import StatusSelect from "@/components/StatusSelect";
import { Icon } from "@/components/icons";
import { ErrorNote, Loading } from "@/components/States";
import { CATEGORY_COLOR, isoToLocal, offerLink, scorerLabel } from "@/lib/ui";

export default function JobPage() {
  return (
    <Suspense fallback={<Loading />}>
      <JobDetailView />
    </Suspense>
  );
}

// Application tracker steps. `status` is the backend status set when the step is
// clicked; "Saved" is the baseline (no application yet).
const STEPS = [
  { label: "Saved", status: null as string | null, icon: "check" as const },
  { label: "Applied", status: "applied", icon: "send" as const },
  { label: "Screening", status: "screen", icon: "user" as const },
  { label: "Interview", status: "interview", icon: "users" as const },
  { label: "Offer", status: "offer", icon: "check-circle" as const },
];

function stepIndex(status: string | null | undefined): number {
  switch (status) {
    case "offer": return 4;
    case "interview": return 3;
    case "screen": return 2;
    case "applied": case "rejected": case "withdrawn": case "no_response": return 1;
    default: return 0;
  }
}

// Terminal outcomes don't sit on the linear path — they get an explicit chip
// (mapped to the same CATEGORY_COLOR the funnel uses), not a fake "Applied".
const TERMINAL: Record<string, string> = {
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  no_response: "No response",
};

function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = isoToLocal(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function fmtWhen(iso: string): string {
  const d = isoToLocal(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// Interview rounds are day-granular (the backend models them by date, anchored to
// noon), so their time-of-day is fabricated — show the date only. Real instants
// (notes, status changes) keep the time.
function fmtEventWhen(e: AppEvent): string {
  return e.kind === "interview" ? fmtDate(e.ts) ?? fmtWhen(e.ts) : fmtWhen(e.ts);
}

function parseStages(s: string | null | undefined): string[] {
  if (!s) return [];
  try {
    const a = JSON.parse(s);
    return Array.isArray(a) ? a.map(String) : [];
  } catch {
    return [];
  }
}

const STATUS_LABEL: Record<string, string> = {
  applied: "Applied",
  screen: "Screening",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  no_response: "No response",
};

// Timeline dot color per event kind.
const EVENT_DOT: Record<string, string> = {
  note: "#16a34a",
  status_change: "#64748b",
  interview: "#2563eb",
  next_action: "#d97706",
};

function eventLabel(e: AppEvent): string {
  if (e.kind === "status_change") {
    const to = STATUS_LABEL[e.to_status ?? ""] ?? e.to_status ?? "";
    return e.from_status ? `Moved to ${to}` : `Started tracking — ${to}`;
  }
  if (e.kind === "interview") {
    // The round/stage lives in meta {stage, index} — surface it so a dated round
    // reads "Interview · R3 · Hiring Manager", not a bare "interview".
    let stage: string | undefined;
    let index: number | undefined;
    try {
      const m = JSON.parse(e.meta || "{}");
      stage = typeof m.stage === "string" ? m.stage : undefined;
      index = typeof m.index === "number" ? m.index : undefined;
    } catch {
      /* meta absent or malformed — fall back to a plain label */
    }
    const tag = [index ? `R${index}` : null, stage].filter(Boolean).join(" · ");
    const head = tag ? `Interview · ${tag}` : "Interview";
    return e.body ? `${head} — ${e.body}` : head;
  }
  return e.body || e.kind;
}

function salaryText(job: Record<string, string | null>): string | null {
  if (job.salary_text) return job.salary_text;
  const parts = [job.salary_min, job.salary_max].filter(Boolean);
  return parts.length ? parts.join(" – ") : null;
}

// B-15: a Cowork-estimated band, shown only when the employer disclosed none. Kept
// visually distinct from a real band (a dashed "est." chip) so the two never blur.
function fmtK(n: number | null): string | null {
  if (n == null) return null;
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}
function estimateText(est: SalaryEstimate): string | null {
  const lo = fmtK(est.est_min);
  const hi = fmtK(est.est_max);
  const range = lo && hi ? `${lo}–${hi}` : lo ?? hi;
  if (!range) return null;
  const cur = est.currency ? ` ${est.currency}` : "";
  const per = est.period === "month" ? "/mo" : est.period === "hour" ? "/hr" : "/yr";
  return `~${range}${cur}${per}`;
}

function JobDetailView() {
  const id = useSearchParams().get("id") ?? "";
  const [data, setData] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [documents, setDocuments] = useState<AppDocument[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setLocalStatus] = useState<string | null>(null); // optimistic
  // Interview process inline editor state
  const [editing, setEditing] = useState(false);
  const [processDraft, setProcessDraft] = useState("");
  const [processBusy, setProcessBusy] = useState(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [justCompleted, setJustCompleted] = useState(false);
  const [advanceDate, setAdvanceDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [timing, setTiming] = useState<ProcessTiming>(null);
  // B-18: the description reads occasionally, so it's collapsed by default when long.
  const [descOpen, setDescOpen] = useState(false);
  // prep-docs: Overview (funnel + notes) vs Prep documents (full-width reader).
  const [view, setView] = useState<"overview" | "prep">("overview");

  const load = useCallback(() => {
    if (!id) return;
    // Timing and documents are supplementary — never let them block the page (a job with no
    // application returns null/[]; any other hiccup degrades to "no timing/docs" rather than
    // an error screen).
    Promise.all([
      getJob(id),
      getEvents(id),
      getProcessTiming(id).catch(() => null),
      getDocuments(id).catch(() => [] as AppDocument[]),
    ])
      .then(([d, ev, t, docs]) => {
        setData(d);
        setLocalStatus(d.application?.status ?? null);
        setEvents(ev);
        setTiming(t);
        setDocuments(docs);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load"));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!id) return <p className="text-sm text-on-surface-faint">No job selected.</p>;
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <Loading label="Loading this role…" />;

  const { job, score } = data;
  const appOnly = job === null; // imported/manual row with no jobs data
  const link = job
    ? offerLink({ linkedin_url: job.linkedin_url, apply_url: job.apply_url, easy_apply_url: job.easy_apply_url })
    : null;
  const reasons = (score?.match_reasons ?? "").split(",").map((r) => r.trim()).filter(Boolean);
  const sal = job ? salaryText(job) : null;
  // Precedence: structured band > a band the employer stated in the description (B-17) >
  // a Cowork estimate (B-15). Each only fills in when the more-authoritative one is absent.
  const listing = !sal ? data?.salary_listing ?? null : null;
  const est = !sal && !listing && data?.salary_estimate ? estimateText(data.salary_estimate) : null;
  const description = job?.description ?? null;
  const longDesc = (description?.length ?? 0) > 600;
  const wp = job?.workplace_type
    ? job.workplace_type.replace(/_/g, "-").replace(/\b\w/g, (c) => c.toUpperCase())
    : null;
  const current = stepIndex(status);
  const terminal = status ? TERMINAL[status] ?? null : null;
  const terminalColor = terminal ? CATEGORY_COLOR[terminal] : null;
  const accent = terminal && terminalColor ? terminalColor : "var(--color-primary)";

  // Prep documents live in their own full-width "Prep documents" view (the index + reader),
  // grouped by stage there — never mixed into the timeline. This is just the tab count.
  const prepDocCount = documents.length;

  async function setStep(next: string) {
    setLocalStatus(next); // optimistic
    await setStatus(id, next); // status-only write-path; also records a status_change event
    load();
  }

  async function addNote() {
    const body = draft.trim();
    if (!body) return;
    // Solo-note write-path: appends to the timeline, never fabricates an 'applied' row.
    await addEvent(id, { kind: "note", body });
    setDraft("");
    load();
  }

  async function patchField(key: keyof ApplicationFields, value: string) {
    await patchApplication(id, { [key]: value }); // structured fields; never touches status
  }

  async function onAdvance() {
    const r = await advanceProcess(id, undefined, advanceDate);
    load();
    if (r.completed) {
      setJustCompleted(true);
    }
  }

  function openEditor(prefill: string) {
    setProcessDraft(prefill);
    setSuggestError(null);
    setEditing(true);
  }

  function onEditProcess() {
    const current = parseStages(data?.application?.process_stages).join("\n");
    openEditor(current);
  }

  async function onSuggestProcess() {
    setProcessBusy(true);
    setSuggestError(null);
    try {
      const { stages } = await suggestProcess(id);
      openEditor(stages.join("\n"));
    } catch {
      setSuggestError("Could not suggest stages — try again.");
    } finally {
      setProcessBusy(false);
    }
  }

  async function onSaveProcess() {
    const stages = processDraft.split("\n").map((s) => s.trim()).filter(Boolean);
    setProcessBusy(true);
    try {
      await setProcess(id, stages);
      setEditing(false);
      load();
    } finally {
      setProcessBusy(false);
    }
  }

  async function onMarkOffer() {
    await setStatus(id, "offer");
    setJustCompleted(false);
    load();
  }

  return (
    <div className="space-y-8">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm font-medium text-primary transition-colors hover:text-primary-hover"
      >
        <Icon name="arrow-left" size={18} /> Back to shortlist
      </Link>

      {/* hero + status strip */}
      <div className="rounded-card border border-border/40 bg-surface p-6 shadow-card">
        <div className="flex flex-col items-start justify-between gap-6 md:flex-row">
          <div className="flex flex-col gap-4">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight text-on-surface md:text-4xl">
                {job?.title ?? "Role added manually"}
              </h1>
              {job?.company_name ? (
                <p className="mt-1 flex items-center gap-2 text-xl text-on-surface-variant">
                  <Icon name="building" size={20} /> {job.company_name}
                </p>
              ) : (
                appOnly && (
                  <p className="mt-1 text-sm text-on-surface-faint">
                    In your tracker but not in the market dataset — no scoring or company data.
                  </p>
                )
              )}
            </div>
            {!appOnly && (
              <div className="flex flex-wrap gap-2">
                {job?.location && <Chip icon="map-pin">{job.location}</Chip>}
                {wp && <Chip icon="briefcase" tone="primary">{wp}</Chip>}
                {sal && <Chip icon="banknote">{sal}</Chip>}
                {listing && (
                  <Chip icon="banknote" title="Stated in the job description">{listing}</Chip>
                )}
                {est && (
                  <Chip icon="banknote" estimated title={data?.salary_estimate?.basis ?? "Estimated, not disclosed by the employer"}>
                    {est} · est.
                  </Chip>
                )}
              </div>
            )}
          </div>
          <div className="flex flex-col items-center gap-1.5">
            {appOnly ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-sunken px-3 py-1.5 text-xs font-medium text-on-surface-variant">
                <Icon name="building" size={12} /> No market data
              </span>
            ) : (
              <>
                <ScoreRing score={score?.match_score ?? null} size={96} label />
                {scorerLabel(score?.backend) && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-2.5 py-1 text-xs font-medium text-on-surface-variant">
                    <Icon name="sparkles" size={12} /> Scored {fmtDate(score?.scored_date) ?? "—"} by{" "}
                    {scorerLabel(score?.backend)}
                  </span>
                )}
              </>
            )}
            {data.application?.updated_at && (
              <span className="text-xs text-on-surface-faint">
                Updated {fmtDate(data.application.updated_at)}
              </span>
            )}
          </div>
        </div>

        {/* status strip — ex "Application tracker", now a compact band under the title:
            mini funnel + state pill + status selector + open posting */}
        <div className="mt-6 flex flex-col gap-4 border-t border-border/60 pt-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center">
            {STEPS.map((s, i) => {
              const done = i <= current;
              const isCurrent = i === current && !terminal;
              const clickable = s.status != null;
              return (
                <div key={s.label} className="flex items-center">
                  <button
                    disabled={!clickable}
                    onClick={() => clickable && s.status && setStep(s.status)}
                    title={clickable ? `Mark as ${s.label}` : "Saved"}
                    style={done ? { background: accent, color: "var(--color-on-primary)" } : undefined}
                    className={`flex h-6 w-6 items-center justify-center rounded-full transition-colors ${
                      done ? "" : "bg-surface-sunken text-on-surface-faint"
                    } ${isCurrent ? "ring-2 ring-primary/25" : ""} ${
                      clickable ? "cursor-pointer hover:opacity-90" : "cursor-default"
                    }`}
                  >
                    <Icon name={s.icon} size={13} />
                  </button>
                  <span className={`ml-1.5 hidden text-[11px] font-semibold sm:inline ${done ? "text-on-surface" : "text-on-surface-faint"}`}>
                    {s.label}
                  </span>
                  {i < STEPS.length - 1 && (
                    <span
                      className="mx-2 h-0.5 w-4 rounded sm:w-5"
                      style={{ background: i < current ? accent : "var(--color-surface-sunken)" }}
                    />
                  )}
                </div>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            {terminal && terminalColor ? (
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold"
                style={{ color: terminalColor, background: `${terminalColor}1f`, border: `1px solid ${terminalColor}40` }}
              >
                Closed · {terminal}
              </span>
            ) : data.application ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-tint px-3 py-1.5 text-xs font-semibold text-primary-strong">
                <span className="h-1.5 w-1.5 rounded-full bg-primary" /> In process
              </span>
            ) : null}
            <StatusSelect key={status ?? "none"} jobId={id} value={status} onChanged={load} />
            {link && (
              <a
                href={link}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-full border border-border bg-surface-sunken px-3.5 py-1.5 text-xs font-semibold text-on-surface transition-colors hover:border-primary/50 hover:text-primary"
              >
                <Icon name="external" size={14} /> Open posting
              </a>
            )}
          </div>
        </div>
      </div>

      {/* view switch — only when there are prep documents to read */}
      {prepDocCount > 0 && <ViewTabs view={view} onChange={setView} prepCount={prepDocCount} />}

      {view === "prep" && prepDocCount > 0 ? (
        <PrepDocsView documents={documents} events={events} />
      ) : (
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        {/* left: actionable first — interview process, notes, then the long description */}
        <div className="space-y-8 lg:col-span-2">
          {data.application && (() => {
            const stages = parseStages(data.application.process_stages);
            const cur = data.application.process_current ?? 0;
            return (
              <div className="rounded-card border border-border/40 bg-surface p-6 shadow-card">
                <div className="flex items-center justify-between">
                  <h2 className="text-xl font-semibold text-on-surface">Interview process</h2>
                  {stages.length > 0 && (
                    <span className="text-xs text-on-surface-variant">
                      Stage {Math.min(cur + (cur < stages.length ? 1 : 0), stages.length)} of {stages.length}
                    </span>
                  )}
                </div>

                {/* Process-complete banner */}
                {justCompleted && (
                  <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/10 px-4 py-3">
                    <span className="text-sm font-medium text-on-surface">
                      Process complete 🎉 —{" "}
                      <button
                        onClick={onMarkOffer}
                        className="font-semibold text-primary underline-offset-2 hover:underline"
                      >
                        Mark as Offer
                      </button>
                    </span>
                    <button
                      onClick={() => setJustCompleted(false)}
                      className="text-xs text-on-surface-faint hover:text-on-surface"
                      aria-label="Dismiss"
                    >
                      ✕
                    </button>
                  </div>
                )}

                {stages.length === 0 && !editing && (
                  <>
                    <p className="mt-3 text-sm text-on-surface-variant">No process defined yet.</p>
                    {suggestError && (
                      <p className="mt-2 text-sm text-red-500">{suggestError}</p>
                    )}
                    <div className="mt-3 flex gap-2">
                      <button
                        onClick={onEditProcess}
                        className="rounded-lg border border-border px-3 py-1.5 text-sm"
                      >
                        Define stages
                      </button>
                      <button
                        onClick={onSuggestProcess}
                        disabled={processBusy}
                        className="rounded-lg border border-border px-3 py-1.5 text-sm disabled:opacity-50"
                      >
                        {processBusy ? "Suggesting…" : "Suggest from posting"}
                      </button>
                    </div>
                  </>
                )}

                {stages.length > 0 && !editing && (
                  <>
                    <ol className="mt-3 space-y-1.5">
                      {stages.map((name, i) => (
                        <li key={i} className="flex items-center gap-2 text-sm">
                          <span>{i < cur ? "✅" : i === cur ? "◉" : "○"}</span>
                          <span className={i === cur ? "font-medium" : "text-on-surface-variant"}>{name}</span>
                        </li>
                      ))}
                    </ol>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <button
                        onClick={onAdvance}
                        disabled={cur >= stages.length}
                        className="rounded-lg bg-primary px-3 py-1.5 text-sm text-on-primary disabled:opacity-50"
                      >
                        Advance stage
                      </button>
                      <input
                        type="date"
                        value={advanceDate}
                        onChange={(e) => setAdvanceDate(e.target.value)}
                        className="rounded-lg border border-border bg-bg px-2 py-1.5 text-sm text-on-surface"
                        aria-label="Round date"
                      />
                      <button
                        onClick={onEditProcess}
                        className="rounded-lg border border-border px-3 py-1.5 text-sm"
                      >
                        Edit stages
                      </button>
                      <button
                        onClick={onSuggestProcess}
                        disabled={processBusy}
                        className="rounded-lg border border-border px-3 py-1.5 text-sm disabled:opacity-50"
                      >
                        {processBusy ? "Suggesting…" : "Suggest from posting"}
                      </button>
                    </div>
                    {timing && (
                      <p className="mt-2 text-xs text-on-surface-variant">
                        Process: {timing.duration_days} days · avg gap {Math.round(timing.avg_gap_days)} days
                      </p>
                    )}
                    {suggestError && (
                      <p className="mt-2 text-sm text-red-500">{suggestError}</p>
                    )}
                  </>
                )}

                {/* Inline editor */}
                {editing && (
                  <div className="mt-4 space-y-3">
                    <textarea
                      value={processDraft}
                      onChange={(e) => setProcessDraft(e.target.value)}
                      placeholder={"Recruiter screen\nTechnical\nHiring Manager\nFinal"}
                      rows={5}
                      className="w-full rounded-lg border border-border bg-bg p-3 text-sm text-on-surface outline-none transition-colors placeholder:text-on-surface-faint focus:border-primary focus:ring-1 focus:ring-primary"
                    />
                    <p className="text-xs text-on-surface-faint">One stage per line</p>
                    <div className="flex gap-2">
                      <button
                        onClick={onSaveProcess}
                        disabled={processBusy}
                        className="rounded-lg bg-primary px-3 py-1.5 text-sm text-on-primary disabled:opacity-50"
                      >
                        {processBusy ? "Saving…" : "Save"}
                      </button>
                      <button
                        onClick={() => { setEditing(false); setSuggestError(null); }}
                        disabled={processBusy}
                        className="rounded-lg border border-border px-3 py-1.5 text-sm disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

          <Panel title="Notes & activity">
            <div className="space-y-3">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") addNote();
                }}
                placeholder="Add a note — recruiter call, interview prep, a reminder…"
                rows={3}
                className="w-full rounded-lg border border-border bg-bg p-4 text-sm text-on-surface outline-none transition-colors placeholder:text-on-surface-faint focus:border-primary focus:ring-1 focus:ring-primary"
              />
              <div className="flex items-center justify-between">
                <span className="text-xs text-on-surface-faint">⌘/Ctrl + Enter to add</span>
                <button
                  onClick={addNote}
                  disabled={!draft.trim()}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary shadow-sm transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-primary"
                >
                  <Icon name="check" size={18} /> Add note
                </button>
              </div>
            </div>
            <div className="mt-5 border-t border-border pt-4">
              {events.length === 0 ? (
                <p className="text-sm text-on-surface-faint">
                  No activity yet — your notes and status changes appear here, newest first.
                </p>
              ) : (
                <ul className="space-y-4">
                  {events.map((e) => (
                    <TimelineRow key={e.event_id} e={e} />
                  ))}
                </ul>
              )}
            </div>
          </Panel>

          {/* description last — long, occasional read; collapsed by default */}
          {description ? (
            <Panel title="Description">
              <div className={`relative ${longDesc && !descOpen ? "max-h-[260px] overflow-hidden" : ""}`}>
                <JobDescription text={description} />
                {longDesc && !descOpen && (
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-surface to-transparent" />
                )}
              </div>
              {longDesc && (
                <button
                  onClick={() => setDescOpen((o) => !o)}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-on-surface transition-colors hover:border-primary hover:text-primary"
                >
                  <Icon name="chevron-right" size={16} className={`transition-transform ${descOpen ? "rotate-90" : ""}`} />
                  {descOpen ? "Show less" : "Show full description"}
                </button>
              )}
            </Panel>
          ) : (
            // Imported tracker rows carry no description (the spreadsheet never had one).
            // Show an honest empty-state instead of silently dropping the panel.
            (appOnly || data.application) && (
              <Panel title="Description">
                <p className="text-sm leading-relaxed text-on-surface-variant">
                  No description on file — this role came from your tracker.
                  {link ? " Open the posting to read it." : " No posting link saved either."}
                </p>
                {link && (
                  <a
                    href={link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-semibold text-on-surface transition-colors hover:border-primary hover:text-primary"
                  >
                    <Icon name="external" size={16} /> Open posting
                  </a>
                )}
              </Panel>
            )
          )}
        </div>

        {/* right: why it matches + tracking details + company */}
        <div className="space-y-8">
          {/* why this matches — first on the right; wraps inside the card (B-18 overflow fix) */}
          {!appOnly && reasons.length > 0 && (
            <div className="rounded-card border border-primary/30 bg-primary-tint p-6">
              <h3 className="mb-4 text-lg font-semibold text-primary-strong">Why this matches you</h3>
              <ul className="space-y-3">
                {reasons.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-on-surface-variant">
                    <span className="mt-0.5 shrink-0 text-primary">
                      <Icon name="check-circle" size={18} />
                    </span>
                    <span className="min-w-0 break-words [overflow-wrap:anywhere]">{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* per-offer skills — which of your taxonomy skills this role asks for */}
          {!appOnly && data.skills_match && (data.skills_match.matched.length > 0 || data.skills_match.missing.length > 0) && (
            <div className="rounded-card border border-border bg-surface p-6 shadow-card">
              <h3 className="mb-1 text-lg font-semibold text-on-surface">Skills for this role</h3>
              <p className="mb-4 flex items-center gap-1.5 text-sm text-on-surface-variant">
                {data.skills_match.source === "claude" ? (
                  <>
                    <Icon name="sparkles" size={13} /> Judged by Claude against your profile.
                  </>
                ) : (
                  "Matched from your profile."
                )}
              </p>
              {data.skills_match.matched.length > 0 && (
                <div className="mb-4">
                  <p className="mb-2 text-xs font-medium text-on-surface-variant">You have</p>
                  <div className="flex flex-wrap gap-2">
                    {data.skills_match.matched.map((s) => (
                      <SkillChip key={s.skill} skill={s.skill} status={s.status ?? "have"} note={s.note} />
                    ))}
                  </div>
                </div>
              )}
              {data.skills_match.missing.length > 0 && (
                <div>
                  <p className="mb-2 text-xs font-medium text-on-surface-variant">Gaps it asks for</p>
                  <div className="flex flex-wrap gap-2">
                    {data.skills_match.missing.map((s) => (
                      <SkillChip key={s.skill} skill={s.skill} status="gap" note={s.note} closeVia={s.close_via} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* tracking details — Priority removed (unused); Follow-up date kept: it drives
              the "Needs attention" nudge, so it must stay editable + clearable here. */}
          {data.application && (
            <Panel title="Tracking details">
              <div className="space-y-4">
                <FieldRow label="Next action">
                  <input
                    defaultValue={data.application.next_action ?? ""}
                    onBlur={(e) => patchField("next_action", e.target.value)}
                    placeholder="e.g. send portfolio"
                    className={FIELD_CLS}
                  />
                </FieldRow>
                {/* Follow-up date drives the "Needs attention" nudge on the applications
                    page (overdue/due). Editable + clearable here so a reminder you no
                    longer need can be updated or removed — leaving it empty silences it. */}
                <FieldRow label="Follow-up date">
                  <input
                    type="date"
                    key={data.application.next_action_date ?? "none"}
                    defaultValue={(data.application.next_action_date ?? "").slice(0, 10)}
                    onChange={(e) => patchField("next_action_date", e.target.value)}
                    className={FIELD_CLS}
                  />
                  <span className="mt-1 block text-xs text-on-surface-faint">
                    When a follow-up is due. Clear it to remove the “Needs attention” reminder.
                  </span>
                </FieldRow>
                <FieldRow label="Contact">
                  <input
                    defaultValue={data.application.contact ?? ""}
                    onBlur={(e) => patchField("contact", e.target.value)}
                    placeholder="recruiter / hiring manager"
                    className={FIELD_CLS}
                  />
                </FieldRow>
                <FieldRow label="CV version">
                  <input
                    defaultValue={data.application.cv_version ?? ""}
                    onBlur={(e) => patchField("cv_version", e.target.value)}
                    placeholder="which CV you sent"
                    className={FIELD_CLS}
                  />
                </FieldRow>
              </div>
            </Panel>
          )}

          {!appOnly && job && (
            <Panel title="Company details">
              <div className="grid grid-cols-2 gap-3">
                <Fact icon="building" label="Size" value={job.company_size} />
                <Fact icon="users" label="Applicants" value={job.applicants} />
                <Fact icon="calendar" label="Posted" value={job.posted_date} />
                <Fact icon="user" label="Recruiter" value={job.recruiter_name} />
              </div>
            </Panel>
          )}
        </div>
      </div>
      )}
    </div>
  );
}

function Chip({
  icon,
  tone = "default",
  estimated = false,
  title,
  children,
}: {
  icon: "map-pin" | "briefcase" | "banknote";
  tone?: "default" | "primary";
  estimated?: boolean; // dashed outline → "estimated, not a disclosed band"
  title?: string;
  children: React.ReactNode;
}) {
  const cls = estimated
    ? "border border-dashed border-border bg-transparent text-on-surface-faint"
    : tone === "primary"
      ? "bg-primary-tint text-primary-strong"
      : "bg-surface-sunken text-on-surface-variant";
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium ${cls}`}
    >
      <Icon name={icon} size={16} /> {children}
    </span>
  );
}

const FIELD_CLS =
  "w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-on-surface outline-none transition-colors placeholder:text-on-surface-faint focus:border-primary focus:ring-1 focus:ring-primary";

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-on-surface-variant">{label}</span>
      {children}
    </label>
  );
}

function TimelineRow({ e }: { e: AppEvent }) {
  const dot = EVENT_DOT[e.kind] ?? "#64748b";
  const isNote = e.kind === "note";
  return (
    <li className="flex gap-3">
      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: dot }} />
      <div className="min-w-0 flex-1">
        <p
          className={`text-sm ${
            isNote ? "whitespace-pre-wrap text-on-surface" : "font-medium text-on-surface-variant"
          }`}
        >
          {eventLabel(e)}
        </p>
        <p className="mt-0.5 text-xs text-on-surface-faint">{fmtEventWhen(e)}</p>
      </div>
    </li>
  );
}

const DOC_TYPE_LABEL: Record<string, string> = {
  prep: "Prep",
  debrief: "Debrief",
  study: "Study",
  other: "Doc",
};

// Segmented control switching the body between the Overview (funnel + notes) and the
// full-width Prep documents reader.
function ViewTabs({
  view,
  onChange,
  prepCount,
}: {
  view: "overview" | "prep";
  onChange: (v: "overview" | "prep") => void;
  prepCount: number;
}) {
  const tabs: { key: "overview" | "prep"; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "prep", label: "Prep documents" },
  ];
  return (
    <div className="flex w-fit items-center gap-1 rounded-full border border-border/60 bg-surface p-1">
      {tabs.map((t) => {
        const active = view === t.key;
        return (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className={`flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
              active ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-on-surface"
            }`}
          >
            {t.label}
            {t.key === "prep" && (
              <span
                className={`rounded-full px-1.5 text-[11px] font-semibold ${
                  active ? "bg-on-primary/20 text-on-primary" : "bg-surface-sunken text-on-surface-faint"
                }`}
              >
                {prepCount}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

type DocGroup = { key: string; label: string; docs: AppDocument[] };

// Group documents for the index: offer-level first, then by the timeline event (round) they
// anchor to, ordered chronologically. The round label is the event's own body ("R3 · …") when
// it has one; otherwise it falls back to an ordinal + date ("Round 2 · 15 jun 2026") derived
// from the event's position among the application's interview rounds — so unlabelled rounds
// (the common case) still read as distinct stages instead of a row of bare "Round"s.
function buildDocGroups(documents: AppDocument[], events: AppEvent[]): DocGroup[] {
  const evById = new Map(events.map((e) => [e.event_id, e]));
  // 1-based position of each interview event among all interview rounds, by date.
  const ordinal = new Map<number, number>();
  events
    .filter((e) => e.kind === "interview")
    .sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))
    .forEach((e, i) => ordinal.set(e.event_id, i + 1));

  const offer = documents.filter((d) => d.event_id == null);
  const byEvent = new Map<number, AppDocument[]>();
  for (const d of documents) {
    if (d.event_id != null) {
      const list = byEvent.get(d.event_id) ?? [];
      list.push(d);
      byEvent.set(d.event_id, list);
    }
  }
  const eventGroups = [...byEvent.entries()]
    .map(([eid, docs]) => {
      const e = evById.get(eid);
      const body = (e?.body ?? "").trim();
      const ord = e ? ordinal.get(e.event_id) : undefined;
      const date = e ? fmtDate(e.ts) : null;
      const label = body || (ord ? `Round ${ord}${date ? ` · ${date}` : ""}` : "Round");
      return { key: `ev${eid}`, label, order: e ? Date.parse(e.ts) : 0, docs };
    })
    .sort((a, b) => a.order - b.order);
  const groups: DocGroup[] = [];
  if (offer.length) groups.push({ key: "offer", label: "Offer-level", docs: offer });
  for (const g of eventGroups) groups.push({ key: g.key, label: g.label, docs: g.docs });
  return groups;
}

// Full-width prep-documents reader: a stage-grouped, collapsible index + a wide reading pane.
function PrepDocsView({ documents, events }: { documents: AppDocument[]; events: AppEvent[] }) {
  const groups = useMemo(() => buildDocGroups(documents, events), [documents, events]);
  const allIds = useMemo(() => groups.flatMap((g) => g.docs.map((d) => d.doc_id)), [groups]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [indexOpen, setIndexOpen] = useState(true);
  const readerRef = useRef<HTMLDivElement>(null);

  // Derive the active doc instead of storing (and effect-correcting) a possibly-stale id:
  // the selection falls back to the first doc when unset or no longer present (re-ingest).
  const activeId = selectedId != null && allIds.includes(selectedId) ? selectedId : allIds[0] ?? null;
  const active = documents.find((d) => d.doc_id === activeId) ?? null;

  function select(docId: number) {
    setSelectedId(docId);
    readerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (!active) return null;
  const typeMeta = `${DOC_TYPE_LABEL[active.doc_type] ?? "Doc"}${
    active.updated_at ? ` · updated ${fmtDate(active.updated_at)}` : ""
  }`;

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      {/* stage index */}
      {indexOpen && (
        <aside className="lg:w-72 lg:shrink-0">
          <div className="lg:sticky lg:top-6 rounded-card border border-border/40 bg-surface p-3 shadow-card">
            <div className="mb-2 flex items-center justify-between px-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-on-surface-faint">
                Documents
              </span>
              <button
                onClick={() => setIndexOpen(false)}
                title="Hide index"
                aria-label="Hide index"
                className="rounded p-1 text-on-surface-faint transition-colors hover:bg-surface-sunken hover:text-on-surface"
              >
                <Icon name="panel-left" size={16} />
              </button>
            </div>
            <nav className="space-y-3">
              {groups.map((g) => (
                <div key={g.key}>
                  <p className="flex items-baseline justify-between gap-2 px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-on-surface-variant">
                    <span className="min-w-0 truncate">{g.label}</span>
                    <span className="shrink-0 font-normal text-on-surface-faint">{g.docs.length}</span>
                  </p>
                  <ul className="space-y-0.5">
                    {g.docs.map((d) => {
                      const isActive = d.doc_id === activeId;
                      return (
                        <li key={d.doc_id}>
                          <button
                            onClick={() => select(d.doc_id)}
                            className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                              isActive
                                ? "bg-primary-tint font-medium text-primary-strong"
                                : "text-on-surface-variant hover:bg-surface-sunken"
                            }`}
                          >
                            <Icon name="file-text" size={15} className="shrink-0" />
                            <span className="min-w-0 flex-1 truncate">{d.title}</span>
                            <span className="shrink-0 text-[10px] font-semibold uppercase text-on-surface-faint">
                              {DOC_TYPE_LABEL[d.doc_type] ?? "Doc"}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </nav>
          </div>
        </aside>
      )}

      {/* reader */}
      <article ref={readerRef} className="min-w-0 flex-1 scroll-mt-6">
        <div className="rounded-card border border-border/40 bg-surface shadow-card">
          <header className="flex items-center gap-3 border-b border-border/60 px-5 py-4 lg:px-8">
            {!indexOpen && (
              <button
                onClick={() => setIndexOpen(true)}
                title="Show index"
                aria-label="Show index"
                className="shrink-0 rounded-lg border border-border p-1.5 text-on-surface-faint transition-colors hover:text-on-surface"
              >
                <Icon name="panel-left" size={16} />
              </button>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-lg font-semibold text-on-surface">{active.title}</h2>
              <p className="mt-0.5 text-xs text-on-surface-faint">{typeMeta}</p>
            </div>
          </header>
          <div className="px-5 py-6 lg:px-10 lg:py-8">
            <DocumentViewer key={active.doc_id} body={active.body} />
          </div>
        </div>
      </article>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border border-border/40 bg-surface p-6 shadow-card">
      <h2 className="mb-4 text-xl font-semibold text-on-surface">{title}</h2>
      {children}
    </section>
  );
}

function Fact({
  icon,
  label,
  value,
}: {
  icon: "building" | "users" | "calendar" | "user";
  label: string;
  value: string | null;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-surface-alt p-3">
      <span className="text-on-surface-faint">
        <Icon name={icon} size={18} />
      </span>
      <span className="text-xs font-semibold text-on-surface-variant">{label}</span>
      <span className="text-sm font-medium text-on-surface">{value || "—"}</span>
    </div>
  );
}

// Skill status → chip color (have green / partial amber / gap red), mirroring Discovery.
const SKILL_STATUS_COLOR: Record<string, string> = {
  have: "var(--color-score-high)",
  partial: "var(--color-accent-amber)",
  gap: "var(--color-accent-red)",
};

function SkillChip({
  skill,
  status,
  note,
  closeVia,
}: {
  skill: string;
  status: string;
  note?: string;
  closeVia?: string;
}) {
  const color = SKILL_STATUS_COLOR[status] ?? "var(--color-on-surface-faint)";
  const title = note || (closeVia ? `Close via: ${closeVia}` : undefined);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium"
      style={{ color, background: `color-mix(in srgb, ${color} 12%, transparent)` }}
      title={title}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {skill}
    </span>
  );
}
