import { ANNOTATOR_VERSION } from "@readlayer/annotator";

// Stub service worker; activation, redaction and auth arrive in M8 (DESIGN §11.3).
chrome.runtime.onInstalled.addListener(() => {
  console.info(`ReadLayer installed (annotator ${ANNOTATOR_VERSION})`);
});
