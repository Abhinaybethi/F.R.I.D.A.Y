/** Inline SVG icon set — local, no icon-font or CDN dependency. */

import type { SVGProps } from "react";

export type IconName =
  | "home"
  | "chat"
  | "mic"
  | "eye"
  | "image"
  | "search"
  | "code"
  | "bolt"
  | "folder"
  | "users"
  | "cpu"
  | "activity"
  | "settings"
  | "book"
  | "close"
  | "minimize"
  | "maximize"
  | "refresh"
  | "send"
  | "trash"
  | "copy"
  | "check"
  | "external"
  | "clock"
  | "shield"
  | "terminal"
  | "chip"
  | "warning"
  | "spark"
  | "chevron";

const PATHS: Record<IconName, string> = {
  home: "M3 10.8 12 3l9 7.8M5.5 9.5V21h13V9.5M9.5 21v-6h5v6",
  chat: "M21 12a8 8 0 0 1-8 8H4l1.6-3.2A8 8 0 1 1 21 12Z",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3ZM5 11a7 7 0 0 0 14 0M12 18v3M9 21h6",
  eye: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Zm9.5 2.7a2.7 2.7 0 1 0 0-5.4 2.7 2.7 0 0 0 0 5.4Z",
  image: "M3 5h18v14H3zM3 15l4.5-4.5 4 4L15 11l6 6M8.5 9.2a1.3 1.3 0 1 1-2.6 0 1.3 1.3 0 0 1 2.6 0Z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.3-4.3",
  code: "m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
  bolt: "M13 2 4 14h6l-1 8 9-12h-6l1-8Z",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
  users: "M16 20v-1.5a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4V20M9 10.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM17 3.6a3.5 3.5 0 0 1 0 6.8M22 20v-1.5a4 4 0 0 0-3-3.8",
  cpu: "M6 6h12v12H6zM9.5 9.5h5v5h-5zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3",
  activity: "M3 12h4l2.5-7 4 14 2.5-7h5",
  settings: "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Zm8-3.2a8 8 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a8 8 0 0 0-2-1.2L15 3H9l-.5 2.6a8 8 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a8 8 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a8 8 0 0 0 2 1.2L9 21h6l.5-2.6a8 8 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.07-.4.1-.8.1-1.2Z",
  book: "M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5v-16ZM4 19.5A2.5 2.5 0 0 1 6.5 17H20",
  close: "M5 5l14 14M19 5 5 19",
  minimize: "M5 12h14",
  maximize: "M5 5h14v14H5z",
  refresh: "M20 12a8 8 0 1 1-2.4-5.7M20 4v4h-4",
  send: "M21 3 10.5 13.5M21 3l-6.5 18-4-8-8-4L21 3Z",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6",
  copy: "M9 9h11v11H9zM15 9V4H4v11h5",
  check: "m4 12.5 5 5L20 6.5",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3.5 2",
  shield: "M12 3 4.5 6v6c0 4.3 3.2 7.7 7.5 9 4.3-1.3 7.5-4.7 7.5-9V6L12 3Z",
  terminal: "M4 5h16v14H4zM8 9.5 10.5 12 8 14.5M12.5 15H16",
  chip: "M8 4h8v16H8zM4 8h4M4 16h4M16 8h4M16 16h4M4 12h4M16 12h4",
  warning: "M12 3 2.5 20h19L12 3ZM12 9v5M12 17.2v.1",
  spark: "M12 2.5 14 9l6.5 2-6.5 2-2 6.5-2-6.5L3.5 11 10 9l2-6.5Z",
  chevron: "m9 6 6 6-6 6",
};

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 16, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
