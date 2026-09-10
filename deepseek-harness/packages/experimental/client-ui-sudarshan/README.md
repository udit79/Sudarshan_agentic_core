# Sudarshan Harness UI plugin

This package is the replaceable Sudarshan presentation layer for the DeepSeek
Harness web client. It owns only the shared brand slots:

- `sidebar.brand.mark`
- `sidebar.brand.name`
- `conversation.hero.brand.mark`

It does not own model calls, MCP tools, session state, or artifact rendering.
Those remain Harness or Sudarshan backend responsibilities. A different brand
can replace this package in the web bundle without changing the core UI.

Build it with `pnpm --filter @deepseek-ai/dsh-experimental-client-ui-sudarshan bundle`.
