import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  connectAuthEmulator,
  getAuth,
  onAuthStateChanged,
  signInAnonymously,
  signInWithCredential,
  signInWithPopup,
  signOut,
  type Auth,
  type User,
} from "firebase/auth";
import { useSyncExternalStore } from "react";

/**
 * Firebase Auth: Google sign-in, or Anonymous sign-in for the demo (personas). The web config
 * is public by design; it comes from Vite env (apps/web/.env.local, written by `make web-config`)
 * so it never lands in git. The ID token goes to our API only, never to storage we control.
 */
// Local emulator harness only (`make dev-emulator`, M7); the Vite build refuses it for production.
const useEmulators = import.meta.env.VITE_USE_EMULATORS === "1";
const config = useEmulators
  ? { apiKey: "demo-key", authDomain: "localhost", projectId: "demo-readlayer", appId: "demo" }
  : {
      apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
      authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
      projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
      appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
    };

export const authConfigured = Boolean(config.apiKey && config.authDomain && config.projectId);
const auth: Auth | null = authConfigured ? getAuth(initializeApp(config)) : null;

if (useEmulators && auth) {
  connectAuthEmulator(auth, "http://127.0.0.1:9099", { disableWarnings: true });
  // The Auth emulator accepts an unsigned Google identity: lets a headless browser be two
  // different "Google" readers without real accounts. Never present outside emulator builds.
  (window as unknown as { __rlEmulatorSignIn?: unknown }).__rlEmulatorSignIn = async (
    email: string,
    name: string,
  ) => {
    const claims = { sub: email, email, email_verified: true, name };
    await signInWithCredential(auth, GoogleAuthProvider.credential(JSON.stringify(claims)));
  };
}

export type Session =
  | { status: "loading" }
  | { status: "unavailable" }
  | { status: "signed_out" }
  | { status: "signed_in"; uid: string; isDemo: boolean; name: string | null };

let session: Session = auth ? { status: "loading" } : { status: "unavailable" };
const listeners = new Set<() => void>();

function toSession(user: User | null): Session {
  if (!user) return { status: "signed_out" };
  return { status: "signed_in", uid: user.uid, isDemo: user.isAnonymous, name: user.displayName };
}

/**
 * "A session exists" hint for public/theme-init.js, which runs before any JS bundle: with it,
 * "/" paints a neutral loading shell instead of the static landing hero. Cleared on sign-out,
 * End demo and delete (all end in a null user). Holds no identity.
 */
export const SIGNED_IN_HINT = "readlayer:signed-in";

function writeHint(signedIn: boolean): void {
  try {
    if (signedIn) localStorage.setItem(SIGNED_IN_HINT, "1");
    else localStorage.removeItem(SIGNED_IN_HINT);
  } catch {
    // Storage blocked (private mode): the landing hero shows briefly, then the app takes over.
  }
}

auth &&
  onAuthStateChanged(auth, (user) => {
    session = toSession(user);
    writeHint(user !== null);
    listeners.forEach((l) => l());
  });

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

export function useSession(): Session {
  // Same snapshot while hydrating the landing's static hero (main.tsx, decision 47).
  return useSyncExternalStore(subscribe, () => session, () => session);
}

/** A fresh-enough ID token for the current user, or null when signed out. */
export async function idToken(forceRefresh = false): Promise<string | null> {
  const user = auth?.currentUser;
  return user ? user.getIdToken(forceRefresh) : null;
}

export async function signInWithGoogle(): Promise<void> {
  if (!auth) throw new Error("sign-in is not configured");
  await signInWithPopup(auth, new GoogleAuthProvider());
}

export async function startDemo(): Promise<void> {
  if (!auth) throw new Error("sign-in is not configured");
  if (!auth.currentUser) await signInAnonymously(auth);
}

export async function signOutUser(): Promise<void> {
  if (auth) await signOut(auth);
}

/** Readable text for a failed sign-in; never the raw Firebase message. */
export function signInError(error: unknown): string | null {
  const code = (error as { code?: string } | null)?.code ?? "";
  if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") return null;
  if (code === "auth/popup-blocked") return "Your browser blocked the sign-in window. Allow pop-ups for this site and try again.";
  if (code === "auth/network-request-failed") return "We couldn't reach Google. Check your connection and try again.";
  return "Sign-in didn't work. Try again in a moment.";
}

export function useIsDemo(): boolean {
  const s = useSession();
  return s.status === "signed_in" && s.isDemo;
}
