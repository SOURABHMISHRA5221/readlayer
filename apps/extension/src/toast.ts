/**
 * A quiet status line on the page while ReadLayer reads it ("Reading this page…", "Notes are
 * ready"). Only on accepted pages, after our CSS is in (refusals are told in the popup). Marked
 * data-rl-ui so the annotator's anchors and copies skip it.
 */

let toast: HTMLElement | null = null;
let hideTimer: ReturnType<typeof setTimeout> | null = null;

export function showToast(text: string, options: { busy?: boolean; hideAfterMs?: number } = {}): void {
  if (!toast) {
    toast = document.createElement("div");
    toast.className = "rl-ext-toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("data-rl-ui", "");
    document.body.append(toast);
  }
  const brand = document.createElement("span");
  brand.className = "rl-ext-toast__brand";
  brand.textContent = "ReadLayer";
  const line = document.createElement("span");
  line.textContent = text;
  toast.replaceChildren(brand, line);
  toast.setAttribute("aria-busy", String(Boolean(options.busy)));
  toast.dataset.state = "shown";
  if (hideTimer) clearTimeout(hideTimer);
  hideTimer = options.hideAfterMs ? setTimeout(hideToast, options.hideAfterMs) : null;
}

export function hideToast(): void {
  if (toast) toast.dataset.state = "hidden";
}
