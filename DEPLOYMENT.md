# Deployment State

Last updated: 2026-07-30

## Active deployment

- Host: Fly.io
- App: `jasper-telegrambot`
- Public URL: `https://jasper-telegrambot.fly.dev`
- Runtime: one shared CPU Machine with 512 MB RAM in `ewr`
- Lifecycle: `auto_stop_machines = "stop"`, `auto_start_machines = true`, `min_machines_running = 0`
- Telegram webhook: registered to the Fly URL on process startup when `FLY_APP_NAME` is present

The Machine may stop while idle. Incoming Telegram webhook traffic wakes it automatically. Background-only work, including spontaneous proactive messages, does not run while the Machine is stopped.

## Retained fallback

- Host: Render
- Service ID: `srv-d809pe8g4nts73f2nur0`
- State on 2026-07-30: suspended after free-tier usage was exhausted
- Auto-Deploy: Off
- Keep this service for rollback; do not delete it
- Do not run the Render and Fly copies at the same time with the same Telegram bot token

## Safety rules

1. Exactly one deployment may own this Telegram bot token at a time.
2. Before moving hosts, stop the old runtime, deploy the new runtime, switch and verify the webhook, then keep the old service suspended.
3. Host-specific files such as `fly.toml` belong only to Jasper unless another bot is intentionally migrated.
4. The inactive-owner mention notification was removed on 2026-07-30. Do not restore it without an explicit request.
5. Jasper, Lucien, and Cloudy share an architecture, but changes must be reviewed and deployed per repository.
