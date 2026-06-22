# Branch Name Rules

Branches must follow: `<type>/<ticket_number_or_000>-<description>`

**Allowed types** (same as Conventional Commits):
`feat`, `fix`, `chore`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `revert`, `config`

**Description:** lowercase, hyphen-separated words.

**Examples:**
```
feat/042-add-semantic-search
fix/000-correct-embedding-query
chore/007-update-dependencies
```

- Never commit directly to `main`.
- Use `000` when there is no ticket number.
