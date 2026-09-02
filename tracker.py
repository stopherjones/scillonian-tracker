import asyncio
import json
import os
import smtplib
from email.mime.text import MIMEText
import websockets

# Vessel Identifiers for SCILLONIAN IV
MMSI = "232059789"
IMO = "1056355"

# Secrets loaded from GitHub Environment Variables
AISSTREAM_KEY = os.getenv("AISSTREAM_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

async def fetch_ais_position():
    """Connects to AISStream WebSocket and listens for a position report."""
    if not AISSTREAM_KEY:
        return None
        
    url = "wss://stream.aisstream.io/v0/stream"
    subscription = {
        "APIKey": AISSTREAM_KEY,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FiltersShipMMSI": [MMSI]
    }
    
    position = None
    try:
        async with websockets.connect(url) as websocket:
            await websocket.send(json.dumps(subscription))
            # Listen for up to 30 seconds for a broadcast
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < 30:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=5)
                    data = json.loads(msg)
                    if data.get("MessageType") == "PositionReport":
                        pos = data["Message"]["PositionReport"]
                        meta = data.get("MetaData", {})
                        position = {
                            "lat": pos["Latitude"],
                            "lon": pos["Longitude"],
                            "time": meta.get("time_utc", "Recently")
                        }
                        break
                except asyncio.TimeoutError:
                    continue
    except Exception as err:
        print(f"AISStream connection notice: {err}")
    return position

def send_notification(position):
    """Sends an HTML email with map links."""
    vf_map = f"https://www.vesselfinder.com/?imo={IMO}"
    mt_map = f"https://www.marinetraffic.com/en/ais/details/ships/imo:{IMO}"
    
    if position:
        gmaps_link = f"https://www.google.com/maps?q={position['lat']},{position['lon']}"
        content = f"""
        <h3>SCILLONIAN IV Location Update</h3>
        <p><b>Latitude / Longitude:</b> {position['lat']}, {position['lon']}</p>
        <p><b>Timestamp (UTC):</b> {position['time']}</p>
        <p><b>Google Maps:</b> <a href="{gmaps_link}">{gmaps_link}</a></p>
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
        <p>No direct AIS signal was received during today's 30-second window (vessel may be out of range of terrestrial receivers during transit).</p>
        <p>You can check for cached position updates directly on the map platforms:</p>
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
    latest_pos = asyncio.run(fetch_ais_position())
    send_notification(latest_pos)