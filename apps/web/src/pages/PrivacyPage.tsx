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
      "The country you chose, to mix in news from there. It picks which news outlets count as local for you, and gives a few terms common there (like RBI or SEBI in India) a small head start on your map; it is never sent to the AI or to web search.",
      "What you do (your field) sets a starting level for that field's topics on your map, and how you like to take things in (read, watch, listen) orders your suggestions. Both are kept with your account.",
      "While you set up: the cards we showed you and which you marked “I'd read this” or “Not for me” (these shape your feed only), and your Quick check answers about a few terms (these are your own word, so they stay as evidence on your map). The card list is cleared when you finish setting up.",
    ],
  },
  {
    id: "pv-learn",
    title: "What the notes learn",
    items: [
      "Your knowledge map: for each idea, how likely you are to know it and the evidence that moved it.",
      "For each topic, a knowledge level and how interested you are.",
      "Changes you asked for on your profile: what changed, never the words you typed.",
    ],
  },
  {
    id: "pv-reading",
    title: "What you consume",
    items: [
      "Activity events: notes you opened, skipped or marked, and time spent on paragraphs (as word counts, never the text). Deleted automatically after 90 days.",
      "Weekly totals: words read, notes shown and the articles they came from.",
      "What you opened or dismissed in your feed, your saved articles and the pages you brought in.",
      "Goals: their type, numbers and target topics, never the goal as you wrote it.",
      "Daily counters that keep usage within limits (links added, videos opened, explanations made, edits, goals, onboarding matches).",
    ],
  },
  {
    id: "pv-videos",
    title: "Videos",
    items: [
      "A video's page shows its thumbnail from YouTube, so YouTube sees your IP address, browser and the video's id.",
      "The player loads only when you press play, from YouTube, and YouTube is told it is playing on Gloss's site. From then on YouTube gets what any embedded video sends and may set cookies; if you are signed in to YouTube in this browser, it can link the view to your account.",
      "Transcripts are made by Gemini on Google Cloud from the public recording only, with nothing about you. A transcript is stored once and listed only for the consumers who opened the video; like the video itself, anyone with its link can read it.",
    ],
  },
  {
    id: "pv-podcasts",
    title: "Podcasts",
    items: [
      "An episode's audio streams straight from its publisher and nothing is requested until you press play. Then the publisher, and any measurement services its episode link passes through, see your IP address and browser, and your browser tells them you came from Gloss's site (its address, not the page).",
      "Transcripts are made by Gemini on Google Cloud from the public recording only, with nothing about you. A transcript is stored once and listed only for the consumers who opened the episode; like the episode itself, anyone with its link can read it.",
    ],
  },
  {
    id: "pv-extension",
    title: "The Gloss extension",
    items: [
      "Nothing until you click it on a page. Then the article's title, text and address, with emails, phone numbers and card numbers removed in your browser first. Never forms, comments or anything you type, and never mail, banking or private pages.",
      "Your sign-in stays in the browser's session storage until the browser closes. Signing out, ending the demo or deleting your data disconnects it.",
      "An article page you bring in with it is stored once and readable only by the consumers who brought it in. It is listed with the pages you brought in, and deleting your data removes that link.",
      "On a YouTube video, Open in Gloss sends only the video's address, without playlist, time or tracking parts. The video then opens as if you had pasted its link: like any video in Gloss, anyone with its link can read its transcript, and only the entry in your library is yours.",
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
              Only the paragraph it explains, a knowledge level and your analogy style. Never who you are or what else you've
              opened.
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
