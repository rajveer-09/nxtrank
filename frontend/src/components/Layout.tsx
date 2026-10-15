/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import type { Me } from "../api";
import { useLogout } from "../auth";
import { useIntentPrefetch } from "../prefetch";
import { useTheme } from "../theme";
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

export default function Layout({ me, children }: { me: Me; children: ReactNode }) {
  const { pathname } = useLocation();
  useIntentPrefetch(me.role); // any link about to be opened: its page's code and data
  const links = [
    ...(me.role === "instructor" ? [{ to: "/my-students", label: "My students", end: false }] : []),
    { to: "/", label: "Contests", end: true },
    { to: "/analytics", label: "Analytics", end: false },
    { to: "/students", label: "Students", end: false },
    ...(me.role === "admin" ? [{ to: "/admin", label: "Admin", end: false }] : []),
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
      <header className="app-header sticky top-0 z-30">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6 md:grid md:grid-cols-[1fr_auto_1fr] md:gap-6">
          <NavLink to="/" onClick={toTop} aria-label="NxtRank home" className="ripple -ml-1 shrink-0 justify-self-start rounded-md p-1">
            <Brand />
          </NavLink>
          <nav
            ref={navRef}
            className="nav-track relative flex min-w-0 items-center gap-2 overflow-x-auto rounded-[10px] p-1 md:justify-self-center"
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
      <main key={pathname.split("/")[1]} className="page-enter mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    </div>
  );
}
