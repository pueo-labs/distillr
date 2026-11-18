# Grok 4.7 default migration

As verified on 2026-11-14, xAI documents `grok-4.7` as its flagship text model.
Distill uses it for analysis, reranking, synthesis, site and paper work, briefs,
and ordered report section writing.

Configured xAI text ids from earlier generations, including `grok-4.6`,
`grok-4.5`, `grok-4.3`, and `grok-4.20`, are rewritten to `grok-4.7` before a
call. `grok-4.7` has a 500K context window, $2 input and $6 output per 1M
short-context tokens, and $4 input and $12 output once a prompt reaches 200K
tokens. Those long-context rates apply to every token in the request. Retired
reasoning slugs substitute to `grok-4.7`. Configured reasoning effort is sent
to `grok-4.7`. Distill still sends only `low`, `medium`, and `high`.

The August 2026 move to `grok-4.6` is recorded in
[migration-grok-4.6.md](migration-grok-4.6.md).

Prices and context: [xAI models](https://docs.x.ai/developers/models) and
[xAI pricing](https://docs.x.ai/developers/pricing).
