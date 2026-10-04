import type { ReactNode } from "react";

import type { ApiErrorKind } from "../lib/api";

interface StateViewProps {
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  role?: "alert" | "status";
}

export function StateView({ title, children, actions, role = "status" }: StateViewProps) {
  return (
    <section className="state" role={role}>
      <h2 className="state__title">{title}</h2>
      {children && <p className="state__body">{children}</p>}
      {actions && <div className="state__actions">{actions}</div>}
    </section>
  );
}

export const ERROR_COPY: Record<ApiErrorKind, { title: string; body: string }> = {
  not_found: {
    title: "We couldn't find that article",
    body: "It may have been removed from the library, or the link is incomplete.",
  },
  unauthorized: {
    title: "Your session has ended",
    body: "Sign in again to keep reading. Your notes and progress are where you left them.",
  },
  server: {
    title: "Something went wrong on our side",
    body: "The API answered with an error. Try again in a moment.",
  },
  offline: {
    title: "ReadLayer can't reach its API",
    body: "Check your connection, then try again.",
  },
};
