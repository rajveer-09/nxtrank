/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 18 October 2026
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { api, type Rules } from "../api";
import { LOGO_URL } from "../components/Layout";
import { PageSkeleton } from "../components/skeletons";
import { Card, Empty, ErrorBox, Input, cx } from "../components/ui";

/** "About NxtWave": facts from NxtWave's own website (ccbp.in), October 2026. */
const ABOUT_NXTWAVE: string[] = [
  "NxtWave is an Indian edtech company, founded in 2020 and based in Hyderabad. It trains students for careers in software through its Continuous Career Building Program (CCBP).",
  "Its programs include CCBP 4.0 Academy, for students after 12th class or Intermediate; NxtWave Intensive, a full-stack job programme for graduates; and NIAT, industry-ready upskilling run at collaborating institutions across India.",
  "NxtWave was founded by Rahul Attuluri (CEO), Anupam Pedarla and Sashank Gujjula.",
];

const SOCIAL = [
  {
    label: "LinkedIn",
    href: "https://www.linkedin.com/in/rajveer-sharma933/",
    icon: <path d="M3.6 5.6h2.1v6.8H3.6V5.6Zm1-3.4a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4ZM7 5.6h2v.9h.03c.28-.53.97-1.1 2-1.1 2.13 0 2.53 1.4 2.53 3.23v3.77h-2.1V9.06c0-.8-.02-1.84-1.12-1.84-1.12 0-1.3.88-1.3 1.78v3.4H7V5.6Z" />,
  },
  {
    label: "X (Twitter)",
    href: "https://x.com/rajveer__09",
    icon: <path d="M12.2 2h2.1l-4.6 5.3L15 14h-4.2l-3.3-4.3L3.7 14H1.6l4.9-5.6L1.4 2h4.3l3 3.9L12.2 2Zm-.7 10.8h1.2L4.9 3.1H3.6l7.9 9.7Z" />,
  },
];

const pct = (x: number) => `${Math.round(x * 100)}%`;
const ordinal = (n: number) => `${n}${n === 1 ? "st" : n === 2 ? "nd" : n === 3 ? "rd" : "th"}`;

// 16px line icons, drawn with currentColor
const ICON: Record<string, ReactNode> = {
  people: <path d="M6 7.5a2.25 2.25 0 1 0 0-4.5 2.25 2.25 0 0 0 0 4.5ZM2 13c.3-2.2 1.9-3.5 4-3.5s3.7 1.3 4 3.5M10.5 3.2a2.25 2.25 0 0 1 0 4.1M12 9.8c1.1.5 1.8 1.6 2 3.2" />,
  calendar: <path d="M3 4.5h10v8.5H3zM3 7h10M5.5 3v2.5M10.5 3v2.5" />,
  rank: <path d="M3 13.5V9h3v4.5M6.5 13.5V5h3v8.5M10 13.5V7.5h3v6" />,
  medal: <path d="M5.5 2.5 8 6.5l2.5-4M8 13.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM8 8.6v2.2" />,
  pulse: <path d="M1.5 8.5h3l1.5-4 3 7 1.5-3h4" />,
  trend: <path d="M2 11.5 6 7.5l2.5 2.5L14 4.5M10.5 4.5H14V8" />,
  question: <path d="M8 14A6 6 0 1 0 8 2a6 6 0 0 0 0 12ZM6.3 6.2a1.8 1.8 0 1 1 2.5 1.7c-.5.2-.8.6-.8 1.1v.4M8 11.3v.2" />,
  tag: <path d="M2.5 3.5h5l6 6-4 4-6-6v-4ZM5.25 6.25h.01" />,
  clock: <path d="M8 14A6 6 0 1 0 8 2a6 6 0 0 0 0 12ZM8 4.5V8l2.3 1.5" />,
  star: <path d="m8 2 1.8 3.7 4 .6-2.9 2.8.7 4L8 11.2 4.4 13.1l.7-4L2.2 6.3l4-.6L8 2Z" />,
  review: <path d="M3 2.5h7l3 3v8H3v-11ZM9.5 2.5V6H13M5.5 9l1.5 1.5L10.5 7" />,
};

type Rule = { id: string; icon: string; title: string; lead: ReactNode; formula?: ReactNode; example?: ReactNode; notes?: ReactNode[]; words: string };

function rulesFrom(r: Rules): Rule[] {
  const a = r.analytics, t = r.tags, s = r.schedule;
  const exampleScore = Math.round(100 * (a.attendance_weight * 0.8 + a.stability_weight * (1 - 0.43 / a.std_cap)));
  const list: Omit<Rule, "words">[] = [
    {
      id: "rules-participation", icon: "people", title: "Participation",
      lead: <>A student <b>attended</b> a contest when they appear on its leaderboard, whether or not they solved anything.</>,
      formula: <>Attendance rate = contests attended ÷ contests scanned</>,
      notes: [<>Otherwise they're <b>absent</b>, or flagged as having an <b>invalid</b>, <b>missing</b> or <b>duplicate</b> LeetCode handle.</>],
    },
    {
      id: "rules-windows", icon: "calendar", title: "Periods",
      lead: <>Analytics cover the last {a.windows.join(", ")} or all scanned contests, newest first.</>,
      notes: [<>Contests nobody scanned don't count.</>],
    },
    {
      id: "rules-positions", icon: "rank", title: "Ranks",
      lead: <>Three ranks, each answering a different question.</>,
      formula: <>Top % = profile rank ÷ everyone who took part worldwide × 100</>,
      notes: [
        <><b>Profile rank</b>: the rank on the student's LeetCode profile. Until LeetCode publishes it (a few days after the contest) it's worked out from the leaderboard.</>,
        <><b>Leaderboard rank</b>: the position on the global leaderboard, used for links.</>,
        <><b>College rank</b>: the order of the portal's students in that contest, by their contest rank; a tie goes to less total time. Contest pages list students in this order.</>,
      ],
    },
    {
      id: "rules-portal-rank", icon: "medal", title: "Portal rank, medals and colleges",
      lead: <>Students are ranked by LeetCode contest points over the period.</>,
      formula: <>Order: points ↓, then total time ↑, then best rank, then name</>,
      notes: [<>The top {a.medals} get medals. Colleges are compared by how many of their students are in the portal's top {a.top_n}.</>, <>Students with no points aren't ranked.</>],
    },
    {
      id: "rules-consistency", icon: "pulse", title: "Consistency",
      lead: <>How regularly a student takes part, and how steady their results are. Needs at least {a.consistency_min_contests} scanned contests.</>,
      formula: <>Consistency = {pct(a.attendance_weight)} attendance + {pct(a.stability_weight)} stability, where stability = 1 − min(1, std-dev of problems solved ÷ {a.std_cap})</>,
      example: <>8 of 10 contests attended, solving 2, 2, 3, 2, 2, 3, 2, 2 problems (std-dev 0.43): stability = 1 − 0.43 ÷ {a.std_cap} = 0.71, so consistency = <b>{exampleScore}</b>.</>,
      notes: [<>Labels: {a.consistency_labels.map((l) => `${l.label} (${l.from}+)`).join(", ")}.</>],
    },
    {
      id: "rules-trend", icon: "trend", title: "Trend and needs attention",
      lead: <>Whether a student is solving more or fewer problems than before.</>,
      formula: <>Trend = average solved in the last (up to) {a.trend_k} attended contests − average in the {a.trend_k} before</>,
      notes: [<>Beyond ±{a.trend_threshold} it reads <b>improving</b> or <b>declining</b>.</>, <><b>Needs attention</b>: {a.absent_streak_alert} or more absences in a row, or a declining trend.</>],
    },
    {
      id: "rules-questions", icon: "question", title: "Question stats",
      lead: <>Per question, for the students who took part.</>,
      formula: <>Solve rate = students who solved it ÷ students who took part</>,
      notes: [<><b>Solve time</b> runs from the contest's start to the accepted submission, without penalties.</>, <><b>Wrong submissions</b> are only known for problems a student solved; LeetCode doesn't publish them otherwise.</>],
    },
    {
      id: "rules-topics", icon: "tag", title: "Topic stats",
      lead: <>Each question uses one source of tags at a time, so it never counts twice under a topic. LeetCode's <b>official</b> tags always win; until they arrive (usually 1–4 weeks after a contest), <b>provisional</b> tags come from the topics community solutions use.</>,
      formula: <>Provisional: LeetCode topics only, ≥ max({t.min_mentions}, {pct(t.top_share)} of the top topic) mentions, at most {t.max_tags} tags</>,
      notes: [
        <>Too little data (top topic under {t.min_top} mentions, or under {t.min_total} in all): the question is left out until it has enough, or official tags arrive.</>,
        <><b>Appeared</b> = tagged questions in contests attended · <b>solve rate</b> = solved ÷ appeared · <b>accuracy</b> = accepted ÷ (accepted + wrong submissions).</>,
        <><b>Weakest topics</b>: the lowest solve rates among topics seen at least {t.weak_min_appeared} times. Group median times are to the minute.</>,
        <>When official tags arrive they replace the provisional ones and every topic stat is recounted, with no rescan.</>,
      ],
    },
    {
      id: "rules-timing", icon: "clock", title: "When results arrive",
      lead: <>Early results first, final results once LeetCode has settled ranks and rejudges.</>,
      notes: [
        <><b>Early results</b>: {s.scan_delay_minutes} minutes after a contest ends, retried after {s.provisional_retries_minutes.slice(1).join(", ")} more minutes if LeetCode isn't ready.</>,
        ...(s.final_working_days != null ? [<><b>Final results</b>: at {s.final_time} ({s.timezone}) on the {ordinal(s.final_working_days)} working day after the contest.</>] : []),
      ],
    },
    {
      id: "rules-flagged", icon: "review", title: "Flagged by LeetCode",
      lead: <>Students who scored on the early results but whom LeetCode later removed from the final leaderboard, set to 0 points or moved to the bottom (last 2%).</>,
      notes: [
        <>LeetCode does this to entries it finds breaking contest rules, such as copied solutions, but doesn't publish the reason. So NxtRank says "flagged", not "cheated": check before acting.</>,
        <>Spotted by comparing a later scan with the earlier one, so it needs early results first. The contest page lists them with their early and final positions, and the Excel and CSV files get a column for it.</>,
      ],
    },
    {
      id: "rules-ratings", icon: "star", title: "Ratings",
      lead: <>Each student's LeetCode contest rating, from their profile.</>,
      notes: [<>Refreshed every {s.ratings_every_hours} hours and after each final scan. A student's page also checks it live.</>],
    },
    {
      id: "rules-review", icon: "review", title: "Scan review",
      lead: r.review.enabled ? <>Scans asked for from the dashboard wait as a draft until an admin adds them.</> : <>Every scan counts as soon as it finishes.</>,
      notes: r.review.enabled ? [<>Until a draft is added, nothing on the dashboard changes. Unreviewed drafts are discarded after {r.review.draft_days} days. Automatic scans count straight away.</>] : [],
    },
  ];
  return list.map((rule) => ({ ...rule, words: `${rule.title} ${textOf(rule.lead)} ${textOf(rule.formula)} ${textOf(rule.example)} ${(rule.notes ?? []).map(textOf).join(" ")}`.toLowerCase() }));
}

/** Plain text of a JSX fragment, for the search box. */
function textOf(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

/** The Guide: every rule with the numbers the code uses (/api/rules), how data gets
 *  here, and who built it. Every heading has a stable link (#rules-consistency, ...). */
export default function Guide() {
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules, staleTime: Infinity });
  const { hash } = useLocation();
  const [q, setQ] = useState("");
  const all = useMemo(() => (rules.data ? rulesFrom(rules.data) : []), [rules.data]);
  const shown = q.trim() ? all.filter((r) => q.toLowerCase().split(/\s+/).every((w) => r.words.includes(w))) : all;
  const sections = [
    { id: "rules", title: "Rules and definitions", children: shown.map((r) => ({ id: r.id, title: r.title })) },
    { id: "how-it-works", title: "How NxtRank works", children: [] },
    ...(ABOUT_NXTWAVE.length ? [{ id: "about", title: "About NxtWave", children: [] }] : []),
    { id: "credits", title: "Credits and contact", children: [] },
  ];
  const current = useScrollSpy([...sections.flatMap((s) => [s.id, ...s.children.map((c) => c.id)])]);

  useEffect(() => {
    if (!rules.data || !hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [rules.data, hash]);

  if (rules.isPending) return <PageSkeleton />;
  if (rules.isError) return <ErrorBox error={rules.error} onRetry={() => rules.refetch()} />;
  const r = rules.data;

  return (
    <div className="flex flex-col gap-6">
      <header className="guide-hero relative overflow-hidden rounded-2xl px-6 py-7 ring-1 ring-inset ring-fg/[0.07] sm:px-8">
        <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-accent-ink">NxtRank Guide</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">How every number is worked out</h1>
        <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-ink-2">
          The rules behind the dashboard, with the exact thresholds the code uses, so this page is always up to date. Search for a word like "consistency" or "final".
        </p>
        <div className="mt-4 max-w-md">
          <Input type="search" placeholder="Search the rules" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the rules" />
        </div>
      </header>

      <KeyNumbers r={r} />

      <div className="grid items-start gap-6 lg:grid-cols-[232px_minmax(0,1fr)]">
        <nav aria-label="Guide sections" className="guide-toc hidden rounded-2xl bg-surface p-2 ring-1 ring-inset ring-fg/[0.07] lg:sticky lg:top-24 lg:block">
          {sections.map((s) => (
            <div key={s.id}>
              <a href={`#${s.id}`} className={cx("block rounded-lg px-2.5 py-1.5 text-[13px] font-medium", current === s.id ? "bg-accent-soft text-ink" : "text-ink-2 hover:bg-fg/[0.04] hover:text-ink")}>
                {s.title}
              </a>
              {s.children.length > 0 && (
                <ul className="mb-1 ml-3 border-l border-fg/[0.08] pl-1">
                  {s.children.map((c) => (
                    <li key={c.id}>
                      <a
                        href={`#${c.id}`}
                        className={cx("block truncate rounded-md px-2 py-1 text-[12px]", current === c.id ? "font-medium text-accent-ink" : "text-ink-3 hover:text-ink")}
                      >
                        {c.title}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </nav>

        <div className="flex min-w-0 flex-col gap-8">
          <section id="rules" className="scroll-mt-24">
            <SectionTitle>Rules and definitions</SectionTitle>
            {shown.length === 0 ? (
              <Card>
                <Empty>No rules mention "{q}". Try another word.</Empty>
              </Card>
            ) : (
              <div className="grid gap-3">
                {shown.map((rule) => (
                  <RuleCard key={rule.id} rule={rule} />
                ))}
              </div>
            )}
          </section>

          <section id="how-it-works" className="scroll-mt-24">
            <SectionTitle>How NxtRank works</SectionTitle>
            <HowItWorks r={r} />
          </section>

          {ABOUT_NXTWAVE.length > 0 && (
            <section id="about" className="scroll-mt-24">
              <SectionTitle>About NxtWave</SectionTitle>
              <Card>
                <div className="flex flex-col gap-3 px-6 py-5 text-[13px] leading-relaxed text-ink-2">
                  <img src={LOGO_URL} alt="NxtWave" className="h-8 w-fit rounded bg-white px-1.5 py-1" />
                  {ABOUT_NXTWAVE.map((p) => (
                    <p key={p}>{p}</p>
                  ))}
                  <a href="https://www.ccbp.in/" target="_blank" rel="noreferrer" className="w-fit font-medium text-accent-ink hover:underline">
                    NxtWave's website (ccbp.in) ↗
                  </a>
                </div>
              </Card>
            </section>
          )}

          <section id="credits" className="scroll-mt-24">
            <SectionTitle>Credits and contact</SectionTitle>
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-5 text-[13px] text-ink-2">
                <div className="flex flex-col gap-2">
                  <p>
                    NxtRank was built by <b className="text-ink">Rajveer Sharma</b> for NxtWave.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {SOCIAL.map((l) => (
                      <a
                        key={l.href}
                        href={l.href}
                        target="_blank"
                        rel="noreferrer"
                        className="ripple inline-flex items-center gap-2 rounded-lg bg-fg/[0.04] px-3 py-1.5 text-[12px] font-medium text-ink ring-1 ring-inset ring-fg/[0.07] hover:bg-fg/[0.07]"
                      >
                        <svg aria-hidden viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="currentColor">
                          {l.icon}
                        </svg>
                        {l.label}
                      </a>
                    ))}
                  </div>
                  <p>For access, a wrong handle or any data issue, contact one of your NxtRank admins.</p>
                </div>
                <span className="tabular rounded-full bg-fg/[0.05] px-3 py-1 text-xs text-ink-2 ring-1 ring-inset ring-fg/[0.06]">
                  Version {__APP_VERSION__} · {__BUILD_DATE__}
                </span>
              </div>
            </Card>
          </section>
        </div>
      </div>
    </div>
  );
}

/** The id of the section nearest the top of the screen, for the contents menu. */
function useScrollSpy(ids: string[]) {
  const [current, setCurrent] = useState<string | null>(null);
  const key = ids.join(",");
  useEffect(() => {
    const els = key.split(",").map((id) => document.getElementById(id)).filter((e): e is HTMLElement => !!e);
    if (!els.length) return;
    const onScroll = () => {
      let best: string | null = els[0].id;
      for (const el of els) if (el.getBoundingClientRect().top <= 120) best = el.id;
      setCurrent(best);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [key]);
  return current;
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="mb-3 text-lg font-semibold tracking-tight text-ink">{children}</h2>;
}

function RuleCard({ rule }: { rule: Rule }) {
  return (
    <Card>
      <article id={rule.id} className="flex scroll-mt-24 gap-4 px-5 py-4">
        <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-ink">
          <svg viewBox="0 0 16 16" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
            {ICON[rule.icon]}
          </svg>
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-2 text-[13px] leading-relaxed text-ink-2">
          <h3 className="text-[14px] font-semibold text-ink">
            <a href={`#${rule.id}`} className="hover:underline">{rule.title}</a>
          </h3>
          <p>{rule.lead}</p>
          {rule.formula && <div className="rounded-lg bg-fg/[0.035] px-3 py-2 font-mono text-[12px] leading-relaxed text-ink ring-1 ring-inset ring-fg/[0.06]">{rule.formula}</div>}
          {rule.example && (
            <div className="rounded-lg border-l-2 border-accent bg-accent-soft/50 px-3 py-2">
              <span className="mr-1.5 text-[11px] font-semibold uppercase tracking-wide text-accent-ink">Example</span>
              {rule.example}
            </div>
          )}
          {rule.notes && rule.notes.length > 0 && (
            <ul className="flex list-disc flex-col gap-1 pl-4 marker:text-ink-3">
              {rule.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      </article>
    </Card>
  );
}

function KeyNumbers({ r }: { r: Rules }) {
  const s = r.schedule;
  const tiles = [
    { value: `${s.scan_delay_minutes} min`, label: "after a contest: early results" },
    ...(s.final_working_days != null ? [{ value: `${ordinal(s.final_working_days)} day`, label: `working day, ${s.final_time}: final results` }] : []),
    { value: `Top ${r.analytics.medals}`, label: "students get medals" },
    { value: `Top ${r.analytics.top_n}`, label: "decides the college ranking" },
    { value: `${r.analytics.consistency_min_contests}+`, label: "contests for a consistency score" },
    ...(r.review.enabled ? [{ value: `${r.review.draft_days} days`, label: "a scan draft waits for review" }] : []),
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-xl bg-surface px-4 py-3 ring-1 ring-inset ring-fg/[0.07]">
          <div className="tabular text-lg font-semibold tracking-tight text-ink">{t.value}</div>
          <div className="text-[11.5px] leading-snug text-ink-3">{t.label}</div>
        </div>
      ))}
    </div>
  );
}

function HowItWorks({ r }: { r: Rules }) {
  const s = r.schedule;
  const steps: { title: string; body: ReactNode }[] = [
    { title: "Students and handles", body: <>The roster lists every student with their LeetCode handle. NxtRank matches them to LeetCode's public contest leaderboards; nothing is entered by hand.</> },
    { title: "A contest ends", body: <>A small program called the <b>worker</b> notices. A <b>scan</b> is one full read of the contest's leaderboard and takes about 10 minutes.</> },
    { title: "Early results", body: <>{s.scan_delay_minutes} minutes after the contest ends, the first scan runs and the dashboard updates.</> },
    ...(s.final_working_days != null
      ? [{ title: "Final results", body: <>On the {ordinal(s.final_working_days)} working day at {s.final_time}, once LeetCode has settled ranks and rejudges, the contest is scanned again and ratings refresh.</> }]
      : []),
    { title: "Topics fill in", body: <>Every night at {r.tags.nightly_time}, topic tags are refreshed for the last {r.tags.recent_days} days' questions, and for every question on {r.tags.monthly} each month.</> },
  ];
  return (
    <Card>
      <ol className="flex flex-col px-6 py-5">
        {steps.map((step, i) => (
          <li key={step.title} className="relative flex gap-4 pb-5 last:pb-0">
            {i < steps.length - 1 && <span aria-hidden className="absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-px bg-fg/[0.1]" />}
            <span className="tabular grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-ink ring-1 ring-inset ring-accent/20">{i + 1}</span>
            <div className="min-w-0 pt-0.5 text-[13px] leading-relaxed text-ink-2">
              <div className="font-semibold text-ink">{step.title}</div>
              {step.body}
            </div>
          </li>
        ))}
      </ol>
      <p className="border-t border-fg/[0.06] px-6 py-3 text-xs text-ink-3">
        Between {s.worker_awake_window.replace("-", " and ")} ({s.timezone}) the worker checks for work every minute; outside those hours it rests until the next job. Admins can view the
        dashboard as an instructor sees it (read-only, up to {r.review.view_as_minutes} minutes).
      </p>
    </Card>
  );
}
