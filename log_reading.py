#!/usr/bin/env python3
"""Log Nest thermostat readings from Google SDM to Notion."""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


TORONTO = ZoneInfo("America/Toronto")
TOKEN_URL = "https://www.googleapis.com/oauth2/v4/token"
SDM_DEVICES_URL = (
    "https://smartdevicemanagement.googleapis.com/v1/enterprises/{project_id}/devices"
)
NOTION_PAGES_URL = "https://api.notion.com/v1/pages"
NOTION_DATABASE_ID = "f08b630932ce44ecbc9022bf8d207f46"
REQUIRED_ENV = (
    "SDM_PROJECT_ID",
    "SDM_CLIENT_ID",
    "SDM_CLIENT_SECRET",
    "SDM_REFRESH_TOKEN",
    "NOTION_TOKEN",
)


def request(url, *, method="GET", headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return None, f"request error: {exc.reason}"


def parse_json(body):
    if not body.strip():
        return None
    try:
        value = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def required_environment():
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print(f"missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        return None
    return {name: os.environ[name] for name in REQUIRED_ENV}


def refresh_access_token(config):
    form = urllib.parse.urlencode(
        {
            "client_id": config["SDM_CLIENT_ID"],
            "client_secret": config["SDM_CLIENT_SECRET"],
            "refresh_token": config["SDM_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")

    for attempt in range(3):
        _status, body = request(
            TOKEN_URL,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=form,
        )
        payload = parse_json(body)
        if payload and payload.get("access_token"):
            return payload["access_token"]
        if attempt < 2:
            time.sleep(2)

    print("failed to refresh SDM access token after 3 attempts", file=sys.stderr)
    return None


def read_devices(project_id, access_token):
    url = SDM_DEVICES_URL.format(
        project_id=urllib.parse.quote(project_id, safe="")
    )
    last_status = None
    last_payload = None

    for attempt in range(3):
        last_status, body = request(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        last_payload = parse_json(body)
        if last_payload is not None and "devices" in last_payload:
            if last_status == 200:
                return last_payload["devices"], 0
            print(
                f"SDM device read failed with status {last_status}",
                file=sys.stderr,
            )
            return None, 1
        if attempt < 2:
            time.sleep(2)

    if last_status == 200 and last_payload == {}:
        print("no devices granted", file=sys.stderr)
        return None, 2

    status_text = last_status if last_status is not None else "request_error"
    print(
        f"failed to read SDM devices after 3 attempts (status {status_text})",
        file=sys.stderr,
    )
    return None, 1


def extract_reading(device):
    traits = device["traits"]
    studio = device["parentRelations"][0]["displayName"]
    ambient = round(
        traits["sdm.devices.traits.Temperature"]["ambientTemperatureCelsius"],
        2,
    )
    humidity = traits["sdm.devices.traits.Humidity"]["ambientHumidityPercent"]
    mode = traits["sdm.devices.traits.ThermostatMode"]["mode"]
    setpoint = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})
    cool_setpoint = setpoint.get("coolCelsius")
    if cool_setpoint is not None:
        cool_setpoint = round(cool_setpoint, 2)
    hvac = traits["sdm.devices.traits.ThermostatHvac"]["status"]
    return {
        "studio": studio,
        "studio_select": "509" if studio.startswith("509") else "901",
        "ambient": ambient,
        "humidity": humidity,
        "mode": mode,
        "cool_setpoint": cool_setpoint,
        "hvac": hvac,
    }


def format_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def rich_text(content):
    if not content:
        return {"rich_text": []}
    return {
        "rich_text": [
            {
                "type": "text",
                "text": {"content": content},
            }
        ]
    }


def notion_page(reading, when_iso):
    cool_setpoint = reading["cool_setpoint"]
    setpoint_text = (
        f"COOL {format_number(cool_setpoint)}"
        if cool_setpoint is not None
        else ""
    )
    notes = (
        f"mode {reading['mode']} · HVAC {reading['hvac']} · "
        f"humidity {format_number(reading['humidity'])}% · via gh-actions"
    )

    return {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Entry": {
                "title": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"SDM reading — {reading['studio']}"
                        },
                    }
                ]
            },
            "Studio": {"select": {"name": reading["studio_select"]}},
            "Kind": {"select": {"name": "observation"}},
            "Source": {"select": {"name": "controller"}},
            "Inside °C": {"number": reading["ambient"]},
            "Setpoint": rich_text(setpoint_text),
            "Notes": rich_text(notes),
            "When": {"date": {"start": when_iso}},
        },
    }


def write_notion_page(notion_token, page):
    body = json.dumps(page, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    for attempt in range(2):
        status, response_body = request(
            NOTION_PAGES_URL,
            method="POST",
            headers=headers,
            data=body,
        )
        if status is not None and 200 <= status < 300:
            return True

        status_text = status if status is not None else "request_error"
        print(
            f"Notion write failed with status {status_text}: {response_body}",
            file=sys.stderr,
        )
        if status == 404 and "object_not_found" in response_body:
            print(
                "hint: share the Climate Controller page with the Notion integration",
                file=sys.stderr,
            )
        if attempt == 0:
            time.sleep(2)

    return False


def main():
    now = datetime.now(TORONTO)
    if os.environ.get("FORCE") != "1" and not (9 <= now.hour <= 23 or now.hour == 3):
        print(
            f"outside Toronto logging window at {now.isoformat(timespec='seconds')}; skipping"
        )
        return 0

    config = required_environment()
    if config is None:
        return 1

    access_token = refresh_access_token(config)
    if access_token is None:
        return 1

    devices, exit_code = read_devices(config["SDM_PROJECT_ID"], access_token)
    if devices is None:
        return exit_code

    readings = []
    for device in devices:
        try:
            readings.append(extract_reading(device))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            print(f"invalid SDM device payload: {exc}", file=sys.stderr)
            return 1

    any_failed = False
    when_iso = now.isoformat(timespec="seconds")
    for reading in readings:
        page = notion_page(reading, when_iso)
        if write_notion_page(config["NOTION_TOKEN"], page):
            print(
                f"logged {reading['studio_select']}: {reading['ambient']:.2f}C "
                f"mode {reading['mode']} hvac {reading['hvac']}"
            )
        else:
            any_failed = True

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
