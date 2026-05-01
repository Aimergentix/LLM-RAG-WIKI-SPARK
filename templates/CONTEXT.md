# Context — {{DOMAIN}}

> Optional. Use `CONTEXT.md` files when the wiki spans **multiple bounded
> contexts** with their own ubiquitous language (DDD-style). Borrowed from
> mattpocockuk/domain-model.

## When to add CONTEXT.md files

Default: a wiki has **one** `SCHEMA.md` at the root and no `CONTEXT.md`.

Add per-context `CONTEXT.md` files only when:

- Two subdomains use the **same word** to mean **different things**.
- Subdomains have **fundamentally different** entity types or workflows.
- You routinely need to translate between subdomains.

If you add per-context files, also create a `CONTEXT-MAP.md` at the root that
lists every context and its boundary.

## Per-context structure

```
{wiki-root}/
├── CONTEXT-MAP.md           Lists all contexts + boundaries
├── wiki/
│   ├── {context-a}/
│   │   ├── CONTEXT.md       Glossary + relations local to this context
│   │   ├── concepts/
│   │   ├── entities/
│   │   └── sources/
│   └── {context-b}/
│       ├── CONTEXT.md
│       └── …
```

## CONTEXT.md template

```markdown
# Context — {Context Name}

## Boundary
{What's inside this context. What's NOT.}

## Glossary
| Term | Definition | Aliases to avoid |
|---|---|---|

## Relations to other contexts
- `{this} → {other}` — translation rule
```
