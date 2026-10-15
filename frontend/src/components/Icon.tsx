/** Small inline SVG icon set (stroke icons, 16px default). */
import type { SVGProps } from "react";

export type IconName =
  | "check"
  | "x"
  | "alert"
  | "info"
  | "help"
  | "clock"
  | "play"
  | "stop"
  | "plus"
  | "trash"
  | "chevron-right"
  | "chevron-down"
  | "sun"
  | "moon"
  | "upload"
  | "download"
  | "lock"
  | "unlock"
  | "zoom-in"
  | "zoom-out"
  | "list"
  | "layers"
  | "graph"
  | "calendar"
  | "flag"
  | "star"
  | "refresh"
  | "compare"
  | "settings"
  | "factory"
  | "book"
  | "briefcase"
  | "file"
  | "arrow-right"
  | "external"
  | "circle"
  | "ban"
  | "loader"
  | "save"
  | "copy";

const paths: Record<IconName, JSX.Element> = {
  check: <path d="M3 8.5l3 3 7-7" />,
  x: <path d="M4 4l8 8M12 4l-8 8" />,
  alert: (
    <>
      <path d="M8 2.2L14.5 13.5h-13z" />
      <path d="M8 6.5v3M8 11.6v.1" />
    </>
  ),
  info: (
    <>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 7.2v4M8 4.9v.1" />
    </>
  ),
  help: (
    <>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M6.2 6.3a1.9 1.9 0 113 1.6c-.8.5-1.2.9-1.2 1.7M8 11.6v.1" />
    </>
  ),
  clock: (
    <>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 4.6V8l2.4 1.6" />
    </>
  ),
  play: <path d="M5 3.5v9l7.5-4.5z" />,
  stop: <rect x="4" y="4" width="8" height="8" rx="1" />,
  plus: <path d="M8 3v10M3 8h10" />,
  trash: <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" />,
  "chevron-right": <path d="M6 3.5L10.5 8 6 12.5" />,
  "chevron-down": <path d="M3.5 6L8 10.5 12.5 6" />,
  sun: (
    <>
      <circle cx="8" cy="8" r="2.8" />
      <path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" />
    </>
  ),
  moon: <path d="M13 9.6A5.5 5.5 0 016.4 3a5.5 5.5 0 106.6 6.6z" />,
  upload: <path d="M8 10.5V2.5M5 5.5l3-3 3 3M2.5 10.5v3h11v-3" />,
  download: <path d="M8 2.5v8M5 7.5l3 3 3-3M2.5 10.5v3h11v-3" />,
  lock: (
    <>
      <rect x="3.5" y="7" width="9" height="6.5" rx="1" />
      <path d="M5.5 7V5a2.5 2.5 0 015 0v2" />
    </>
  ),
  unlock: (
    <>
      <rect x="3.5" y="7" width="9" height="6.5" rx="1" />
      <path d="M5.5 7V5a2.5 2.5 0 014.8-1" />
    </>
  ),
  "zoom-in": (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.3 10.3L14 14M5 7h4M7 5v4" />
    </>
  ),
  "zoom-out": (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.3 10.3L14 14M5 7h4" />
    </>
  ),
  list: <path d="M5.5 4h8M5.5 8h8M5.5 12h8M2.5 4h.1M2.5 8h.1M2.5 12h.1" />,
  layers: <path d="M8 2l6 3-6 3-6-3zM2 8l6 3 6-3M2 11l6 3 6-3" />,
  graph: (
    <>
      <circle cx="3.5" cy="8" r="1.8" />
      <circle cx="12.5" cy="3.5" r="1.8" />
      <circle cx="12.5" cy="12.5" r="1.8" />
      <path d="M5.2 7.2l5.6-2.8M5.2 8.8l5.6 2.8" />
    </>
  ),
  calendar: (
    <>
      <rect x="2.5" y="3.5" width="11" height="10" rx="1" />
      <path d="M2.5 6.5h11M5.5 2v3M10.5 2v3" />
    </>
  ),
  flag: <path d="M3.5 14V2.5M3.5 3h8l-1.5 3 1.5 3h-8" />,
  star: <path d="M8 2l1.8 3.8 4.1.5-3 2.8.8 4.1L8 11.2l-3.7 2 .8-4.1-3-2.8 4.1-.5z" />,
  refresh: <path d="M13 8a5 5 0 11-1.5-3.5M13 2.5v3h-3" />,
  compare: <path d="M5 2.5v11M11 2.5v11M2.5 5H5M2.5 11H5M11 8h2.5" />,
  settings: (
    <>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.8v1.7M8 12.5v1.7M1.8 8h1.7M12.5 8h1.7M3.6 3.6l1.2 1.2M11.2 11.2l1.2 1.2M3.6 12.4l1.2-1.2M11.2 4.8l1.2-1.2" />
    </>
  ),
  factory: <path d="M2 13.5V7l3.5 2V7l3.5 2V7l3.5 2V3h1.5v10.5z" />,
  book: <path d="M2.5 3.5c2-1 4-1 5.5.5 1.5-1.5 3.5-1.5 5.5-.5v9.5c-2-1-4-1-5.5.5-1.5-1.5-3.5-1.5-5.5-.5zM8 4v9.5" />,
  briefcase: (
    <>
      <rect x="2" y="5" width="12" height="8.5" rx="1" />
      <path d="M6 5V3.5h4V5M2 9h12" />
    </>
  ),
  file: <path d="M4 2h5.5L12 4.5V14H4zM9.5 2v2.5H12" />,
  "arrow-right": <path d="M3 8h10M9 4l4 4-4 4" />,
  external: <path d="M9 2.5h4.5V7M13.5 2.5L7.5 8.5M11.5 9.5v4h-9v-9h4" />,
  circle: <circle cx="8" cy="8" r="5.5" />,
  ban: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M3.8 12.2l8.4-8.4" />
    </>
  ),
  loader: <path d="M8 2a6 6 0 106 6" />,
  save: <path d="M3 2.5h8l2 2v9H3zM5.5 2.5v3h4v-3M5 13.5v-4h6v4" />,
  copy: (
    <>
      <rect x="5" y="5" width="8.5" height="8.5" rx="1" />
      <path d="M3 10.5V2.5h7.5" />
    </>
  ),
};

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
  title?: string;
}

export function Icon({ name, size = 16, title, className, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      className={(className ?? "") + (name === "loader" ? " spin" : "")}
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {paths[name]}
    </svg>
  );
}
