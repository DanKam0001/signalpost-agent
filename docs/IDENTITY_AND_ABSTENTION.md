# Identity resolution and abstention

The organisation number is the identity anchor. Every registry fact is fetched by that exact key,
so registry facts cannot belong to another company. Precision rules for everything else:

1. **Candidates are not facts.** Website candidates come from the registry `hjemmeside`, the
   registered e-mail domain (unless a generic provider such as gmail.com or online.no), the input
   row's `website` field, and — only when none of those exist — two guesses from the legal name
   (`www.<name>.no`, `www.<name-with-hyphens>.no`). No search engine is used.
2. **Publication gate.** A site is published as the official website only with:
   - the organisation number on the site (any formatting: `923609016`, `923 609 016`,
     `NO 923 609 016 MVA`, JSON-LD `vatID`/`taxID`) — method `organisation_number_on_site`; or
   - the full legal name (with its form suffix) together with the registered street address and
     postcode, or with the registered phone/e-mail — `name_and_address_on_site` /
     `name_and_contact_on_site`; or
   - for the registry-declared `hjemmeside` only: the site loads and nothing on it contradicts the
     identity — `registry_declared` (confidence 0.8). If it cannot be crawled, the URL is still
     published from registry evidence alone (confidence 0.7, `site_crawled: false`) and the
     section shows why it could not be crawled.
   Name guesses count only with the organisation number on the site.
3. **Conflicts.** If a site presents a different organisation number (labelled or printed as
   `ddd ddd ddd`) and not ours — typically a parent, group, franchise or brand site — the website
   section is `ambiguous`, a `website_candidate_relationship` claim names the other number, and
   **no** site facts are published. A guessed or externally supplied site showing both numbers is
   also treated as a conflict.
4. **Facts from a verified site** (description, brand, contacts, social links, careers page, job
   postings, dated news) are labelled `company_owned`; the summary presents the site description
   as the company's own words, not as an independent assessment.
5. **Parent units** (`overordnetEnhet`) are published as a labelled relationship, never merged.
6. **Abstention states.** `not_available` = looked, nothing there; `blocked` = the source refused
   (403/429/robots); `ambiguous` = not sure it is the right company; `failed` = the run broke;
   `not_applicable` = the question does not apply (e.g. accounts for a sub-unit). Absence is never
   turned into zero; a missing number is an explicit `not_available` claim.
7. **No LLM** decides identity, extracts facts or writes the summary.
