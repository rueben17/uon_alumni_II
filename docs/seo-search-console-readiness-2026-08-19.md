# Search Console Submission Readiness — 2026-08-19

Read-only audit. No application file was modified to produce this report. All
"verified by curl against production" items were fetched live against
`https://www.uonalumni.or.ke`, `https://uonalumni.or.ke`, `https://staff.uonalumni.or.ke`,
and `https://students.uonalumni.or.ke` on 2026-08-19 between 09:45–09:50 UTC.
All "read from the codebase" items are cited by file and line; a template
being correct does not mean the deployed page reflects it — see the note on
`uon_alumni_contact_us.html` under Phase 4.

I do not have Search Console access. No claim below states current indexing,
impressions, clicks, position, or crawl stats — those are marked "requires
Search Console" throughout.

---

## 1. GO / NO-GO

# NO-GO

Two independent, sitemap-wide defects each meet the stated blocking bar
("a sitemap containing 3xx/4xx/5xx URLs is the single most common cause of
Search Console coverage errors" / "the sitemap must list final destination
URLs only"):

1. **Every one of the 17 URLs in sitemap.xml uses the bare domain
   (`https://uonalumni.or.ke/...`), and every one of them 301-redirects** to
   the `www.` host, which is the site's actual canonical host (confirmed by
   canonical tag, JSON-LD notwithstanding — see Phase 2 item 8). A sitemap
   listing 3xx URLs, en masse, is a direct violation of the stated rule.
2. **One of those 17 URLs — Scholarship — does not lead to this site at
   all.** After the 301 to `www.`, it 302s to
   `https://students.uonalumni.or.ke/accounts/google/login/`, which itself
   proceeds to a live `accounts.google.com` OAuth screen. Googlebot (and
   every anonymous visitor, including a human clicking the sitemap result)
   is bounced into a third-party sign-in flow and never sees scholarship
   content. This is a 200-at-the-end redirect chain whose destination is not
   a page on this domain.

Both are fixable without a content decision — the fixes are `apps/home/sitemaps.py`'s
`get_domain()` and `apps/home/views.py`'s `uon_alumni_scholarship` view — but
per the task's hard rules, nothing was changed here.

Submit nothing until both are resolved and re-verified live.

---

## 2. Sitemap findings, ordered by severity

### 2.1 — BLOCKING — Scholarship sitemap entry resolves to a third-party OAuth screen, not a page on this site
**Verified by curl against production.**

```
curl -sD- https://uonalumni.or.ke/uon-alumni-scholarship/
→ 301 Location: https://www.uonalumni.or.ke/uon-alumni-scholarship/

curl -sD- https://www.uonalumni.or.ke/uon-alumni-scholarship/
→ 302 Location: https://students.uonalumni.or.ke/accounts/google/login/
   Set-Cookie: sessionid=...; Domain=.uonalumni.or.ke  (a session cookie is
   minted on every anonymous hit, including Googlebot's)

→ (followed) 200 accounts.google.com/v3/signin/identifier?...
   redirect_uri=https%3A%2F%2Fstudents.uonalumni.or.ke%2Faccounts%2Fgoogle%2Flogin%2Fcallback%2F
```

**Root cause, read from the codebase:** `apps/home/views.py:777-780` —
`uon_alumni_scholarship()` sends every unauthenticated request straight to
Google sign-in on the students subdomain:
```python
if not request.user.is_authenticated:
    messages.info(request, "Please sign in with your @students.uonbi.ac.ke account to apply.")
    request.session["post_login_next"] = request.build_absolute_uri()
    return redirect(_students_subdomain_url(request, "/accounts/google/login/"))
```
This is documented as deliberate in the view's own docstring (2026-08-14:
"Strictly students... An anonymous visitor is sent to sign in there") — it
gates the *application form*. But this same view also serves the page that
was meant to carry public scholarship information (eligibility, past
recipients — flagged as still-needed copy in `docs/todo.md`'s Content
Authoring Backlog, item 13). As built, there is no code path where an
anonymous visitor — or Googlebot — ever sees scholarship content on this
URL. It cannot be indexed, ever, in its current form.

**Impact:** Google will report this as a redirect error, and if it ever
resolves the OAuth chain, an unindexable page. A human clicking this result
in search gets bounced into a Google sign-in prompt with no context. This is
the single worst entry in the sitemap.

---

### 2.2 — BLOCKING — Every sitemap URL is a 301 redirect, not a final destination
**Verified by curl against production.** All 17 checked:

| Sitemap URL (as listed) | Status | Redirects to | Final status |
|---|---|---|---|
| `https://uonalumni.or.ke/` | 301 | `https://www.uonalumni.or.ke/` | 200 |
| `https://uonalumni.or.ke/uon-alumni-history/` | 301 | `.../uon-alumni-history/` (www) | 200 |
| `https://uonalumni.or.ke/uon-alumni-executive-committee/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-gallery/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-membership-categories/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-donate/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-scholarship/` | 301 | www, then **302 → students.uonalumni.or.ke → accounts.google.com** | see 2.1 |
| `https://uonalumni.or.ke/uon-alumni-in-memoriam/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-contact-us/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-news/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-walk/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-chapters/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-secretariat/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-partners/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-mission-vision/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-downloads/` | 301 | www | 200 |
| `https://uonalumni.or.ke/uon-alumni-careers/` | 301 | www | 200 |

**Root cause, read from the codebase:** `apps/home/sitemaps.py:29-30`,
`UonAlumniSitemap.get_domain()`:
```python
def get_domain(self, site=None):
    return 'lvh.me:8000' if settings.DEBUG else settings.SUBDOMAIN_DOMAIN
```
`settings.SUBDOMAIN_DOMAIN` (`main/settings.py:422`) is `'uonalumni.or.ke'`
— the bare domain, no `www.`. Every sitemap `<loc>` is built from this
value, hardcoded, regardless of which host actually serves the site as
canonical. Separately, the production web server (nginx; its config is not
in this repository and was not inspected directly — this conclusion is from
observed `Location:` headers only) 301s every bare-domain request to `www.`.
The two are simply out of sync: nothing in this codebase or its deploy
pipeline enforces that `get_domain()` return the same host the server treats
as canonical.

**Every single content URL in the sitemap is affected** — not a subset.

---

### 2.3 — Legal pages (Privacy / Cookie / Terms) correctly absent from the sitemap, but for a reason worth flagging separately
**Verified by curl against production; cross-referenced against the codebase.**

`https://www.uonalumni.or.ke/uon-alumni-page/privacy/`,
`.../uon-alumni-page/cookies/`, `.../uon-alumni-page/terms/` all return `200`,
`index, follow`, with a self-referential canonical — but the response body
contains the literal placeholder text **"This page's content is being
prepared — check back soon"**
(`templates/home/standing_page.html:20`), not actual policy text. The view,
`apps/home/views.py:96-98`, filters on `Article.objects.filter(type=PAGE,
page_key=page_key, is_published=True)` — the same filter
`StandingPageSitemap` (`apps/home/sitemaps.py:86-91`) uses — so the
placeholder rendering is proof these `Article` rows are not currently
published (or don't exist) in production, regardless of what
`docs/todo.md` records about them. **The sitemap's exclusion of these three
URLs is therefore correct, not a bug** — but it means `docs/todo.md`'s claim
that Privacy/Cookie/Terms are live (cited there as already provided to
Google for OAuth consent-screen verification) does not match production
right now. This is a content/ops finding, not a sitemap-mechanics one — see
Phase 4.

Not a GO/NO-GO blocker on its own (Google does not error on sitemap
under-coverage), but relevant to OAuth app verification, which depends on
these same URLs per `docs/todo.md`'s C.2 section.

---

### 2.4 — Clean: robots.txt / noindex / canonical-self-match / subdomain isolation
**Verified by curl against production.**

- **robots.txt, public host:** `https://www.uonalumni.or.ke/robots.txt` →
  `200`, `Disallow: /2005/`, `Disallow: /membership-admin/`,
  `Sitemap: https://www.uonalumni.or.ke/sitemap.xml` — this Sitemap: line
  correctly uses `www.` (it's built from `request.build_absolute_uri()` in
  `apps/home/context_processors.py:132`, which reflects whichever host
  served the request — not the same hardcoded-domain bug as 2.2). It
  resolves: confirmed `200` on that exact URL (see 2.5).
- **robots.txt, bare domain:** also 301s to `www.` — consistent with the
  site-wide bare→www behavior, not a robots.txt-specific issue.
- **robots.txt, staff subdomain:** `Disallow: /` — correct, blanket block.
- **robots.txt, students subdomain:** `Disallow: /` — correct, blanket
  block.
- **No sitemap URL is disallowed by robots.txt** (item 5): none of the 16
  reachable content URLs fall under `/2005/` or `/membership-admin/`.
- **No staff/students/admin/QR/evaluation/export URL appears in the sitemap**
  (item 7): confirmed — `UonAlumniStaticSitemap.items()` lists exactly 17
  named `home:` routes, none of them staff/student/QR/admin routes
  (`apps/home/sitemaps.py:46-65`).
- **Every checked page (once past the redirect) carries a self-referential
  canonical** matching its own final `www.` URL exactly, trailing slash
  included (item 4 and item 6, conditional on 2.2 being fixed first — once
  the sitemap lists `www.` URLs, canonical match will already be exact
  character-for-character; confirmed no separate trailing-slash drift).
- **X-Robots-Tag on sitemap.xml itself:** `noindex, noodp, noarchive` —
  correct; the sitemap file itself should never be indexed as a page,
  unrelated to whether the URLs it lists get indexed.

---

### 2.5 — Sitemap file validation
**Verified by curl + local parse against the production file content.**

- **XML well-formedness:** `xmllint` is not installed on this machine (Git
  Bash / Windows, confirmed via `which xmllint` — not found). Substituted
  Python's stdlib `xml.dom.minidom.parse()` against the live file — **parses
  cleanly, no errors.** This is a substitution, not `xmllint`'s own output;
  flagged per the instruction to report exactly what was run.
- **Namespace:** `xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"` +
  `xmlns:xhtml="http://www.w3.org/1999/xhtml"` — correct sitemap namespace.
  The `xhtml` namespace is declared but unused (no `<xhtml:link>` elements
  anywhere in the file) — harmless, not an error.
- **URL count:** 17. Far under the 50,000 limit.
- **Byte size:** 2,237 bytes uncompressed. Far under the 50 MB limit.
- **lastmod:** **0 of 17 URLs carry a `lastmod` value.**
  `UonAlumniStaticSitemap` (the only sitemap class currently producing any
  output — see 2.6) defines no `lastmod()` method. This is not the
  "uniform/perpetually-now" failure mode the task warns about (which
  actively teaches Google to distrust the field) — it's simple absence,
  which just means Google gets no recency signal from this field at all.
  Lower severity than a fabricated value would be, but worth fixing once
  the blockers above are resolved.
- **Content-Type:** `application/xml` on the `www.` host — correct.
- **`/sitemap.xml` on staff subdomain:** `404` — correct, not a redirect,
  not an error page; the route simply isn't mounted in
  `apps.staff.site_urls`.
- **`/sitemap.xml` on students subdomain:** `404` — same, correct.

---

### 2.6 — Coverage note: only `UonAlumniStaticSitemap` currently produces any URLs
**Read from the codebase, cross-referenced against `docs/todo.md`'s own
record of production row counts (2026-08-07 audit, not independently
re-verified against the production database here — no DB access was used
for this report).**

`apps/home/sitemaps.py` registers five sitemap classes
(`UonAlumniStaticSitemap`, `StandingPageSitemap`, `ArticleSitemap`,
`EventSitemap`, `ChapterSitemap`) in `main/urls.py:24-30`, but the live
sitemap.xml contains only the 17 URLs from `UonAlumniStaticSitemap`. This is
consistent with `docs/todo.md`'s own note that every content model
(`Article` type=news/feature/notice, `Event`, `Chapter`, `Publication`, etc.)
currently has zero published rows in production — not a sitemap bug, a
content-population gap. Flagged here only so it isn't mistaken for a
missing-code problem later.

---

### 2.7 — Cross-reference against the in-progress error-page audit
**From this session's own prior work, not re-derived here.**

Two site-wide 500 bugs were found and fixed earlier in this session:
1. `templates/400.html` / `403.html` / `404.html` — unpinned
   `{% url 'home:...' %}` crashed those error pages on staff/students
   subdomains (fixed, commit `603504a`).
2. `apps/home/context_processors.py`'s `contacts()` — `reverse("student:...",
   urlconf="main.urls")` crashed on every page for any staff/superuser
   session, site-wide (fixed, commit `087bced`).

**Neither confirmed-broken URL overlaps with any sitemap-listed URL** — the
sitemap contains zero staff/students-subdomain URLs, and neither fix touched
a route that appears in `UonAlumniStaticSitemap`. Both fixes are already
deployed and were confirmed live (VPS gunicorn journal, clean since restart)
prior to this audit. No cross-reference action needed.

---

## 3. Title and description table — every public page checked

"Suffix branch" = which of the three title blocks
(`title_brand`/`title_interior`/`title_bare`) the template sets, per the
policy documented in `templates/base.html`. All rows below verified live
against `https://www.uonalumni.or.ke` (the actual final destination after
the 2.2 redirect), not the sitemap's own bare-domain URL.

| URL (final, www) | Title | Chars | Description | Chars | Suffix branch |
|---|---|--:|---|--:|---|
| `/` | Home \| University of Nairobi Alumni Association | 47 | University of Nairobi Alumni Association | 40 | BRAND |
| `/uon-alumni-history/` | History \| UoNAA | 15 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-executive-committee/` | Executive Committee \| UoNAA | 27 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-gallery/` | Alumni Gallery \| UoNAA | 22 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-membership-categories/` | Membership Categories & Benefits \| UoNAA | 40 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-donate/` | Donate \| UoNAA | 14 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-scholarship/` | *(never reached — see 2.1)* | — | — | — | — |
| `/uon-alumni-in-memoriam/` | In Memoriam \| UoNAA | 19 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-contact-us/` | Contact Us \| University of Nairobi Alumni Association | 53 | University of Nairobi Alumni Association | 40 | BRAND |
| `/uon-alumni-news/` | News & Articles \| UoNAA | 23 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-walk/` | UoN Alumni Walk \| UoNAA | 23 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-chapters/` | Chapters \| UoNAA | 16 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-secretariat/` | Secretariat \| UoNAA | 19 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-partners/` | Partners \| UoNAA | 16 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-mission-vision/` | Mission, Vision & Core Values \| UoNAA | 37 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-downloads/` | Downloads \| UoNAA | 17 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-careers/` | Careers \| UoNAA | 15 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-page/privacy/` *(not sitemapped — see 2.3)* | Privacy Policy \| UoNAA | 22 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-page/cookies/` *(not sitemapped — see 2.3)* | Cookie Policy \| UoNAA | 21 | University of Nairobi Alumni Association | 40 | INTERIOR |
| `/uon-alumni-page/terms/` *(not sitemapped — see 2.3)* | Terms of Service \| UoNAA | 24 | University of Nairobi Alumni Association | 40 | INTERIOR |

### Findings from this table

1. **No missing titles or descriptions.** Every checked page renders both
   (item 1: clean).
2. **Every single page — all 19 that render — uses the framework's generic
   default description, verbatim: "University of Nairobi Alumni
   Association."** (item 2). This is `base.html`'s own fallback
   (`{% block meta_description %}{{ name_title }}{% endblock %}`,
   `templates/base.html:77`); grep confirms only `article_detail.html` and
   `walk_detail.html` override `meta_description` anywhere in the codebase
   (`grep -rl "block meta_description" templates/`), and neither is reachable
   from the current sitemap (zero published Articles/Events — see 2.6). This
   means **19 of 19 checked pages carry an identical, duplicate description**
   — technically item 3 (duplicate description) applies to the entire set at
   once, not a pairwise case.
3. **No missing-default check needed separately from #2 above** — item 2
   and item 3's finding are the same underlying fact here: 100% of pages
   still serve the default.
4. **No title exceeds 55 characters.** Longest is Contact Us at 53
   (BRAND branch). No title-length or truncation-risk finding (items 4-5:
   clean pass). Stated per the task's own caveat: pixel-width truncation at
   ~580px cannot be verified without rendering; character count is a proxy
   only, and every title here has enough margin under even a conservative
   estimate that this isn't a close call.
5. **Description length: all 19 are 40 characters — well outside the
   140–155 target** (item 4, description half). Not merely under-length by
   a little; at 40 characters this isn't functioning as a search-result
   description at all, it's the org's name repeated in a field meant for a
   one-sentence summary of the page.
6. **BRAND pages, suffix check (item 6):** Both BRAND pages found
   (`/` and `/uon-alumni-contact-us/`) correctly end with the full
   "University of Nairobi Alumni Association." No BRAND page found missing
   the suffix. **No INTERIOR page exceeds 60 characters** — the framework's
   own budget policy (documented at length in `templates/base.html`'s
   comment block) held on every page checked.
7. **og:site_name (item 7):** `University of Nairobi Alumni Association` on
   every single page checked, including the two BRAND pages — never the
   "UoNAA" abbreviation, never a page-specific override. Clean pass.
8. **JSON-LD Organization block (item 8):** Exactly one `Organization` block
   per page on every page checked (no page has two, no page has zero).
   `name` is always the full form, `alternateName` is always `"UoNAA"` —
   never reversed, never merged into a single field. Clean pass on
   structure. **However:** the JSON-LD `"url"` field is hardcoded to
   `https://uonalumni.or.ke/` (`apps/home/context_processors.py:142,152` —
   `base = ... 'https://uonalumni.or.ke'`, non-www) on every page, including
   pages actually served from `www.`. This is the same bare-vs-www
   inconsistency as the sitemap (2.2), now inside structured data too — a
   crawler parsing this JSON-LD is told the organization's canonical URL is
   a host that itself immediately redirects. Not one of the eight
   enumerated JSON-LD checks verbatim, but squarely the same defect class;
   flagged here rather than silently passed.
9. **Factual grounding (item 9):** There is nothing to fact-check. No
   description on any page contains a membership count, founding date,
   superlative, or any claim at all beyond restating the organization's own
   name. Zero unverifiable claims exist — but only because there is
   effectively no descriptive content to begin with (see finding #2/#5).
   Separately, on-page body copy (not meta description, not audited for
   ranking-relevant reasons, only crawled incidentally): `uon_alumni_history.html`
   states "UoNAA was officially launched on February 5, 2005" — this is
   stated as historical fact in visible page content, not a meta claim, and
   was not independently verified against a primary source here; noted only
   because it's the one factual date claim found anywhere in scope.
10. **Content promised vs. delivered (item 10):** N/A in the strict sense —
    no description promises specific content, since no description contains
    any content-specific claim (see #2/#9). The closer match is 2.3: three
    pages carry titles ("Privacy Policy", "Cookie Policy", "Terms of
    Service") that promise substantive legal text and deliver a "being
    prepared" placeholder instead, while still serving `index, follow`.

---

## 4. Findings requiring content decisions, not code fixes

1. **All 19 meta descriptions need real, page-specific copy.** This is
   authoring work — matches `docs/todo.md`'s own Content Authoring Backlog
   framing (item 17 there, now marked done for the *mechanism* — the
   per-page override blocks exist and work, per `article_detail.html`/
   `walk_detail.html` — but no page except those two has ever had one
   written). Writing 19 descriptions is a content task, not a template fix.
2. **Privacy Policy / Cookie Policy / Terms of Service have no real text in
   production** (2.3). This is more than an SEO gap: `docs/todo.md`'s C.2
   section records these URLs as already "provided to Google for the OAuth
   consent screen's required links." If Google's OAuth verification checked
   these URLs and found the "being prepared" placeholder, that is a
   standing risk independent of Search Console — worth surfacing to
   whoever owns that verification, not assumed resolved here.
3. **Scholarship page copy** (eligibility, past recipients, "what happens
   after you apply") was already flagged as missing in `docs/todo.md` item
   13 — that gap is now compounded by 2.1: even once written, it's
   currently unreachable by anyone who isn't already signed in, so the copy
   would have nowhere to render for an anonymous visitor or Googlebot
   without an accompanying code change (out of scope here) to serve public
   informational content before the sign-in gate.
4. **Whether `uon_alumni_scholarship` should show public info content to
   anonymous visitors at all**, with the sign-in gate applying only to the
   actual application form/submission, is a product decision, not
   something this report resolves. Flagged as the underlying question
   behind 2.1's fix.

---

## 5. Local-codebase note, not a production finding

`templates/home/uon_alumni_contact_us.html` has uncommitted local changes
(confirmed via `git status` / `git log origin/main..HEAD` — zero unpushed
commits, one modified-but-uncommitted file). None of this session's Contact
Us layout work (background image, card styling, map/form arrangement) is
live; the currently-deployed version is whatever shipped in commit `80d731e`.
One specific thing worth noting before that file is next committed: line 4
currently reads `{% block title_brand %} Contact Us | University of Nairobi
Alumni Association{% endblock %}` — a leading space before "Contact Us."
Confirmed by hex-dumping the *live* title tag that this space is **not**
currently present in production (production is running the pre-edit
version), so this is not a live defect today — but Django does not
auto-trim block content, so if this file is committed and deployed as-is,
that leading space would very likely render literally in the `<title>` tag.
Not fixed here per the read-only constraint; noting it so it isn't
rediscovered from scratch later.

---

## 6. Phase 3 — Submission readiness, stated accurately

**Resubmission mechanics:** Resubmitting an unchanged sitemap URL in Search
Console does not make Google crawl it any sooner than its own schedule
would already have. Resubmission is worth doing when the sitemap URL itself
is new to Search Console, or when its contents have materially changed —
which they will, once 2.1 and 2.2 are fixed, since every `<loc>` value
changes host.

**URL Inspection vs. sitemap submission:** For the handful of specific pages
here (17, soon possibly 20), URL Inspection → Request Indexing per-page is
the faster instrument once the URLs are correct. The sitemap's job is
discovery at scale; with only 17-20 URLs total, sitemap submission and
manual inspection are both cheap here — but Request Indexing still can't be
used meaningfully until the URLs it would be pointed at actually resolve to
content instead of a redirect chain.

**Meta descriptions and ranking:** Meta descriptions are not a ranking
factor. Google rewrites the displayed snippet for a large share of queries
regardless of what's in the tag. Writing real descriptions (finding #1 in
Phase 4) is worth doing for click-through rate on the results page, on its
own merits — it will not, and should not be described as, an action that
improves ranking or indexing.

**What to check in Search Console after submission — in order:**
1. **Sitemaps report — discovered vs. indexed count.** No local check
   substitutes for this; it is the only place that shows how many of the
   submitted URLs Google actually chose to index versus merely discovered.
   *Requires Search Console.*
2. **Page Indexing report — excluded reasons.** This is where a redirect
   chain like 2.1/2.2 would show up as "Page with redirect" or similar,
   confirming from Google's own side that the issues found here actually
   affected crawl/index behavior, not just that they exist. *Requires
   Search Console.*
3. **Core Web Vitals.** Nothing in this audit measured real-user
   performance; this report makes no claim about it. *Requires Search
   Console* (or a separate, dedicated tool — not attempted here).

No number in this report should be read as a substitute for any of the
three above. This report establishes what the pages currently *say and do*;
Search Console is the only source for how Google currently treats them.
