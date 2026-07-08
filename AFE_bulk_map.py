import gfwapiclient as gfw
import pandas as pd 
from shapely.geometry import Polygon
from shapely.geometry import mapping
import plotly.express as px
import pandas as pd
import folium 
import geopandas as gpd
from shapely.geometry import LineString, Polygon
from folium.plugins import GroupedLayerControl
from folium.plugins import HeatMap
import json
from shapely.geometry import box
import numpy as np
from branca.element import MacroElement
import jinja2


def create_AFE_heatmap(df, buffer_dis=3, filter_type="All Vessels", progress_callback=None):
    """
    Generates a Folium map featuring HeatMaps paired with an interactive, transparent grid matrix. 
    Hovering or clicking over a cell displays vessel and country fishing effort breakdown.
    """
    df = df.copy()

    def update_progress(text, value):
        if progress_callback:
            progress_callback(text, value)

    if filter_type == "Trawlers Only":
        df = df[df['gear_type'].str.upper() == 'TRAWLERS']

    standard_crs = "EPSG:4326"
    
    # 1. Clean up ship names and construct a unique, readable label per vessel
    update_progress("Preparing vessel data...", 0.1)
    df['ship_name_clean'] = df['ship_name'].astype(str).str.strip().replace({'None': '', 'nan': '', '': None})
    df['vessel_label'] = df['ship_name_clean'].fillna(df['vessel_id'].astype(str).str[:8]) + " [" + df['flag'] + "]"


    # 2. Read base layers from map_files
    greek_eez_gdf = gpd.read_file('map_files/greek_eez.json').to_crs(standard_crs)
    italy_eez_gdf = gpd.read_file('map_files/italy_eez.geojson').to_crs(standard_crs)
    marine_park_alonnisos = gpd.read_file('map_files/MarineNationalPark_AlonnisosNorthernSporades.shp').to_crs(standard_crs)
    no_trawl_zone = gpd.read_file('map_files/MarineNationalPark_AlonnisosNorthernSporades_NoTrawlingZone.shp').to_crs(standard_crs)
    marine_park_zakynthos = gpd.read_file('map_files/MarineNationalPark_Kakinthos.shp').to_crs(standard_crs)
    natura_2000_sites = gpd.read_file('map_files/Natura200_end2020_epsg3035_Greece_HabitatDirective.shp').to_crs(standard_crs)

    update_progress("Loading spatial layers...", 0.2)
    for col in natura_2000_sites.columns:
        if pd.api.types.is_datetime64_any_dtype(natura_2000_sites[col]):
            natura_2000_sites[col] = natura_2000_sites[col].astype(str)


    # 3. Add base maps 
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
    

    # 4. Read and add environment layers
    update_progress("Loading spatial layers...", 0.3)
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

    update_progress("Loading spatial layers...", 0.4)
    base_layers.append(folium.GeoJson(expanded_region_gdf, name="Search Area (GFW download region)",
        style_function=lambda x: {"fillColor": "none", "fillOpacity": 0, "color": "black", "weight": 1, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(greek_eez_gdf, name="Greek EEZ", style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}).add_to(m))
    base_layers.append(folium.GeoJson(italy_eez_gdf, name="Italian EEZ", show=False, style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}).add_to(m))
    update_progress("Loading spatial layers...", 0.5)
    base_layers.append(folium.GeoJson(ais_buffer_gdf, name=f"{buffer_dis}NM AIS signal Buffer Zone", style_function=lambda x: {"fillColor": "red", "color": "red", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(mlt_territorial_waters, name="Malta Territorial Waters", style_function=lambda x: {"fillColor": "none", "color": "yellow", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(ita_territorial_waters, name="Italy Territorial Waters", style_function=lambda x: {"fillColor": "none", "color": "orange", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    update_progress("Loading spatial layers...", 0.6)
    base_layers.append(folium.GeoJson(grc_territorial_waters, name="Greece Territorial Waters", style_function=lambda x: {"fillColor": "none", "color": "orange", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(tur_territorial_waters, name="Turkey Territorial Waters", style_function=lambda x: {"fillColor": "none", "color": "yellow", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    base_layers.append(folium.GeoJson(mlt_FMZ_waters, name="Malta FMZ Waters", style_function=lambda x: {"fillColor": "none", "color": "#85DFE6", "fillOpacity": 0.08, "weight": 1.5, "dashArray": "5, 5"}).add_to(m))
    
    protected_layers = []
    pa_configs = [
        (marine_park_alonnisos, "MNP Alonnisos Sporades", "teal", False),
        (marine_park_zakynthos, "MNP Zakynthos", "teal", False),
        (natura_2000_sites, "Natura 2000 Sites", "teal", False),
        (no_trawl_zone, "No Trawling Zone (Alonnisos)", "darkred", True)
    ]
    update_progress("Loading spatial layers...", 0.7)
    for pgdf, name, color, is_dashed in pa_configs:
        style = {'fillColor': color, 'color': color, 'fillOpacity': 0.1, 'weight': 2}
        if is_dashed: style['dashArray'] = '5, 5'
        protected_layers.append(folium.GeoJson(pgdf, name=name, style_function=lambda x, s=style: s, tooltip=name).add_to(m))


    # 5. Generate heatmap layers per flag and add to map
    update_progress("Generating heatmap...", 0.8)
    flags = df['flag'].dropna().unique().tolist()
    heatmap_layers = []
    for flag in flags:
        flag_heat_data = df[df['flag'] == flag][['lat', 'lon', 'hours']].groupby(['lat', 'lon']).sum().reset_index().values.tolist()
        heatmap_layers.append(HeatMap(
            data=flag_heat_data, 
            radius=6, 
            blur=3, 
            max_zoom=10,
            pane="tilePane",
            name=f'[{flag}] Fishing Effort (Hours)'
        ).add_to(m))


    # 6. Create heatmap legend as a fixed-position HTML element and add to map
    legend_html = '''
    <div style="
        position: fixed; bottom: 30px; left: 20px; width: 240px; height: auto; 
        background-color: rgba(255, 255, 255, 0.85); backdrop-filter: blur(5px); -webkit-backdrop-filter: blur(5px);
        border: 1px solid rgba(0, 0, 0, 0.15); z-index: 9999; 
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
        padding: 12px 15px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    ">
        <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #2c3e50; margin-bottom: 8px;">
            Apparent Fishing Effort <span style="font-weight: 400; color: #7f8c8d; text-transform: none;">(Hours)</span>
        </div>
        <div style="background: linear-gradient(to right, #002ff9, #00ff00, #ffff00, #ff0000); height: 8px; width: 100%; border-radius: 4px;"></div>
        <div style="display: flex; justify-content: space-between; margin-top: 6px; font-size: 11px; color: #34495e; font-weight: 500;">
            <span>Low activity</span>
            <span>High activity</span>
        </div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))


    # 7. Create a transparent grid layer with interactive tooltips and popups for vessel effort breakdowns
    CELL_SIZE = 0.01  
    half_size = CELL_SIZE / 2
    
    # Retain both 'flag' and 'vessel_label' to handle dual grouping layers
    grid_agg = df.groupby(['lat', 'lon', 'flag', 'vessel_label'])['hours'].sum().reset_index()

    # Formatter callback modified to generate Country Breakdown over Vessel Breakdown
    def format_vessel_hover_text(group):
        html_out = "<div style='min-width: 200px; max-width: none; white-space: nowrap;'>"
        
        # --- Section A: Country Breakdown ---
        html_out += "<b>Country Breakdown:</b><div style='margin-bottom: 4px;'></div>"
        country_agg = group.groupby('flag')['hours'].sum().sort_values(ascending=False)
        for flag, c_hours in country_agg.items():
            html_out += f"<div style='margin-bottom: 3px;'>• <b>{flag}</b>: {c_hours:.2f} hrs</div>"
        
        # Spacer divider between categories
        html_out += "<div style='margin-top: 8px; margin-bottom: 8px; border-top: 1px dashed #ccc;'></div>"
        
        # --- Section B: Vessel Breakdown ---
        html_out += "<b>Vessel Breakdown:</b><div style='margin-bottom: 4px;'></div>"
        sorted_vessels = group.sort_values(by='hours', ascending=False)
        for _, row in sorted_vessels.iterrows():
            html_out += f"<div style='margin-bottom: 3px;'>• <b>{row['vessel_label']}</b>: {row['hours']:.2f} hrs</div>"
            
        html_out += "</div>"
        return html_out

    hover_data = (
        grid_agg.groupby(['lat', 'lon'])
        .apply(format_vessel_hover_text, include_groups=False)
        .reset_index(name='vessel_effort')
    )

    # Formulate cell geometries
    hover_data['geometry'] = hover_data.apply(
        lambda row: box(
            row['lon'] - half_size,
            row['lat'] - half_size,
            row['lon'] + half_size,
            row['lat'] + half_size
        ), 
        axis=1
    )
    grid_cells_to_plot = gpd.GeoDataFrame(hover_data, geometry='geometry', crs=standard_crs)

    # Generate dynamic tooltip built for multi-vessel vertical listings
    grid_tooltip = folium.GeoJsonTooltip(
        fields=['vessel_effort'],
        labels=False,
        localize=True,
        sticky=True,
        style="""
            background-color: #F0F2F5;
            color: #333333;
            font-family: sans-serif;
            font-size: 12px;
            padding: 10px;
            max-height: 250px;
            overflow-y: auto;
            width: max-content;
        """
    )

    # Generate matching click-action popups
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

    # Apply the transparent vector matrix layer combining tooltips and popups
    grid_layer = folium.GeoJson(
        grid_cells_to_plot,
        name="AFE Grid Cells",
        style_function=lambda x: {
            "fillColor": "black",     
            "fillOpacity": 0.0,  
            "color": "#666666",
            "weight": 0.5,
            "opacity": 0.4
        },
        highlight_function=lambda x: {
            "fillColor": "#04585E",   
            "fillOpacity": 0.20,
            "weight": 1.2
        },
        tooltip=grid_tooltip,
        popup=grid_popup
    ).add_to(m)


    # Force tooltip and popup wrappers to dynamically resize based on content, remove default shadows.
    clean_popup_css = '''
    <style>
    /* Force popup wrappers to dynamically shrink/expand to fit text lengths on one line */
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
    /* Let the tooltip grow naturally, drop horizontal scroll limitations, and kill shadows */
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
    GroupedLayerControl(
        groups={
            'Base Map': basemap_layers,
            'Environment': base_layers, 
            'Protected Areas': protected_layers, 
            'Fishing Effort': heatmap_layers,
            'Grid Cells': [grid_layer],
        },
        exclusive_groups=False, 
        collapsed=False
    ).add_to(m)

    update_progress("Saving map to folder...", 0.9)
    output_path = "AFE_heatmap_allvessels.html"
    m.save(output_path)
    return output_path

