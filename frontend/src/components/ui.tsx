/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import {
  Children,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ChangeEvent,
  type InputHTMLAttributes,
  type Ref,
  type TextareaHTMLAttributes,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { ApiError, type ContestState, type HandleStatus, type ResultStatus } from "../api";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx("overflow-hidden rounded-lg bg-surface shadow-card ring-1 ring-inset ring-(--card-ring)", className)}>{children}</section>;
}

export function CardHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-3 pt-4">
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold tracking-tight text-ink">{title}</h2>
        {subtitle && <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-ink-3">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const buttonBase =
  "ripple inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md font-medium select-none " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent " +
  "transition-[color,background-color,border-color,box-shadow,transform,opacity] duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)] " +
  "active:scale-[0.97] active:duration-75 " +
  "disabled:pointer-events-none disabled:opacity-45";

const buttonVariant = {
  primary: "bg-btn-primary text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.18),0_1px_2px_rgb(0_0_0/0.4)] hover:bg-btn-primary-hover active:bg-btn-primary-hover",
  secondary: "border border-border bg-(--btn-bg) text-ink shadow-(--btn-shadow) hover:border-border-strong hover:bg-(--btn-bg-hover)",
  ghost: "text-ink-2 hover:bg-fg/5 hover:text-ink",
};

const buttonSize = {
  sm: "h-7 px-2.5 text-xs pointer-coarse:h-10 pointer-coarse:px-3.5", // touch screens: a 40px target
  md: "h-8 px-3 text-[13px] pointer-coarse:h-10",
  lg: "h-9 px-4 text-[13px]",
};

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof buttonVariant;
  size?: keyof typeof buttonSize;
};

export function Button({ variant = "secondary", size = "md", className, ...props }: ButtonProps) {
  return <button {...props} className={cx(buttonBase, buttonSize[size], buttonVariant[variant], className)} />;
}

export function LinkButton({ href, children, download }: { href: string; children: ReactNode; download?: boolean }) {
  return (
    <a href={href} download={download} className={cx(buttonBase, buttonSize.md, buttonVariant.secondary)}>
      {children}
    </a>
  );
}

const fieldClass =
  "h-8 rounded-md border border-border bg-field px-2.5 text-[13px] text-ink shadow-(--field-shadow) placeholder:text-ink-3 " +
  "hover:border-border-strong focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/20";

export function Input(props: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return <input {...props} className={cx(fieldClass, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(fieldClass, "h-auto py-1.5 leading-relaxed", props.className)} />;
}

// ---- popovers & select ------------------------------------------------------------

type PopoverPos = { top: number; left: number; minWidth: number; placement: "bottom" | "top" };

/** A floating panel anchored to an element. Rendered in a portal (cards clip overflow),
 *  placed below the anchor or above it when there's no room; closes on outside click and
 *  Escape, and follows scroll/resize. */
export function usePopover<A extends HTMLElement>() {
  const anchorRef = useRef<A>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<PopoverPos | null>(null);

  const place = useCallback(() => {
    const a = anchorRef.current;
    const panel = panelRef.current;
    if (!a || !panel) return;
    const r = a.getBoundingClientRect();
    const h = panel.offsetHeight;
    const w = Math.max(r.width, panel.offsetWidth);
    const placement = window.innerHeight - r.bottom < h + 12 && r.top > h + 12 ? "top" : "bottom";
    setPos({
      top: placement === "bottom" ? r.bottom + 6 : r.top - h - 6,
      left: Math.max(8, Math.min(r.left, window.innerWidth - w - 8)),
      minWidth: r.width,
      placement,
    });
  }, []);

  useLayoutEffect(() => {
    if (open) place();
    else setPos(null);
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!anchorRef.current?.contains(t) && !panelRef.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, place]);

  return { anchorRef, panelRef, open, setOpen, pos };
}

type Popover = { panelRef: React.RefObject<HTMLDivElement | null>; pos: PopoverPos | null };

export function PopoverPanel({ pop, className, children }: { pop: Popover; className?: string; children: ReactNode }) {
  return createPortal(
    <div
      ref={pop.panelRef}
      data-placement={pop.pos?.placement ?? "bottom"}
      className={cx("popover fixed z-50 rounded-lg border border-border bg-popover p-1 shadow-pop", className)}
      style={{ top: pop.pos?.top ?? -9999, left: pop.pos?.left ?? -9999, minWidth: pop.pos?.minWidth, visibility: pop.pos ? "visible" : "hidden" }}
    >
      {children}
    </div>,
    document.body,
  );
}

type Opt = { value: string; label: ReactNode; text: string; disabled?: boolean };

const textOf = (n: ReactNode): string =>
  typeof n === "string" || typeof n === "number" ? String(n) : Array.isArray(n) ? n.map(textOf).join("") : "";

function optionsOf(children: ReactNode): Opt[] {
  return Children.toArray(children)
    .filter((c): c is ReactElement<{ value?: string | number; children?: ReactNode; disabled?: boolean }> => isValidElement(c) && c.type === "option")
    .map(({ props }) => ({
      value: String(props.value ?? textOf(props.children)),
      label: props.children,
      text: textOf(props.children).toLowerCase(),
      disabled: props.disabled,
    }));
}

type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "onChange"> & {
  label: string;
  hideLabel?: boolean;
  onChange?: (e: ChangeEvent<HTMLSelectElement>) => void;
};

/** Drop-in for <select> (same <option> children and onChange event shape) with a styled,
 *  animated list. Keyboard: arrows, Home/End, Enter/Space, Escape, type-to-jump. */
export function Select({ label, hideLabel, className, children, value, onChange, disabled }: SelectProps) {
  const opts = optionsOf(children);
  const uid = useId();
  const labelId = `${uid}-label`;
  const listId = `${uid}-list`;
  const optId = (i: number) => `${uid}-opt-${i}`;
  const pop = usePopover<HTMLButtonElement>();
  const selected = Math.max(0, opts.findIndex((o) => o.value === String(value ?? "")));
  const [active, setActive] = useState(selected);
  const typed = useRef({ text: "", at: 0 });

  useEffect(() => {
    if (pop.open) document.getElementById(optId(active))?.scrollIntoView({ block: "nearest" });
  }, [active, pop.open]); // eslint-disable-line react-hooks/exhaustive-deps

  const openList = () => {
    setActive(selected);
    pop.setOpen(true);
  };
  const choose = (i: number) => {
    const o = opts[i];
    if (!o || o.disabled) return;
    pop.setOpen(false);
    if (o.value !== String(value ?? ""))
      onChange?.({ target: { value: o.value }, currentTarget: { value: o.value } } as unknown as ChangeEvent<HTMLSelectElement>);
  };
  const move = (d: number) =>
    setActive((a) => {
      let i = a;
      for (let k = 0; k < opts.length; k++) {
        i = (i + d + opts.length) % opts.length;
        if (!opts[i].disabled) return i;
      }
      return a;
    });

  function onKey(e: KeyboardEvent<HTMLButtonElement>) {
    if (!pop.open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        openList();
      }
      return;
    }
    if (e.key === "Tab") return pop.setOpen(false);
    if (e.key === "ArrowDown") move(1);
    else if (e.key === "ArrowUp") move(-1);
    else if (e.key === "Home") setActive(0);
    else if (e.key === "End") setActive(opts.length - 1);
    else if (e.key === "Enter" || e.key === " ") choose(active);
    else if (e.key.length === 1) {
      const now = Date.now();
      typed.current = { text: (now - typed.current.at < 600 ? typed.current.text : "") + e.key.toLowerCase(), at: now };
      const i = opts.findIndex((o) => o.text.startsWith(typed.current.text));
      if (i >= 0) setActive(i);
    } else return;
    e.preventDefault();
  }

  return (
    <label className="flex flex-col gap-1.5">
      <span id={labelId} className={hideLabel ? "sr-only" : "text-[11px] font-medium uppercase tracking-wide text-ink-3"}>
        {label}
      </span>
      <button
        ref={pop.anchorRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={pop.open}
        aria-controls={listId}
        aria-labelledby={labelId}
        aria-activedescendant={pop.open ? optId(active) : undefined}
        disabled={disabled}
        onClick={() => (pop.open ? pop.setOpen(false) : openList())}
        onKeyDown={onKey}
        className={cx(
          fieldClass,
          "ripple inline-flex cursor-pointer items-center justify-between gap-2 pr-2 text-left",
          pop.open && "border-accent ring-3 ring-accent/20",
          className,
        )}
      >
        <span className="truncate">{opts[selected]?.label}</span>
        <svg aria-hidden viewBox="0 0 12 12" className={cx("h-3 w-3 shrink-0 text-ink-3 transition-transform duration-200", pop.open && "rotate-180 text-ink")}>
          <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {pop.open && (
        <PopoverPanel pop={pop}>
          <ul role="listbox" id={listId} aria-labelledby={labelId} className="max-h-72 overflow-auto">
            {opts.map((o, i) => (
              <li
                key={o.value + i}
                id={optId(i)}
                role="option"
                aria-selected={i === selected}
                aria-disabled={o.disabled || undefined}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(i)}
                className={cx(
                  "flex cursor-pointer items-center gap-2 rounded-[5px] py-1.5 pl-2 pr-3 text-[13px] transition-colors duration-100",
                  i === active ? "bg-fg/[0.07] text-ink" : "text-ink-2",
                  o.disabled && "cursor-not-allowed opacity-40",
                )}
              >
                <svg aria-hidden viewBox="0 0 12 12" className={cx("h-3 w-3 shrink-0 text-accent", i === selected ? "opacity-100" : "opacity-0")}>
                  <path d="M2.5 6.2 5 8.5l4.5-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="whitespace-nowrap">{o.label}</span>
              </li>
            ))}
          </ul>
        </PopoverPanel>
      )}
    </label>
  );
}

export function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">{children}</span>;
}

/** Rank on the student's LeetCode profile: leetcode.com users only, and only those whose
 *  rating the contest counted for (LeetCode leaves out users still in their first few
 *  contests). Shown as "~" while it is our estimate, until LeetCode publishes it. */
export function ProfileRank({ rank, official }: { rank: number | null; official?: boolean }) {
  if (rank == null) return <span className="text-ink-3">—</span>;
  return official ? (
    <span className="tabular font-medium text-ink" title="Official rank, as on the student's LeetCode profile.">
      {rank.toLocaleString()}
    </span>
  ) : (
    <span
      className="tabular text-ink-2"
      title="Estimate. LeetCode publishes the profile rank a few days after the contest; it can be better than this, because LeetCode leaves out users in their first few contests."
    >
      ~{rank.toLocaleString()}
    </span>
  );
}

/** Position on the contest's Global leaderboard (leetcode.com + leetcode.cn users),
 *  linking to the leaderboard page that shows the student. */
export function LeaderboardRank({ rank, url }: { rank: number | null | undefined; url: string | null }) {
  if (rank == null || !url) return <span className="text-ink-3">—</span>;
  return (
    <ExternalLink href={url} className="tabular" title="Position on the contest's Global leaderboard (includes leetcode.cn users). Opens that page.">
      {rank.toLocaleString()}
    </ExternalLink>
  );
}

const MEDAL = { 1: ["medal-gold", "Gold"], 2: ["medal-silver", "Silver"], 3: ["medal-bronze", "Bronze"] } as const;

/** Gold / silver / bronze for places 1-3; a plain number after that. */
export function Medal({ place, size = "md" }: { place: number | null | undefined; size?: "sm" | "md" | "lg" }) {
  const dims = size === "lg" ? "h-9 w-9 text-sm" : size === "sm" ? "h-5 w-5 text-[10px]" : "h-7 w-7 text-xs";
  if (place == null) return <span className={cx("inline-grid place-items-center text-ink-3", dims)}>—</span>;
  const medal = MEDAL[place as 1 | 2 | 3];
  if (!medal) return <span className={cx("tabular inline-grid place-items-center font-medium text-ink-3", dims)}>{place}</span>;
  return (
    <span className={cx("medal tabular inline-grid shrink-0 place-items-center rounded-full font-bold", medal[0], dims)} title={`${medal[1]} · #${place}`}>
      {place}
    </span>
  );
}

export function ExternalLink({ href, children, className, title }: { href: string; children: ReactNode; className?: string; title?: string }) {
  return (
    <a
      href={href}
      title={title}
      target="_blank"
      rel="noopener noreferrer"
      className={cx("text-accent-ink decoration-accent-ink/40 underline-offset-2 hover:text-accent-ink-hover hover:underline", className)}
    >
      {children}
      <svg aria-hidden viewBox="0 0 12 12" className="ml-1 inline-block h-3 w-3 align-[-1px] opacity-60">
        <path d="M4.5 2.5h5v5M9.5 2.5 3 9" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
      <span className="sr-only">(opens LeetCode in a new tab)</span>
    </a>
  );
}

// ---- status badges: tinted pill + icon + text label (never colour alone) -----------

type Tone = "good" | "info" | "warning" | "serious" | "critical" | "neutral" | "accent";
type Icon = "check" | "seal" | "clock" | "queue" | "spin" | "live" | "cross" | "alert" | "dash" | "calendar" | "minus" | "dot";

const toneStyle: Record<Tone, { pill: string; icon: string }> = {
  good: { pill: "from-good/[0.16] to-good/[0.07] text-good-ink ring-good/25", icon: "text-good" },
  info: { pill: "from-info/[0.16] to-info/[0.07] text-info-ink ring-info/25", icon: "text-info" },
  warning: { pill: "from-warning/[0.16] to-warning/[0.07] text-warning-ink ring-warning/25", icon: "text-warning" },
  serious: { pill: "from-serious/[0.16] to-serious/[0.07] text-serious-ink ring-serious/25", icon: "text-serious" },
  critical: { pill: "from-critical/[0.16] to-critical/[0.07] text-critical-ink ring-critical/30", icon: "text-critical" },
  neutral: { pill: "from-fg/[0.06] to-fg/[0.03] text-ink-2 ring-fg/10", icon: "text-ink-3" },
  accent: { pill: "from-accent/20 to-accent/[0.08] text-accent-ink ring-accent/30", icon: "text-accent" },
};

const toneIcon: Record<Tone, Icon> = {
  good: "check",
  info: "clock",
  warning: "clock",
  serious: "alert",
  critical: "cross",
  neutral: "dash",
  accent: "dot",
};

function StatusIcon({ name }: { name: Icon }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  switch (name) {
    case "check":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <circle cx="7" cy="7" r="6" fill="currentColor" opacity="0.18" />
          <path d="M4.4 7.2 6.2 9l3.4-3.8" {...common} />
        </svg>
      );
    case "seal":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <path d="M7 1.2 8.4 2.3l1.8-.1.5 1.7 1.5 1-.6 1.7.6 1.7-1.5 1-.5 1.7-1.8-.1L7 12.8l-1.4-1.1-1.8.1-.5-1.7-1.5-1 .6-1.7-.6-1.7 1.5-1 .5-1.7 1.8.1L7 1.2Z" fill="currentColor" opacity="0.2" />
          <path d="M4.6 7.1 6.2 8.7l3.2-3.4" {...common} />
        </svg>
      );
    case "clock":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <circle cx="7" cy="7" r="5.6" {...common} />
          <path d="M7 4.2V7l1.9 1.2" {...common} />
        </svg>
      );
    case "queue":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <path d="M4 2h6M4 12h6M4.6 2c0 2.6 4.8 2.4 4.8 5S4.6 9.4 4.6 12M9.4 2c0 2.6-4.8 2.4-4.8 5s4.8 2.4 4.8 5" {...common} />
        </svg>
      );
    case "spin":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <circle cx="7" cy="7" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.8" opacity="0.25" />
          <path d="M7 1.8a5.2 5.2 0 0 1 5.2 5.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    case "live":
      return (
        <span className="relative grid h-3.5 w-3.5 place-items-center">
          <span className="live-dot h-2 w-2 rounded-full bg-current" />
        </span>
      );
    case "cross":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <circle cx="7" cy="7" r="6" fill="currentColor" opacity="0.18" />
          <path d="m5 5 4 4m0-4-4 4" {...common} />
        </svg>
      );
    case "alert":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <path d="M7 1.8 12.6 11.6H1.4L7 1.8Z" fill="currentColor" opacity="0.18" />
          <path d="M7 1.8 12.6 11.6H1.4L7 1.8ZM7 5.6v2.6M7 10v.1" {...common} />
        </svg>
      );
    case "dash":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <circle cx="7" cy="7" r="5.4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.2 2" />
        </svg>
      );
    case "minus":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <circle cx="7" cy="7" r="6" fill="currentColor" opacity="0.18" />
          <path d="M4.6 7h4.8" {...common} />
        </svg>
      );
    case "calendar":
      return (
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5">
          <rect x="1.8" y="2.8" width="10.4" height="9.4" rx="2" {...common} />
          <path d="M1.8 5.8h10.4M4.8 1.6v2.4M9.2 1.6v2.4" {...common} />
        </svg>
      );
    case "dot":
      return (
        <span className="grid h-3.5 w-3.5 place-items-center">
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      );
  }
}

export function Badge({ tone, icon, children }: { tone: Tone; icon?: Icon | null; children: ReactNode }) {
  const t = toneStyle[tone];
  const name = icon === undefined ? toneIcon[tone] : icon;
  return (
    <span
      className={cx(
        "status-badge inline-flex h-[22px] items-center gap-1 whitespace-nowrap rounded-full bg-linear-to-b text-[11px] font-medium leading-none ring-1 ring-inset",
        name ? "pl-1 pr-2" : "px-2",
        t.pill,
      )}
    >
      {name && (
        <span aria-hidden className={cx("shrink-0", t.icon)}>
          <StatusIcon name={name} />
        </span>
      )}
      {children}
    </span>
  );
}

const resultStatus: Record<ResultStatus, [Tone, string, Icon]> = {
  solved: ["good", "Solved", "check"],
  zero: ["warning", "0 solved", "minus"],
  absent: ["neutral", "Absent", "dash"],
  invalid_handle: ["critical", "Invalid handle", "cross"],
  no_handle: ["serious", "No handle", "alert"],
  duplicate_handle: ["serious", "Duplicate handle", "alert"],
};

export const resultStatusLabel = (s: ResultStatus) => resultStatus[s][1];

export function ResultStatusBadge({ status }: { status: ResultStatus }) {
  const [tone, label, icon] = resultStatus[status];
  return (
    <Badge tone={tone} icon={icon}>
      {label}
    </Badge>
  );
}

const handleStatus: Record<HandleStatus, [Tone, string, Icon]> = {
  valid: ["good", "Valid", "seal"],
  invalid: ["critical", "Invalid", "cross"],
  unchecked: ["neutral", "Not checked", "dash"],
  missing: ["serious", "Missing", "alert"],
};

export const handleStatusLabel = (s: HandleStatus) => handleStatus[s][1];

export function HandleStatusBadge({ status }: { status: HandleStatus }) {
  const [tone, label, icon] = handleStatus[status];
  return (
    <Badge tone={tone} icon={icon}>
      {label}
    </Badge>
  );
}

const contestState: Record<ContestState, [Tone, string, Icon]> = {
  upcoming: ["neutral", "Upcoming", "calendar"],
  live: ["critical", "Live now", "live"],
  scheduled: ["warning", "Results soon", "clock"],
  scanning: ["accent", "Scanning", "spin"],
  queued: ["warning", "Queued", "queue"],
  provisional: ["info", "Early results", "check"],
  final: ["good", "Final results", "seal"],
  failed: ["critical", "Scan failed", "cross"],
  not_scanned: ["neutral", "Not scanned", "dash"],
};

const contestStateHint: Partial<Record<ContestState, string>> = {
  provisional:
    "Collected 30 minutes after the contest. Ranks can still move a little until LeetCode finalises the contest (removes disqualified users, publishes ratings, within 5 working days); final results are collected at 11 pm on the 5th working day.",
  final: "Collected at 11 pm on the 5th working day after the contest, once LeetCode has finalised ranks and published ratings. These numbers won't change.",
  scheduled: "Results are collected automatically 30 minutes after the contest ends.",
};

export function ContestStateBadge({ state }: { state: ContestState }) {
  const [tone, label, icon] = contestState[state];
  return (
    <span title={contestStateHint[state]} className="inline-flex">
      <Badge tone={tone} icon={icon}>
        {label}
      </Badge>
    </span>
  );
}

// ---- stat tile ------------------------------------------------------------------

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="stat rounded-md bg-surface px-4 py-3 shadow-card ring-1 ring-inset ring-(--card-ring)">
      <div className="text-[11px] font-medium uppercase tracking-wide text-ink-3">{label}</div>
      <div className="stat-value mt-1 text-xl font-semibold leading-tight tracking-tight text-ink">{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

// ---- states -----------------------------------------------------------------------

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex flex-col gap-2.5 py-6" aria-live="polite">
      <span className="sr-only">{label}</span>
      <span aria-hidden className="skeleton h-3.5 w-1/3" />
      <span aria-hidden className="skeleton h-3 w-2/3" />
      <span aria-hidden className="skeleton h-3 w-1/2" />
    </div>
  );
}

/** What to tell the person about a failed request. The server's own text is kept for
 *  4xx errors (it says what to fix); crashes and outages get a calm message plus the
 *  reference that finds the request in the server's log. */
export function describeError(error: unknown): { message: string; reference: string | null } {
  if (!(error instanceof ApiError)) return { message: error instanceof Error ? error.message : String(error), reference: null };
  const reference = error.requestId;
  if (error.status === 0) return { message: "You're offline or the server can't be reached. Check your connection and try again.", reference: null };
  if (error.status === 401) return { message: "Your session has ended. Sign in again to continue.", reference: null };
  if (error.status === 403) return { message: error.message && error.message !== "Forbidden" ? error.message : "You don't have access to this.", reference: null };
  if (error.status === 404) return { message: error.message && error.message !== "Not Found" ? capitalise(error.message) + "." : "This page or item doesn't exist (any more).", reference: null };
  if (error.status === 429) return { message: error.message || "Too many attempts. Wait a moment and try again.", reference: null };
  if (error.code === "leetcode_blocked" || error.code === "upstream") return { message: error.message, reference };
  if (error.status >= 500) return { message: "Something went wrong on our side. Try again in a moment; if it keeps happening, share the reference below.", reference };
  return { message: error.message, reference: null };
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { message, reference } = describeError(error);
  return (
    <div role="alert" className="flex items-start gap-2.5 rounded-md border border-critical/30 bg-critical/8 px-3.5 py-2.5 text-[13px] text-critical-ink">
      <svg aria-hidden viewBox="0 0 16 16" className="mt-0.5 h-4 w-4 shrink-0 text-critical">
        <path d="M8 1.5 15 14H1L8 1.5Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
        <path d="M8 6v3.5M8 11.5v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <span className="min-w-0 flex-1">
        {message}
        {reference && <span className="mt-0.5 block font-mono text-[11.5px] opacity-75">Reference: {reference}</span>}
      </span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="ripple -my-0.5 shrink-0 rounded px-2 py-0.5 font-medium underline-offset-2 hover:underline">
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-5 py-10 text-center text-[13px] text-ink-3">{children}</div>;
}

// ---- dialog ------------------------------------------------------------------------

/** A centred pop-up over a dimmed page. Escape or a click outside closes it (unless busy). */
export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  busy = false,
  wide = false,
  xl = false,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer: ReactNode;
  busy?: boolean;
  wide?: boolean;
  xl?: boolean;
}) {
  const titleId = useId();
  useModal(open, busy, onClose);
  if (!open) return null;
  return createPortal(
    <ModalFrame onClose={onClose} busy={busy} labelledBy={titleId} size={xl ? "xl" : wide ? "wide" : "md"}>
      <div className="shrink-0 px-5 pb-1 pt-5">
        <h2 id={titleId} className="text-base font-semibold tracking-tight text-ink">
          {title}
        </h2>
      </div>
      {/* only the middle scrolls: the title and the buttons stay in view */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3 text-[13px] text-ink-2">{children}</div>
      <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-fg/[0.06] bg-fg/[0.02] px-5 py-3">{footer}</div>
    </ModalFrame>,
    document.body,
  );
}

/** Escape closes, the page behind doesn't scroll, and focus returns where it was. */
function useModal(open: boolean, busy: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      before?.focus?.({ preventScroll: true });
    };
  }, [open, busy, onClose]);
}

/** The backdrop and panel every pop-up shares: centred on larger screens, a sheet from
 *  the bottom on phones, never taller than the screen. */
function ModalFrame({ onClose, busy, labelledBy, label, size, children }: { onClose: () => void; busy: boolean; labelledBy?: string; label?: string; size: "md" | "wide" | "xl"; children: ReactNode }) {
  return (
    <div
      className="dialog-backdrop fixed inset-0 z-50 flex items-end justify-center bg-black/45 backdrop-blur-[2px] sm:items-center sm:p-4"
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-label={label}
        className={cx(
          "dialog-panel flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl bg-surface shadow-(--shadow-pop) ring-1 ring-inset ring-fg/10 sm:max-h-[calc(100dvh-2rem)] sm:rounded-xl",
          size === "xl" ? "sm:max-w-5xl" : size === "wide" ? "sm:max-w-2xl" : "sm:max-w-md",
        )}
      >
        {children}
      </div>
    </div>
  );
}

/** A form in a pop-up (add / edit), opened over the page where you clicked, with the
 *  first field focused. The form brings its own heading and buttons. */
export function Modal({ open, onClose, label, busy = false, wide = true, children }: { open: boolean; onClose: () => void; label: string; busy?: boolean; wide?: boolean; children: ReactNode }) {
  const body = useRef<HTMLDivElement>(null);
  useModal(open, busy, onClose);
  useEffect(() => {
    if (open) body.current?.querySelector<HTMLElement>("input:not([type=hidden]), select, textarea")?.focus({ preventScroll: true });
  }, [open]);
  if (!open) return null;
  return createPortal(
    <ModalFrame onClose={onClose} busy={busy} label={label} size={wide ? "wide" : "md"}>
      <div ref={body} className="min-h-0 flex-1 overflow-y-auto">
        {children}
      </div>
    </ModalFrame>,
    document.body,
  );
}

/** "Remove Asha Rao?" — says what will happen; nothing changes until Confirm.
 *  `blocked` explains why it can't be done (Confirm disabled). */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  danger = false,
  busy = false,
  error,
  blocked,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: ReactNode;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  error?: unknown;
  blocked?: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            disabled={busy || !!blocked}
            autoFocus
            className={danger ? "bg-critical hover:bg-critical/90 active:bg-critical/90" : undefined}
          >
            {busy ? "Working…" : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {children}
        {blocked && <ErrorBox error={blocked} />}
        {error != null && <ErrorBox error={error} />}
      </div>
    </Dialog>
  );
}

/** A short list of consequences inside a ConfirmDialog. */
export function Consequences({ items }: { items: ReactNode[] }) {
  return (
    <ul className="flex flex-col gap-1.5 rounded-lg bg-fg/[0.03] px-4 py-3 ring-1 ring-inset ring-fg/[0.06]">
      {items.filter(Boolean).map((it, i) => (
        <li key={i} className="flex gap-2">
          <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-ink-3" />
          <span>{it}</span>
        </li>
      ))}
    </ul>
  );
}

/** The id of a row that just changed, for 2 seconds (its row briefly highlights). */
export function useFlash(ms = 2000): [number | null, (id: number) => void] {
  const [id, setId] = useState<number | null>(null);
  useEffect(() => {
    if (id == null) return;
    const t = setTimeout(() => setId(null), ms);
    return () => clearTimeout(t);
  }, [id, ms]);
  return [id, setId];
}

/** After paging a long table: bring its top back into view (under the sticky header)
 *  if it's scrolled away, so the new page starts at its first row, not mid-list. */
export function scrollToTopOf(el: HTMLElement | null, offset = 76) {
  if (!el) return;
  const top = el.getBoundingClientRect().top;
  if (top >= offset && top < window.innerHeight) return; // already in view
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top: Math.max(0, top + window.scrollY - offset), behavior: reduce ? "auto" : "smooth" });
}
