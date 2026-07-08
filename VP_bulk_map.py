import pandas as pd
import folium 
import geopandas as gpd
from shapely.geometry import LineString, Polygon
from folium.plugins import GroupedLayerControl
import os


def get_encounter_events(df, dist_threshold_meters=500, time_threshold_hours=2):
    """
    Optimized version using Spatial Joins instead of nested loops.
    """
    if df.empty or 'vessel_id' not in df.columns:
        return gpd.GeoDataFrame(columns=['geometry', 'popup_text'], crs="EPSG:4326")


    # 1. Prepare and project to metric CRS
    gdf = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")
    gdf_metric = gdf.to_crs("EPSG:32634")
    gdf_metric['date'] = pd.to_datetime(gdf_metric['date'])
    
    # Keep only columns we absolutely need to save memory
    cols = ['vessel_id', 'ship_name', 'date', 'geometry']
    gdf_metric = gdf_metric[cols]


    # 2. Add a search buffer to one side of the join
    gdf_buffered = gdf_metric.copy()
    gdf_buffered['geometry'] = gdf_buffered.geometry.buffer(dist_threshold_meters)


    # 3. Spatial Join: Find points that are within 'dist_threshold_meters' of each other
    # This replaces the double loop entirely
    spatial_join = gpd.sjoin(gdf_metric, gdf_buffered, how='inner', predicate='within')


    # 4. Filter out self-joins and duplicates (v1 < v2 ensures we only check pairs once)
    pairs = spatial_join[spatial_join['vessel_id_left'] < spatial_join['vessel_id_right']].copy()
    if pairs.empty:
        return gpd.GeoDataFrame(columns=['geometry', 'popup_text'], crs="EPSG:4326")


    # 5. Vectorized Time Window Filter (Max 30 mins apart)
    pairs['time_diff'] = (pairs['date_left'] - pairs['date_right']).abs()
    close_pairs = pairs[pairs['time_diff'] <= pd.Timedelta(minutes=30)].copy()
    if close_pairs.empty:
        return gpd.GeoDataFrame(columns=['geometry', 'popup_text'], crs="EPSG:4326")


    # 6. Group consecutive moments into events using Pandas
    # Create a unique key for each vessel pair
    close_pairs['pair_id'] = close_pairs['vessel_id_left'].astype(str) + "_" + close_pairs['vessel_id_right'].astype(str)
    close_pairs = close_pairs.sort_values(['pair_id', 'date_left'])
    
    # Identify gaps > 1 hour between consecutive points in a pair interaction
    close_pairs['time_gap'] = close_pairs.groupby('pair_id')['date_left'].diff()
    close_pairs['group'] = (close_pairs['time_gap'] > pd.Timedelta(hours=1)).cumsum()


    # 7. Aggregate events
    raw_encounters = []
    # Aggregate by both pair and group
    grouped = close_pairs.groupby(['pair_id', 'group'])
    
    for _, grp in grouped:
        start = grp['date_left'].min()
        end = grp['date_left'].max()
        dur = (end - start).total_seconds() / 3600
        
        if dur >= time_threshold_hours:
            # Pick a middle point for the geometry representation
            mid_idx = len(grp) // 2
            raw_encounters.append({
                'v1': grp.iloc[mid_idx]['ship_name_left'],
                'v2': grp.iloc[mid_idx]['ship_name_right'],
                'start': start,
                'end': end,
                'duration': round(dur, 2),
                'geom': grp.iloc[mid_idx]['geometry'] # left side point geometry
            })

    if not raw_encounters:
        # Match your original empty structure
        return gpd.GeoDataFrame(columns=['geometry', 'popup_text'], crs="EPSG:4326")


    # 8. Final Clustered Popup Construction (Keeping your original logic structure)
    temp_gdf = gpd.GeoDataFrame(raw_encounters, geometry='geom', crs="EPSG:32634")
    final_data = []
    
    for _, row in temp_gdf.groupby(temp_gdf.geometry.buffer(500).to_wkt()):
        popup_lines = []
        for _, enc in row.iterrows():
            line = f"<b>{enc['v1']}</b> & <b>{enc['v2']}</b><br>" \
                   f"Start: {enc['start'].strftime('%Y-%m-%d %H:%M')}<br>" \
                   f"End: {enc['end'].strftime('%Y-%m-%d %H:%M')}<br>" \
                   f"Duration: {enc['duration']}h<br>---"
            popup_lines.append(line)
        
        final_data.append({
            'geometry': row.iloc[0]['geom'],
            'popup_text': "<br>".join(popup_lines)
        })

    return gpd.GeoDataFrame(final_data, crs="EPSG:32634").to_crs("EPSG:4326")

def create_bulk_map(df, buffer_dis=3, filter_type="All Vessels", progress_callback=None):
    df = df.copy()

    def update_progress(text, value):
        if progress_callback:
            progress_callback(text, value)

    if filter_type == "Trawlers Only":
        df = df[df['gear_type'].str.upper() == 'TRAWLERS']

    standard_crs = "EPSG:4326"
    metric_crs = "EPSG:32634" 
    

    # 1. Load Base Layers
    update_progress("Preparing vessel data...", 0.1)
    greece_eez_gdf = gpd.read_file('map_files/greek_eez.json').to_crs(standard_crs)
    italy_eez_gdf = gpd.read_file('map_files/italy_eez.geojson').to_crs(standard_crs)
    ais_buffer_gdf = gpd.read_file(f'map_files/ais_buffer_{buffer_dis}nm.geojson').to_crs(standard_crs)
    mlt_territorial_waters = gpd.read_file(f'map_files/mlt_national_waters.geojson').to_crs(standard_crs)
    mlt_FMZ_waters = gpd.read_file(f'map_files/mlt_FMZ_waters.geojson').to_crs(standard_crs)
    ita_territorial_waters = gpd.read_file(f'map_files/ita_national_waters.geojson').to_crs(standard_crs)
    grc_territorial_waters = gpd.read_file(f'map_files/grc_territorial_waters.geojson').to_crs(standard_crs)
    tur_territorial_waters = gpd.read_file(f'map_files/tur_national_waters.geojson').to_crs(standard_crs)
    
    # Load Protected Area Layers
    update_progress("Preparing vessel data...", 0.2)
    marine_park_alonnisos = gpd.read_file('map_files/MarineNationalPark_AlonnisosNorthernSporades.shp').to_crs(standard_crs)
    no_trawl_zone = gpd.read_file('map_files/MarineNationalPark_AlonnisosNorthernSporades_NoTrawlingZone.shp').to_crs(standard_crs)
    marine_park_zakynthos = gpd.read_file('map_files/MarineNationalPark_Kakinthos.shp').to_crs(standard_crs)
    natura_2000_sites = gpd.read_file('map_files/Natura200_end2020_epsg3035_Greece_HabitatDirective.shp').to_crs(standard_crs)

    for col in natura_2000_sites.columns:
        if pd.api.types.is_datetime64_any_dtype(natura_2000_sites[col]):
            natura_2000_sites[col] = natura_2000_sites[col].astype(str)

    
    # 2. Data Preparation
    update_progress("Preparing vessel data...", 0.3)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['vessel_id', 'date'])
    df['datetime_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
    
    raw_gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=standard_crs)
    res = gpd.sjoin(raw_gdf, ais_buffer_gdf, how="left", predicate="within")
    raw_gdf['is_inside'] = ~res['index_right'].isna()
    raw_gdf['point_status'] = 'green'


    # 3. Add base maps 
    update_progress("Adding base maps...", 0.4)
    m = folium.Map(location=[38.0, 24.5], zoom_start=6, tiles=None, prefer_canvas=True)
    
    # Define your Base Maps as Folium TileLayers
    tile_esri_light = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Light Gray",
        name="Esri Light Gray",
        overlay=False, # Tells Folium it's a base map
        control=True
    ).add_to(m)

    tile_world_imagery = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Esri World Imagery",
        overlay=False,
        control=True
    ).add_to(m)

    # Base maps list for the controller
    basemap_layers = [tile_esri_light, tile_world_imagery]
    

    # 4. Read environment layers from map_files and add to map
    update_progress("Adding environment layers...", 0.5)
    base_layers = []
    expanded_lat_lons = [
        (11.0, 33.0),   # Bottom Left: South of Ionian Sea / Malta
        (30.5, 33.0),   # Bottom Right: South of Antalya
        (30.5, 36.5),   # Right Pivot: Near Antalya
        (26.5, 41.5),   # Right Diagonal: To Edirne region
        (22.0, 41.5),   # Top Left: Northern edge (Shortened to allow for the left diagonal)
        (11.0, 36.5),   # Left Pivot: Near Malta / Ionian Sea (Mirrors Antalya)
        (11.0, 33.0)    # Closing the loop
    ]
    expanded_poly = Polygon(expanded_lat_lons)
    expanded_region_gdf = gpd.GeoDataFrame(index=[0], crs=standard_crs, geometry=[expanded_poly])

    # Search Area 
    base_layers.append(folium.GeoJson(expanded_region_gdf, name="Search Area (GFW download region)",
        style_function=lambda x: {"fillColor": "none", "fillOpacity": 0, "color": "black", "weight": 1, "dashArray": "5, 5"}).add_to(m))
    
    # Greek EEZ
    base_layers.append(folium.GeoJson(greece_eez_gdf, name="Greek EEZ", 
        style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}).add_to(m))
    
    # Italian EEZ
    base_layers.append(folium.GeoJson(italy_eez_gdf, name="Italian EEZ", show=False, 
        style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}).add_to(m))
    
    update_progress("Adding environment layers...", 0.6)
    # AIS Buffer Zone
    base_layers.append(folium.GeoJson(ais_buffer_gdf, name=f"{buffer_dis}NM AIS signal Buffer Zone",
        style_function=lambda x: {"fillColor": "red", "color": "red", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    
    # Malta territorial waters 
    base_layers.append(folium.GeoJson(mlt_territorial_waters, name="Malta Territorial Waters",
        style_function=lambda x: {"fillColor": "none", "color": "yellow", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    
    # Italy territorial waters
    base_layers.append(folium.GeoJson(ita_territorial_waters, name="Italy Territorial Waters",
        style_function=lambda x: {"fillColor": "none", "color": "orange", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    
    # Greece territorial waters
    base_layers.append(folium.GeoJson(grc_territorial_waters, name="Greece Territorial Waters",
        style_function=lambda x: {"fillColor": "none", "color": "orange", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    update_progress("Adding environment layers...", 0.65)
    # Turkey territorial waters
    base_layers.append(folium.GeoJson(tur_territorial_waters, name="Turkey Territorial Waters",
        style_function=lambda x: {"fillColor": "none", "color": "yellow", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    
    # Malta Fisheries Management Zone (FMZ) Waters
    base_layers.append(folium.GeoJson(mlt_FMZ_waters, name="Malta FMZ Waters",
        style_function=lambda x: {"fillColor": "none", "color": "#85DFE6", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))


    # Add Protected Area Layers 
    update_progress("Adding protected areas...", 0.7)
    protected_layers = []
    pa_configs = [
        (marine_park_alonnisos, "MNP Alonnisos Sporades", "teal", False),
        (marine_park_zakynthos, "MNP Zakynthos", "teal", False),
        (natura_2000_sites, "Natura 2000 Sites", "teal", False),
        (no_trawl_zone, "No Trawling Zone (Alonnisos)", "darkred", True)
    ]
    update_progress("Adding protected areas...", 0.75)
    for pgdf, name, color, is_dashed in pa_configs:
        style = {'fillColor': color, 'color': color, 'fillOpacity': 0.1, 'weight': 2}
        if is_dashed: style['dashArray'] = '5, 5'
        protected_layers.append(folium.GeoJson(pgdf, name=name, style_function=lambda x, s=style: s, tooltip=name).add_to(m))


    # 5. Process each vessel individually
    update_progress("Adding protected areas...", 0.8)
    vessel_groups_dict = {}
    line_kwds = {"weight": 2, "opacity": 0.8, "dashArray": "2, 5"}

    for vessel_id, v_data in raw_gdf.groupby('vessel_id'):
        v_data = v_data.sort_values('date').reset_index(drop=True)
        ship_name = str(v_data.iloc[0]['ship_name']) if pd.notnull(v_data.iloc[0]['ship_name']) else "Unknown"
        mmsi = str(int(v_data.iloc[0]['mmsi'])) if pd.notnull(v_data.iloc[0]['mmsi']) else "N/A"
        flag_iso = str(v_data.iloc[0]['flag']).upper().strip() if 'flag' in v_data.columns and pd.notnull(v_data.iloc[0]['flag']) else "UNKNOWN"
        
        # layer_display_name = f"{ship_name} ({mmsi})"
        layer_display_name = f"[{flag_iso}] {ship_name} ({mmsi})"
        v_group = folium.FeatureGroup(name=layer_display_name)
        
        # Segment logic
        v_data['gap_hours'] = v_data['date'].diff().dt.total_seconds() / 3600
        
        green_lines, orange_lines, red_lines = [], [], []
        
        for i in range(1, len(v_data)):
            p1, p2 = v_data.iloc[i-1], v_data.iloc[i]
            gap = p2['gap_hours']
            line = LineString([p1.geometry, p2.geometry])
            
            if gap > 3:
                is_suspicious = (not p1['is_inside']) and (not p2['is_inside'])
                status = 'red' if is_suspicious else 'orange'
                
                gap_data = {
                    'geometry': line,
                    'duration': round(gap, 2),
                    'start': p1['datetime_str'],
                    'end': p2['datetime_str']
                }
                if status == 'orange': orange_lines.append(gap_data)
                else: red_lines.append(gap_data)
                
                # Update status for points
                for idx in [i-1, i]:
                    current = v_data.at[idx, 'point_status']
                    if status == 'red' or current == 'green':
                        v_data.at[idx, 'point_status'] = status
            else:
                green_lines.append(line)

        # Add tracks to vessel group
        for lines, track_type, color in [(green_lines, "Normal", "green"), (orange_lines, "Gap", "orange"), (red_lines, "Suspicious", "red")]:
            if lines:
                if track_type == 'Normal':
                    data = gpd.GeoDataFrame(geometry=lines, crs=standard_crs)
                    popup = None
                else:
                    data = gpd.GeoDataFrame(lines, crs=standard_crs)
                    popup = folium.GeoJsonPopup(fields=['duration', 'start', 'end'], aliases=['Gap Hours', 'Start', 'End'])
                
                folium.GeoJson(
                    data, 
                    name=f"{track_type} Track",
                    popup=popup, 
                    tooltip=f'{track_type} Segment' if track_type != 'Normal' else None,
                    style_function=lambda x, c=color: {**line_kwds, "color": c}
                ).add_to(v_group)

        # Aggregate and add pings for this vessel
        v_agg = v_data.groupby(['lon', 'lat']).agg({
            'datetime_str': lambda x: " • " + " <br> • ".join(x),
            'ship_name': 'first',
            'mmsi': 'first',
            'point_status': lambda x: 'red' if 'red' in x.values else ('orange' if 'orange' in x.values else 'green'),
            'date': 'count' 
        }).reset_index().rename(columns={'date': 'pings_at_loc'})
        v_agg_gdf = gpd.GeoDataFrame(v_agg, geometry=gpd.points_from_xy(v_agg.lon, v_agg.lat), crs=standard_crs)

        for color, p_status, rad in [('green', 'green', 1), ('orange', 'orange', 1.5), ('red', 'red', 1.5)]:
            subset = v_agg_gdf[v_agg_gdf['point_status'] == p_status]
            if not subset.empty:
                folium.GeoJson(
                    subset, 
                    name=f"Pings: {p_status}",
                    marker=folium.CircleMarker(radius=rad, fill=True, color=color, fillColor=color),
                    popup=folium.GeoJsonPopup(fields=["ship_name", "datetime_str", "mmsi", "pings_at_loc"])
                ).add_to(v_group)

        vessel_groups_dict[layer_display_name] = v_group

    vessel_layers = []
    for sorted_name in sorted(vessel_groups_dict.keys()):
        group = vessel_groups_dict[sorted_name]
        group.add_to(m)
        vessel_layers.append(group)


    # 6. Generate Encounter Events
    update_progress("Calculating encounter events...", 0.85)
    encounter_gdf = get_encounter_events(df)
    encounter_layers = []
    
    if not encounter_gdf.empty:
        enc_outside = gpd.sjoin(encounter_gdf, ais_buffer_gdf, how="left", predicate="within")
        encounter_gdf = enc_outside[enc_outside['index_right'].isna()].copy()

        if not encounter_gdf.empty:
            enc_group = folium.FeatureGroup(name="Encounter Events")
            
            for _, row in encounter_gdf.iterrows():
                folium.CircleMarker(
                    location=[row.geometry.y, row.geometry.x],
                    radius=8,
                    color='purple',
                    fill=True,
                    fillColor='purple',
                    fillOpacity=0.7,
                    tooltip="Encounter Event",
                    popup=folium.Popup(row['popup_text'], max_width=400)
                ).add_to(enc_group)
            
            enc_group.add_to(m)
            encounter_layers.append(enc_group)


    # 7. Add Layer Control with Grouping
    update_progress("Calculating encounter events...", 0.9)
    GroupedLayerControl(
        groups={
            'Base Map': basemap_layers,
            'Environment': base_layers, 
            'Protected Areas': protected_layers, 
            'Events': encounter_layers,
            'Vessels': vessel_layers
        },
        exclusive_groups=False, 
        collapsed=False
    ).add_to(m)


    # 8. Inject CSS & JS for scrolling, UI controls, and DYNAMIC ZOOM RESIZING
    custom_macro = """
    <style>
    .leaflet-control-layers-expanded {
        max-height: 600px !important;
        overflow-y: auto !important;
        background-color: white;
    }
    .toggle-all-container {
        padding: 8px 0;
        border-bottom: 1px solid #ccc;
        margin-bottom: 5px;
        display: flex;
        gap: 5px;
    }
    .toggle-all-btn {
        background-color: #f8f9fa;
        border: 1px solid #ced4da;
        border-radius: 4px;
        cursor: pointer;
        font-size: 10px;
        font-weight: 700;
        padding: 6px 0;
        flex: 1;
        color: #495057;
        text-align: center;
        transition: all 0.2s;
    }
    .toggle-all-btn:hover { background-color: #e9ecef; border-color: #adb5bd; }
    .toggle-all-btn:active { background-color: #dee2e6; }
    </style>
    
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        // --- 1. EXISTING SELECT/DESELECT UI LOGIC ---
        var layersControl = document.querySelector('.leaflet-control-layers');
        if (layersControl) {
            L.DomEvent.disableScrollPropagation(layersControl);
            var groups = document.querySelectorAll('.leaflet-control-layers-group');
            var vesselGroup = Array.from(groups).find(g => g.innerText.includes('Vessels'));

            if (vesselGroup) {
                var container = document.createElement('div');
                container.className = 'toggle-all-container';
                
                var btnSelect = document.createElement('button');
                btnSelect.type = 'button'; 
                btnSelect.innerHTML = 'SELECT ALL';
                btnSelect.className = 'toggle-all-btn';
                
                var btnDeselect = document.createElement('button');
                btnDeselect.type = 'button'; 
                btnDeselect.innerHTML = 'DESELECT ALL';
                btnDeselect.className = 'toggle-all-btn';
                
                var setAllVessels = function(e, shouldBeVisible) {
                    if (e) {
                        e.preventDefault(); 
                        e.stopPropagation();
                    }
                    var checkboxes = vesselGroup.querySelectorAll('input[type="checkbox"]');
                    checkboxes.forEach(function(cb) {
                        if (cb.checked !== shouldBeVisible) {
                            cb.click();
                        }
                    });
                };

                btnSelect.onclick = function(e) { setAllVessels(e, true); };
                btnDeselect.onclick = function(e) { setAllVessels(e, false); };
                container.appendChild(btnSelect);
                container.appendChild(btnDeselect);
                
                var label = vesselGroup.querySelector('.leaflet-control-layers-group-name');
                label.parentNode.insertBefore(container, label.nextSibling);
            }
        }

        // --- 2. NEW DYNAMIC ZOOM RESIZING LOGIC ---
        // Find the Leaflet map object instantiated by folium
        var mapElement = document.querySelector('.leaflet-container');
        if (mapElement && mapElement._leaflet_id) {
            // Retrieve map instance via internal reference safely
            var mapKey = Object.keys(window).find(k => window[k] instanceof L.Map);
            var map = window[mapKey];

            if (map) {
                function updateLayerSizes() {
                    var currentZoom = map.getZoom();
                    
                    // Define rules based on zoom level
                    // Higher zoom = larger display dimensions
                    var pingRadius, lineWeight, encounterRadius;
                    
                    if (currentZoom <= 5) {
                        pingRadius = 0.5;
                        lineWeight = 1;
                        encounterRadius = 3;
                    } else if (currentZoom == 6) {
                        pingRadius = 1;
                        lineWeight = 1.5;
                        encounterRadius = 6;
                    } else if (currentZoom == 7) {
                        pingRadius = 1.5;
                        lineWeight = 2;
                        encounterRadius = 9;
                    } else if (currentZoom == 8) {
                        pingRadius = 2;
                        lineWeight = 2.5;
                        encounterRadius = 16;
                    } else { // Zoom 9+
                        pingRadius = 2;
                        lineWeight = 2.5;
                        encounterRadius = 18;
                    }

                    // Iterate over every path layer drawn onto the canvas
                    map.eachLayer(function(layer) {
                        if (layer.setStyle) {
                            // Check the visual markers by looking up their popup features or structure
                            if (layer.options && layer.options.radius) {
                                // Differentiate Encounter events (purple) from regular pings
                                if (layer.options.fillColor === 'purple') {
                                    layer.setRadius(encounterRadius);
                                } else {
                                    layer.setRadius(pingRadius);
                                }
                            } else {
                                // It's a line/track segment (Normal, Gap, Suspicious tracks)
                                // We keep environmental bounds fixed, only altering tracks
                                if (layer.options && (layer.options.color === 'green' || layer.options.color === 'orange' || layer.options.color === 'red')) {
                                    layer.setStyle({ weight: lineWeight });
                                }
                            }
                        }
                    });
                }

                // Run on map load and attach to zoom events
                map.on('zoomend', updateLayerSizes);
                updateLayerSizes(); 
            }
        }
    });
    </script>
    """
    m.get_root().header.add_child(folium.Element(custom_macro))

    update_progress("Saving map to folder...", 0.95)
    output_path = "AIS_gap_map_allvessels.html"
    m.save(output_path)
    return output_path