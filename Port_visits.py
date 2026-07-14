import asyncio
from asyncio import events
import pandas as pd
import gfwapiclient as gfw
import tempfile
import os

async def search_vessel(query, client):
    result = await client.vessels.search_vessels(
        query=query,
        datasets=["public-global-vessel-identity:latest"],
        includes=["OWNERSHIP", "MATCH_CRITERIA"],
    )
    df = result.df()
    if df.empty:
        return df

    def _d(x):
        """Pydantic -> dict si besoin."""
        if hasattr(x, "model_dump"):
            return x.model_dump()
        return x if isinstance(x, dict) else {}

    rows = []
    for _, r in df.iterrows():
        d = r.to_dict()

        owners = d.get("registry_owners") or []
        owner_name = _d(owners[-1]).get("name") if owners else None

        registry = d.get("registry_info") or []
        reg = _d(registry[-1]) if registry else {}
        reg_imo = reg.get("imo")
        reg_length = reg.get("length_m")
        reg_tonnage = reg.get("tonnage_gt")

        gear_by_vid, ship_by_vid = {}, {}
        any_gear = any_ship = None

        for c in (d.get("combined_sources_info") or []):
            c = _d(c)
            vid = c.get("vessel_id")
            gears = c.get("gear_types") or []
            ships = c.get("ship_types") or []
            if gears:
                g = _d(gears[-1]).get("name")
                gear_by_vid[vid] = g
                any_gear = any_gear or g
            if ships:
                s = _d(ships[-1]).get("name")
                ship_by_vid[vid] = s
                any_ship = any_ship or s

        for i in (d.get("self_reported_info") or []):
            i = _d(i)
            vid = i.get("id")
            rows.append({
                "vessel_id": vid,
                "ship_name": i.get("ship_name"),
                "mmsi": i.get("ssvid"),
                "imo": i.get("imo") or reg_imo,
                "call_sign": i.get("call_sign"),
                "flag": i.get("flag"),
                "vessel_type": ship_by_vid.get(vid),
                "gear_type": gear_by_vid.get(vid),
                "length_m": reg_length,
                "tonnage_gt": reg_tonnage,
                "owner": owner_name,
                "from": i.get("transmission_date_from"),
                "to": i.get("transmission_date_to"),
            })

    out = pd.DataFrame(rows)
    out = out[out["vessel_id"].notna()].drop_duplicates(subset=["vessel_id"])
    return out


async def load_port_visits(vessel_ids, start, end, client):
    if isinstance(vessel_ids, str):
        vessel_ids = [vessel_ids]

    events = await client.events.get_all_events(
        datasets=["public-global-port-visits-events:latest"],
        vessels=vessel_ids,
        start_date=start,
        end_date=end,
        limit=99999,
    )
    
    df = events.df()
    if df.empty:
        return df

    df = df.copy()
    df["_start"] = pd.to_datetime(df["start"], utc=True, errors="coerce")
    df["_end"] = pd.to_datetime(df["end"], utc=True, errors="coerce")
    df = df.sort_values("_start")

    # --- FILTER 1 : drop corrupted visits (exit never detected) ---
    # If a visit ends after the next one starts, its end date is wrong.
    corrupted = df["_end"] > df["_start"].shift(-1)
    df = df[~corrupted]
    if df.empty:
        return df

    # --- FILTER 2 : keep only visits overlapping the requested window ---
    win_start = pd.to_datetime(start, utc=True)
    win_end = pd.to_datetime(end, utc=True) + pd.Timedelta(days=1)

    overlaps = (df["_start"] < win_end) & (df["_end"] >= win_start)
    df = df[overlaps].drop(columns=["_start", "_end"])
    if df.empty:
        return df

    def _anchor(pv, key):
        if pv is None:
            return None
        # Objet Pydantic → dict
        if hasattr(pv, "model_dump"):
            pv = pv.model_dump()
        elif hasattr(pv, "dict"):
            pv = pv.dict()
        if not isinstance(pv, dict):
            return None
        a = (pv.get("intermediate_anchorage")
             or pv.get("intermediateAnchorage")
             or pv.get("start_anchorage")
             or pv.get("startAnchorage")
             or {})
        if hasattr(a, "model_dump"):
            a = a.model_dump()
        return a.get(key) if isinstance(a, dict) else None
    
    df["port_name"] = df["port_visit"].apply(lambda p: _anchor(p, "name"))
    df["port_flag"] = df["port_visit"].apply(lambda p: _anchor(p, "flag"))
    df["port_id"] = df["port_visit"].apply(lambda p: _anchor(p, "id"))

    def _field(pv, key):
        if hasattr(pv, "model_dump"):
            pv = pv.model_dump()
        return pv.get(key) if isinstance(pv, dict) else None

    df["duration_hrs"] = df["port_visit"].apply(lambda p: _field(p, "duration_hrs"))
    df["confidence"] = df["port_visit"].apply(lambda p: _field(p, "confidence"))

    # Dates lisibles
    df["start"] = pd.to_datetime(df["start"]).dt.strftime("%Y-%m-%d %H:%M")
    df["end"] = pd.to_datetime(df["end"]).dt.strftime("%Y-%m-%d %H:%M")
    df["duration_hrs"] = pd.to_numeric(df["duration_hrs"], errors="coerce").round(1)

    keep = ["start", "end", "port_name", "port_flag", "port_id",
            "duration_hrs", "confidence", "lat", "lon"]
    keep = [c for c in keep if c in df.columns]
    return df[keep].sort_values("start")


def generate_port_report(vessel_ids, vessel_name, start, end, client,
                         owner=None, mmsi=None, imo=None,
                         vessel_type=None, gear_type=None, length_m=None,
                         progress_callback=None):
    if progress_callback:
        progress_callback("Fetching port visits...", 0.3)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    df = loop.run_until_complete(
        load_port_visits(vessel_ids, start, end, client)
    )

    if progress_callback:
        progress_callback("Writing report...", 0.8)

    if df.empty:
        raise ValueError("No port visits found for this vessel/period.")

    df.insert(0, "length_m", length_m if length_m else "Unknown")
    df.insert(0, "gear_type", gear_type if gear_type else "Unknown")
    df.insert(0, "vessel_type", vessel_type if vessel_type else "Unknown")
    df.insert(0, "imo", imo if imo else "Unknown")
    df.insert(0, "mmsi", mmsi if mmsi else "Unknown")
    df.insert(0, "owner", owner if owner else "Unknown")
    df.insert(0, "ship_name", vessel_name)

    safe = "".join(c for c in str(vessel_name) if c.isalnum() or c in " _-").strip()

    tmp_dir = tempfile.gettempdir()
    out = os.path.join(tmp_dir, f"PORT_visits_{safe}_{start}-{end}.csv")

    df.to_csv(out, index=False)

    n_ports = df["port_name"].nunique()
    return out, len(df), n_ports