import pandas as pd
import folium 
import geopandas as gpd
from shapely.geometry import LineString
from shapely.geometry import Polygon
from folium.plugins import Search
from folium.plugins import GroupedLayerControl
import os
import sys


def get_vessel_data(df, vessel_id):
    """
    Selects a specific vessel by its ID and returns its chronologically sorted data.
    """
    # Create a dataframe for this specific vessel and sort by date 
    vessel_data = df[df['vessel_id'] == vessel_id].sort_values('date')
    
    if vessel_data.empty:
        raise ValueError(f"No data found for vessel ID: {vessel_id}")
        
    return vessel_data

def create_map(vessel_data, buffer_dis=3, progress_callback=None):
    vessel_data = vessel_data.copy()

    def update_progress(text, value):
        if progress_callback:
            progress_callback(text, value)

    # Setup and CRS
    standard_crs = "EPSG:4326"
    metric_crs = "EPSG:32634" 


    # 1. Data Preparation
    update_progress("Preparing vessel data...", 0.1)
    vessel_data['ship_name_clean'] = vessel_data['ship_name'].astype(str).str.strip().replace({'None': '', 'nan': '', '': None})
    vessel_data['vessel_label'] = vessel_data['ship_name_clean'].fillna(vessel_data['vessel_id'].astype(str).str[:8]) + " [" + vessel_data['flag'] + "]"
    target_label = vessel_data['vessel_label'].iloc[0] 

    # Load geospatial layers
    update_progress("Preparing vessel data...", 0.2)
    greece_eez_gdf = gpd.read_file('map_files/greek_eez.json').to_crs(standard_crs)
    italy_eez_gdf = gpd.read_file('map_files/italy_eez.geojson').to_crs(standard_crs)
    ais_buffer_gdf = gpd.read_file(f'map_files/ais_buffer_{buffer_dis}nm.geojson').to_crs(standard_crs)
    mlt_territorial_waters = gpd.read_file(f'map_files/mlt_national_waters.geojson').to_crs(standard_crs)
    mlt_FMZ_waters = gpd.read_file(f'map_files/mlt_FMZ_waters.geojson').to_crs(standard_crs)
    ita_territorial_waters = gpd.read_file(f'map_files/ita_national_waters.geojson').to_crs(standard_crs)
    grc_territorial_waters = gpd.read_file(f'map_files/grc_territorial_waters.geojson').to_crs(standard_crs)
    tur_territorial_waters = gpd.read_file(f'map_files/tur_national_waters.geojson').to_crs(standard_crs)

    update_progress("Preparing vessel data...", 0.3)
    vessel_data['date'] = pd.to_datetime(vessel_data['date'])
    vessel_data = vessel_data.sort_values('date')
    vessel_data['datetime_str'] = vessel_data['date'].dt.strftime('%Y-%m-%d %H:%M')
    vessel_data['gap_hours'] = vessel_data['date'].diff().dt.total_seconds() / 3600
    vessel_data['gap_hours'] = vessel_data['gap_hours'].fillna(0)

    raw_gdf = gpd.GeoDataFrame(
        vessel_data, 
        geometry=gpd.points_from_xy(vessel_data.lon, vessel_data.lat), 
        crs=standard_crs
    )

    res = gpd.sjoin(raw_gdf, ais_buffer_gdf, how="left", predicate="within")
    raw_gdf['is_inside'] = ~res['index_right'].isna()

    # 2. Analyze Segments
    raw_gdf['point_status'] = 'normal'
    green_lines, orange_lines, red_lines = [], [], []
    highlight_gaps_metadata = [] 

    for i in range(len(raw_gdf) - 1):
        p1 = raw_gdf.iloc[i]
        p2 = raw_gdf.iloc[i+1]
        gap = p2['gap_hours']
        line = LineString([p1.geometry, p2.geometry])
        
        if gap > 3:
            # Only suspicious if BOTH points are outside the buffer
            is_suspicious = (not p1['is_inside']) and (not p2['is_inside'])
            status = 'red' if is_suspicious else 'orange'
            
            if status == 'orange': 
                orange_lines.append(line)
            else: 
                red_lines.append(line)
                highlight_gaps_metadata.append({
                    'line': line,
                    'p1_geom': p1.geometry,
                    'p2_geom': p2.geometry,
                    'duration': gap,
                    'start': p1['datetime_str'],
                    'end': p2['datetime_str']
                })
            
            for idx in [raw_gdf.index[i], raw_gdf.index[i+1]]:
                current = raw_gdf.at[idx, 'point_status']
                if status == 'red' or current == 'normal':
                    raw_gdf.at[idx, 'point_status'] = status
        else:
            green_lines.append(line)


    # 3. Aggregation for standard points
    agg_df = raw_gdf.groupby(['lon', 'lat']).agg({
        'datetime_str': lambda x: " • " + " <br> • ".join(x),
        'ship_name': 'first',
        'mmsi': 'first',
        'point_status': lambda x: 'red' if 'red' in x.values else ('orange' if 'orange' in x.values else 'green'),
        'date': 'count' 
    }).reset_index().rename(columns={'date': 'pings_at_loc'})
    agg_gdf = gpd.GeoDataFrame(agg_df, geometry=gpd.points_from_xy(agg_df.lon, agg_df.lat), crs=standard_crs)


    # 4. Add base maps
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
    
    
    # 5. Inject custom CSS and JavaScript: Removes outline/box on click, styles popup spacing, and makes the Layer Control scrollable
    no_outline_style = """
    <style>
    path.leaflet-interactive:focus {
        outline: none;
    }
    .leaflet-popup-content {
        max-height: 300px;
        overflow-y: auto;
        line-height: 1.5;
    }
    .leaflet-control-layers-expanded {
        max-height: 600px !important;
        overflow-y: auto !important;
        background-color: white;
    }
    /* Toggle Button Styling */
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
    """
    m.get_root().header.add_child(folium.Element(no_outline_style))

    # JavaScript: Disables map zoom on scroll AND adds SELECT/DESELECT ALL buttons for gaps
    advanced_ui_js = """
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        var layersControl = document.querySelector('.leaflet-control-layers');
        if (layersControl) {
            // 1. Stop mouse wheel from zooming the map when scrolling the menu
            L.DomEvent.disableScrollPropagation(layersControl);
            
            // 2. Find all grouped layers sections
            var groups = document.querySelectorAll('.leaflet-control-layers-group');
            var gapGroup = Array.from(groups).find(g => g.innerText.includes('Highlight Suspicious Gaps'));

            if (gapGroup) {
                // Create button container
                var container = document.createElement('div');
                container.className = 'toggle-all-container';
                
                // Create SELECT ALL button
                var btnSelect = document.createElement('button');
                btnSelect.type = 'button'; 
                btnSelect.innerHTML = 'SELECT ALL';
                btnSelect.className = 'toggle-all-btn';
                
                // Create DESELECT ALL button
                var btnDeselect = document.createElement('button');
                btnDeselect.type = 'button'; 
                btnDeselect.innerHTML = 'DESELECT ALL';
                btnDeselect.className = 'toggle-all-btn';
                
                // Toggle logic function
                var setAllGaps = function(e, shouldBeVisible) {
                    if (e) {
                        e.preventDefault(); 
                        e.stopPropagation();
                    }
                    var checkboxes = gapGroup.querySelectorAll('input[type="checkbox"]');
                    checkboxes.forEach(function(cb) {
                        if (cb.checked !== shouldBeVisible) {
                            cb.click();
                        }
                    });
                };

                // Attach click handlers
                btnSelect.onclick = function(e) { setAllGaps(e, true); };
                btnDeselect.onclick = function(e) { setAllGaps(e, false); };
                
                container.appendChild(btnSelect);
                container.appendChild(btnDeselect);
                
                // Inject the buttons right below the "Highlight Suspicious Gaps" header text
                var label = gapGroup.querySelector('.leaflet-control-layers-group-name');
                if (label) {
                    label.parentNode.insertBefore(container, label.nextSibling);
                }
            }
        }
    });
    </script>
    """
    m.get_root().header.add_child(folium.Element(advanced_ui_js))


    # 6. Add Environment Layers
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
    update_progress("Adding environment layers...", 0.6)
    base_layers.append(folium.GeoJson(expanded_region_gdf, name="Search Area (GFW download region)",
        style_function=lambda x: {"fillColor": "none", "fillOpacity": 0, "color": "black", "weight": 1, "dashArray": "5, 5"}).add_to(m))
    
    # Greek EEZ
    base_layers.append(folium.GeoJson(greece_eez_gdf, name="Greek EEZ", 
        style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}).add_to(m))
    
    # Italian EEZ
    base_layers.append(folium.GeoJson(italy_eez_gdf, name="Italian EEZ", show=False,
        style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}).add_to(m))
    
    update_progress("Adding environment layers...", 0.65)
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
    
    update_progress("Adding environment layers...", 0.7)
    # Turkey territorial waters
    base_layers.append(folium.GeoJson(tur_territorial_waters, name="Turkey Territorial Waters",
        style_function=lambda x: {"fillColor": "none", "color": "yellow", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    
    # Malta Fisheries Management Zone (FMZ) Waters
    base_layers.append(folium.GeoJson(mlt_FMZ_waters, name="Malta FMZ Waters",
        style_function=lambda x: {"fillColor": "none", "color": "#85DFE6", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))

    # Protected Areas 
    update_progress("Adding protected areas...", 0.75)
    # Load protected area files
    marine_park_alonnisos = gpd.read_file('map_files/MarineNationalPark_AlonnisosNorthernSporades.shp').to_crs(standard_crs)
    no_trawl_zone = gpd.read_file('map_files/MarineNationalPark_AlonnisosNorthernSporades_NoTrawlingZone.shp').to_crs(standard_crs)
    marine_park_zakynthos = gpd.read_file('map_files/MarineNationalPark_Kakinthos.shp').to_crs(standard_crs)
    natura_2000_sites = gpd.read_file('map_files/Natura200_end2020_epsg3035_Greece_HabitatDirective.shp').to_crs(standard_crs)

    for col in natura_2000_sites.columns:
        if pd.api.types.is_datetime64_any_dtype(natura_2000_sites[col]):
            natura_2000_sites[col] = natura_2000_sites[col].astype(str)
        
    update_progress("Adding protected areas...", 0.8)
    protected_layers = []
    pa_configs = [
        (marine_park_alonnisos, "MNP Alonnisos Sporades", "teal", False),
        (marine_park_zakynthos, "MNP Zakynthos", "teal", False),
        (natura_2000_sites, "Natura 2000 Sites", "teal", False),
        (no_trawl_zone, "No Trawling Zone (Alonnisos)", "darkred", True)
    ]
    for gdf, name, color, is_dashed in pa_configs:
        style = {'fillColor': color, 'color': color, 'fillOpacity': 0.1, 'weight': 2}
        if name == "Natura 2000 Sites": update_progress("Adding protected areas...", 0.85)
        if is_dashed: style['dashArray'] = '5, 5'
        l = folium.GeoJson(gdf, name=name, style_function=lambda x, s=style: s, tooltip=name).add_to(m)
        protected_layers.append(l)



    # 7. Add Tracks & Pings 
    update_progress("Adding layer control...", 0.9)
    track_layers = []
    line_kwds = {"weight": 2, "opacity": 0.8, "dashArray": "2, 5"}
    for lines, name, color in [(green_lines, "Track: Normal", "green"), (orange_lines, "Track: Gap", "orange"), (red_lines, "Track: Suspicious", "red")]:
        if lines:
            l = folium.GeoJson(gpd.GeoDataFrame(geometry=lines, crs=standard_crs), name=name, style_function=lambda x, c=color: {**line_kwds, "color": c}).add_to(m)
            track_layers.append(l)

    point_layers = []
    for color, name, rad in [('green', 'Pings: Normal', 3), ('orange', 'Pings: Gap', 3.5), ('red', 'Pings: Suspicious', 3.5)]:
        subset = agg_gdf[agg_gdf['point_status'] == color]
        if not subset.empty:
            l = folium.GeoJson(subset, name=name, marker=folium.CircleMarker(radius=rad, fill=True, color=color, fillColor=color),
                               popup=folium.GeoJsonPopup(fields=["ship_name", "datetime_str", "mmsi", "pings_at_loc"])).add_to(m)
            point_layers.append(l)


    # Highlight Individual Suspicious Gaps Only 
    highlight_gaps_metadata.sort(key=lambda x: x['duration'], reverse=True)
    highlight_gap_layers = []
    for gap in highlight_gaps_metadata:
        label = f"Highlight: {gap['duration']:.1f}h Gap ({gap['start'].split(' ')[0]})"
        fg = folium.FeatureGroup(name=label, show=False)
        
        # 3 nice separate lines for the popup
        popup_html = (
            f"<b>Duration:</b> {gap['duration']:.2f} hours<br>"
            f"<b>Start:</b> {gap['start']}<br>"
            f"<b>End:</b> {gap['end']}"
        )
        
        # Line Segment
        folium.PolyLine(
            locations=[(p[1], p[0]) for p in gap['line'].coords],
            color="red", weight=8, opacity=1,
            tooltip="Click for gap details",
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(fg)
        
        # Start/End Highlight Pings
        for geom in [gap['p1_geom'], gap['p2_geom']]:
            folium.CircleMarker(
                location=[geom.y, geom.x], radius=6, color="darkorange", fill=True, fillColor="black", weight=4
            ).add_to(fg)
            
        fg.add_to(m)
        highlight_gap_layers.append(fg)


    # 8. Add layer control
    GroupedLayerControl(
        groups={
            'Base Map': basemap_layers,
            'Environment': base_layers,
            'Protected Areas': protected_layers,
            'Track': track_layers,
            'Pings': point_layers,
            'Highlight Suspicious Gaps': highlight_gap_layers
        },
        exclusive_groups=False, collapsed=False
    ).add_to(m)

    update_progress("Saving map to folder...", 0.95)
    raw_vessel_name = "".join(c for c in target_label if c.isalnum() or c in (' ', '_', '-')).strip()
    vessel_name = raw_vessel_name.replace(' ', '_')
    filename = f"AIS_gap_map_{vessel_name}.html"
    m.save(filename)
    return filename