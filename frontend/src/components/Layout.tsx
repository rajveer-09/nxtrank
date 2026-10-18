/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { NavLink, useLocation } from "react-router-dom";
import type { Me } from "../api";
import { useLogout, useViewAs } from "../auth";
import { useIntentPrefetch } from "../prefetch";
import { useTheme } from "../theme";
import ErrorBoundary from "./ErrorBoundary";
import { PopoverPanel, cx, usePopover } from "./ui";

export const LOGO_URL = "https://d14qv6cm1t62pm.cloudfront.net/ccbp-website/Nxtwave_Colored.svg";

type Rect = { left: number; width: number };

const rectOf = (el: HTMLElement | null | undefined): Rect | null =>
  el ? { left: el.offsetLeft, width: el.offsetWidth } : null;

/** NxtWave logo + product name. The logo's navy lettering sits on a white tile in dark mode. */
export function Brand({ size = "md" }: { size?: "md" | "lg" }) {
  // the NxtWave logo comes from their CDN; if it can't load, show the app's own mark (bundled)
  const [failed, setFailed] = useState(false);
  return (
    <span className="flex items-center gap-2.5">
      {failed ? (
        <img src="/favicon.svg" alt="NxtRank" className={size === "lg" ? "h-9 w-9" : "h-7 w-7"} />
      ) : (
        <span className={cx("logo-tile flex items-center rounded-md", size === "lg" ? "px-2 py-1.5" : "px-1.5 py-1")}>
          <img src={LOGO_URL} alt="NxtWave" onError={() => setFailed(true)} className={size === "lg" ? "h-8 w-auto" : "h-6 w-auto"} />
        </span>
      )}
      <span className={cx("font-semibold tracking-tight text-ink", size === "lg" ? "text-lg" : "hidden text-base sm:inline")}>
        NxtRank
      </span>
    </span>
  );
}

/** An anime-style face (DiceBear "lorelei", drawn in the browser from the login, so each
 *  person always gets the same one); initials if it can't be drawn. */
function Avatar({ seed, initials, className }: { seed: string; initials: string; className?: string }) {
  const [uri, setUri] = useState<string | null>(null);
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    let alive = true;
    import("./avatar")
      .then((m) => alive && setUri(m.animeAvatar(seed)))
      .catch(() => alive && setBroken(true));
    return () => {
      alive = false;
    };
  }, [seed]);
  if (!uri || broken)
    return <span className={cx("avatar grid place-items-center rounded-full font-semibold tracking-wide text-white", className)}>{initials}</span>;
  return <img src={uri} alt="" onError={() => setBroken(true)} className={cx("avatar-img rounded-full object-cover", className)} />;
}

export function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const dark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      className="ripple relative grid h-8 w-8 place-items-center rounded-md text-ink-2 hover:bg-fg/5 hover:text-ink"
    >
      {/* shows the mode you switch to: sun in dark mode, moon in light mode; they rotate into each other */}
      <svg aria-hidden viewBox="0 0 16 16" className={cx("theme-icon absolute h-4 w-4", dark ? "opacity-100" : "-rotate-90 scale-50 opacity-0")}>
        <circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <svg aria-hidden viewBox="0 0 16 16" className={cx("theme-icon absolute h-4 w-4", dark ? "rotate-90 scale-50 opacity-0" : "opacity-100")}>
        <path d="M13.5 9.6A5.5 5.5 0 0 1 6.4 2.5a5.5 5.5 0 1 0 7.1 7.1Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

function displayName(username: string) {
  const local = username.replace(/@.*/, "");
  return local
    .split(/[._\-\s]+/)
    .filter(Boolean)
    .map((w) => w[0]!.toUpperCase() + w.slice(1))
    .join(" ");
}

function UserMenu({ me }: { me: Me }) {
  const { logout, leaving } = useLogout();
  const pop = usePopover<HTMLButtonElement>();
  const name = me.name || displayName(me.username) || me.username;
  const initials =
    name
      .split(" ")
      .slice(0, 2)
      .map((w) => w[0])
      .join("") || "?";
  const isEmail = me.username.includes("@");
  return (
    <>
      <button
        ref={pop.anchorRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={pop.open}
        onClick={() => pop.setOpen(!pop.open)}
        className={cx("avatar-trigger ripple rounded-full", pop.open && "is-open")}
        title={me.username}
      >
        <Avatar seed={me.username} initials={initials} className="h-8 w-8 text-[11px]" />
        <span className="sr-only">Account menu for {me.username}</span>
      </button>
      {pop.open && (
        <PopoverPanel pop={pop} className="w-72 p-0!">
          <div role="menu" aria-label="Account" className="overflow-hidden rounded-[inherit]">
            <div className="profile-head flex items-center gap-3 px-4 pb-3.5 pt-4">
              <Avatar seed={me.username} initials={initials} className="h-11 w-11 shrink-0 text-sm" />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-ink">{name}</div>
                {isEmail && <div className="truncate text-xs text-ink-3">{me.username}</div>}
                <span className="mt-1.5 inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-ink">
                  <svg aria-hidden viewBox="0 0 12 12" className="h-2.5 w-2.5">
                    {me.role === "admin" ? (
                      <path d="M6 1 10 2.6v3c0 2.4-1.7 4.3-4 5.4C3.7 9.9 2 8 2 5.6v-3L6 1Z" fill="currentColor" />
                    ) : me.role === "instructor" ? (
                      <path d="M6 1.5 11 4 6 6.5 1 4l5-2.5ZM3 5.3v2.4C3 8.9 4.3 10 6 10s3-1.1 3-2.3V5.3L6 6.8 3 5.3Z" fill="currentColor" />
                    ) : (
                      <path d="M1.5 6S3.3 2.5 6 2.5 10.5 6 10.5 6 8.7 9.5 6 9.5 1.5 6 1.5 6Z M6 7.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" fill="currentColor" fillRule="evenodd" />
                    )}
                  </svg>
                  {me.is_super ? "Super admin" : me.role === "admin" ? "Administrator" : me.role === "instructor" ? "Instructor" : "Viewer"}
                </span>
              </div>
            </div>
            <div className="border-t border-fg/[0.06] p-1.5">
              <button
                role="menuitem"
                type="button"
                onClick={logout}
                disabled={leaving}
                className="group flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[13px] text-ink-2 hover:bg-critical/10 hover:text-critical-ink"
              >
                <svg aria-hidden viewBox="0 0 16 16" className="h-3.5 w-3.5">
                  <path d="M6 2.5H3.5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1H6M10.5 11 13.5 8l-3-3M13.5 8H6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {leaving ? "Signing out…" : "Log out"}
              </button>
            </div>
            <div className="border-t border-fg/[0.06] bg-fg/[0.02] px-4 py-2 text-[11px] text-ink-3">NxtRank by NxtWave</div>
          </div>
        </PopoverPanel>
      )}
    </>
  );
}

const NAV_ICONS: Record<string, ReactNode> = {
  "/": <path d="M5 2.5h6v3.5a3 3 0 0 1-6 0V2.5ZM5 4H2.5v1A2.5 2.5 0 0 0 5 7.5M11 4h2.5v1A2.5 2.5 0 0 1 11 7.5M8 9v2.5M5.5 13.5h5M6.5 11.5h3v2h-3z" />,
  "/analytics": <path d="M2.5 13.5h11M4.5 11V8M8 11V4.5M11.5 11V6.5" />,
  "/students": <path d="M6 7.5a2.25 2.25 0 1 0 0-4.5 2.25 2.25 0 0 0 0 4.5ZM2 13c.3-2.2 1.9-3.5 4-3.5s3.7 1.3 4 3.5M10.5 3.2a2.25 2.25 0 0 1 0 4.1M12 9.8c1.1.5 1.8 1.6 2 3.2" />,
  "/my-students": <path d="M7 7.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM2.5 13.5c.4-2.4 2.2-4 4.5-4 1 0 1.9.3 2.6.8M10 12l1.5 1.5L14 11" />,
  "/admin": <path d="M8 1.75 13.5 4v3.6c0 3.1-2.3 5.6-5.5 6.65C4.8 13.2 2.5 10.7 2.5 7.6V4L8 1.75ZM5.75 8l1.6 1.6L10.5 6.5" />,
  "/guide": <path d="M2.5 3.5c1.8-.6 3.7-.4 5.5.7 1.8-1.1 3.7-1.3 5.5-.7v9c-1.8-.6-3.7-.4-5.5.7-1.8-1.1-3.7-1.3-5.5-.7v-9ZM8 4.2v9" />,
};

/** Phones: the main sections as a tab bar at the bottom, within thumb reach. */
function BottomNav({ links, onSame }: { links: { to: string; label: string; end: boolean }[]; onSame: () => void }) {
  // in <body>: the app's entrance animation leaves a transform on the wrapper, which
  // would pin a fixed element to the page instead of the screen
  return createPortal(
    <nav aria-label="Main" className="bottom-nav fixed inset-x-0 bottom-0 z-30 border-t border-fg/[0.08] pb-[env(safe-area-inset-bottom)] md:hidden">
      <ul className="mx-auto grid max-w-lg" style={{ gridTemplateColumns: `repeat(${links.length}, minmax(0, 1fr))` }}>
        {links.map((l) => (
          <li key={l.to}>
            <NavLink
              to={l.to}
              end={l.end}
              onClick={onSame}
              className={({ isActive }) =>
                cx("flex h-14 flex-col items-center justify-center gap-1 text-[11px] font-medium", isActive ? "text-accent-ink" : "text-ink-2 active:text-ink")
              }
            >
              {({ isActive }) => (
                <>
                  <span className={cx("grid h-7 w-12 place-items-center rounded-full transition-colors", isActive && "bg-accent-soft")}>
                    <svg aria-hidden viewBox="0 0 16 16" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                      {NAV_ICONS[l.to]}
                    </svg>
                  </span>
                  <span className="max-w-full truncate px-0.5">{l.label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>,
    document.body,
  );
}

/** On every page while an admin views the dashboard as an instructor. */
function ViewingAsBanner({ me }: { me: Me }) {
  const { stop, pending } = useViewAs();
  const until = me.viewing_as ? new Date(me.viewing_as.until).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  return (
    <div role="status" className="border-b border-accent/25 bg-accent-soft px-4 py-2 text-center text-[13px] text-ink">
      You're viewing as <span className="font-semibold">{me.name || me.username}</span> (instructor), read-only until {until} ·{" "}
      <button type="button" onClick={() => stop()} disabled={pending} className="font-semibold text-accent-ink underline-offset-2 hover:underline disabled:opacity-60">
        {pending ? "Returning…" : "Return to admin"}
      </button>
    </div>
  );
}

/** navigator.onLine, kept up to date. */
function useOnline() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  return online;
}

export default function Layout({ me, children }: { me: Me; children: ReactNode }) {
  const { pathname } = useLocation();
  useIntentPrefetch(me.role); // any link about to be opened: its page's code and data
  const online = useOnline();
  const links = [
    ...(me.role === "instructor" ? [{ to: "/my-students", label: "My students", end: false }] : []),
    { to: "/", label: "Contests", end: true },
    { to: "/analytics", label: "Analytics", end: false },
    { to: "/students", label: "Students", end: false },
    ...(me.role === "admin" ? [{ to: "/admin", label: "Admin", end: false }] : []),
    { to: "/guide", label: "Guide", end: false },
  ];

  // A highlight that slides to the active tab, and a hover highlight that glides
  // between tabs, instead of backgrounds snapping on and off.
  const navRef = useRef<HTMLElement>(null);
  const [active, setActive] = useState<Rect | null>(null);
  const [hover, setHover] = useState<Rect | null>(null);
  const [animate, setAnimate] = useState(false); // no slide on first paint

  const measure = useCallback(() => {
    setActive(rectOf(navRef.current?.querySelector<HTMLElement>('a[aria-current="page"]')));
  }, []);

  useLayoutEffect(measure, [pathname, measure]);

  // A new page opens at the top; clicking the tab you're on (or the logo) scrolls back up.
  useLayoutEffect(() => {
    window.scrollTo({ top: 0 }); // block body: scrollTo may return a Promise, which React would treat as a cleanup
  }, [pathname]);
  const toTop = () => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
  };

  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const ro = new ResizeObserver(measure);
    ro.observe(nav);
    document.fonts?.ready.then(measure); // tab widths change once Inter loads
    const id = requestAnimationFrame(() => setAnimate(true));
    return () => {
      ro.disconnect();
      cancelAnimationFrame(id);
    };
  }, [measure]);

  const pill = "pointer-events-none absolute inset-y-0 left-0 my-auto h-8 rounded-md";
  const motion = animate ? "nav-pill-motion" : "";

  return (
    <div className="app-enter min-h-screen">
      {/* keyboard users: jump past the navigation */}
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-[13px] focus:font-medium focus:text-ink focus:shadow-[var(--shadow-pop)]">
        Skip to content
      </a>
      <header className="app-header sticky top-0 z-30">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6 md:grid md:grid-cols-[1fr_auto_1fr] md:gap-6">
          <NavLink to="/" onClick={toTop} aria-label="NxtRank home" className="ripple -ml-1 shrink-0 justify-self-start rounded-md p-1">
            <Brand />
          </NavLink>
          <nav
            ref={navRef}
            aria-label="Main"
            className="nav-track relative hidden min-w-0 items-center gap-2 overflow-x-auto rounded-[10px] p-1 md:flex md:justify-self-center"
            onMouseLeave={() => setHover(null)}
          >
            <span
              aria-hidden
              className={cx(pill, motion, "bg-fg/[0.04]", hover ? "opacity-100" : "opacity-0")}
              style={hover ? { transform: `translateX(${hover.left}px)`, width: hover.width } : { width: active?.width ?? 0, transform: `translateX(${active?.left ?? 0}px)` }}
            />
            <span
              aria-hidden
              className={cx(pill, motion, "nav-active-pill", active ? "opacity-100" : "opacity-0")}
              style={{ transform: `translateX(${active?.left ?? 0}px)`, width: active?.width ?? 0 }}
            />
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                onClick={toTop}
                onMouseEnter={(e) => setHover(rectOf(e.currentTarget))}
                onFocus={(e) => setHover(rectOf(e.currentTarget))}
                onBlur={() => setHover(null)}
                className={({ isActive }) =>
                  cx(
                    "ripple relative z-10 shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] font-medium sm:px-5",
                    isActive ? "text-ink" : "text-ink-2 hover:text-ink",
                  )
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex shrink-0 items-center gap-3 md:justify-self-end">
            <ThemeToggle />
            <UserMenu me={me} />
          </div>
        </div>
      </header>
      {me.viewing_as && <ViewingAsBanner me={me} />}
      {!online && (
        <div role="status" className="border-b border-warning/30 bg-warning/10 px-4 py-2 text-center text-[13px] text-warning-ink">
          You're offline. What's on screen may be out of date; it refreshes once you're back online.
        </div>
      )}
      <main id="main" tabIndex={-1} key={pathname.split("/")[1]} className="page-enter outline-none mx-auto max-w-7xl px-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-6 sm:px-6 sm:pt-8 md:pb-8">
        <ErrorBoundary key={pathname}>{children}</ErrorBoundary>
      </main>
      <BottomNav links={links} onSame={toTop} />
    </div>
  );
}
