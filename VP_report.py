import pandas as pd 
import geopandas as gpd
from shapely.geometry import Point
from VP_bulk_map import get_encounter_events

def filter_trawlers(df):
    return df[df['gear_type'].str.upper() == 'TRAWLERS']

def generate_vessel_report(df, filter_type="All", start_date="N/A", end_date="N/A", buffer_dis=3, output_filename="VP_report.csv", progress_callback=None):
    
    # Helper to execute the callback safely if it is provided
    def update_progress(text, value):
        if progress_callback:
            progress_callback(text, value)

    # 1. Setup Spatial Data
    update_progress("Loading spatial layers and AIS buffer...", 0.10)
    standard_crs = "EPSG:4326"

    # Load the AIS buffer zone 
    ais_buffer_gdf = gpd.read_file(f'map_files/ais_buffer_{buffer_dis}nm.geojson').to_crs(standard_crs)


    # 2. Prepare DataFrame & Gaps
    update_progress("Sorting data and calculating chronological gaps...", 0.25)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['vessel_id', 'date']).copy()
    
    # Calculate time gaps in hours
    df['gap_hours'] = df.groupby('vessel_id')['date'].diff().dt.total_seconds() / 3600
    df['gap_hours'] = df['gap_hours'].fillna(0)

    # Determine spatial status for Gaps
    update_progress("Performing spatial join with AIS buffer...", 0.40)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=standard_crs)
    res = gpd.sjoin(gdf, ais_buffer_gdf, how="left", predicate="within")
    df['is_inside'] = ~res['index_right'].isna()
    df['prev_is_inside'] = df.groupby('vessel_id')['is_inside'].shift(1)


    # 3. Define Logic for Suspicious Gaps
    df['is_gap'] = df['gap_hours'] > 3
    df['is_suspicious'] = (
        (df['is_gap']) & 
        (df['is_inside'] == False) & 
        (df['prev_is_inside'] == False)
    )


    # 4. Generate & Filter Encounter Events
    update_progress("Generating and filtering encounter events...", 0.60)
    encounter_gdf = get_encounter_events(df)
    
    # Apply Spatial Filter: Keep only encounters OUTSIDE ais_buffer_gdf
    if not encounter_gdf.empty:
        enc_outside = gpd.sjoin(encounter_gdf, ais_buffer_gdf, how="left", predicate="within")
        encounter_gdf = enc_outside[enc_outside['index_right'].isna()].copy()

    # 5. Filter working set by vessel type
    update_progress("Applying vessel type filters and aggregating metrics...", 0.75)
    selection_label = "Trawlers" if filter_type == "Trawlers Only" else "Fishing Vessels"
    if filter_type == "Trawlers Only":
        working_df = df[df['gear_type'].str.upper() == 'TRAWLERS'].copy()
    else:
        working_df = df.copy()

    # Handle missing names/MMSIs safely
    working_df['ship_name'] = working_df['ship_name'].fillna("UNKNOWN NAME")
    working_df['mmsi'] = working_df['mmsi'].fillna("UNKNOWN MMSI")
    working_df['flag'] = working_df['flag'].fillna("Unknown")

    # PRE-CALCULATE: Isolate gap hours to avoid slow nested operations inside group loops
    working_df['only_gap_hrs'] = working_df['gap_hours'].where(working_df['is_gap'], 0)
    working_df['only_suspicious_hrs'] = working_df['gap_hours'].where(working_df['is_suspicious'], 0)


    # 6. Aggregate Metrics (Optimized & Vectorized)
    vessel_stats = working_df.groupby('vessel_id').agg(
        vessel_name=('ship_name', 'first'),
        mmsi=('mmsi', 'first'),
        flag=('flag', 'first'),
        total_span_hrs=('date', lambda x: (x.max() - x.min()).total_seconds() / 3600),
        total_gap_hrs=('only_gap_hrs', 'sum'),
        suspicious_gap_hrs=('only_suspicious_hrs', 'sum')
    )
    
    # Calculate Active Tracking Activity: Total Chronological Span minus Total Gap hours
    vessel_stats['total_activity_hrs'] = (vessel_stats['total_span_hrs'] - vessel_stats['total_gap_hrs']).clip(lower=0)


    # 7. Add Encounter Counts
    vessel_stats['encounter_events'] = 0
    if not encounter_gdf.empty:
        all_encounter_text = " ".join(encounter_gdf['popup_text'].astype(str).tolist())
        valid_names = vessel_stats[vessel_stats['vessel_name'] != "UNKNOWN NAME"]['vessel_name'].unique()
        counts = {name: all_encounter_text.count(name) for name in valid_names}
        vessel_stats['encounter_events'] = vessel_stats['vessel_name'].map(counts).fillna(0).astype(int)


    # 8. Sort and Finalize Columns
    final_report = vessel_stats[[
        'vessel_name', 
        'mmsi', 
        'flag', 
        'suspicious_gap_hrs', 
        'total_gap_hrs', 
        'total_activity_hrs', 
        'encounter_events'
    ]].sort_values(by='suspicious_gap_hrs', ascending=False)

    final_report.columns = [
        'Vessel Name', 
        'MMSI', 
        'Country', 
        'Gap Hours (outside AIS buffer)', 
        'Total Gap Hours', 
        'Tracked Activity (Hrs)', 
        'Encounter Events'
    ]

    # Calculate Total Values for the summary rows
    total_suspicious = final_report['Gap Hours (outside AIS buffer)'].sum()
    total_gaps = final_report['Total Gap Hours'].sum()
    total_activity = final_report['Tracked Activity (Hrs)'].sum()
    total_encounters = final_report['Encounter Events'].sum()

    # Get Report-level Flag for metadata header block safely
    report_flag = "N/A"
    if not vessel_stats.empty:
        valid_flags = vessel_stats['flag'].replace("Unknown", pd.NA).dropna()
        if not valid_flags.empty:
            report_flag = valid_flags.iloc[0]


    # 9. Manual File Write for Custom Layout & Totals
    update_progress("Writing finalized metrics to CSV report structure...", 0.95)
    with open(output_filename, 'w', encoding='utf-8', newline='') as f:
        header_text = (
            f"Vessel Report | Period: {start_date} to {end_date} | "
            f"Selection: {selection_label} | Global Flag: {report_flag} | "
            f"Total Vessels: {len(final_report)} | Sorted by: Gap Hours (outside AIS buffer) Descending"
        )
        f.write(f'"{header_text}"\n\n')
        
        final_report.to_csv(f, index=False)
        f.write("\n\n\n")
        f.write(f'"TOTALS",,,{total_suspicious:.2f},{total_gaps:.2f},{total_activity:.2f},{total_encounters}\n')
    
    update_progress("Report generated successfully!", 1.0)
    return len(final_report), output_filename