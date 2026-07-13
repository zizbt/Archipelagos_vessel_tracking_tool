import asyncio
import pandas as pd
import gfwapiclient as gfw


async def search_vessel(query, client):
    result = await client.vessels.search_vessels(
        query=query,
        datasets=["public-global-vessel-identity:latest"],
        includes=["OWNERSHIP"],
    )
    df = result.df()
    if df.empty:
        return df

    rows = []
    for _, r in df.iterrows():
        d = r.to_dict()

        # Les identités sont dans self_reported_info (liste de dicts)
        infos = d.get("self_reported_info") or d.get("selfReportedInfo")

        if isinstance(infos, list) and infos:
            for i in infos:
                rows.append({
                    "vessel_id": i.get("id"),
                    "ship_name": i.get("ship_name") or i.get("shipname"),
                    "mmsi": i.get("ssvid"),
                    "imo": i.get("imo"),
                    "flag": i.get("flag"),
                    "from": i.get("transmission_date_from"),
                    "to": i.get("transmission_date_to"),
                })
        else:
            # Fallback : structure déjà aplatie
            rows.append({
                "vessel_id": d.get("id"),
                "ship_name": d.get("ship_name") or d.get("shipname"),
                "mmsi": d.get("ssvid") or d.get("mmsi"),
                "imo": d.get("imo"),
                "flag": d.get("flag"),
                "from": d.get("transmission_date_from"),
                "to": d.get("transmission_date_to"),
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

    print("EVENT COLUMNS:", df.columns.tolist())
    print("PORT_VISIT SAMPLE:", df.iloc[0].get("port_visit"))
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
    df["duration_hrs"] = df["port_visit"].apply(
        lambda p: p.get("durationHrs") if isinstance(p, dict) else None
    )
    df["confidence"] = df["port_visit"].apply(
        lambda p: p.get("confidence") if isinstance(p, dict) else None
    )

    keep = ["vessel_id", "start", "end", "port_name", "port_flag",
            "duration_hrs", "confidence", "lat", "lon"]
    keep = [c for c in keep if c in df.columns]
    return df[keep].sort_values("start")


def generate_port_report(vessel_id, vessel_name, start, end, client,
                         progress_callback=None):
    if progress_callback:
        progress_callback("Fetching port visits...", 0.3)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    df = loop.run_until_complete(
        load_port_visits(vessel_id, start, end, client)
    )

    if progress_callback:
        progress_callback("Writing report...", 0.8)

    if df.empty:
        raise ValueError("No port visits found for this vessel/period.")

    df.insert(0, "ship_name", vessel_name)
    safe = "".join(c for c in str(vessel_name) if c.isalnum() or c in " _-").strip()
    out = f"PORT_visits_{safe}_{start}-{end}.csv"
    df.to_csv(out, index=False)
    return out, len(df)