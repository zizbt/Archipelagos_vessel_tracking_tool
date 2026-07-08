import gfwapiclient as gfw
import pandas as pd 
from shapely.geometry import Polygon
from shapely.geometry import mapping


def get_gfw_client(api_key):
    gfw_client = gfw.Client(access_token=api_key)
    return gfw_client   

# # Greek EEZ region from GFW dataset 
# greek_region = {"dataset": "public-eez-areas", "id": "5679",}


async def load_VP_data(flag, start, end, client):

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
    region_geometry = mapping(expanded_poly)

    # Clean formatting check for batch SQL optimization
    if isinstance(flag, list):
        flag_filter = "flag IN (" + ", ".join(["'{}'".format(f) for f in flag]) + ")"
    else:
        flag_filter = f"flag = '{flag}'"

    # Generate presence report 
    presence_report = await client.fourwings.create_ais_presence_report(
        spatial_resolution="HIGH",
        temporal_resolution="HOURLY",
        group_by="VESSEL_ID",
        filters=[f"{flag_filter} AND vessel_type = 'fishing'"],
        start_date=start,
        end_date=end,
        geojson=region_geometry,
    )

    dataframe = presence_report.df()
    return dataframe



async def load_AFE_data(flag, start, end, client):

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
    region_geometry = mapping(expanded_poly)

    # Clean formatting check for batch SQL optimization
    if isinstance(flag, list):
        flag_filter = "flag IN (" + ", ".join(["'{}'".format(f) for f in flag]) + ")"
    else:
        flag_filter = f"flag = '{flag}'"

    api_filters = [
        flag_filter, 
        "distance_from_port_km > 3"
    ]

    # Generate fishing effort report 
    fishing_effort_report = await client.fourwings.create_fishing_effort_report(
        spatial_resolution="HIGH",
        temporal_resolution="HOURLY",
        group_by="VESSEL_ID",
        # filters=[f"{flag_filter}"],
        filters=api_filters,
        start_date=start,
        end_date=end,
        geojson=region_geometry,
    )

    dataframe = fishing_effort_report.df()
    # Don't attempt to filter empty dataframe  
    if dataframe.empty:
        return dataframe

    # Only return fishing vessels
    filtered_df = dataframe[dataframe['vessel_type'] == 'FISHING']
    return filtered_df



def get_monthly_chunks(start_date, end_date):
    """
    Splits a date range into [start, end] pairs for each calendar month.
    """
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    
    chunks = []
    current_start = start
    
    while current_start < end:
        month_end = current_start + pd.offsets.MonthEnd(0)
        current_end = min(month_end, end)
        chunks.append((current_start.strftime('%Y-%m-%d'), current_end.strftime('%Y-%m-%d')))
        current_start = current_end + pd.Timedelta(days=1)
        
    return chunks



# Use this streamlined version below:
async def bulk_load_data(flag, start_date, end_date, client, progress_callback=None, data="VP"):
    chunks = get_monthly_chunks(start_date, end_date)
    all_chunks = []
    total_chunks = len(chunks)
    
    for i, (start, end) in enumerate(chunks):
        status = f"Processing {start} to {end}..."
        if progress_callback: 
            progress_callback(status, (i / total_chunks))

        # Pass the whole list or string down to load_data directly
        if data == "VP":
            df_month = await load_VP_data(flag, start, end, client)
        elif data == "AFE":
            df_month = await load_AFE_data(flag, start, end, client)

        if not df_month.empty:
            all_chunks.append(df_month)

    if all_chunks:
        if progress_callback: progress_callback("Concatenating and saving...", 0.95)
        final_df = pd.concat(all_chunks, ignore_index=True)
        
        date_col = 'timestamp' if 'timestamp' in final_df.columns else ('date' if 'date' in final_df.columns else None)
        
        if date_col:
            ts_series = pd.to_datetime(final_df[date_col])
            actual_start = ts_series.min().strftime('%Y-%m-%d')
            actual_end = ts_series.max().strftime('%Y-%m-%d')
        else:
            actual_start, actual_end = start_date, end_date
            
        # Dynamically evaluate naming for strings or list arrays
        flag_tag = "ALL_FLAGS" if isinstance(flag, list) else flag
        filename = f"{data}_{flag_tag}_{actual_start}-{actual_end}.csv"
        final_df.to_csv(filename, index=False)
        
        return final_df, actual_start, actual_end
    else:
        return pd.DataFrame(), None, None