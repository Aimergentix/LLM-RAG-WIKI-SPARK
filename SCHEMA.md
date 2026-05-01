# Wiki Schema — {{DOMAIN}}

> Created: {{DATE}}

## Domain

{{DESCRIPTION}}

## Custom Page Types

<!-- The skill auto-generates 3–5 domain-specific page types here at init.
     Examples by domain:
     - Research wiki: Paper, Researcher, Dataset, Method, Venue
     - Personal-health wiki: Symptom, Treatment, Practitioner, Protocol, Study
     - Product wiki: Feature, Customer, Competitor, Release, Metric
-->

## Glossary

The LLM extends this table inline whenever a new domain term appears during
ingest (lazy domain-model discipline).

| Term | Definition | Aliases to avoid |
|---|---|---|
|  |  |  |

## Relation Codes

Bounded vocabulary for cross-references. Lint rules check distribution.

- `isA` — taxonomic class membership
- `partOf` — composition / containment
- `hasAttribute` — possesses a property
- `relatedTo` — generic association (use sparingly)
- `dependentOn` — functional dependency
- `causes` — causal link
- `locatedIn` — spatial containment
- `occursAt` — temporal placement
- `derivedFrom` — origin / provenance
- `opposes` — contradiction / negation

## Confidence Levels

- **high** — supported by 3+ independent sources
- **medium** — 1–2 sources, plausible
- **low** — single source or extrapolation
- **speculative** — inference, no direct source

## Linking Conventions

- **Internal links** — plain Markdown: `[Page Title](relative/path.md)`. Works
  in any Markdown viewer.
- **Wikilinks** — `[[Page Title]]` allowed only if the user has Foam (VS Code)
  installed. Otherwise avoid.
- **Source citations** — `[Source Title](sources/slug.md)` or
  `(source: raw/{slug}.md)` for inline mentions.
- **External links** — standard Markdown `[text](url)`, only for original
  source URLs.

## ADRs

Architectural decisions about the wiki itself. Add only when **all three** are
present: hard to reverse, surprising, real trade-off. Use the template at
`templates/ADR-template.md`. Keep this list short.

| # | Date | Title | Status |
|---|---|---|---|
|   |      |       |        |

## Ingest Protocol

Standard ingest is 7 steps (see SKILL.md / AGENTS.md / chatmode). Add
domain-specific additions here:

<!-- e.g. "For papers, always extract the venue and citation count into the
     entity page." -->

## Lint Schedule

Recommended cadence:

- **Weekly** — full lint with graph-state classification
- **Per 10 sources** — quick structural pass
- **Manual** — anytime you suspect drift

If cron is installed, `bin/lint-cron.sh` runs the weekly schedule.
