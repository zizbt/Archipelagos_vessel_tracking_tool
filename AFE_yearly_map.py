import pandas as pd
import folium
import geopandas as gpd
import numpy as np
import html as html_lib
from shapely.geometry import Polygon, box
from folium.plugins import GroupedLayerControl, HeatMapWithTime
from functools import lru_cache

CELL_SIZE = 0.05
HALF_SIZE = CELL_SIZE / 2
STANDARD_CRS = "EPSG:4326"
GRADIENT = {0.0: '#002ff9', 0.4: '#00ff00', 0.7: '#ffff00', 1.0: '#ff0000'}


@lru_cache(maxsize=None)
def _load_layer(path, crs):
    gdf = gpd.read_file(path)
    return gdf.to_crs(crs)


# 1. PREPARATION OF DATA
def _prepare_data(df, filter_type="All Vessels"):
    df = df.copy()

    if filter_type == "Trawlers Only":
        df = df[df['gear_type'].astype(str).str.upper() == 'TRAWLERS']

    df['lat'] = (df['lat'] / CELL_SIZE).round() * CELL_SIZE
    df['lon'] = (df['lon'] / CELL_SIZE).round() * CELL_SIZE

    df['year'] = pd.to_datetime(df['date'], errors='coerce').dt.year
    df = df.dropna(subset=['year'])
    df['year'] = df['year'].astype(int)

    df['ship_name_clean'] = (
        df['ship_name'].astype(str).str.strip()
        .replace({'None': '', 'nan': '', '': None})
    )
    df['vessel_label'] = (
        df['ship_name_clean'].fillna(df['vessel_id'].astype(str).str[:8])
        + " [" + df['flag'] + "]"
    )

    years = sorted(df['year'].unique())
    time_index = [str(y) for y in years]

    cell_hours = df.groupby(['year', 'lat', 'lon'])['hours'].sum()
    log_max = np.log1p(cell_hours.max())

    heat_data_per_year = []
    for y in years:
        year_df = (
            df[df['year'] == y][['lat', 'lon', 'hours']]
            .groupby(['lat', 'lon']).sum().reset_index()
        )
        year_df['weight'] = (np.log1p(year_df['hours']) / log_max).clip(0, 1.0)
        heat_data_per_year.append(year_df[['lat', 'lon', 'weight']].values.tolist())

    return df, years, time_index, heat_data_per_year


# 2. INTERACTIVE GRID
def _build_grid_layer(df):
    grid_agg = df.groupby(['lat', 'lon', 'flag', 'vessel_label'])['hours'].sum().reset_index()
    grid_agg = grid_agg[grid_agg['hours'] > 0.1]

    def fmt(group):
        out = "<div style='min-width:200px; white-space:nowrap;'>"
        out += "<b>Country Breakdown:</b><div style='margin-bottom:4px;'></div>"
        for flag, h in group.groupby('flag')['hours'].sum().sort_values(ascending=False).items():
            out += f"<div style='margin-bottom:3px;'>&bull; <b>{flag}</b>: {h:.2f} hrs</div>"
        out += "<div style='margin:8px 0; border-top:1px dashed #ccc;'></div>"
        out += "<b>Vessel Breakdown:</b><div style='margin-bottom:4px;'></div>"
        for _, r in group.sort_values('hours', ascending=False).iterrows():
            out += f"<div style='margin-bottom:3px;'>&bull; <b>{r['vessel_label']}</b>: {r['hours']:.2f} hrs</div>"
        return out + "</div>"

    hover = (grid_agg.groupby(['lat', 'lon'])
             .apply(fmt, include_groups=False)
             .reset_index(name='vessel_effort'))

    hover['geometry'] = hover.apply(
        lambda r: box(r['lon'] - HALF_SIZE, r['lat'] - HALF_SIZE,
                      r['lon'] + HALF_SIZE, r['lat'] + HALF_SIZE), axis=1)

    cells = gpd.GeoDataFrame(hover, geometry='geometry', crs=STANDARD_CRS)

    tip_style = ("background-color:#F0F2F5; color:#333; font-family:sans-serif; "
                 "font-size:12px; padding:10px; max-height:250px; overflow-y:auto; width:max-content;")

    return folium.GeoJson(
        cells,
        name="AFE Grid Cells",
        style_function=lambda x: {"fillColor": "black", "fillOpacity": 0.0,
                                  "color": "#666666", "weight": 0, "opacity": 0},
        highlight_function=lambda x: {"fillColor": "#04585E", "fillOpacity": 0.20, "weight": 1.2},
        tooltip=folium.GeoJsonTooltip(fields=['vessel_effort'], labels=False, sticky=True, style=tip_style),
        popup=folium.GeoJsonPopup(fields=['vessel_effort'], labels=False, style=tip_style),
    )


# 3. MAP BUILD
#    light=False -> everything, including EEZ and protected areas
#    light=True  -> heatmap + EEZ, no protected areas, no grid, no legend
def _build_map(df, time_index, heat_data_per_year, buffer_dis=3,
               light=True, sync=True, update_progress=None):
    def progress(text, value):
        if update_progress:
            update_progress(text, value)

    m = folium.Map(location=[38.0, 24.5], zoom_start=6, tiles=None, prefer_canvas=False)

    tile_light = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Light Gray", name="Esri Light Gray", overlay=False, control=True
    ).add_to(m)
    tile_imagery = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Esri World Imagery", overlay=False, control=True
    ).add_to(m)
    basemap_layers = [tile_light, tile_imagery]

    greek_eez = _load_layer('map_files/greek_eez.json', STANDARD_CRS)
    eez_layer = folium.GeoJson(
        greek_eez, name="Greek EEZ",
        style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.05, "weight": 1}
    ).add_to(m)
    base_layers = [eez_layer]
    protected_layers = []

    if not light:
        progress("Chargement des couches spatiales...", 0.3)

        italy_eez = _load_layer('map_files/italy_eez.geojson', STANDARD_CRS)
        ais_buffer = _load_layer(f'map_files/ais_buffer_{buffer_dis}nm.geojson', STANDARD_CRS)
        mlt_waters = _load_layer('map_files/mlt_national_waters.geojson', STANDARD_CRS)
        mlt_fmz = _load_layer('map_files/mlt_FMZ_waters.geojson', STANDARD_CRS)
        ita_waters = _load_layer('map_files/ita_national_waters.geojson', STANDARD_CRS)
        grc_waters = _load_layer('map_files/grc_territorial_waters.geojson', STANDARD_CRS)
        tur_waters = _load_layer('map_files/tur_national_waters.geojson', STANDARD_CRS)

        expanded_poly = Polygon([
            (11.0, 33.0), (30.5, 33.0), (30.5, 36.5), (26.5, 41.5),
            (22.0, 41.5), (11.0, 36.5), (11.0, 33.0)
        ])
        expanded_gdf = gpd.GeoDataFrame(index=[0], crs=STANDARD_CRS, geometry=[expanded_poly])

        base_layers.append(folium.GeoJson(
            expanded_gdf, name="Search Area (GFW download region)",
            style_function=lambda x: {"fillColor": "none", "fillOpacity": 0,
                                      "color": "black", "weight": 1, "dashArray": "5, 5"}
        ).add_to(m))
        base_layers.append(folium.GeoJson(
            italy_eez, name="Italian EEZ", show=False,
            style_function=lambda x: {"color": "#85DFE6", "fillOpacity": 0.08}
        ).add_to(m))
        base_layers.append(folium.GeoJson(
            ais_buffer, name=f"{buffer_dis}NM AIS signal Buffer Zone",
            style_function=lambda x: {"fillColor": "red", "color": "red", "fillOpacity": 0.08,
                                      "weight": 1.5, "dashArray": "5, 5"}
        ).add_to(m))

        for gdf, nm, col in [
            (mlt_waters, "Malta Territorial Waters", "yellow"),
            (ita_waters, "Italy Territorial Waters", "orange"),
            (grc_waters, "Greece Territorial Waters", "orange"),
            (tur_waters, "Turkey Territorial Waters", "yellow"),
            (mlt_fmz, "Malta FMZ Waters", "#85DFE6"),
        ]:
            base_layers.append(folium.GeoJson(
                gdf, name=nm,
                style_function=lambda x, c=col: {"fillColor": "none", "color": c,
                                                 "fillOpacity": 0.08, "weight": 1.5,
                                                 "dashArray": "5, 5"}
            ).add_to(m))

        progress("Processing protected areas...", 0.5)
        natura = _load_layer('map_files/Natura200_end2020_epsg3035_Greece_HabitatDirective.shp', STANDARD_CRS).copy()
        for col in natura.columns:
            if pd.api.types.is_datetime64_any_dtype(natura[col]):
                natura[col] = natura[col].astype(str)

        pa_configs = [
            (_load_layer('map_files/MarineNationalPark_AlonnisosNorthernSporades.shp', STANDARD_CRS),
             "MNP Alonnisos Sporades", "teal", False),
            (_load_layer('map_files/MarineNationalPark_Kakinthos.shp', STANDARD_CRS),
             "MNP Zakynthos", "teal", False),
            (natura, "Natura 2000 Sites", "teal", False),
            (_load_layer('map_files/MarineNationalPark_AlonnisosNorthernSporades_NoTrawlingZone.shp', STANDARD_CRS),
             "No Trawling Zone (Alonnisos)", "darkred", True),
        ]
        for pgdf, nm, col, dashed in pa_configs:
            style = {'fillColor': col, 'color': col, 'fillOpacity': 0.1, 'weight': 2}
            if dashed:
                style['dashArray'] = '5, 5'
            protected_layers.append(folium.GeoJson(
                pgdf, name=nm, style_function=lambda x, s=style: s, tooltip=nm
            ).add_to(m))

    progress("Generation of the heatmap...", 0.7)
    HeatMapWithTime(
        data=heat_data_per_year, index=time_index, name="Fishing Effort",
        radius=8, max_opacity=0.8, min_opacity=0, use_local_extrema=False,
        auto_play=False, display_index=True, gradient=GRADIENT,
    ).add_to(m)

    if not light:
        m.get_root().html.add_child(folium.Element(_LEGEND_HTML))
        grid_layer = _build_grid_layer(df)
        grid_layer.add_to(m)
        m.get_root().html.add_child(folium.Element(_POPUP_CSS))
        GroupedLayerControl(
            groups={
                'Base Map': basemap_layers,
                'Environment': base_layers,
                'Protected Areas': protected_layers,
                'Grid Cells': [grid_layer],
            },
            exclusive_groups=False, collapsed=False
        ).add_to(m)

    if sync:
        m.get_root().html.add_child(folium.Element(_SYNC_JS))
    if light:
        m.get_root().html.add_child(folium.Element(_COMPACT_CSS))

    return m


# 4. END-TO-END FUNCTION TO CREATE AFE HEATMAP
def create_AFE_heatmap(df, buffer_dis=3, filter_type="All Vessels", progress_callback=None):
    def progress(t, v):
        if progress_callback:
            progress_callback(t, v)

    progress("Preparation of the data...", 0.1)
    df, years, time_index, heat_data = _prepare_data(df, filter_type)

    # 1 detail map + 4 light maps (comparison view)
    progress("Detail map...", 0.2)
    m_full = _build_map(df, time_index, heat_data, buffer_dis, light=False, sync=True)
    full_panel = html_lib.escape(m_full.get_root().render(), quote=True)

    # 4 light maps for comparison view
    panels = []
    for i in range(4):
        progress(f"Comparison map {i + 1}/4...", 0.55 + i * 0.1)
        m = _build_map(df, time_index, heat_data, buffer_dis, light=True, sync=True)
        panels.append(html_lib.escape(m.get_root().render(), quote=True))

    progress("Assembly of the page...", 0.95)
    grid_iframes = "\n  ".join(f'<iframe srcdoc="{p}"></iframe>' for p in panels)
    page = (_WRAPPER_TEMPLATE
            .replace("{{FULL_IFRAME}}", f'<iframe srcdoc="{full_panel}"></iframe>')
            .replace("{{GRID_IFRAMES}}", grid_iframes))

    out = "AFE_heatmap_yearly.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    return out


# 5. FRAGMENTS
_LEGEND_HTML = '''
<div style="position:fixed; bottom:60px; left:12px; width:240px;
    background:rgba(255,255,255,0.88); backdrop-filter:blur(5px);
    border:1px solid rgba(0,0,0,0.15); z-index:9999;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
    padding:12px 15px; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.1);">
  <div style="font-size:11px; font-weight:700; text-transform:uppercase;
              letter-spacing:0.5px; color:#2c3e50; margin-bottom:6px;">
    Apparent Fishing Effort
  </div>
  <div style="background:linear-gradient(to right,#002ff9,#00ff00,#ffff00,#ff0000);
              height:8px; border-radius:4px;"></div>
  <div style="display:flex; justify-content:space-between; margin-top:5px;
              font-size:11px; color:#34495e; font-weight:500;">
    <span>Low</span><span>High</span>
  </div>
</div>
'''

_POPUP_CSS = '''
<style>
.leaflet-popup-content-wrapper { background:#F0F2F5 !important; padding:0 !important;
  width:max-content !important; max-width:none !important; box-shadow:none !important; }
.leaflet-popup-content { margin:0 !important; padding:0 !important;
  width:max-content !important; max-width:none !important; }
.leaflet-popup-tip-container { display:none !important; }
.leaflet-tooltip { width:max-content !important; max-width:none !important;
  white-space:nowrap !important; box-shadow:none !important; }
/* Descend le layer control pour ne pas chevaucher le bouton Comparer */
.leaflet-top.leaflet-right { margin-top: 60px !important; }
</style>
'''

_SYNC_JS = '''
<script>
document.addEventListener('DOMContentLoaded', function () {
  var key = Object.keys(window).find(function (k) {
    return k.indexOf('map_') === 0 && window[k] && window[k]._container;
  });
  if (!key) { return; }
  var M = window[key];
  var lock = false;
  M.on('moveend zoomend', function () {
    if (lock) { return; }
    var c = M.getCenter();
    parent.postMessage({ type: 'mapmove', lat: c.lat, lng: c.lng, z: M.getZoom() }, '*');
  });
  window.addEventListener('message', function (e) {
    var d = e.data;
    if (!d) { return; }
    if (d.type === 'setview') {
      lock = true;
      M.setView([d.lat, d.lng], d.z, { animate: false });
      setTimeout(function () { lock = false; }, 60);
    } else if (d.type === 'refresh') {
      M.invalidateSize();
    }
  });
});
</script>
'''

_COMPACT_CSS = '''
<style>
.leaflet-control-layers,
.leaflet-control-attribution,
.leaflet-control-zoom,
.leaflet-control-layers-expanded { display: none !important; }
.leaflet-control-container .leaflet-bottom.leaflet-left {
  display: flex !important; flex-direction: row !important; align-items: center !important;
  margin: 0 0 8px 8px !important;
}
.leaflet-control-container .leaflet-bottom .leaflet-control {
  background: rgba(255,255,255,0.85) !important; border: none !important;
  border-radius: 0 !important; margin: 0 !important; padding: 0 !important;
  box-shadow: none !important; float: none !important; display: flex !important;
  align-items: center !important; width: auto !important; min-width: 0 !important;
}
.leaflet-bar { border-radius: 6px 0 0 6px !important; overflow: hidden !important; }
.leaflet-bar a {
  width: 24px !important; height: 24px !important; line-height: 24px !important;
  border: none !important; background: transparent !important;
}
.timecontrol-date, .leaflet-control-timecontrol.timecontrol-date {
  font-size: 12px !important; font-weight: 600 !important; color: #2c3e50 !important;
  white-space: nowrap !important; padding: 0 10px !important;
  height: 24px !important; line-height: 24px !important;
  width: auto !important; min-width: 0 !important; max-width: none !important;
  border-radius: 0 6px 6px 0 !important;
}
</style>
<script>
document.addEventListener('DOMContentLoaded', function () {
  setTimeout(function () {
    document.querySelectorAll('div').forEach(function (d) {
      if (d.textContent.trim().indexOf('APPARENT FISHING EFFORT') === 0
          && d.style.position === 'fixed') { d.remove(); }
    });
    document.querySelectorAll('.leaflet-control-timecontrol').forEach(function (el) {
      var c = el.className;
      if (c.indexOf('slider') !== -1 || c.indexOf('speed') !== -1) { el.remove(); }
    });
    document.querySelectorAll('.leaflet-bar').forEach(function (bar) {
      var links = bar.querySelectorAll('a');
      if (links.length >= 5) {
        [4, 2, 1].forEach(function (i) { if (links[i]) links[i].remove(); });
      }
    });
  }, 300);
});
</script>
'''

_WRAPPER_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AFE - Greece</title>
<style>
  html, body { margin:0; padding:0; height:100%; overflow:hidden;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif; }
  #single { height:100vh; width:100vw; }
  #single iframe { width:100%; height:100%; border:0; }
  #grid { display:none; height:100vh; gap:2px; background:#2b2b2b;
          grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; }
  #grid iframe { width:100%; height:100%; border:0; }
  body.compare #single { display:none; }
  body.compare #grid { display:grid; }
  #toggle { position:fixed; top:14px; right:14px; z-index:99999;
    padding:10px 18px; border:0; border-radius:8px; background:#1f538d; color:#fff;
    font-size:13px; font-weight:600; cursor:pointer;
    box-shadow:0 4px 12px rgba(0,0,0,0.25); }
  #toggle:hover { background:#2a6cb5; }
</style>
</head>
<body>
<button id="toggle">Compare (2x2)</button>
<div id="single">
  {{FULL_IFRAME}}
</div>
<div id="grid">
  {{GRID_IFRAMES}}
</div>
<script>
var btn = document.getElementById('toggle');
btn.addEventListener('click', function () {
  document.body.classList.toggle('compare');
  var on = document.body.classList.contains('compare');
  btn.textContent = on ? 'Simple View' : 'Compare (2x2)';
  setTimeout(function () {
    document.querySelectorAll('iframe').forEach(function (f) {
      try { f.contentWindow.postMessage({ type: 'refresh' }, '*'); } catch (e) {}
    });
  }, 120);
});

var syncing = false;
window.addEventListener('message', function (e) {
  var d = e.data;
  if (syncing || !d || d.type !== 'mapmove') { return; }
  syncing = true;
  document.querySelectorAll('iframe').forEach(function (f) {
    if (f.contentWindow !== e.source) {
      try {
        f.contentWindow.postMessage(
          { type: 'setview', lat: d.lat, lng: d.lng, z: d.z }, '*');
      } catch (err) {}
    }
  });
  setTimeout(function () { syncing = false; }, 70);
});
</script>
</body>
</html>
'''