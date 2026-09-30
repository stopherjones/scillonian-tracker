import asyncio
import json
import os
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import websockets

# Vessel identifiers for SCILLONIAN IV
MMSI = "232059789"
IMO = "1056355"

# Secrets / settings from the GitHub Actions environment
AISSTREAM_KEY = os.getenv("AISSTREAM_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")
LISTEN_SECONDS = int(os.getenv("LISTEN_SECONDS", "240"))
SEND_EMAIL = os.getenv("SEND_EMAIL", "false").lower() == "true"

LOG_FILE = Path(__file__).with_name("positions.json")


def map_url():
    """Builds the GitHub Pages URL from the repo name, e.g. https://you.github.io/repo/"""
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    return f"https://{owner}.github.io/{name}/"


def to_iso(raw):
    """AISStream gives '2026-09-30 08:00:01.123 +0000 UTC'; convert to ISO 8601."""
    try:
        return raw[:19].replace(" ", "T") + "Z"
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def fetch_ais_position():
    """Connects to AISStream and listens for a position report."""
    if not AISSTREAM_KEY:
        return None

    url = "wss://stream.aisstream.io/v0/stream"
    subscription = {
        "APIKey": AISSTREAM_KEY,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FiltersShipMMSI": [MMSI],
        "FilterMessageTypes": ["PositionReport"],
    }

    position = None
    try:
        async with websockets.connect(url) as websocket:
            await websocket.send(json.dumps(subscription))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + LISTEN_SECONDS
            while loop.time() < deadline:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                data = json.loads(msg)
                if data.get("MessageType") == "PositionReport":
                    pos = data["Message"]["PositionReport"]
                    meta = data.get("MetaData", {})
                    position = {
                        "time": to_iso(meta.get("time_utc", "")),
                        "lat": pos["Latitude"],
                        "lon": pos["Longitude"],
                        "sog": pos.get("Sog"),  # speed over ground, knots
                        "cog": pos.get("Cog"),  # course over ground, degrees
                    }
                    break
    except Exception as err:
        print(f"AISStream connection notice: {err}")
    return position


def load_log():
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_log(log):
    LOG_FILE.write_text(json.dumps(log, indent=1) + "\n")


def send_notification(fix, log):
    """Sends an HTML email. Uses the last logged position if this run caught nothing."""
    vf_map = f"https://www.vesselfinder.com/?imo={IMO}"
    mt_map = f"https://www.marinetraffic.com/en/ais/details/ships/imo:{IMO}"
    site = map_url()
    site_line = f'<p><b>Track map:</b> <a href="{site}">{site}</a> ({len(log)} positions logged)</p>' if site else ""

    shown = fix or (log[-1] if log else None)
    if shown:
        gmaps_link = f"https://www.google.com/maps?q={shown['lat']},{shown['lon']}"
        heading = "Location Update" if fix else "Last Known Location (no new signal today)"
        speed = f"{shown['sog']} kn" if shown.get("sog") is not None else "n/a"
        course = f"{shown['cog']}°" if shown.get("cog") is not None else "n/a"
        content = f"""
        <h3>SCILLONIAN IV {heading}</h3>
        <p><b>Latitude / Longitude:</b> {shown['lat']}, {shown['lon']}</p>
        <p><b>Timestamp (UTC):</b> {shown['time']}</p>
        <p><b>Speed / Course:</b> {speed} / {course}</p>
        <p><b>Google Maps:</b> <a href="{gmaps_link}">{gmaps_link}</a></p>
        {site_line}
        <hr>
        <p><b>Maritime Trackers:</b></p>
        <ul>
            <li><a href="{vf_map}">VesselFinder Page</a></li>
            <li><a href="{mt_map}">MarineTraffic Page</a></li>
        </ul>
        """
    else:
        content = f"""
        <h3>SCILLONIAN IV Daily Update</h3>
        <p>No AIS signal has been received yet (the vessel may be out of range of terrestrial receivers).</p>
        {site_line}
        <ul>
            <li><a href="{vf_map}">VesselFinder Map Link</a></li>
            <li><a href="{mt_map}">MarineTraffic Map Link</a></li>
        </ul>
        """

    msg = MIMEText(content, "html")
    msg["Subject"] = "Daily Vessel Tracking Update: SCILLONIAN IV"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())


if __name__ == "__main__":
    latest = asyncio.run(fetch_ais_position())
    log = load_log()

    if latest and (not log or log[-1]["time"] != latest["time"]):
        log.append(latest)
        save_log(log)
        print(f"Logged position {latest['lat']}, {latest['lon']} at {latest['time']}")
    elif not latest:
        print("No position received this run.")

    if SEND_EMAIL:
        send_notification(latest, log)