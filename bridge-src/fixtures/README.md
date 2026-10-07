# Evolution webhook fixtures

These payloads are sanitized fixtures derived from the Evolution Go event shapes.
The live instance has recently emitted `Message` events with `text`, `media`, and
`reaction` message types, plus `GroupInfo`, `PushName`, `HistorySync`, and
`Receipt` events. Group JIDs (`@g.us`) are intentionally ignored by the bridge.
`message-evolution-go.json` covers the native `Info`/`Message` envelope observed
in production; the other message fixtures cover the older `key`/`message` shape.

The fixture IDs and phone numbers are synthetic. Do not copy production message
bodies or media into this directory.
