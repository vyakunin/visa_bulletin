# People-Search / Data-Broker Feasibility Research (2026-06-02)

Research brief requested by owner after the named-PERM-applicant premise was
disproven (see `PEOPLE_SEARCH.md`). Question: how are consumer people-search
sites (Spokeo, BeenVerified, Whitepages, Radaris, TruePeopleSearch, Intelius…)
actually built, what data is publicly available, and what would it take to
collect many datasets and combine them into one comprehensive people DB.

**TL;DR:** Technically very doable and well-trodden — it's data acquisition +
entity resolution + a search UI. The hard part is **not** engineering; it's
**legal/compliance + sourcing economics + reputational fit**. As of 2026 the
regulatory surface (CA Delete Act/DROP live, FCRA enforcement, GDPR for any EU
person) makes a *comprehensive US person DB* a registered-data-broker business
with ongoing legal obligations, not a side feature. Recommendation at the end.

---

## 1. How these sites are actually built

Three moving parts, nothing exotic:

1. **Ingest** many independent record sets (public records + licensed feeds +
   web crawl + the sites copying each other).
2. **Entity resolution (identity matching)** — the core IP. Link records that
   refer to the same person using name + DOB + address history + phone + email
   + household links. Hybrid approach: deterministic rules on strong
   identifiers first (high-confidence merges), then probabilistic/fuzzy/ML
   scoring for the messy rest. Output = one merged profile per person.
   *Errors are inherent* — common-name collisions mis-merge people (this is the
   #1 accuracy complaint and a litigation vector).
3. **Serve** — search by name / phone / email / address / username → profile
   page. SEO-optimized profile pages are the traffic engine.

Notable: the big sites **cross-reference each other** (Spokeo pulls/echoes
Whitepages, Intelius, BeenVerified). Much "coverage" is the same underlying
public-record + licensed data recycled across vendors.

Sources: [deletemyinfo: how Spokeo collects data](https://deletemyinfo.com/how-does-spokeo-collect-data/),
[Spokeo help: where data comes from](https://help.spokeo.com/hc/en-us/articles/115010352567-Where-does-Spokeo-get-its-data),
[RudderStack: what is entity resolution](https://www.rudderstack.com/blog/what-is-entity-resolution/),
[PeopleDataLabs: entity resolution guide](https://www.peopledatalabs.com/data-lab/datafication/entity-resolution-guide).

---

## 2. What data is publicly available, and where

| Source | Contains | Access / cost |
|---|---|---|
| **State voter files** | Name, address, age/DOB (state-dependent), party, vote history; sometimes phone/email | 32 states + DC "open"; 15 "mixed"; 4 "restricted". Price $0–$37,000/state. **Most states ban *commercial* use** — big constraint. ([Ballotpedia](https://ballotpedia.org/Availability_of_state_voter_files), [EAC PDF](https://www.eac.gov/sites/default/files/voters/Available_Voter_File_Information.pdf)) |
| **Property / assessor + recorder** | Owner name, address, parcel, value, deeds, mortgages | Per-county portals, public; bulk varies by county. Aggregated by NETROnline etc. ([NETROnline](https://publicrecords.netronline.com/)) |
| **Court records** | Civil/criminal/bankruptcy/judgments/liens | County + PACER (federal). Public; bulk access uneven, often paid/scraped |
| **Business registrations / UCC** | Officers, registered agents, addresses | Secretary-of-State portals, mostly public |
| **Professional & occupational licenses** | Name, license, location | State boards, public |
| **Vital records (marriage/divorce/birth/death)** | Names, dates, relationships | State/county; availability varies; SSDI for deaths |
| **Web + social crawl** | Usernames, profiles, photos, employer, contacts | Public web scraping (ToS/legal grey area; *hiQ v. LinkedIn* gave some cover for public data, but fragile) |
| **Licensed/commercial feeds** | Phone↔name, email↔name, address history | Bought from telco/marketing data brokers; the "secret sauce" coverage |

Key takeaway: the *foundational* identity spine (name↔address↔phone) is mostly
**bought from upstream data brokers**, not assembled from raw public records.
Public records add property/court/license color on top.

---

## 3. Two build paths

### Path A — License/resell via APIs (fast, low-build, ongoing cost)
Stand up a search UI over a paid people-data API. Providers:
- **People Data Labs** — ~1.5B person profiles, ~$0.01–0.10/record. (B2B/professional skew.)
- **Open People Search API (Datarade)** — ~2.8B records from gov + public sources.
- **Searchbug, Apollo, ZoomInfo, Cognism** — contact-data skew (B2B), ZoomInfo $15k+/yr.

Pros: live in days–weeks. Cons: recurring per-record cost, vendor ToS limits
redistribution, you inherit their accuracy + compliance posture, thin moat.
Sources: [herohunt: 10 people-search APIs](https://www.herohunt.ai/blog/10-best-people-search-apis-full-in-depth-guide/),
[Datarade open-people-search](https://datarade.ai/data-products/the-open-people-search-api-for-usa-consumers-and-businesses-open-people-search).

### Path B — DIY aggregate raw public records + crawl (the "comprehensive DB")
Buy/scrape voter files (where commercial use allowed), county property +
court + license data, crawl public web/social, then build the entity-resolution
pipeline yourself.
Pros: own the data + moat. Cons: **massive** ongoing data-acquisition + ETL +
50-state/3000-county heterogeneity + scraping legal risk + entity-resolution
engineering + refresh treadmill. This is a multi-engineer, multi-quarter program
and a real company, not a feature.

---

## 4. The actual blocker: legal / compliance (2026 reality)

This is where "garbage people-search sites" earn the label and the lawsuits.

- **FCRA.** If the data is *used* for eligibility decisions (employment,
  housing, credit, insurance), you're a Consumer Reporting Agency with full FCRA
  duties. **A "not for FCRA purposes" disclaimer does NOT insulate you** — FTC
  fined Spokeo $800k; FTC guidance is explicit that saying "we're not a CRA"
  isn't enough if you market/operate like one.
  ([FTC blog](https://www.ftc.gov/business-guidance/blog/2013/01/background-screening-reports-fcra-just-saying-youre-not-consumer-reporting-agency-isnt-enough),
  [Hogan Lovells: $800k Spokeo fine](https://www.hoganlovells.com/en/publications/ftc-fines-data-broker-800000-for-marketing-consumer-profiles-to-employers-without-complying-with-fcra)).
- **CA Delete Act + DROP (LIVE 2026).** Operating a comprehensive person DB =
  "data broker." Must **register Jan 1–31 each year** ($6,000 fee + processing;
  $200/day late). From **Aug 1, 2026**: poll the state DROP deletion platform
  ≥ every 45 days and honor deletion requests within 90 days ($200/request/day
  penalties). **SB 361 (2025)** adds disclosure of sensitive categories
  collected — explicitly including **citizenship/immigration status** (directly
  relevant given our dataset). Third-party audits from 2028.
  ([CPPA data brokers](https://cppa.ca.gov/data_brokers/),
  [Clark Hill: DROP live](https://www.clarkhill.com/news-events/news/is-your-business-a-data-broker-californias-drop-goes-live-and-calprivacy-continues-to-enforce-delete-act/),
  [ComplianceHub guide](https://compliancehub.wiki/california-delete-act-drop-platform-compliance-guide-2026/)).
- **Other state data-broker laws** — TX, OR, VT registration regimes; more
  states adding. Each = registration + opt-out machinery.
- **CCPA/CPRA** — deletion/opt-out/"do not sell" for CA residents generally.
- **GDPR** — any EU person in the DB triggers lawful-basis, DSAR, erasure
  obligations. (Owner is EU-resident; the site has EU traffic.)
- **Voter-file commercial-use bans** — most states prohibit using the voter
  file commercially; using it to power a paid search likely violates the terms.
- **Scraping** — public-data scraping has *some* cover (hiQ) but ToS/CFAA risk
  is live and vendor-dependent.

---

## 5. Reputational / strategic fit

- visa-bulletin.us serves an **anxious immigrant audience**; the Reddit growth
  channel (CivilCandidate1349) is already banned from r/immigration. A
  "search people by name" product reads as **surveillance/doxxing** to exactly
  that audience → brand damage + channel loss. (Same risk flagged in
  `PEOPLE_SEARCH.md`.)
- "Comprehensive people DB" is a **different company** with a different risk
  profile, compliance org, and cost base than a visa-data analytics site.

---

## 6. Options / decision points

1. **Don't build a general people-search.** Keep the site's moat (visa/PERM/LCA
   wage analytics). Lowest risk. (Recommended.)
2. **Narrow, defensible "people" search on data we already have** — attorneys /
   law firms / employer immigration contacts (names ARE in LCA/PERM disclosure;
   professionals acting commercially, not vulnerable applicants). ~3 days, no
   new data, far lower risk. (Already scoped in `PEOPLE_SEARCH.md`.)
3. **Resell path (Path A)** as a separate product — fast but thin moat + you
   become a registered data broker (CA fee + DROP + deletion ops) the moment
   it's comprehensive + commercial.
4. **Full DIY comprehensive DB (Path B)** — a real multi-quarter company with a
   standing legal/compliance function (registration in multiple states, DROP
   deletion pipeline, FCRA firewall, GDPR). Only worth it if this becomes *the*
   business, not a feature.

**Recommendation:** Option 2 if he wants a "people search" shipped now;
Option 1 otherwise. Options 3/4 are viable businesses but carry data-broker
registration + FCRA + GDPR obligations that dwarf the engineering, and clash
with the current site's audience/brand.

---

## Sources
Inline above. Primary: CPPA data-broker portal, FTC FCRA guidance + Spokeo
enforcement, Ballotpedia/EAC voter-file availability, PeopleDataLabs/RudderStack
entity-resolution, Datarade/herohunt people-search API market.
