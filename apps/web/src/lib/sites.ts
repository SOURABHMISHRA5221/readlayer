/** The new web address (decision 62); the old one serves the same build. */
export const GLOSS_HOST = "glossreader.web.app";

/** Sign-in through the page's own host on GLOSS_HOST (its /__/auth/handler), so Google's account
 *  chooser names Gloss; every other host keeps the built authDomain. */
export function authDomainFor(hostname: string, built: string | undefined): string | undefined {
  return hostname === GLOSS_HOST ? hostname : built;
}
