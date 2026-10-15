/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { ApiError, api } from "../api";
import { takeSignOutReason, type SignOutReason } from "../auth";
import { Brand, ThemeToggle } from "../components/Layout";
import { Button, ContestStateBadge, Medal, cx } from "../components/ui";

const LAST_LOGIN = "nxt.lastLogin"; // remembered on this browser only, for convenience

function remembered(): string {
  try {
    return localStorage.getItem(LAST_LOGIN) ?? "";
  } catch {
    return "";
  }
}

function remember(username: string) {
  try {
    localStorage.setItem(LAST_LOGIN, username);
  } catch {
    /* private mode: fine */
  }
}

function friendly(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "That email and password don't match. Check them and try again.";
    if (err.status === 429) return "Too many attempts. For your security, wait 15 minutes before trying again.";
    if (err.status >= 500) return "The server ran into a problem. Try again in a moment.";
    return err.message;
  }
  return "Can't reach the server. Check your connection and try again.";
}

const NOTICE: Record<SignOutReason, string> = {
  signed_out: "You've signed out.",
  expired: "Your session expired. Sign in again to pick up where you left off.",
};

type Phase = "idle" | "busy" | "success";

export default function Login() {
  return (
    <div className="login-shell grid min-h-screen lg:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)]">
      <Showcase />
      <main className="relative flex min-h-screen flex-col items-center justify-center px-6 py-12 sm:px-10">
        <div className="absolute right-4 top-4 z-10">
          <ThemeToggle />
        </div>
        <SignInForm />
        <p className="login-foot absolute inset-x-0 bottom-5 text-center text-[11px] text-ink-3">© NxtWave · NxtRank</p>
      </main>
    </div>
  );
}

// ---- the form ------------------------------------------------------------------------------

function SignInForm() {
  const qc = useQueryClient();
  const [notice] = useState(() => takeSignOutReason());
  const [username, setUsername] = useState(remembered);
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bad, setBad] = useState<{ user: boolean; pass: boolean }>({ user: false, pass: false }); // fields to highlight
  const [phase, setPhase] = useState<Phase>("idle");
  const [shake, setShake] = useState(0);
  const userRef = useRef<HTMLInputElement>(null);
  const passRef = useRef<HTMLInputElement>(null);

  // returning user: their email is filled in, so start in the password box
  useEffect(() => {
    (username ? passRef : userRef).current?.focus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (phase !== "idle") return;
    if (!username.trim() || !password) {
      setBad({ user: !username.trim(), pass: !password });
      setError(!username.trim() && !password ? "Enter your email and password." : !username.trim() ? "Enter your email." : "Enter your password.");
      setShake((n) => n + 1);
      window.setTimeout(() => (!username.trim() ? userRef : passRef).current?.focus(), 50);
      return;
    }
    setPhase("busy");
    setError(null);
    setBad({ user: false, pass: false });
    try {
      const me = await api.login(username.trim(), password);
      remember(username.trim());
      setPhase("success");
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      // let the "Signed in" tick and the exit play, then show the dashboard
      window.setTimeout(() => qc.setQueryData(["me"], me), reduce ? 0 : 520);
    } catch (err) {
      setPhase("idle");
      setError(friendly(err));
      setBad({ user: false, pass: err instanceof ApiError && err.status === 401 });
      setShake((n) => n + 1);
      if (err instanceof ApiError && err.status === 401) {
        window.setTimeout(() => {
          passRef.current?.focus();
          passRef.current?.select();
        }, 50);
      }
    }
  }

  const capsCheck = (e: KeyboardEvent<HTMLInputElement>) => setCaps(e.getModifierState?.("CapsLock") ?? false);
  const busy = phase !== "idle";

  return (
    <div className={cx("w-full max-w-[380px]", phase === "success" && "login-exit")}>
      <div className="mb-8 lg:hidden">
        <Brand size="lg" />
      </div>
      <div className="rise">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Sign in</h1>
        <p className="mt-1.5 text-sm text-ink-2">Welcome back. Use the email your admin set up for you.</p>
      </div>

      {notice && !error && (
        <div
          role="status"
          className={cx(
            "notice mt-6 flex items-start gap-2 rounded-lg px-3 py-2.5 text-[13px] ring-1 ring-inset",
            notice === "expired" ? "bg-warning/10 text-warning-ink ring-warning/25" : "bg-good/10 text-good-ink ring-good/25",
          )}
        >
          <svg aria-hidden viewBox="0 0 16 16" className="mt-0.5 h-3.5 w-3.5 shrink-0">
            {notice === "expired" ? (
              <path d="M8 4.5V8l2 1.5M14 8A6 6 0 1 1 2 8a6 6 0 0 1 12 0Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            ) : (
              <path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            )}
          </svg>
          {NOTICE[notice]}
        </div>
      )}

      <form key={shake} onSubmit={submit} noValidate aria-busy={busy} className={cx("mt-7 flex flex-col gap-5", shake ? "shake" : "rise rise-2")}>
        <Field label="Email" invalid={bad.user} icon={<path d="M2.5 4.5h11v7h-11zM2.5 4.5 8 9l5.5-4.5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />}>
          <input
            ref={userRef}
            autoComplete="username"
            inputMode="email"
            spellCheck={false}
            autoCapitalize="none"
            placeholder="you@nxtwave.co.in"
            value={username}
            onChange={(e) => {
              setUsername(e.target.value);
              setBad((b) => ({ ...b, user: false }));
            }}
            required
            disabled={busy}
            className="login-input"
          />
        </Field>

        <Field
          label="Password"
          aside={caps ? <span className="text-[11px] font-medium text-warning-ink">Caps Lock is on</span> : null}
          icon={<path d="M4.5 7V5.5a3.5 3.5 0 0 1 7 0V7M3.5 7h9v6.5h-9z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />}
          trailing={
            <button
              type="button"
              onClick={() => {
                setShow((s) => !s);
                passRef.current?.focus();
              }}
              aria-label={show ? "Hide password" : "Show password"}
              aria-pressed={show}
              title={show ? "Hide password" : "Show password"}
              className="grid h-full w-11 place-items-center rounded-r-lg text-ink-3 transition-colors hover:text-ink"
            >
              <svg aria-hidden viewBox="0 0 16 16" className="h-4 w-4">
                <path d="M1.5 8S3.8 3.5 8 3.5 14.5 8 14.5 8 12.2 12.5 8 12.5 1.5 8 1.5 8Z M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
                {show && <path d="M2.5 2.5l11 11" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />}
              </svg>
            </button>
          }
          invalid={bad.pass}
        >
          <input
            ref={passRef}
            type={show ? "text" : "password"}
            autoComplete="current-password"
            placeholder="Your password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setBad((b) => ({ ...b, pass: false }));
            }}
            onKeyDown={capsCheck}
            onKeyUp={capsCheck}
            required
            disabled={busy}
            aria-invalid={bad.pass || undefined}
            className="login-input pr-11"
          />
        </Field>

        {error && (
          <div role="alert" className="flex items-start gap-2 rounded-lg bg-critical/10 px-3 py-2.5 text-[13px] text-critical-ink ring-1 ring-inset ring-critical/25">
            <svg aria-hidden viewBox="0 0 16 16" className="mt-0.5 h-3.5 w-3.5 shrink-0">
              <path d="M8 5v3.5M8 11h.01M14 8A6 6 0 1 1 2 8a6 6 0 0 1 12 0Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            {error}
          </div>
        )}

        <Button variant="primary" type="submit" disabled={busy} className="login-submit group mt-1 h-11 w-full text-sm">
          {phase === "busy" ? (
            <>
              <span aria-hidden className="btn-spinner" /> Signing in…
            </>
          ) : phase === "success" ? (
            <>
              <svg aria-hidden viewBox="0 0 16 16" className="h-4 w-4">
                <path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="tick-draw" />
              </svg>
              Signed in
            </>
          ) : (
            <>
              Sign in
              <svg aria-hidden viewBox="0 0 16 16" className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5">
                <path d="M3 8h10M9 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </>
          )}
        </Button>
      </form>

      <p className="rise rise-3 mt-6 text-[12px] leading-relaxed text-ink-3">
        Forgot your password, or don't have a login yet? Ask an admin: they can add you or reset it in a minute.
      </p>
    </div>
  );
}

function Field({ label, icon, aside, trailing, invalid, children }: { label: string; icon: ReactNode; aside?: ReactNode; trailing?: ReactNode; invalid?: boolean; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-2">
      <span className="flex items-baseline justify-between">
        <span className="text-[13px] font-medium text-ink">{label}</span>
        {aside}
      </span>
      <span className={cx("login-field relative flex h-11 items-center", invalid && "is-invalid")}>
        <svg aria-hidden viewBox="0 0 16 16" className="pointer-events-none absolute left-3.5 h-4 w-4 text-ink-3">
          {icon}
        </svg>
        {children}
        {trailing && <span className="absolute inset-y-0 right-0">{trailing}</span>}
      </span>
    </label>
  );
}

// ---- the showcase (large screens) -------------------------------------------------------------

const FEATURES: { title: string; text: string; icon: ReactNode }[] = [
  {
    title: "Results 30 minutes after every contest",
    text: "Early results the same day; final results every Friday night (by about 11:10 pm), once LeetCode settles the ranks.",
    icon: <path d="M8 4.5V8l2.5 1.5M14 8A6 6 0 1 1 2 8a6 6 0 0 1 12 0Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />,
  },
  {
    title: "Every student, every question",
    text: "Solve times, wrong attempts, consistency and rating, student by student.",
    icon: <path d="M2.5 13.5V9M6.2 13.5V5M9.8 13.5V7.5M13.5 13.5V3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />,
  },
  {
    title: "Toppers and college rankings",
    text: "See who leads the portal, each college and each instructor's group.",
    icon: <path d="M5 2.5h6v3.5a3 3 0 0 1-6 0V2.5ZM5 3.5H3a2 2 0 0 0 2 2.5M11 3.5h2a2 2 0 0 1-2 2.5M8 9v2.5M5.5 13.5h5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />,
  },
];

const SAMPLE = [
  { name: "Diya Varma", college: "Alpha Institute", solved: "4/4", rank: "3" },
  { name: "Meera Reddy", college: "Gamma University", solved: "4/4", rank: "10" },
  { name: "Tanvi Sharma", college: "Alpha Institute", solved: "3/4", rank: "249" },
];

function Showcase() {
  return (
    <aside className="login-showcase relative hidden flex-col overflow-hidden px-12 py-10 lg:flex xl:px-16">
      <div className="relative z-10">
        <Brand size="lg" />
      </div>

      <div className="relative z-10 mt-auto max-w-lg pt-14">
        <h2 className="rise text-[34px] font-semibold leading-[1.15] tracking-tight text-ink xl:text-[38px]">
          Every student's LeetCode contest,
          <span className="text-ink-2"> ranked and explained.</span>
        </h2>
        <ul className="mt-8 flex flex-col gap-5">
          {FEATURES.map((f, i) => (
            <li key={f.title} className="rise flex gap-3.5" style={{ animationDelay: `${120 + i * 80}ms` }}>
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-fg/[0.05] text-accent-ink ring-1 ring-inset ring-fg/[0.08]">
                <svg aria-hidden viewBox="0 0 16 16" className="h-4 w-4">
                  {f.icon}
                </svg>
              </span>
              <span>
                <span className="block text-sm font-medium text-ink">{f.title}</span>
                <span className="mt-0.5 block text-[13px] leading-snug text-ink-2">{f.text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* a glimpse of the product, in the app's own components */}
      <div className="relative z-10 mt-12 mb-auto" aria-hidden>
        <div className="preview-card float-in relative max-w-md rounded-xl bg-surface p-4 shadow-pop ring-1 ring-inset ring-fg/[0.08]">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[13px] font-semibold text-ink">Weekly Contest 523</div>
              <div className="text-[11px] text-ink-3">66 of 67 students took part</div>
            </div>
            <ContestStateBadge state="final" />
          </div>
          <ol className="mt-3 divide-y divide-fg/[0.06]">
            {SAMPLE.map((s, i) => (
              <li key={s.name} className="flex items-center gap-3 py-2">
                <Medal place={i + 1} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-ink">{s.name}</span>
                  <span className="block truncate text-[11px] text-ink-3">{s.college}</span>
                </span>
                <span className="tabular text-xs text-ink-2">{s.solved}</span>
                <span className="tabular w-12 text-right text-xs text-ink-3">#{s.rank}</span>
              </li>
            ))}
          </ol>
        </div>
        <div className="preview-card float-in float-in-2 absolute -bottom-10 left-[58%] w-56 rounded-xl bg-surface p-3.5 shadow-pop ring-1 ring-inset ring-fg/[0.08] xl:left-[62%]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">LeetCode rating</span>
            <span className="rounded-full bg-good/12 px-1.5 py-px text-[10px] font-semibold text-good-ink">+124</span>
          </div>
          <div className="tabular mt-1 text-lg font-semibold text-ink">1,883</div>
          <svg viewBox="0 0 200 44" className="mt-1 h-11 w-full">
            <defs>
              <linearGradient id="spark" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor="var(--accent)" stopOpacity="0.28" />
                <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M0 36 L25 33 L50 35 L75 27 L100 29 L125 20 L150 22 L175 12 L200 8 L200 44 L0 44 Z" fill="url(#spark)" />
            <path d="M0 36 L25 33 L50 35 L75 27 L100 29 L125 20 L150 22 L175 12 L200 8" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" className="spark-draw" />
          </svg>
        </div>
      </div>

      <p className="relative z-10 mt-16 text-[11px] text-ink-3">Built for NxtWave instructors and admins.</p>
    </aside>
  );
}
