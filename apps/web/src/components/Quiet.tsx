import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Shown in place of the part that failed; nothing by default. */
  fallback?: ReactNode;
}

/**
 * A boundary for optional, lazily loaded parts of a page (the library's week map, the reader's
 * spine): if their chunk or their render fails, e.g. a tab left open across a deploy, the page
 * they decorate stays up. React still reports the error it caught.
 */
export class Quiet extends Component<Props, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  override render(): ReactNode {
    return this.state.failed ? (this.props.fallback ?? null) : this.props.children;
  }
}
