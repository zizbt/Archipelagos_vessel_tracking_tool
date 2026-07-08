# AFE_map.py
import folium
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, box
from folium.plugins import GroupedLayerControl, HeatMap

def get_vessel_data(df, vessel_id):
    """Filters the tracking DataFrame for a specific vessel ID."""
    return df[df['vessel_id'] == vessel_id].copy()

def create_AFE_vessel_heatmap(df, buffer_dis=3, vessel_id=None, progress_callback=None):
    """
    Generates a localized Folium map featuring a HeatMap and interactive grid matrix
    exclusively isolating a single target fishing vessel.
    """
    if df.empty:
        raise ValueError("The provided dataframe is empty.")
        
    df = df.copy()
    standard_crs = "EPSG:4326"

    def update_progress(text, value):
        if progress_callback:
            progress_callback(text, value)
    
    # 1. Clean up name labels
    update_progress("Preparing vessel data...", 0.1)
    df['ship_name_clean'] = df['ship_name'].astype(str).str.strip().replace({'None': '', 'nan': '', '': None})
    df['vessel_label'] = df['ship_name_clean'].fillna(df['vessel_id'].astype(str).str[:8]) + " [" + df['flag'] + "]"
    
    # Identify the target vessel parameters for centering and naming
    target_label = df['vessel_label'].iloc[0] if 'vessel_label' in df.columns else str(vessel_id)
    center_lat = df['lat'].mean()
    center_lon = df['lon'].mean()

    # 2. Add base maps
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
    

    # 3. Read Environment Layers from map_files and add to map
    update_progress("Loading environment layers...", 0.2)
    greek_eez_gdf = gpd.read_file('map_files/greek_eez.json').to_crs(standard_crs)
    italy_eez_gdf = gpd.read_file('map_files/italy_eez.geojson').to_crs(standard_crs)
    ais_buffer_gdf = gpd.read_file(f'map_files/ais_buffer_{buffer_dis}nm.geojson').to_crs(standard_crs)
    mlt_territorial_waters = gpd.read_file(f'map_files/mlt_national_waters.geojson').to_crs(standard_crs)
    mlt_FMZ_waters = gpd.read_file(f'map_files/mlt_FMZ_waters.geojson').to_crs(standard_crs)
    ita_territorial_waters = gpd.read_file(f'map_files/ita_national_waters.geojson').to_crs(standard_crs)
    grc_territorial_waters = gpd.read_file(f'map_files/grc_territorial_waters.geojson').to_crs(standard_crs)
    tur_territorial_waters = gpd.read_file(f'map_files/tur_national_waters.geojson').to_crs(standard_crs)
    
    base_layers = []
    expanded_lat_lons = [
        (11.0, 33.0), (30.5, 33.0), (30.5, 36.5), (26.5, 41.5),
        (22.0, 41.5), (11.0, 36.5), (11.0, 33.0)
    ]
    expanded_poly = Polygon(expanded_lat_lons)
    expanded_region_gdf = gpd.GeoDataFrame(index=[0], crs=standard_crs, geometry=[expanded_poly])

    update_progress("Loading environment layers...", 0.3)
    base_layers.append(folium.GeoJson(expanded_region_gdf, name="Search Area (GFW download region)",
        style_function=lambda x: {"fillColor": "none", "fillOpacity": 0, "color": "black", "weight": 1, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(greek_eez_gdf, name="Greek EEZ", style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}).add_to(m))
    base_layers.append(folium.GeoJson(italy_eez_gdf, name="Italian EEZ", show=False, style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}).add_to(m))
    update_progress("Loading environment layers...", 0.4)
    base_layers.append(folium.GeoJson(ais_buffer_gdf, name=f"{buffer_dis}NM AIS signal Buffer Zone", style_function=lambda x: {"fillColor": "red", "color": "red", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(mlt_territorial_waters, name="Malta Territorial Waters", style_function=lambda x: {"fillColor": "none", "color": "yellow", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(ita_territorial_waters, name="Italy Territorial Waters", style_function=lambda x: {"fillColor": "none", "color": "orange", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    update_progress("Loading environment layers...", 0.5)
    base_layers.append(folium.GeoJson(grc_territorial_waters, name="Greece Territorial Waters", style_function=lambda x: {"fillColor": "none", "color": "orange", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(tur_territorial_waters, name="Turkey Territorial Waters", style_function=lambda x: {"fillColor": "none", "color": "yellow", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(mlt_FMZ_waters, name="Malta FMZ Waters", style_function=lambda x: {"fillColor": "none", "color": "#85DFE6", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    

    # 4. Generate single vessel AFE heatmap and add to map
    update_progress("Generating heatmap...", 0.6)
    heat_data = df[['lat', 'lon', 'hours']].groupby(['lat', 'lon']).sum().reset_index().values.tolist()
    heatmap_layers = []
    heatmap_layer = HeatMap(
        data=heat_data, 
        radius=7, 
        blur=4, 
        max_zoom=11,
        pane="tilePane",
        name=f"Effort: {target_label}"
    ).add_to(m)
    heatmap_layers.append(heatmap_layer)


    # 5. Create and add custom legend
    legend_html = f'''
    <div style="
        position: fixed; bottom: 30px; left: 20px; width: 250px; height: auto; 
        background-color: rgba(255, 255, 255, 0.85); backdrop-filter: blur(5px); -webkit-backdrop-filter: blur(5px);
        border: 1px solid rgba(0, 0, 0, 0.15); z-index: 9999; 
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        padding: 12px 15px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    ">
        <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #2c3e50; margin-bottom: 4px;">
            Fishing Effort (Hours)
        </div>
        <div style="font-size: 10px; color: #7f8c8d; margin-bottom: 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            Vessel: {target_label}
        </div>
        <div style="background: linear-gradient(to right, #002ff9, #00ff00, #ffff00, #ff0000); height: 8px; width: 100%; border-radius: 4px;"></div>
        <div style="display: flex; justify-content: space-between; margin-top: 6px; font-size: 10px; color: #34495e;">
            <span>Low activity</span>
            <span>High activity</span>
        </div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))


    # 6. Generate and add interactive grid cells (Hover Tooltip + Click Popup)
    update_progress("Creating interactive grid...", 0.7)
    CELL_SIZE = 0.01  
    half_size = CELL_SIZE / 2
    
    grid_agg = df.groupby(['lat', 'lon', 'vessel_label'])['hours'].sum().reset_index()

    def format_hover_text(group):
        row = group.iloc[0]
        return f"<div style='min-width: 160px; white-space: nowrap;'><b>Vessel:</b> {row['vessel_label']}<br><b>Effort:</b> {row['hours']:.2f} hrs</div>"

    hover_data = grid_agg.groupby(['lat', 'lon']).apply(format_hover_text, include_groups=False).reset_index(name='vessel_effort')
    hover_data['geometry'] = hover_data.apply(lambda r: box(r['lon']-half_size, r['lat']-half_size, r['lon']+half_size, r['lat']+half_size), axis=1)
    
    grid_gdf = gpd.GeoDataFrame(hover_data, geometry='geometry', crs=standard_crs)

    # Hover tooltip configuration
    grid_tooltip = folium.GeoJsonTooltip(
        fields=['vessel_effort'], labels=False, sticky=True,
        style="background-color: #F0F2F5; font-family: sans-serif; font-size: 12px; padding: 8px;"
    )

    # Click popup configuration matching AFE_bulk_map behavior
    grid_popup = folium.GeoJsonPopup(
        fields=['vessel_effort'],
        labels=False,
        localize=True,
        style="""
            background-color: #F0F2F5;
            color: #333333;
            font-family: sans-serif;
            font-size: 12px;
            padding: 10px;
            max-height: 280px;
            overflow-y: auto;
            width: max-content;
        """
    )

    grid_layer = folium.GeoJson(
        grid_gdf,
        name="AFE grid cells",
        style_function=lambda x: {"fillColor": "black", "fillOpacity": 0.0, "color": "#666666", "weight": 0.5, "opacity": 0.4},
        highlight_function=lambda x: {"fillColor": "#04585E", "fillOpacity": 0.25, "weight": 1.0},
        tooltip=grid_tooltip,
        popup=grid_popup
    ).add_to(m)

    # 7. Force clean Leaflet sizing, overflow, and shadow overrides for tooltips and popups
    clean_popup_css = '''
    <style>
    .leaflet-popup-content-wrapper {
        background: #F0F2F5 !important;
        padding: 0px !important;
        width: max-content !important;
        max-width: none !important;
        box-shadow: none !important;
        filter: none !important;
    }
    .leaflet-popup-content {
        margin: 0px !important;
        padding: 0px !important;
        width: max-content !important;
        max-width: none !important;
    }
    .leaflet-popup-tip-container {
        display: none !important;
    }
    .leaflet-tooltip {
        width: max-content !important;
        max-width: none !important;
        white-space: nowrap !important;
        box-shadow: none !important;
        filter: none !important;
    }
    </style>
    '''
    m.get_root().html.add_child(folium.Element(clean_popup_css))

    # 8. Add layer control
    update_progress("Add layer control...", 0.8)
    GroupedLayerControl(
        groups={
            'Base Map': basemap_layers,
            'Environment': base_layers, 
            'Fishing Effort': heatmap_layers,
            'Grid Cells': [grid_layer],
        },
        exclusive_groups=False,  
        collapsed=False
    ).add_to(m)

    raw_vessel_name = "".join(c for c in target_label if c.isalnum() or c in (' ', '_', '-')).strip()
    vessel_name = raw_vessel_name.replace(' ', '_')

    update_progress("Saving map to folder...", 0.9)
    output_path = f"AFE_heatmap_{vessel_name}.html"
    m.save(output_path)
    return output_path