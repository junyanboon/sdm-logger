# SDM Logger

Deterministic ground-truth inside-temperature logger for the Dance Annex Weatherman. It reads the two Nest thermostats through Google Smart Device Management and writes one `Kind=observation` row per online device (none while Google reports it OFFLINE) to the 🌡️ Thermal Log in Notion.

## GitHub secrets

Configure these five repository secrets:

- `SDM_PROJECT_ID`
- `SDM_CLIENT_ID`
- `SDM_CLIENT_SECRET`
- `SDM_REFRESH_TOKEN`
- `NOTION_TOKEN`

GitHub Actions requests a run hourly at minute 7. The script logs only during the 09:00–23:59 and 03:00–03:59 windows in `America/Toronto`; manual dispatch can bypass that gate.

## Run locally

Set the five environment variables above, then force a reading outside the scheduled window if needed:

```sh
export SDM_PROJECT_ID='...'
export SDM_CLIENT_ID='...'
export SDM_CLIENT_SECRET='...'
export SDM_REFRESH_TOKEN='...'
export NOTION_TOKEN='...'
FORCE=1 python3 log_reading.py
```

Consumed by “The Weatherman” hourly cloud run; see the Studio Climate Controller Notion page.
