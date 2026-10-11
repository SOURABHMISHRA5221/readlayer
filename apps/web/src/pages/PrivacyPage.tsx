import { useEffect } from "react";

import { ThemeToggle } from "../components/ThemeToggle";
import { Wordmark } from "../components/Wordmark";
import "../landing/privacy.css";

/**
 * What Gloss stores (plan A1, B): public, and linked from the landing footer and the consent
 * line. Every item here matches apps/api USER_SUBCOLLECTIONS and UserProfile (DESIGN §11.4);
 * a change to either should change this page.
 */
const GROUPS: { id: string; title: string; items: string[] }[] = [
  {
    id: "pv-you",
    title: "About you",
    items: [
      "An account id from Google sign-in. Your name and email stay with Google sign-in; our database stores neither.",
      "Your settings: how many notes you want, the explanation style, the analogy worlds you think in, and whether learning is paused.",
      "Your consent: which version you agreed to and when. Nothing about you is recorded before it.",
      "Your start: the field you chose and your topics, including topics we matched from anything you typed. Never the text you typed.",
      "The country you chose, to mix in news from there. It picks which news outlets count as local for you; it is never sent to the AI or to web search.",
      "While you set up: the cards we showed you, which you marked “I'd read this” or “Not for me”, and your “Know this?” answers. The list is cleared when you start reading; the answers stay as evidence on your map and topics.",
    ],
  },
  {
    id: "pv-learn",
    title: "What the notes learn",
    items: [
      "Your knowledge map: for each idea, how likely you are to know it and the evidence that moved it.",
      "For each topic, a reading level and how interested you are.",
      "Changes you asked for on your profile: what changed, never the words you typed.",
    ],
  },
  {
    id: "pv-reading",
    title: "Your reading",
    items: [
      "Reading events: notes you opened, skipped or marked, and time spent on paragraphs (as word counts, never the text). Deleted automatically after 90 days.",
      "Weekly totals: words read, notes shown and the articles they came from.",
      "What you opened or dismissed in your feed, your saved articles and the pages you brought in.",
      "Reading goals: their type, numbers and target topics, never the goal as you wrote it.",
      "Daily counters that keep usage within limits (links added, explanations made, edits, goals, onboarding matches).",
    ],
  },
];

export default function PrivacyPage() {
  useEffect(() => {
    document.title = "Gloss · What we store";
  }, []);

  return (
    <div className="pv">
      <header className="lp-bar">
        <Wordmark size="lg" />
        <div className="lp-bar__end">
          <ThemeToggle />
        </div>
      </header>
      <main className="pv__main">
        <h1 className="pv__title">What Gloss stores, and what it never does</h1>
        <p className="pv__lede">
          Gloss keeps a private map of what you know so it can explain only what you'd miss. Here is everything it keeps
          about you, in plain words.
        </p>

        {GROUPS.map((g) => (
          <section key={g.id} className="pv__group" aria-labelledby={g.id}>
            <h2 id={g.id}>{g.title}</h2>
            <ul>
              {g.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        ))}

        <section className="pv__group" aria-labelledby="pv-ai">
          <h2 id="pv-ai">What the AI sees</h2>
          <ul>
            <li>
              Only the paragraph it explains, a reading level and your analogy style. Never who you are or what else you've
              read.
            </li>
            <li>
              Anything you type at the start is matched to topics by our model and isn't stored. Before that, emails and
              phone numbers in it are removed, and it is never sent to web search.
            </li>
          </ul>
        </section>

        <section className="pv__group" aria-labelledby="pv-controls">
          <h2 id="pv-controls">Your controls</h2>
          <ul>
            <li>Export everything as a file, or delete it all, from the account menu at any time.</li>
            <li>Deleting removes every document about you and your sign-in account.</li>
            <li>The demo uses a temporary anonymous account; ending the demo deletes what it recorded.</li>
          </ul>
        </section>
      </main>
    </div>
  );
}
