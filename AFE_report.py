import geopandas as gpd 
import os
import pandas as pd

def create_AFE_report(df, output_csv="AFE_report.csv", progress_callback=None):
    """
    Filters and groups fishing effort data for GRC, TUR, ITA, and MLT territorial waters.
    Formats metrics to force left-alignment, injects a prominent section title at 
    the top of each column block, appends summary totals at the bottom, 
    inserts spacer columns, and stacks everything horizontally.
    """
    standard_crs = "EPSG:4326"

    def update_progress(text, value):
        if progress_callback:
            progress_callback(text, value)

    # 1. Define Paths and Validate Boundary Maps
    paths = {
        'grc': 'map_files/grc_territorial_waters.geojson',
        'tur': 'map_files/tur_national_waters.geojson',
        'ita': 'map_files/ita_national_waters.geojson',
        'mlt_fmz': 'map_files/mlt_FMZ_waters.geojson',
        'mlt_nat': 'map_files/mlt_national_waters.geojson'
    }
    
    missing_files = [name for name, p in paths.items() if not os.path.exists(p)]
    if missing_files:
        raise FileNotFoundError(f"Missing map files: {missing_files}. Run map generators first.")
    
    update_progress("Preparing vessel data...", 0.1)
    # Load boundaries using modern union_all()
    grc_poly = gpd.read_file(paths['grc']).to_crs(standard_crs).geometry.union_all()
    tur_poly = gpd.read_file(paths['tur']).to_crs(standard_crs).geometry.union_all()
    update_progress("Preparing vessel data...", 0.2)
    ita_poly = gpd.read_file(paths['ita']).to_crs(standard_crs).geometry.union_all()
    fmz_poly = gpd.read_file(paths['mlt_fmz']).to_crs(standard_crs).geometry.union_all()
    nat_poly = gpd.read_file(paths['mlt_nat']).to_crs(standard_crs).geometry.union_all()
    

    # 2. Vectorized Point-In-Polygon Checks
    update_progress("Preparing vessel data...", 0.3)
    gdf = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(df.lon, df.lat), crs=standard_crs)
    gdf['in_grc'] = gdf.geometry.within(grc_poly)
    update_progress("Loading spatial layers..", 0.4)
    gdf['in_tur'] = gdf.geometry.within(tur_poly)
    gdf['in_ita'] = gdf.geometry.within(ita_poly)
    update_progress("Loading spatial layers...", 0.5)
    gdf['in_fmz'] = gdf.geometry.within(fmz_poly)
    gdf['in_nat'] = gdf.geometry.within(nat_poly)
    

    # 3. Processing Helper (Handles Country Sub-sections & Bottom Summaries)
    update_progress("Loading spatial layers...", 0.6)
    def build_horizontal_zone_block(boolean_mask, section_title_name, hours_col_name):
        df_zone = gdf[boolean_mask]
        
        # Grand totals for the entire region (placed at the very bottom)
        grand_total_vessels = df_zone['vessel_id'].nunique()
        grand_total_hours = df_zone['hours'].sum()
        
        # Columns setup for uniform DataFrame building
        col_headers = ['Ship Name', 'MMSI', 'Country', hours_col_name]
        
        # --- INJECT TOP SECTION TITLE ---
        title_row = pd.DataFrame([[section_title_name, '', '', '']], columns=col_headers)
        title_spacer = pd.DataFrame([['', '', '', '']], columns=col_headers)
        
        # List to collect all vertical pieces for this specific water block
        block_pieces = [title_row, title_spacer]
        
        # Find country processing order based on total hours in this region
        country_order = (
            df_zone.groupby('flag')['hours']
            .sum()
            .sort_values(ascending=False)
            .index.tolist()
        )
        
        # Process each country group sequentially
        for country in country_order:
            df_country = df_zone[df_zone['flag'] == country]
            
            # Aggregate per vessel within this country
            vSummary = (
                df_country.groupby('vessel_id')
                .agg({'ship_name': 'first', 'mmsi': 'first', 'flag': 'first', 'hours': 'sum'})
                .reset_index()
                .sort_values(by='hours', ascending=False)
            )
            
            country_vessels = len(vSummary)
            country_hours = vSummary['hours'].sum()
            
            # Format columns
            vSummary = vSummary[['ship_name', 'mmsi', 'flag', 'hours']]
            vSummary.columns = col_headers
            vSummary['MMSI'] = vSummary['MMSI'].astype(str)
            vSummary[hours_col_name] = vSummary[hours_col_name].apply(lambda x: f"{x:.2f}")
            
            # Country-specific sub-headers and summaries
            country_header = pd.DataFrame([[f"=== COUNTRY: {str(country).upper()} ===", '', '', '']], columns=col_headers)
            header_labels_row = pd.DataFrame([col_headers], columns=col_headers)
            
            c_vessel_stat = pd.DataFrame([[f"Total {country} Vessels: {country_vessels}", '', '', '']], columns=col_headers)
            c_hours_stat = pd.DataFrame([[f"Total {country} Hours: {country_hours:.2f}", '', '', '']], columns=col_headers)
            country_spacer = pd.DataFrame([['', '', '', '']], columns=col_headers)
            
            # Append country data chunk to block
            block_pieces.extend([
                country_header,
                header_labels_row,
                vSummary,
                c_vessel_stat,
                c_hours_stat,
                country_spacer # gap before next country
            ])
            
        # --- INJECT GRAND BOTTOM SUMMARIES ---
        blank_row_1 = pd.DataFrame([['', '', '', '']], columns=col_headers)
        grand_header = pd.DataFrame([["=== GRAND TOTALS FOR REGION ===", '', '', '']], columns=col_headers)
        vessel_stat_row = pd.DataFrame([[f"Grand Total Vessels: {grand_total_vessels}", '', '', '']], columns=col_headers)
        hours_stat_row = pd.DataFrame([[f"Grand Total Fishing Hours: {grand_total_hours:.2f}", '', '', '']], columns=col_headers)
        
        block_pieces.extend([
            blank_row_1,
            grand_header,
            vessel_stat_row, 
            hours_stat_row
        ])
        
        # Concatenate everything vertically into one final modular regional table
        completed_block = pd.concat(block_pieces, ignore_index=True)
        return completed_block

    # Build the 5 regional blocks with titles
    grc_block = build_horizontal_zone_block(gdf['in_grc'], '--- GREECE (GRC) TERRITORIAL WATERS (6NM) ---', 'Fishing Hours (GRC)')
    tur_block = build_horizontal_zone_block(gdf['in_tur'], '--- TURKEY (TUR) NATIONAL WATERS (6NM)---', 'Fishing Hours (TUR)')
    ita_block = build_horizontal_zone_block(gdf['in_ita'], '--- ITALY (ITA) NATIONAL WATERS (12NM) ---', 'Fishing Hours (ITA)')
    fmz_block = build_horizontal_zone_block(gdf['in_fmz'], '--- MALTA (MLT) FMZ WATERS (25NM) ---', 'Fishing Hours (MLT FMZ)')
    nat_block = build_horizontal_zone_block(gdf['in_nat'], '--- MALTA (MLT) NATIONAL WATERS (12NM) ---', 'Fishing Hours (MLT National)')
    

    # 4. Generate Empty Spacer Columns 
    update_progress("Loading spatial layers...", 0.7)
    def create_spacer():
        spacer_df = pd.DataFrame()
        spacer_df[' '] = ''
        spacer_df['  '] = ''
        return spacer_df


    # 5. Concatenate All Pieces Horizontally (axis=1) and Export
    update_progress("Saving to folder...", 0.8)
    final_horizontal_matrix = pd.concat([
        grc_block, create_spacer(), create_spacer(),
        tur_block, create_spacer(), create_spacer(),
        ita_block, create_spacer(), create_spacer(),
        fmz_block, create_spacer(), create_spacer(),
        nat_block
    ], axis=1)
    
    # Fill structural missing NaN values caused by mismatched row counts with empty strings
    final_horizontal_matrix = final_horizontal_matrix.fillna('')
    
    # Save directly to CSV (header=False removes pandas' default programmatic column names)
    update_progress("Saving to folder...", 0.9)
    final_horizontal_matrix.to_csv(output_csv, index=False, header=False)
    print(f"Successfully generated left-aligned horizontal report with country sub-sections: '{output_csv}'")
    return output_csv