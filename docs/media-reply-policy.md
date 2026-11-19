# Telegram media reply policy (2026-11-19)

Incoming voice and audio messages are temporarily ignored, including queued voice jobs. They are not downloaded, transcribed, or answered.

Group photos and albums shared by people other than the configured owner are offered to the model with a choice: reply when interested and able to add something concrete, otherwise return `[SKIP]`. The marker is consumed before Telegram delivery and is not stored as an assistant reply. Owner photos and private chats keep their normal reply behavior. The optional rule is retained on primary/backup API routes and follow-up calls after borrowing tools.

Validation: `python -m unittest discover -s tests`. New media tests exercise real webhook and processing functions using synthetic messages and mocked model/network calls. No test sends Telegram messages or invokes real models. Actual interest in an image remains a model decision.

## Follow-up: explicit image choice gate

The earlier optional `[SKIP]` instruction did not reliably prevent replies to every group image in real use. Unsolicited group images now require a valid structured model choice with `interested: true`, one specific basis (direct question, personal interest, or a concrete addition to the ongoing conversation), and a nonempty reply. Missing choices, plain descriptions, generic-praise categories, explicit declines, and malformed choices remain silent before capability/action handling. The runtime image rule follows the persona and other dynamic context. Ordinary text, owner images, and private images retain their existing behavior. No random reply probability or extra model call is introduced.

`[IMAGE-DECISION]` logs record accepted/declined/unconfirmed without logging the decision payload. Local tests mock model decisions; they verify enforcement, not real-model judgment. Real image behavior should be checked through these production logs.
