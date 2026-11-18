# Gemini 3.7 Flash migration

Distill 0.19.56 changes the optional Gemini analysis-provider default from
`gemini-3.6-flash` to `gemini-3.7-flash`. The global Distill default remains
the xAI route. The current xAI default is `grok-4.7`. See
[migration-grok-4.7.md](migration-grok-4.7.md). The Gemini provider default in
current releases is `gemini-3.8-flash`.

## What changes

- `distill provider set gemini` now selects `gemini-3.7-flash`.
- Gemini doctor probes use 3.7 Flash when no explicit model is configured.
- The context registry keeps a conservative 1M-token window.
- Distill omits `temperature`, `top_p`, and `top_k` for 3.7 Flash, matching
  Google's migration guidance for current Flash releases.
- Standard paid-tier pricing is $0.75 input and $3.75 output per 1M tokens
  through 2026-12-31, then $1.50 input and $7.50 output per 1M tokens.

## Existing configurations

In that release, an explicit `DISTILL_MODEL=gemini-3.6-flash` stayed as
configured. Current releases rewrite `gemini-3.6-flash` and `gemini-3.7-flash`
to `gemini-3.8-flash` before a call. The 0.19.56 adoption step was:

```bash
distill provider set gemini gemini-3.7-flash
distill --cost-mode paid-ok doctor
```

`distill provider show` and `distill provider list gemini` display the registry
review date and official Google pricing source. These commands read local
metadata only and do not call a model API.

## Deep Research is separate

This migration changes the Gemini chat model used for analysis and synthesis.
The report agents remain `deep-research-preview-04-2026` and
`deep-research-max-preview-04-2026`. Google bills those agents for underlying
inference and tools and exposes no request-side dollar ceiling. Distill refuses
them before remote setup whenever a hard workflow or MCP budget is active.

Official references:

- [Gemini latest models](https://ai.google.dev/gemini-api/docs/latest-model)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini Deep Research](https://ai.google.dev/gemini-api/docs/deep-research)
