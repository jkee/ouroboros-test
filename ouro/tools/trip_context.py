"""
Trip Context — returns current and upcoming hotel/accommodation info from flights.json.

Use this tool BEFORE answering any route/transport/navigation questions so you 
always know the user's actual hotel and can give personalized directions.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from ouro.tools.registry import ToolEntry

FLIGHTS_PATH = Path("/data/flights.json")


def _load_bookings() -> list:
    if not FLIGHTS_PATH.exists():
        return []
    try:
        return json.loads(FLIGHTS_PATH.read_text())
    except Exception:
        return []


def _get_hotel_name(entry: dict) -> Optional[str]:
    """Try various field names for hotel name."""
    for field in ("hotel_name", "hotel", "property", "subject"):
        val = entry.get(field)
        if val and isinstance(val, str) and len(val) > 5:
            # Skip obviously wrong values like email addresses
            if "@" not in val and "booking.com" not in val.lower():
                return val
    return None


def _get_hotel_location(entry: dict) -> Optional[str]:
    """Try to get hotel location/city."""
    loc = entry.get("location")
    if loc:
        return loc
    # Try to extract from property address
    prop = entry.get("property", "")
    if prop and "," in prop:
        # Last parts of address often have city/country
        parts = [p.strip() for p in prop.split(",")]
        if len(parts) >= 2:
            return ", ".join(parts[-2:])
    return None


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def get_trip_context() -> str:
    """
    Returns current and upcoming hotel bookings and flights from the user's travel data.
    Call this before answering any route/transport/navigation/directions questions.
    """
    bookings = _load_bookings()
    today = date.today()
    future_limit = today + timedelta(days=30)

    current_hotels = []
    upcoming_hotels = []
    upcoming_flights = []

    for entry in bookings:
        entry_type = entry.get("type", "").lower()
        
        # Detect hotel/accommodation entries
        is_hotel = entry_type in ("hotel", "accommodation") or entry.get("checkin") or entry.get("hotel") or entry.get("property")
        is_flight = entry_type == "flight" or (entry.get("route") and entry.get("departure") and not is_hotel)

        if is_hotel and not (entry.get("route") and not entry.get("checkin")):
            checkin = _parse_date(entry.get("checkin"))
            checkout = _parse_date(entry.get("checkout"))
            if not checkin:
                continue
            name = _get_hotel_name(entry)
            location = _get_hotel_location(entry)

            # Current stay
            if checkout and checkin <= today <= checkout:
                current_hotels.append({
                    "name": name or "Unknown hotel",
                    "location": location or "",
                    "checkin": checkin,
                    "checkout": checkout,
                    "address": entry.get("property", ""),
                    "bookingRef": entry.get("bookingRef", entry.get("booking_reference", "")),
                })
            # Upcoming
            elif checkin > today and checkin <= future_limit:
                upcoming_hotels.append({
                    "name": name or "Unknown hotel",
                    "location": location or "",
                    "checkin": checkin,
                    "checkout": checkout,
                    "address": entry.get("property", ""),
                })

        elif is_flight and not is_hotel:
            dep_str = entry.get("departure") or entry.get("departure_date", "")
            dep = _parse_date(dep_str)
            if dep and today < dep <= future_limit:
                route = entry.get("route", {})
                if isinstance(route, dict):
                    from_loc = route.get("from", "")
                    to_loc = route.get("to", "")
                else:
                    from_loc = to_loc = ""
                airline = entry.get("airline", "")
                flight_num = entry.get("flightNumber", "")
                upcoming_flights.append({
                    "date": dep,
                    "from": from_loc,
                    "to": to_loc,
                    "airline": airline,
                    "flightNumber": flight_num,
                })

    # Sort
    upcoming_hotels.sort(key=lambda x: x["checkin"])
    upcoming_flights.sort(key=lambda x: x["date"])

    lines = []

    if current_hotels:
        h = current_hotels[0]  # Use most recent/relevant
        lines.append(f"🏨 Current hotel: {h['name']}")
        if h["location"]:
            lines.append(f"   Location: {h['location']}")
        if h["address"] and h["address"] != h["name"]:
            lines.append(f"   Address: {h['address']}")
        lines.append(f"   Check-in: {h['checkin']} | Check-out: {h['checkout']}")
        if h.get("bookingRef"):
            lines.append(f"   Booking ref: {h['bookingRef']}")
    else:
        lines.append("🏨 No active hotel booking today")

    if upcoming_hotels:
        lines.append("")
        lines.append("🏨 Upcoming hotels:")
        for h in upcoming_hotels:
            checkout_str = h["checkout"].isoformat() if h["checkout"] else "?"
            line = f"   • {h['name']}"
            if h["location"]:
                line += f" in {h['location']}"
            line += f": {h['checkin']} → {checkout_str}"
            lines.append(line)
            if h["address"] and h["address"] != h["name"]:
                lines.append(f"     Address: {h['address']}")

    if upcoming_flights:
        lines.append("")
        lines.append("✈️ Upcoming flights:")
        for f in upcoming_flights:
            parts = [f"   • {f['date']}:"]
            if f["from"] or f["to"]:
                parts.append(f"{f['from']} → {f['to']}")
            if f["airline"]:
                parts.append(f"({f['airline']} {f['flightNumber']})")
            lines.append(" ".join(parts))

    return "\n".join(lines)


def get_tools() -> list:
    return [
        ToolEntry(
            name="get_trip_context",
            schema={
                "name": "get_trip_context",
                "description": (
                    "Returns the user's current and upcoming hotel/accommodation bookings and flights. "
                    "ALWAYS call this tool first when the user asks about: routes, transport, directions, "
                    "getting from A to B, how to get somewhere, navigation, airport transfers, "
                    "or any travel logistics questions. This provides the user's actual hotel address "
                    "so you can give personalized directions FROM their accommodation."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            handler=lambda ctx, **kw: get_trip_context(**kw),
            timeout_sec=15,
        ),
    ]
