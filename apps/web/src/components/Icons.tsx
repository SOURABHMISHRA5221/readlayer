import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 18, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const ArrowLeft = (p: IconProps) => (
  <Icon {...p}>
    <path d="M16 10H4m5-5-5 5 5 5" />
  </Icon>
);
export const ChevronDown = (p: IconProps) => (
  <Icon {...p}>
    <path d="m5 8 5 5 5-5" />
  </Icon>
);
export const External = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 4H4.8a.8.8 0 0 0-.8.8v10.4c0 .4.4.8.8.8h10.4c.4 0 .8-.4.8-.8V12M11 4h5v5m0-5-7.5 7.5" />
  </Icon>
);
export const Search = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="8.8" cy="8.8" r="5.3" />
    <path d="m12.8 12.8 3.7 3.7" />
  </Icon>
);
export const Check = (p: IconProps) => (
  <Icon {...p}>
    <path d="m4.5 10.5 3.5 3.5 7.5-8" />
  </Icon>
);
export const Sun = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="10" cy="10" r="3.4" />
    <path d="M10 2.5v1.8M10 15.7v1.8M2.5 10h1.8M15.7 10h1.8M4.7 4.7l1.3 1.3M14 14l1.3 1.3M4.7 15.3 6 14M14 6l1.3-1.3" />
  </Icon>
);
export const Moon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M16.2 12.4A6.6 6.6 0 0 1 7.6 3.8a6.6 6.6 0 1 0 8.6 8.6Z" />
  </Icon>
);
export const Close = (p: IconProps) => (
  <Icon {...p}>
    <path d="m5 5 10 10M15 5 5 15" />
  </Icon>
);
export const ArticleIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3.5" y="3" width="13" height="14" rx="2" />
    <path d="M6.5 7h7M6.5 10h7M6.5 13h4" />
  </Icon>
);
export const PlayIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2.5" y="4" width="15" height="12" rx="3" />
    <path d="m8.5 7.5 4 2.5-4 2.5z" fill="currentColor" />
  </Icon>
);
export const HeadphonesIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 13v-2.5a6.5 6.5 0 0 1 13 0V13" />
    <rect x="3" y="12" width="3.5" height="5" rx="1.2" />
    <rect x="13.5" y="12" width="3.5" height="5" rx="1.2" />
  </Icon>
);
