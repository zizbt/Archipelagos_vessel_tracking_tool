import os
import pandas as pd
import numpy as np
import geopandas as gpd
import folium
from folium.plugins import GroupedLayerControl
import html as html_lib

def haversine_meters(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points GPS (vectorisé)."""
    R = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))

def get_loitering_events(df, speed_threshold_knots=1.5, min_duration_hours=4,
                          max_gap_hours=1, progress_callback=None):
    """
    Detecte les periodes ou un navire reste globalement immobile
    (vitesse faible) pendant une duree prolongee.
    """
    if df.empty or 'vessel_id' not in df.columns:
        return pd.DataFrame()

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['vessel_id', 'date'])

    events = []
    vessel_groups = list(df.groupby('vessel_id'))

    for idx, (vessel_id, v_data) in enumerate(vessel_groups):
        if progress_callback:
            progress_callback(f"Analyzing vessel {idx+1}/{len(vessel_groups)}...",
                               0.1 + 0.7 * (idx / max(len(vessel_groups), 1)))

        v_data = v_data.reset_index(drop=True)
        if len(v_data) < 2:
            continue

        # Distance et temps entre points consecutifs
        lat1 = v_data['lat'].values[:-1]
        lon1 = v_data['lon'].values[:-1]
        lat2 = v_data['lat'].values[1:]
        lon2 = v_data['lon'].values[1:]
        dist_m = haversine_meters(lat1, lon1, lat2, lon2)
        time_diff_h = (v_data['date'].values[1:] - v_data['date'].values[:-1]) / np.timedelta64(1, 'h')
        time_diff_h = np.where(time_diff_h == 0, 1e-6, time_diff_h)

        speed_knots = (dist_m / 1852) / time_diff_h  # noeuds

        # Un point est "lent" si le segment qui le precede est lent
        is_slow = np.append([False], speed_knots <= speed_threshold_knots)
        # Une grosse coupure AIS casse la continuite de l'evenement
        is_gap = np.append([False], time_diff_h > max_gap_hours)

        v_data['is_slow'] = is_slow
        v_data['is_gap'] = is_gap

        # Grouper les points lents consecutifs (sans coupure)
        v_data['group_break'] = (~v_data['is_slow']) | v_data['is_gap']
        v_data['group_id'] = v_data['group_break'].cumsum()

        for gid, grp in v_data[v_data['is_slow']].groupby('group_id'):
            if len(grp) < 2:
                continue
            start = grp['date'].min()
            end = grp['date'].max()
            dur_h = (end - start).total_seconds() / 3600
            if dur_h < min_duration_hours:
                continue

            centroid_lat = grp['lat'].mean()
            centroid_lon = grp['lon'].mean()
            max_radius_m = haversine_meters(
                centroid_lat, centroid_lon, grp['lat'].values, grp['lon'].values
            ).max()
            speeds = [speed_knots[i-1] for i in grp.index if 0 <= i-1 < len(speed_knots)]
            avg_speed = round(float(np.nanmean(speeds)), 2) if speeds else 0.0

            events.append({
                'vessel_id': vessel_id,
                'ship_name': grp['ship_name'].iloc[0] if 'ship_name' in grp.columns else 'Unknown',
                'mmsi': grp['mmsi'].iloc[0] if 'mmsi' in grp.columns else 'Unknown',
                'vessel_type': grp['vessel_type'].iloc[0] if 'vessel_type' in grp.columns else 'Unknown',
                'gear_type': grp['gear_type'].iloc[0] if 'gear_type' in grp.columns else 'Unknown',
                'flag': grp['flag'].iloc[0] if 'flag' in grp.columns else 'Unknown',
                'start': start,
                'end': end,
                'duration_hours': round(dur_h, 2),
                'n_pings': len(grp),
                'centroid_lat': centroid_lat,
                'centroid_lon': centroid_lon,
                'max_radius_m': round(max_radius_m, 1),
                'avg_speed_knots': avg_speed,
            })

    if progress_callback:
        progress_callback("Loitering analysis complete", 0.85)

    return pd.DataFrame(events)

def clean(val):
    if pd.isna(val):
        return "Unknown"
    s = html_lib.escape(str(val), quote=True)
    s = s.replace("`", "")      # backtick : casse le JS (template literal)
    s = s.replace("\\", "")     # backslash : echappement JS
    s = s.replace("\n", " ").replace("\r", " ")
    return s

def create_loitering_map(df, speed_threshold_knots=1.5, min_duration_hours=4,
                          filter_type="All Vessels", progress_callback=None):
    """
    Genere une carte interactive des zones de loitering detectees,
    et renvoie (chemin_html, dataframe_evenements).
    """
    def update_progress(text, value):
        if progress_callback:
            progress_callback(text, value)

    df = df.copy()
    if filter_type == "Trawlers Only" and 'gear_type' in df.columns:
        df = df[df['gear_type'].str.upper() == 'TRAWLERS']

    # 1. Detecter les evenements de loitering EN PREMIER
    update_progress("Detecting loitering events...", 0.05)
    events_df = get_loitering_events(
        df, speed_threshold_knots=speed_threshold_knots,
        min_duration_hours=min_duration_hours,
        progress_callback=update_progress
    )

    # 2. Verifier la distance a la cote (seulement si on a des evenements)
    update_progress("Checking distance to coast...", 0.87)
    if not events_df.empty:
        try:
            coast_layers = []
            for fname in ['grc_territorial_waters.geojson', 'ita_national_waters.geojson',
                          'tur_national_waters.geojson', 'mlt_national_waters.geojson']:
                path = f'map_files/{fname}'
                if os.path.exists(path):
                    coast_layers.append(gpd.read_file(path).to_crs("EPSG:4326"))

            if coast_layers:
                coastline = pd.concat(coast_layers, ignore_index=True)
                coastline_metric = gpd.GeoDataFrame(coastline, geometry='geometry', crs="EPSG:4326").to_crs("EPSG:32634")
                coastline_boundary = coastline_metric.geometry.boundary.union_all()

                pts = gpd.GeoDataFrame(
                    events_df,
                    geometry=gpd.points_from_xy(events_df['centroid_lon'], events_df['centroid_lat']),
                    crs="EPSG:4326"
                ).to_crs("EPSG:32634")

                events_df['distance_to_coast_nm'] = pts.geometry.distance(coastline_boundary) / 1852
                events_df['likely_in_port'] = events_df['distance_to_coast_nm'] < 1.0
            else:
                events_df['distance_to_coast_nm'] = None
                events_df['likely_in_port'] = False
        except Exception:
            events_df['distance_to_coast_nm'] = None
            events_df['likely_in_port'] = False

    # 3. Construire la carte
    update_progress("Building map...", 0.9)
    m = folium.Map(location=[38.0, 24.5], zoom_start=6, tiles=None, prefer_canvas=True)

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Light Gray", name="Esri Light Gray", overlay=False, control=True
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Esri World Imagery", overlay=False, control=True
    ).add_to(m)

    if not events_df.empty:
        loiter_group = folium.FeatureGroup(name="Loitering Events")
        for _, row in events_df.iterrows():
            is_port = bool(row.get('likely_in_port', False))
            color = '#888888' if is_port else '#FF1493'
            port_flag_text = "Likely in port" if is_port else "Open sea / suspicious"

            popup_html = (
                f"<b>{clean(row['ship_name'])}</b> (MMSI {clean(row['mmsi'])})<br>"
                f"Type: {clean(row['vessel_type'])} | Gear: {clean(row['gear_type'])}<br>"
                f"{port_flag_text}<br>"
                f"Start: {row['start'].strftime('%Y-%m-%d %H:%M')}<br>"
                f"End: {row['end'].strftime('%Y-%m-%d %H:%M')}<br>"
                f"Duration: {row['duration_hours']}h<br>"
                f"Radius: {row['max_radius_m']}m<br>"
                f"Pings: {row['n_pings']}"
            )
            prefix = "[Port] " if is_port else ""
            tooltip_text = f"{prefix}{clean(row['ship_name'])} ({row['duration_hours']}h)"

            folium.Circle(
                location=[row['centroid_lat'], row['centroid_lon']],
                radius=float(max(row['max_radius_m'], 200)),
                color=color,
                fill=True,
                fillColor=color,
                fillOpacity=0.3,
                tooltip=tooltip_text,
                popup=folium.Popup(popup_html, max_width=350)
            ).add_to(loiter_group)
        loiter_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    update_progress("Saving map...", 0.97)
    output_path = "loitering_map.html"
    m.save(output_path)
    return output_path, events_df

def get_loitering_dataframe(events_df):
    """
    Retourne un DataFrame propre et ordonne pour export, sans rien ecrire sur le disque.
    """
    if events_df is None or events_df.empty:
        return None

    cols = ['ship_name', 'mmsi', 'vessel_type', 'gear_type', 'flag',
            'start', 'end', 'duration_hours', 'n_pings',
            'centroid_lat', 'centroid_lon', 'max_radius_m', 'avg_speed_knots',
            'distance_to_coast_nm', 'likely_in_port']
    cols = [c for c in cols if c in events_df.columns]
    return events_df[cols].sort_values('start')