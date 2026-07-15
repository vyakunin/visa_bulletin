# visa_bulletin — Claude Code bootstrap

Django/PostgreSQL/Bazel app parsing US visa bulletin data. Python 3.11+, AWS Lightsail.

This is the **public core** (PolyForm Noncommercial 1.0.0). The private ops/marketing/
monetization shell for visa-bulletin.us lives in the sibling repo
`~/cursor_projects/visa_bulletin_platform`.

## Two-repo split — ownership charter

Clean ownership line between the two repos. The reciprocal of this section lives in
`~/cursor_projects/visa_bulletin_platform/CLAUDE.md`.

- **`visa_bulletin` (this repo, public core)** — the *product*: data collection/ingest,
  prediction models (**VQS**), employer/job-title clustering, page rendering, the app's
  own tests + test-infra, and the app deployment. Model / data / algorithm / test work
  lives here.
- **`visa_bulletin_platform` (private ops shell)** — everything *around* the product:
  marketing/Reddit promo, hosting/ops config, monetization (ads/affiliate), SEO strategy
  docs.

**The Notion `Project` tag follows the split** (Daily Checkup Followups, data source
`d0ad4f4b-ed1c-4c69-9fa9-0202a2b0d4d2`): a ticket about the model / VQS / data ingest /
clustering / app tests / test-infra → tag `visa_bulletin`; a ticket about SEO / marketing
/ promo / monetization / ads / affiliate → tag `visa_bulletin_platform`. Re-tag a
mis-tagged ticket to the owning repo in the same turn.

@AGENTS.md

## Project rules

@.claude/rules/analytics.md
@.claude/rules/blog_content_html.md
@.claude/rules/branching.md
@.claude/rules/deployment.md
@.claude/rules/employer_clustering.md
@.claude/rules/ground_truth.md
@.claude/rules/homeserver_visa_bulletin.md
@.claude/rules/ingest_framework.md
@.claude/rules/job_title_coherence.md
@.claude/rules/perm_messaging.md
@.claude/rules/reddit_campaign_checkup.md
@.claude/rules/scripts.md
@.claude/rules/seo_publish.md
@.claude/rules/vqs.md
@.claude/rules/vqs_research_log.md
