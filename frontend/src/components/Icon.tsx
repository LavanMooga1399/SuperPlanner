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
  | "copy"
  | "search"
  | "menu"
  | "bell"
  | "home"
  | "box"
  | "truck"
  | "wrench"
  | "chart"
  | "dashboard"
  | "users"
  | "database"
  | "shield"
  | "link"
  | "barcode"
  | "keyboard"
  | "sidebar"
  | "columns"
  | "filter"
  | "more"
  | "sort-asc"
  | "sort-desc"
  | "sort"
  | "user"
  | "eye"
  | "grip"
  | "bookmark"
  | "chat";

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
  search: (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L14 14" />
    </>
  ),
  menu: <path d="M2.5 4h11M2.5 8h11M2.5 12h11" />,
  bell: <path d="M4 11V7a4 4 0 018 0v4l1.2 1.5H2.8zM6.5 14h3" />,
  home: <path d="M2.5 7.5L8 3l5.5 4.5V13.5h-3.5v-4h-4v4H2.5z" />,
  box: <path d="M8 1.8l5.7 3v6.4L8 14.2l-5.7-3V4.8zM2.3 4.8L8 7.8l5.7-3M8 7.8v6.4" />,
  truck: (
    <>
      <path d="M1.5 4h8v7h-8zM9.5 6.5h2.8l2.2 2.3V11h-5" />
      <circle cx="4.5" cy="12" r="1.3" />
      <circle cx="11.5" cy="12" r="1.3" />
    </>
  ),
  wrench: <path d="M10.2 2.2a3.3 3.3 0 00-3.9 4.3L2.4 10.4a1.3 1.3 0 001.8 1.8l3.9-3.9a3.3 3.3 0 004.3-3.9l-1.9 1.9-1.6-.4-.4-1.6z" />,
  chart: <path d="M2.5 2.5v11h11M5 10.5V8M8 10.5V5.5M11 10.5V7" />,
  dashboard: (
    <>
      <rect x="2" y="2" width="5" height="6" rx="1" />
      <rect x="9" y="2" width="5" height="3.5" rx="1" />
      <rect x="9" y="7.5" width="5" height="6.5" rx="1" />
      <rect x="2" y="10" width="5" height="4" rx="1" />
    </>
  ),
  users: (
    <>
      <circle cx="6" cy="5.5" r="2.3" />
      <path d="M1.8 13.5c.4-2.4 2.1-3.7 4.2-3.7s3.8 1.3 4.2 3.7M10.5 3.4a2.3 2.3 0 010 4.3M12 9.9c1.2.5 2 1.7 2.2 3.6" />
    </>
  ),
  database: (
    <>
      <ellipse cx="8" cy="3.8" rx="5.2" ry="1.8" />
      <path d="M2.8 3.8v8.4c0 1 2.3 1.8 5.2 1.8s5.2-.8 5.2-1.8V3.8M2.8 8c0 1 2.3 1.8 5.2 1.8s5.2-.8 5.2-1.8" />
    </>
  ),
  shield: <path d="M8 1.8l5 2v4c0 3-2.2 5.3-5 6.4-2.8-1.1-5-3.4-5-6.4v-4z" />,
  link: <path d="M6.8 9.2a2.6 2.6 0 003.7 0l2.2-2.2a2.6 2.6 0 00-3.7-3.7l-.8.8M9.2 6.8a2.6 2.6 0 00-3.7 0L3.3 9a2.6 2.6 0 003.7 3.7l.8-.8" />,
  barcode: <path d="M2 3v10M4.5 3v10M6.5 3v10M9.5 3v10M11.5 3v10M14 3v10" />,
  keyboard: (
    <>
      <rect x="1.5" y="4" width="13" height="8" rx="1.2" />
      <path d="M4 6.5h.1M6.5 6.5h.1M9 6.5h.1M11.5 6.5h.1M5 9.5h6" />
    </>
  ),
  sidebar: (
    <>
      <rect x="2" y="2.5" width="12" height="11" rx="1.2" />
      <path d="M6 2.5v11" />
    </>
  ),
  columns: (
    <>
      <rect x="2" y="2.5" width="12" height="11" rx="1.2" />
      <path d="M6 2.5v11M10 2.5v11" />
    </>
  ),
  filter: <path d="M2 3h12l-4.5 5.3V13l-3-1.5V8.3z" />,
  more: <path d="M3.5 8h.1M8 8h.1M12.5 8h.1" strokeWidth={2.4} />,
  "sort-asc": <path d="M8 13V3M4.5 6.5L8 3l3.5 3.5" />,
  "sort-desc": <path d="M8 3v10M4.5 9.5L8 13l3.5-3.5" />,
  sort: <path d="M5.5 13V3M3 5.5L5.5 3 8 5.5M10.5 3v10M8 10.5l2.5 2.5 2.5-2.5" />,
  user: (
    <>
      <circle cx="8" cy="5.5" r="2.8" />
      <path d="M2.8 14c.5-2.8 2.6-4.3 5.2-4.3s4.7 1.5 5.2 4.3" />
    </>
  ),
  eye: (
    <>
      <path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" />
      <circle cx="8" cy="8" r="2" />
    </>
  ),
  grip: <path d="M6 4h.1M10 4h.1M6 8h.1M10 8h.1M6 12h.1M10 12h.1" strokeWidth={2.2} />,
  bookmark: <path d="M4 2h8v12l-4-3-4 3z" />,
  chat: <path d="M2.5 3.5h11v7.5H7l-3 2.5V11H2.5zM5.5 6.5h5M5.5 8.5h3" />,
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
