import type { SVGProps } from "react";

/** A tulip in the style of the lucide icons used elsewhere (24 px grid, 2 px stroke). */
export function TulipIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d="M12 13.5c2.8 0 5-2.2 5-5V3.5l-2.6 2.2L12 2.5 9.6 5.7 7 3.5v5c0 2.8 2.2 5 5 5Z" />
      <path d="M12 13.5V22" />
      <path d="M12 22c0-3 2.2-5.2 5.5-5.2 0 3-2.4 5.2-5.5 5.2Z" />
      <path d="M12 19.5c-.6-2.1-2.2-3.4-4.5-3.6" />
    </svg>
  );
}
