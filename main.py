import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD
import os
import threading
import asyncio
import re
import platform
import subprocess
import pandas as pd
from tkinter import filedialog
import VP_gfw 
import VP_map 
import VP_bulk_map
import VP_report
import AFE_report
import AFE_bulk_map
import AFE_map
import Port_visits

# --- Configuration ---
ctk.set_appearance_mode("Dark") 
ctk.set_default_color_theme("blue") 
CONFIG_FILE = "config.txt"

def load_api_key():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f: return f.read().strip()
    return None

def save_api_key(key):
    with open(CONFIG_FILE, "w") as f: f.write(key.strip())

class VesselTracker(TkinterDnD.Tk):
    def __init__(self):
        super().__init__() 

        self.title("GFW Vessel Tracker & Analyzer")
        self.geometry("600x750") 
        
        self.configure(bg="#2b2b2b")
        self.api_key = load_api_key()
        self.selected_file = None
        self.last_downloaded_file = None
        self.all_vessels = {} 

        if not self.api_key:
            self.show_setup_view()
        else:
            self.show_main_menu()

    def clear_view(self):
        for widget in self.winfo_children():
            widget.destroy()

    # --- ENHANCED THREADING SUPERVISOR ---
    def run_in_background(self, target_func, progress_bar, status_label, original_btn, next_action=None):
        """
        Runs heavy geospatial operations in a background thread.
        Safely catches exceptions on the background thread and passes errors to the UI.
        """
        is_running = [True]

        def wrapper():
            try:
                result = target_func()
                is_running[0] = False
                if next_action:
                    self.after(0, lambda: next_action(result))
            except Exception as e:
                is_running[0] = False
                error_msg = f"Failed execution: {str(e)}"
                self.after(0, lambda: status_label.configure(text=error_msg, text_color="#FF5252"))
                self.after(0, lambda: progress_bar.set(0))
                self.after(0, lambda: original_btn.configure(state="normal"))

        progress_bar.set(0.05)
        original_btn.configure(state="disabled")
        
        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()




    # --- VIEW: MAIN MENU ---
    def show_main_menu(self):
        self.clear_view()
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)
        
        ctk.CTkLabel(frame, text="Main Menu", font=ctk.CTkFont(size=26, weight="bold")).pack(pady=20)

        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Select Data Type:", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=10, fill="x")
        
        ctk.CTkButton(frame, text="Vessel Presence", height=60, width=350, fg_color="#1f538d",
                      command=self.show_vessel_presence_menu).pack(pady=15)
        
        ctk.CTkButton(frame, text="Apparent Fishing Effort", height=60, width=350, fg_color="#1f538d",
                      command=self.show_fishing_effort_view).pack(pady=10)
        
        ctk.CTkButton(frame, text="Port Visits", height=60, width=350, fg_color="#1f538d",
                      command=self.show_port_visits_view).pack(pady=10)

        ctk.CTkButton(frame, text="Reset API Key", fg_color="transparent", text_color="gray", 
                      command=self.handle_reset).pack(side="bottom", pady=20)
       
    # --- VIEW: VESSEL PRESENCE MENU ---
    def show_vessel_presence_menu(self):
        self.clear_view()
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)
        
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent", command=self.show_main_menu).pack(side="left")
        
        ctk.CTkLabel(frame, text="Vessel Presence Dashboard", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=20)
        
        ctk.CTkButton(frame, text="Download Vessel Presence Data", height=60, width=350, fg_color="#d15400",
                      command=self.show_dashboard_view).pack(pady=10)
        
        ctk.CTkButton(frame, text="Generate AIS Gap Report", height=60, width=350, 
                      command=self.show_report_view).pack(pady=10)
        
        ctk.CTkButton(frame, text="Generate AIS Gap Map (All Vessels)", height=60, width=350, 
                    command=self.show_bulk_map_view).pack(pady=10)
        
        ctk.CTkButton(frame, text="Generate AIS Gap Map (single vessel)", height=60, width=350, 
                      command=self.show_map_view).pack(pady=10)

    # --- VIEW: APPARENT FISHING EFFORT MENU ---
    def show_fishing_effort_view(self):
        self.clear_view()
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent", command=self.show_main_menu).pack(side="left")
        
        ctk.CTkLabel(frame, text="Apparent Fishing Effort Dashboard", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=20)
        
        ctk.CTkButton(frame, text="Download Apparent Fishing Effort Data", height=60, width=350, fg_color="#d15400",
                      command=self.show_afe_dashboard_view).pack(pady=10)
        
        ctk.CTkButton(frame, text="Generate AFE Report", height=60, width=350, 
                      command=self.show_afe_report_view).pack(pady=10)
        
        ctk.CTkButton(frame, text="Generate AFE Heatmap (All Vessels)", height=60, width=350, 
                      command=self.show_afe_heatmap_view).pack(pady=10)
        
        # --- NEW BUTTON TRIGGERED HERE ---
        ctk.CTkButton(frame, text="Generate AFE Heatmap (Single Vessel)", height=60, width=350, 
                      command=self.show_afe_single_vessel_view).pack(pady=10)
 


    # --- VIEW: VESSEL PRESENCE DATA LOADER ---
    def show_dashboard_view(self):
        self.clear_view()
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent", command=self.show_vessel_presence_menu).pack(side="left")
        ctk.CTkLabel(frame, text="GFW Vessel Presence Data Loader", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(0, 20))
        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Download GlobalFishingWatch AIS presence data for a specific country (or ALL) and period. " \
            "Output is saved as a .csv file in the same folder that contains this application.", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(frame, text="Select Country:").pack()
        self.flag_dropdown = ctk.CTkComboBox(frame, values=["ITA", "GRC", "TUR", "MLT", "TUN", "CYP", "DZA", "ALB", "FRA", "ALL"], state="readonly", width=220)
        self.flag_dropdown.set("GRC")
        self.flag_dropdown.pack(pady=(0, 20))

        date_frame = ctk.CTkFrame(frame, fg_color="transparent")
        date_frame.pack(pady=10)
        
        start_box = ctk.CTkFrame(date_frame, fg_color="transparent")
        start_box.pack(side="left", padx=10)
        ctk.CTkLabel(start_box, text="Start Date:").pack()
        self.start_entry = ctk.CTkEntry(start_box, placeholder_text="YYYY-MM-DD", width=140)
        self.start_entry.insert(0, "2026-01-01")
        self.start_entry.pack()

        end_box = ctk.CTkFrame(date_frame, fg_color="transparent")
        end_box.pack(side="left", padx=10)
        ctk.CTkLabel(end_box, text="End Date:").pack()
        self.end_entry = ctk.CTkEntry(end_box, placeholder_text="YYYY-MM-DD", width=140)
        self.end_entry.insert(0, "2026-01-31")
        self.end_entry.pack()

        self.status_label = ctk.CTkLabel(frame, text="", text_color="gray", wraplength=400)
        self.status_label.pack(pady=(30, 5))

        self.progress_bar = ctk.CTkProgressBar(frame, width=380)
        self.progress_bar.set(0)

        self.load_btn = ctk.CTkButton(frame, text="Download Data", fg_color="#d15400", command=lambda: self.start_download_task(data_type="VP"), width=250, height=40, font=ctk.CTkFont(weight="bold"))
        self.load_btn.pack(pady=30)

    # --- VIEW: AIS GAP REPORT GENERATOR ---
    def show_report_view(self):
        self.clear_view()
        self.selected_file = None
        
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent", command=self.show_vessel_presence_menu).pack(side="left")
        
        ctk.CTkLabel(frame, text="AIS Gap Report Generator", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=10)
        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Generates a report (in .csv format) of AIS gaps and encounter events for all vessels in the selected file.", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=20, fill="x")

        self.report_drop_frame = ctk.CTkFrame(frame, width=450, height=150, border_width=2, border_color="gray")
        self.report_drop_frame.pack(pady=10, padx=20)
        self.report_drop_frame.pack_propagate(False)

        self.report_status_label = ctk.CTkLabel(self.report_drop_frame, text="Drag & Drop CSV here\n-- or --", wraplength=300)
        self.report_status_label.pack(expand=True, pady=(10, 0))

        ctk.CTkButton(self.report_drop_frame, text="Browse Files", command=self.browse_report_file).pack(pady=10)

        self.filter_frame = ctk.CTkFrame(frame, fg_color="transparent")
        
        ctk.CTkLabel(self.filter_frame, text="Report Inclusion:").pack(pady=(10, 5))
        self.report_filter_var = ctk.StringVar(value="All Fishing Vessels")
        self.filter_switch = ctk.CTkSegmentedButton(
            self.filter_frame, 
            values=["All Fishing Vessels", "Trawlers Only"],
            variable=self.report_filter_var
        )
        self.filter_switch.pack()

        ctk.CTkLabel(self.filter_frame, text="Buffer Zone for Gap Analysis:").pack(pady=(10, 5))
        self.report_buffer_dropdown = ctk.CTkComboBox(
            self.filter_frame, 
            values=["1.5 nm", "3 nm", "6 nm"], 
            state="readonly"
        )
        self.report_buffer_dropdown.set("3 nm")
        self.report_buffer_dropdown.pack()

        self.report_drop_frame.drop_target_register(DND_FILES)
        self.report_drop_frame.dnd_bind('<<Drop>>', self.handle_report_drop)

        self.report_progress = ctk.CTkProgressBar(frame, width=300)
        self.report_progress.set(0)
        
        self.run_report_btn = ctk.CTkButton(frame, text="Generate Vessel Report", fg_color="#1f538d", 
                                            command=self.handle_generate_report, width=250, height=40)
  
    # --- VIEW: AIS GAP MAP GENERATOR (ALL VESSELS) ---
    def show_bulk_map_view(self):
        self.clear_view()
        self.selected_file = None
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent", command=self.show_vessel_presence_menu).pack(side="left")
        
        ctk.CTkLabel(frame, text="Generate AIS Gap Map (all vessels)", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=10)
        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Generate an interactive map showing the trajectory and AIS gaps for all vessels. "
                 "(map generation may take long depending on the selected time period and number of vessels, for long periods " \
                 "it is recommended to generate a single vessel map for specific vessels instead)", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=20, fill="x")

        self.bulk_drop_frame = ctk.CTkFrame(frame, width=450, height=150, border_width=2, border_color="gray")
        self.bulk_drop_frame.pack(pady=10, padx=20)
        self.bulk_drop_frame.pack_propagate(False)

        self.bulk_status_label = ctk.CTkLabel(self.bulk_drop_frame, text="Drag & Drop CSV here\n-- or --")
        self.bulk_status_label.pack(expand=True, pady=(10, 0))

        ctk.CTkButton(self.bulk_drop_frame, text="Browse", command=self.browse_bulk_file).pack(pady=10)
        
        self.bulk_drop_frame.drop_target_register(DND_FILES)
        self.bulk_drop_frame.dnd_bind('<<Drop>>', self.handle_bulk_drop)

        ctk.CTkLabel(frame, text="Vessel Filter:", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(10, 0))
        self.bulk_filter_var = ctk.StringVar(value="All Vessels")
        self.bulk_filter_toggle = ctk.CTkSegmentedButton(
            frame, 
            values=["All Vessels", "Trawlers Only"],
            variable=self.bulk_filter_var
        )
        self.bulk_filter_toggle.pack(pady=5)

        ctk.CTkLabel(frame, text="Buffer Zone (nm):", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(10, 0))
        self.bulk_buffer_var = ctk.StringVar(value="3")
        self.bulk_buffer_menu = ctk.CTkOptionMenu(
            frame,
            values=["1.5", "3", "6"],
            variable=self.bulk_buffer_var
        )
        self.bulk_buffer_menu.pack(pady=5)

        self.bulk_progress = ctk.CTkProgressBar(frame, width=300)
        self.bulk_progress.set(0)

        self.run_bulk_btn = ctk.CTkButton(frame, text="Generate Bulk Map", command=self.handle_generate_bulk_map, width=250, height=40)
        self.run_bulk_btn.pack(pady=20)

    # --- VIEW: AIS GAP MAP GENERATOR (SINGLE VESSEL)---
    def show_map_view(self):
        self.clear_view()
        self.selected_file = None
        self.current_selected_id = None
        
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=10, fill="both", expand=True) 

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=5) 
        ctk.CTkButton(header, text="← Back", width=50, fg_color="transparent", 
                      command=self.show_vessel_presence_menu).pack(side="left")
        
        ctk.CTkLabel(frame, text="Generate AIS Gap Map (single vessel)", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=2) 
        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Generate an interactive map showing the trajectory and AIS gaps for a single vessel. "
                 "(generating a map for a single vessel is recommended when the selected time period is too long to generate a map for all vessels)", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=20, fill="x")

        self.map_drop_frame = ctk.CTkFrame(frame, width=450, height=100, border_width=2, border_color="gray") 
        self.map_drop_frame.pack(pady=5, padx=20)
        self.map_drop_frame.pack_propagate(False)

        self.map_status_label = ctk.CTkLabel(self.map_drop_frame, text="Drag & Drop CSV or Browse", font=ctk.CTkFont(size=12))
        self.map_status_label.pack(expand=True, pady=(5, 0))

        ctk.CTkButton(self.map_drop_frame, text="Browse", height=28, command=self.browse_map_file).pack(pady=5) 

        self.map_drop_frame.drop_target_register(DND_FILES)
        self.map_drop_frame.dnd_bind('<<Drop>>', self.handle_map_drop)

        self.search_frame = ctk.CTkFrame(frame, fg_color="transparent")
        
        filter_label_row = ctk.CTkFrame(self.search_frame, fg_color="transparent")
        filter_label_row.pack(fill="x", pady=2)
        ctk.CTkLabel(filter_label_row, text="Filter:", font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
        
        self.map_filter_var = ctk.StringVar(value="All Vessels")
        self.map_filter_switch = ctk.CTkSegmentedButton(
            filter_label_row, 
            values=["All Vessels", "Trawlers"], 
            variable=self.map_filter_var,
            command=self.filter_vessels,
            height=28
        )
        self.map_filter_switch.pack(side="right", fill="x", expand=True, padx=5)

        settings_row = ctk.CTkFrame(self.search_frame, fg_color="transparent")
        settings_row.pack(fill="x", pady=2)
        
        self.buffer_dropdown = ctk.CTkComboBox(settings_row, values=["1.5 nm", "3 nm", "6 nm"], 
                                               state="readonly", width=100, height=28)
        self.buffer_dropdown.set("3 nm")
        self.buffer_dropdown.pack(side="left", padx=5)
        
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self.filter_vessels)
        self.vessel_search = ctk.CTkEntry(settings_row, textvariable=self.search_var, 
                                          placeholder_text="Search Name/MMSI...", height=28)
        self.vessel_search.pack(side="right", fill="x", expand=True, padx=5)

        self.vessel_list_frame = ctk.CTkScrollableFrame(self.search_frame, height=220, label_text="Results")
        self.vessel_list_frame.pack(fill="x", pady=5)

        self.selected_vessel_label = ctk.CTkLabel(self.search_frame, text="Selected: None", 
                                                  text_color="#3a7ebf", font=ctk.CTkFont(size=12, weight="bold"))
        self.selected_vessel_label.pack(pady=2)

        self.map_progress = ctk.CTkProgressBar(frame, width=300)
        self.map_progress.set(0)

        self.run_map_btn = ctk.CTkButton(frame, text="Generate Map", fg_color="#1f538d", 
                                         command=self.handle_generate_single_map, width=250, height=35)



    # --- VIEW: APPARENT FISHING EFFORT DATA LOADER ---
    def show_afe_dashboard_view(self):
        self.clear_view()
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent", command=self.show_fishing_effort_view).pack(side="left")
        ctk.CTkLabel(frame, text="GFW Fishing Effort Data Loader", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(0, 20))
        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Download GlobalFishingWatch Apparent Fishing Effort (AFE) data for a specific country (or ALL) and period. " \
            "Output is saved as a .csv file in the same folder that contains this application.", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(frame, text="Select Country:").pack()
        self.flag_dropdown = ctk.CTkComboBox(frame, values=["ITA", "GRC", "TUR", "MLT", "TUN", "CYP", "DZA", "ALB", "FRA", "ALL"], state="readonly", width=220)
        self.flag_dropdown.set("GRC")
        self.flag_dropdown.pack(pady=(0, 20))

        date_frame = ctk.CTkFrame(frame, fg_color="transparent")
        date_frame.pack(pady=10)
        
        start_box = ctk.CTkFrame(date_frame, fg_color="transparent")
        start_box.pack(side="left", padx=10)
        ctk.CTkLabel(start_box, text="Start Date:").pack()
        self.start_entry = ctk.CTkEntry(start_box, placeholder_text="YYYY-MM-DD", width=140)
        self.start_entry.insert(0, "2026-01-01")
        self.start_entry.pack()

        end_box = ctk.CTkFrame(date_frame, fg_color="transparent")
        end_box.pack(side="left", padx=10)
        ctk.CTkLabel(end_box, text="End Date:").pack()
        self.end_entry = ctk.CTkEntry(end_box, placeholder_text="YYYY-MM-DD", width=140)
        self.end_entry.insert(0, "2026-01-31")
        self.end_entry.pack()

        self.status_label = ctk.CTkLabel(frame, text="", text_color="gray", wraplength=400)
        self.status_label.pack(pady=(30, 5))

        self.progress_bar = ctk.CTkProgressBar(frame, width=380)
        self.progress_bar.set(0)

        self.load_btn = ctk.CTkButton(frame, text="Download Data", fg_color="#d15400", command=lambda: self.start_download_task(data_type="AFE"), width=250, height=40, font=ctk.CTkFont(weight="bold"))
        self.load_btn.pack(pady=30)

    # --- VIEW: AFE REPORT GENERATOR ---
    def show_afe_report_view(self):
        self.clear_view()
        self.selected_file = None
        
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent", command=self.show_fishing_effort_view).pack(side="left")
        
        ctk.CTkLabel(frame, text="AFE Report Generator", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=10)
        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Generates a report based on Apparent Fishing Effort (AFE) from the selected dataset.", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=20, fill="x")

        self.afe_drop_frame = ctk.CTkFrame(frame, width=450, height=150, border_width=2, border_color="gray")
        self.afe_drop_frame.pack(pady=10, padx=20)
        self.afe_drop_frame.pack_propagate(False)

        self.afe_status_label = ctk.CTkLabel(self.afe_drop_frame, text="Drag & Drop AFE CSV here\n-- or --", wraplength=300)
        self.afe_status_label.pack(expand=True, pady=(10, 0))

        ctk.CTkButton(self.afe_drop_frame, text="Browse Files", command=self.browse_afe_report_file).pack(pady=10)

        self.afe_drop_frame.drop_target_register(DND_FILES)
        self.afe_drop_frame.dnd_bind('<<Drop>>', self.handle_afe_report_drop)

        self.afe_progress = ctk.CTkProgressBar(frame, width=300)
        self.afe_progress.set(0)
        
        self.run_afe_report_btn = ctk.CTkButton(frame, text="Generate AFE Report", fg_color="#1f538d", 
                                                command=self.handle_generate_afe_report, width=250, height=40)

    # --- VIEW: AFE HEATMAP GENERATOR (ALL VESSELS) ---
    def show_afe_heatmap_view(self):
        self.clear_view()
        self.selected_file = None
        
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent", command=self.show_fishing_effort_view).pack(side="left")
        
        ctk.CTkLabel(frame, text="AFE Heatmap Generator (All Vessels)", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=10)
        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Generates an interactive heatmap showing Apparent Fishing Effort (AFE) for all vessels in the selected file. " \
                 "Each grid cell contains a summary of fishing activity per country and per vessel in that area. Map generation might take a long time for" \
                 " long time periods, it is recommended to generate a single vessel heatmap instead.", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=20, fill="x")

        self.heatmap_drop_frame = ctk.CTkFrame(frame, width=450, height=150, border_width=2, border_color="gray")
        self.heatmap_drop_frame.pack(pady=10, padx=20)
        self.heatmap_drop_frame.pack_propagate(False)

        self.heatmap_status_label = ctk.CTkLabel(self.heatmap_drop_frame, text="Drag & Drop AFE CSV here\n-- or --", wraplength=300)
        self.heatmap_status_label.pack(expand=True, pady=(10, 0))

        ctk.CTkButton(self.heatmap_drop_frame, text="Browse Files", command=self.browse_afe_heatmap_file).pack(pady=10)

        self.heatmap_drop_frame.drop_target_register(DND_FILES)
        self.heatmap_drop_frame.dnd_bind('<<Drop>>', self.handle_afe_heatmap_drop)

        ctk.CTkLabel(frame, text="Vessel Filter:", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(10, 0))
        self.bulk_filter_var = ctk.StringVar(value="All Vessels")
        self.bulk_filter_toggle = ctk.CTkSegmentedButton(
            frame, 
            values=["All Vessels", "Trawlers Only"],
            variable=self.bulk_filter_var
        )
        self.bulk_filter_toggle.pack(pady=5)

        ctk.CTkLabel(frame, text="Buffer Zone (nm):", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(10, 0))
        self.bulk_buffer_var = ctk.StringVar(value="3")
        self.bulk_buffer_menu = ctk.CTkOptionMenu(
            frame,
            values=["1.5", "3", "6"],
            variable=self.bulk_buffer_var
        )
        self.bulk_buffer_menu.pack(pady=5)

        self.heatmap_progress = ctk.CTkProgressBar(frame, width=300)
        self.heatmap_progress.set(0)
        
        self.run_heatmap_btn = ctk.CTkButton(frame, text="Generate AFE Heatmap", fg_color="#1f538d", 
                                             command=self.handle_generate_afe_heatmap, width=250, height=40)
        self.run_heatmap_btn.pack(pady=20)

    # --- VIEW: AFE HEATMAP GENERATOR (SINGLE VESSEL)---
    def show_afe_single_vessel_view(self):
        self.clear_view()
        self.selected_file = None
        self.current_selected_id = None
        
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=10, fill="both", expand=True) 

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=5) 
        ctk.CTkButton(header, text="← Back", width=50, fg_color="transparent", 
                      command=self.show_fishing_effort_view).pack(side="left")
        
        ctk.CTkLabel(frame, text="AFE Heatmap Generator (Single Vessel)", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=2) 
        self.desc_label = ctk.CTkLabel(
            frame, 
            text="Generates an interactive heatmap showing Apparent Fishing Effort (AFE) for the selected vessel. " \
                 "Each grid cell contains a summary of that vessel's activity in that area. A single vessel heatmap is recommended " \
                 "when the selected time period is too long to generate a heatmap for all vessels.", 
            font=ctk.CTkFont(size=12),
            wraplength=400
        )
        self.desc_label.pack(pady=10, padx=20, fill="x")

        self.afe_single_drop_frame = ctk.CTkFrame(frame, width=450, height=100, border_width=2, border_color="gray") 
        self.afe_single_drop_frame.pack(pady=5, padx=20)
        self.afe_single_drop_frame.pack_propagate(False)

        self.afe_single_status_label = ctk.CTkLabel(self.afe_single_drop_frame, text="Drag & Drop AFE CSV or Browse", font=ctk.CTkFont(size=12))
        self.afe_single_status_label.pack(expand=True, pady=(5, 0))

        ctk.CTkButton(self.afe_single_drop_frame, text="Browse", height=28, command=self.browse_afe_single_file).pack(pady=5) 

        self.afe_single_drop_frame.drop_target_register(DND_FILES)
        self.afe_single_drop_frame.dnd_bind('<<Drop>>', self.handle_afe_single_drop)

        self.afe_single_search_frame = ctk.CTkFrame(frame, fg_color="transparent")
        
        filter_label_row = ctk.CTkFrame(self.afe_single_search_frame, fg_color="transparent")
        filter_label_row.pack(fill="x", pady=2)
        ctk.CTkLabel(filter_label_row, text="Filter:", font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
        
        self.afe_single_filter_var = ctk.StringVar(value="All Vessels")
        self.afe_single_filter_switch = ctk.CTkSegmentedButton(
            filter_label_row, 
            values=["All Vessels", "Trawlers"], 
            variable=self.afe_single_filter_var,
            command=self.filter_afe_vessels,
            height=28
        )
        self.afe_single_filter_switch.pack(side="right", fill="x", expand=True, padx=5)

        settings_row = ctk.CTkFrame(self.afe_single_search_frame, fg_color="transparent")
        settings_row.pack(fill="x", pady=2)
        
        self.afe_single_buffer_dropdown = ctk.CTkComboBox(settings_row, values=["1.5 nm", "3 nm", "6 nm"], 
                                                          state="readonly", width=100, height=28)
        self.afe_single_buffer_dropdown.set("3 nm")
        self.afe_single_buffer_dropdown.pack(side="left", padx=5)
        
        self.afe_single_search_var = ctk.StringVar()
        self.afe_single_search_var.trace_add("write", self.filter_afe_vessels)
        self.afe_single_vessel_search = ctk.CTkEntry(settings_row, textvariable=self.afe_single_search_var, 
                                                    placeholder_text="Search Name/Vessel ID...", height=28)
        self.afe_single_vessel_search.pack(side="right", fill="x", expand=True, padx=5)

        self.afe_single_list_frame = ctk.CTkScrollableFrame(self.afe_single_search_frame, height=220, label_text="Vessels Found")
        self.afe_single_list_frame.pack(fill="x", pady=5)

        self.afe_single_selected_label = ctk.CTkLabel(self.afe_single_search_frame, text="Selected: None", 
                                                            text_color="#3a7ebf", font=ctk.CTkFont(size=12, weight="bold"))
        self.afe_single_selected_label.pack(pady=2)

        self.afe_single_progress = ctk.CTkProgressBar(frame, width=300)
        self.afe_single_progress.set(0)

        self.run_afe_single_btn = ctk.CTkButton(frame, text="Generate Map", fg_color="#1f538d", 
                                                   command=self.handle_generate_afe_single_map, width=250, height=35)

    # --- VIEW: PORT VISITS ---
    def show_port_visits_view(self):
        self.clear_view()
        self.pv_selected_vessel = None
        self.pv_results = {}

        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=10, fill="both", expand=True)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(header, text="← Back", width=60, fg_color="transparent",
                        command=self.show_main_menu).pack(side="left")

        ctk.CTkLabel(frame, text="Port Visits Lookup",
                        font=ctk.CTkFont(size=22, weight="bold")).pack(pady=5)
        ctk.CTkLabel(frame, text="Search a vessel by name, MMSI or IMO, then retrieve every "
                                    "port it visited during the selected period.",
                        font=ctk.CTkFont(size=12), wraplength=400).pack(pady=(0, 10), padx=20)

        # --- Search row ---
        search_row = ctk.CTkFrame(frame, fg_color="transparent")
        search_row.pack(fill="x", padx=20, pady=5)
        self.pv_query_entry = ctk.CTkEntry(search_row, placeholder_text="Vessel name / MMSI / IMO", height=32)
        self.pv_query_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.pv_search_btn = ctk.CTkButton(search_row, text="Search", width=90, height=32,
                                            command=self.handle_search_vessel)
        self.pv_search_btn.pack(side="right")

        # --- Results list ---
        self.pv_list_frame = ctk.CTkScrollableFrame(frame, height=160, label_text="Vessels Found")
        self.pv_list_frame.pack(fill="x", padx=20, pady=5)

        self.pv_selected_label = ctk.CTkLabel(frame, text="Selected: None",
                                                text_color="#3a7ebf",
                                                font=ctk.CTkFont(size=12, weight="bold"))
        self.pv_selected_label.pack(pady=2)

        # --- Dates ---
        date_frame = ctk.CTkFrame(frame, fg_color="transparent")
        date_frame.pack(pady=5)

        start_box = ctk.CTkFrame(date_frame, fg_color="transparent")
        start_box.pack(side="left", padx=10)
        ctk.CTkLabel(start_box, text="Start Date:").pack()
        self.pv_start_entry = ctk.CTkEntry(start_box, placeholder_text="YYYY-MM-DD", width=140)
        self.pv_start_entry.insert(0, "2025-01-01")
        self.pv_start_entry.pack()

        end_box = ctk.CTkFrame(date_frame, fg_color="transparent")
        end_box.pack(side="left", padx=10)
        ctk.CTkLabel(end_box, text="End Date:").pack()
        self.pv_end_entry = ctk.CTkEntry(end_box, placeholder_text="YYYY-MM-DD", width=140)
        self.pv_end_entry.insert(0, "2025-12-31")
        self.pv_end_entry.pack()

        self.pv_status_label = ctk.CTkLabel(frame, text="", text_color="gray", wraplength=400)
        self.pv_status_label.pack(pady=(10, 3))

        self.pv_progress = ctk.CTkProgressBar(frame, width=300)
        self.pv_progress.set(0)

        self.pv_run_btn = ctk.CTkButton(frame, text="Get Port Visits", fg_color="#d15400",
                                        command=self.handle_get_port_visits, width=250, height=38,
                                        font=ctk.CTkFont(weight="bold"))
        self.pv_run_btn.pack(pady=15)
        self.pv_start_entry.bind("<KeyRelease>", self.reset_pv_button)
        self.pv_end_entry.bind("<KeyRelease>", self.reset_pv_button)


    # --- LOGIC: PORT VISITS ---
    def update_pv_progress(self, text, value):
        self.after(0, lambda: self.pv_status_label.configure(
            text=text, text_color="#FFB300" if value < 1.0 else "#4CAF50"))
        self.after(0, lambda: self.pv_progress.set(value))

    def handle_search_vessel(self):
        query = self.pv_query_entry.get().strip()
        if not query:
            self.pv_status_label.configure(text="Enter a name, MMSI or IMO first.", text_color="#FF5252")
            return

        self.pv_search_btn.configure(state="disabled", text="...")
        self.pv_status_label.configure(text="Searching GFW vessel registry...", text_color="#FFB300")

        def worker():
            try:
                client = VP_gfw.get_gfw_client(self.api_key)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                df = loop.run_until_complete(Port_visits.search_vessel(query, client))
                self.after(0, lambda: self.populate_vessel_results(df))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self.pv_status_label.configure(
                    text=f"Search failed: {msg[:70]}", text_color="#FF5252"))
                self.after(0, lambda: self.pv_search_btn.configure(state="normal", text="Search"))

        threading.Thread(target=worker, daemon=True).start()

    def populate_vessel_results(self, df):
        for widget in self.pv_list_frame.winfo_children():
            widget.destroy()
        self.pv_results = {}
        self.reset_pv_button()
        self.pv_search_btn.configure(state="normal", text="Search")

        if df is None or df.empty:
            self.pv_status_label.configure(text="No vessel found.", text_color="#FF5252")
            return

        if "to" in df.columns:
            df = df.sort_values("to", ascending=False)

        seen_mmsi = set()
        for _, row in df.iterrows():
            vid = row.get("vessel_id")
            mmsi = row.get("mmsi")
            if pd.isnull(vid) or pd.isnull(mmsi):
                continue

            ids = df[df["mmsi"] == mmsi]["vessel_id"].dropna().tolist()

            if mmsi in seen_mmsi:
                continue
            seen_mmsi.add(mmsi)

            name = row.get("ship_name") if pd.notnull(row.get("ship_name")) else "Unknown"
            flag = row.get("flag") if pd.notnull(row.get("flag")) else "?"
            owner = row.get("owner") if pd.notnull(row.get("owner")) else "Owner unknown"
            label = f"{name} | MMSI {mmsi} | {flag} | Owner Name: {owner}"
            grp = df[df["mmsi"] == mmsi]
            def first_valid(col):
                s = grp[col].dropna() if col in grp.columns else pd.Series(dtype=object)
                return s.iloc[0] if not s.empty else None
            self.pv_results[label] = {
                "ids": ids,
                "name": name,
                "owner": owner,
                "mmsi": mmsi,
                "imo": first_valid("imo"),
                "vessel_type": first_valid("vessel_type"),
                "gear_type": first_valid("gear_type"),
                "length_m": first_valid("length_m"),
            }

            ctk.CTkButton(self.pv_list_frame, text=label, fg_color="transparent",
                          text_color="white", anchor="w", hover_color="#1f538d",
                          command=lambda l=label: self.select_pv_vessel(l)).pack(fill="x", pady=1)

        if not self.pv_results:
            self.pv_status_label.configure(text="Vessels found but no usable ID.", text_color="#FF5252")
            return

        self.pv_status_label.configure(text=f"Found {len(self.pv_results)} vessel(s).",
                                       text_color="#4CAF50")
        
    def select_pv_vessel(self, label):
        self.pv_selected_vessel = (label, self.pv_results[label])
        self.pv_selected_label.configure(text=f"Selected: {label}")
        self.reset_pv_button()

    def handle_get_port_visits(self):
        if not self.pv_selected_vessel:
            self.pv_status_label.configure(text="Select a vessel first!", text_color="#FF5252")
            return

        start = self.pv_start_entry.get().strip()
        end = self.pv_end_entry.get().strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", start) or not re.match(r"^\d{4}-\d{2}-\d{2}$", end):
            self.pv_status_label.configure(text="Error: Use YYYY-MM-DD", text_color="#FF5252")
            return

        self.pv_progress.pack(pady=5)
        self.pv_progress.set(0.1)
        self.pv_run_btn.configure(state="disabled")
        self.pv_status_label.configure(text="Fetching port visit events...", text_color="#FFB300")

        label, info = self.pv_selected_vessel
        vessel_ids = info["ids"]
        vessel_name = info["name"]

        def worker():
            try:
                client = VP_gfw.get_gfw_client(self.api_key)
                out, n, n_ports = Port_visits.generate_port_report(
                    vessel_ids, vessel_name, start, end, client,
                    owner=info["owner"],
                    mmsi=info["mmsi"],
                    imo=info["imo"],
                    vessel_type=info["vessel_type"],
                    gear_type=info["gear_type"],
                    length_m=info["length_m"],
                    progress_callback=self.update_pv_progress
                )
                self.after(0, lambda: self.finish_pv(out, n, n_ports))
            except Exception as e:
                msg = str(e)
                print(msg)
                self.after(0, lambda: self.pv_status_label.configure(
                    text=f"Error: {msg[:150]}", text_color="#FF5252"))
                self.after(0, lambda: self.pv_progress.set(0))
                self.after(0, lambda: self.pv_run_btn.configure(
                    state="normal", text="Get Port Visits", fg_color="#d15400"))

        threading.Thread(target=worker, daemon=True).start()

    def finish_pv(self, out_file, n_visits, n_ports):
        self.pv_progress.set(1.0)
        self.pv_status_label.configure(
            text=f"{n_visits} visits across {n_ports} distinct ports.",
            text_color="#4CAF50")
        self.pv_run_btn.configure(text="Open CSV", state="normal", fg_color="#2E7D32",
                                  command=lambda: self.open_file(out_file))

    def reset_pv_button(self, *args):
        self.pv_run_btn.configure(
            text="Get Port Visits", state="normal", fg_color="#d15400",
            command=self.handle_get_port_visits
        )
        self.pv_progress.set(0)
        self.pv_progress.pack_forget()  

    # --- LOGIC HANDLERS FOR APPARENT FISHING EFFORT ---
    # AFE REPORT
    def browse_afe_report_file(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path: self.update_afe_report_selection(path)

    def handle_afe_report_drop(self, event):
        path = event.data.strip().strip('{}')
        if path.lower().endswith('.csv'): self.update_afe_report_selection(path)

    def update_afe_report_selection(self, path):
        self.selected_file = path
        self.afe_status_label.configure(text=f"Selected:\n{os.path.basename(path)}", text_color="#4CAF50")
        self.run_afe_report_btn.pack(pady=20)

    def update_afe_report_progress(self, text, value):
        """Helper to safely update the specific AFE Report UI widgets from the thread."""
        # Assuming you follow the same naming pattern (e.g., self.afe_status_label and self.afe_progress)
        self.afe_status_label.configure(text=text, text_color="#FFB300" if value < 1.0 else "#4CAF50")
        self.afe_progress.set(value)

    def handle_generate_afe_report(self):
        if not self.selected_file:
            self.afe_status_label.configure(text="Please select a file first!", text_color="#FF5252")
            return

        # 1. Initialize the Progress UI State
        self.afe_progress.pack(pady=5)
        self.afe_progress.set(0.0)
        self.afe_status_label.configure(text="Initializing AFE report thread...", text_color="#FFB300")
        self.run_afe_report_btn.configure(state="disabled") # Prevent double-clicks during generation

        # 2. Define the worker that executes sequentially inside the background thread
        def run_afe_logic_worker():
            try:
                df = pd.read_csv(self.selected_file)
                if 'timestamp' in df.columns and 'date' not in df.columns:
                    df['date'] = df['timestamp']
                
                # Dynamic inputs based on what your AFE UI view provides
                out_filename = "AFE_vessel_report.csv" # Or dynamic path if chosen
                
                # Execute create_AFE_report passing our UI progress updater directly
                # Adjust variable names to match your AFE UI exactly
                AFE_report.create_AFE_report(
                    df, 
                    output_csv=out_filename,
                    progress_callback=self.update_afe_report_progress
                )
                
                # Successfully completed processing and writing out file
                self.update_afe_report_progress("AFE Report Ready!", 1.0)
                self.run_afe_report_btn.configure(
                    text="Open AFE Report", 
                    state="normal", 
                    fg_color="#2E7D32", 
                    command=lambda: self.open_file(out_filename)
                )
                
            except Exception as e:
                self.afe_status_label.configure(text=f"Error: {str(e)[:60]}", text_color="#FF5252")
                self.afe_progress.set(0)
                self.run_afe_report_btn.configure(state="normal", text="Run AFE Report", fg_color="#1f538d")

        # 3. Spawn the background thread to run the process cleanly without locking the UI
        threading.Thread(target=run_afe_logic_worker, daemon=True).start()


    # ALL VESSELS HEATMAP
    def update_all_vessels_heatmap_progress(self, text, value):
        """Helper to safely update the All Vessels AFE Heatmap UI widgets from the background thread."""
        self.heatmap_status_label.configure(text=text, text_color="#FFB300" if value < 1.0 else "#4CAF50")
        self.heatmap_progress.set(value)

    def handle_generate_afe_heatmap(self):
        if not self.selected_file:
            self.heatmap_status_label.configure(text="Please select a file first!", text_color="#FF5252")
            return
        
        # 1. Initialize the Progress UI State inside the View Panel
        self.heatmap_progress.pack(pady=5)
        self.heatmap_progress.set(0.0)
        self.heatmap_status_label.configure(text="Initializing global AFE compilation thread...", text_color="#FFB300")
        self.run_heatmap_btn.configure(state="disabled") # Prevent double-click process spawning

        # 2. Define the execution logic that isolates the heavy processing away from the main loop
        def run_all_heatmap_worker():
            try:
                df = pd.read_csv(self.selected_file)
                if 'timestamp' in df.columns and 'date' not in df.columns:
                    df['date'] = df['timestamp']
                
                # Fetch dropdown configuration variables safely if defined, otherwise apply defaults
                # (Matches create_AFE_heatmap's native arguments)
                buffer_choice = float(self.bulk_buffer_var.get()) if hasattr(self, 'bulk_buffer_var') else 3
                filter_choice = self.bulk_filter_var.get() if hasattr(self, 'bulk_filter_var') else "All Vessels"
                
                # Execute the bulk map pipeline, passing our specific UI update tracker
                out_file = AFE_bulk_map.create_AFE_heatmap(
                    df, 
                    buffer_dis=buffer_choice, 
                    filter_type=filter_choice,
                    progress_callback=self.update_all_vessels_heatmap_progress
                )
                
                # Processing finalized and map file exported successfully
                self.update_all_vessels_heatmap_progress("Heatmap Complete!", 1.0)
                self.run_heatmap_btn.configure(
                    text="Open Heatmap", 
                    state="normal", 
                    fg_color="#2E7D32", 
                    command=lambda: self.open_file(out_file)
                )
                
            except Exception as e:
                self.heatmap_status_label.configure(text=f"Error: {str(e)[:60]}", text_color="#FF5252")
                self.heatmap_progress.set(0)
                self.run_heatmap_btn.configure(state="normal", text="Generate AFE Heatmap", fg_color="#1f538d")

        # 3. Spawn a clean background daemon thread to shield the window framework from freezing
        threading.Thread(target=run_all_heatmap_worker, daemon=True).start()


    # SINGLE VESSEL HEATMAP
    def update_afe_heatmap_progress(self, text, value):
        """Helper to safely update the specific AFE Heatmap UI widgets from the thread."""
        # Adjust these widget names if they differ slightly in your layout
        self.afe_single_status_label.configure(text=text, text_color="#FFB300" if value < 1.0 else "#4CAF50")
        self.afe_single_progress.set(value)

    def handle_generate_afe_single_map(self):
        if not self.selected_file or not self.current_selected_id:
            self.afe_single_status_label.configure(text="Select a file and vessel first!", text_color="#FF5252")
            return
        
        # 1. Initialize the Progress UI State
        self.afe_single_progress.pack(pady=5)
        self.afe_single_progress.set(0.0)
        self.afe_single_status_label.configure(text="Initializing AFE heatmap generation thread...", text_color="#FFB300")
        self.run_afe_single_btn.configure(state="disabled") # Prevent concurrent execution spam

        # 2. Define the worker that executes sequentially inside the background thread
        def run_afe_heatmap_worker():
            try:
                buffer_val = float(self.afe_single_buffer_dropdown.get().split(" ")[0]) # Or your specific AFE drop-down widget
                df = pd.read_csv(self.selected_file)
                if 'timestamp' in df.columns and 'date' not in df.columns:
                    df['date'] = df['timestamp']
                
                # Extract target vessel data subset
                # Assuming AFE_map uses the same get_vessel_data or an equivalent slice filter
                v_data = df[df['vessel_id'] == self.current_selected_id].copy()
                
                # Execute create_AFE_vessel_heatmap passing our direct UI updater callback
                out_file = AFE_map.create_AFE_vessel_heatmap(
                    v_data, 
                    buffer_dis=buffer_val, 
                    progress_callback=self.update_afe_heatmap_progress
                )
                
                # Map successfully compiled and file written to disk
                self.update_afe_heatmap_progress("Heatmap Ready!", 1.0)
                self.run_afe_single_btn.configure(
                    text="Open AFE Heatmap", 
                    state="normal", 
                    fg_color="#2E7D32", 
                    command=lambda: self.open_file(out_file)
                )
                
            except Exception as e:
                self.afe_single_status_label.configure(text=f"Error: {str(e)[:60]}", text_color="#FF5252")
                self.afe_single_progress.set(0)
                self.run_afe_single_btn.configure(state="normal", text="Run Heatmap", fg_color="#1f538d")

        # 3. Spawn a dedicated background thread to run the process
        threading.Thread(target=run_afe_heatmap_worker, daemon=True).start()

    def select_afe_vessel(self, name):
        self.current_selected_id = self.all_vessels[name]
        self.afe_single_selected_label.configure(text=f"Selected: {name}")
        self.afe_single_search_var.set(name)

    def browse_afe_heatmap_file(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path: self.update_afe_heatmap_selection(path)

    def update_afe_heatmap_selection(self, path):
        self.selected_file = path
        self.heatmap_status_label.configure(text=f"Selected:\n{os.path.basename(path)}", text_color="#4CAF50")
        self.run_heatmap_btn.pack(pady=20)

    def browse_afe_single_file(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path: self.update_afe_single_selection(path)

    def handle_afe_single_drop(self, event):
        path = event.data.strip().strip('{}')
        if path.lower().endswith('.csv'): self.update_afe_single_selection(path)

    def update_afe_single_selection(self, path):
        self.selected_file = path
        try:
            self.current_map_df = pd.read_csv(path)
            self.afe_single_status_label.configure(text=f"Loaded: {os.path.basename(path)}", text_color="#4CAF50")
            self.afe_single_search_frame.pack(pady=10, padx=20, fill="x")
            self.run_afe_single_btn.pack(pady=10)
            self.filter_afe_vessels() 
        except Exception as e:
            self.afe_single_status_label.configure(text=f"Error: {str(e)[:50]}", text_color="#FF5252")

    def filter_afe_vessels(self, *args):
        for widget in self.afe_single_list_frame.winfo_children():
            widget.destroy()
        if not hasattr(self, 'current_map_df'):
            return

        df = self.current_map_df
        if self.afe_single_filter_var.get() == "Trawlers" and 'gear_type' in df.columns:
            df = df[df['gear_type'].astype(str).str.upper() == 'TRAWLERS']

        self.all_vessels = {}
        # Checks AFE compatible structure column parameters
        required_cols = ['vessel_id', 'ship_name']
        if not all(col in df.columns for col in required_cols):
            return

        for _, row in df[required_cols].drop_duplicates().iterrows():
            name = str(row['ship_name']) if pd.notnull(row['ship_name']) and str(row['ship_name']) != "" and str(row['ship_name']) != "nan" else "Unknown Vessel"
            display_name = f"{name} (ID: {str(row['vessel_id'])[:8]})"
            self.all_vessels[display_name] = row['vessel_id']

        search_term = self.afe_single_search_var.get().lower()
        matches = [name for name in self.all_vessels.keys() if search_term in name.lower()]

        for name in sorted(matches):
            btn = ctk.CTkButton(
                self.afe_single_list_frame, text=name, fg_color="transparent", text_color="white",
                anchor="w", hover_color="#1f538d", command=lambda n=name: self.select_afe_vessel(n)
            )
            btn.pack(fill="x", pady=1)
        
        self.afe_single_status_label.configure(text=f"Found {len(matches)} vessels", text_color="#4CAF50")

    def handle_afe_heatmap_drop(self, event):
        path = event.data.strip().strip('{}')
        if path.lower().endswith('.csv'): self.update_afe_heatmap_selection(path)




# --- LOGIC HANDLERS FOR VESSEL PRESENCE ---
    # REPORT
    def handle_report_drop(self, event):
        path = event.data.strip().strip('{}')
        if path.lower().endswith('.csv'): self.update_report_selection(path)

    def browse_report_file(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path: self.update_report_selection(path)

    def update_report_selection(self, path):
        self.selected_file = path
        self.report_status_label.configure(text=f"Selected:\n{os.path.basename(path)}", text_color="#4CAF50")
        
        # Reset run button states if another file is picked later
        self.run_report_btn.configure(text="Generate Vessel Report", fg_color="#1f538d", command=self.handle_generate_report)
        
        self.filter_frame.pack(pady=10)
        self.run_report_btn.pack(pady=10)

    def handle_generate_report(self):
        """Generates the VP report using real deterministic progress tracking metrics."""
        if not self.selected_file:
            return
        
        # 1. UI initialization setup
        self.report_progress.pack(pady=5)
        self.run_report_btn.configure(state="disabled")
        self.report_progress.set(0)

        # 2. Extract configuration items from GUI state
        filter_choice = self.report_filter_var.get()
        buffer_val = float(self.report_buffer_dropdown.get().split(" ")[0])
        
        filename = os.path.basename(self.selected_file)
        date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", filename)
        start = date_matches[0] if len(date_matches) >= 1 else "N/A"
        end = date_matches[1] if len(date_matches) >= 2 else "N/A"

        # 3. Safe progress interface callback bridging back to the UI thread
        def progress_callback(status_text, progress_fraction):
            self.after(0, lambda: self.update_report_ui(status_text, progress_fraction))

        # 4. Background processing loop thread target
        def worker():
            try:
                df = pd.read_csv(self.selected_file)
                if 'timestamp' in df.columns and 'date' not in df.columns:
                    df['date'] = df['timestamp']

                output_file = "VP_report.csv"
                
                # Execute report calculations with the explicit progress hook linked
                VP_report.generate_vessel_report(
                    df=df,
                    filter_type=filter_choice,
                    start_date=start,
                    end_date=end,
                    buffer_dis=buffer_val,
                    output_filename=output_file,
                    progress_callback=progress_callback
                )
                
                # Retrieve individual row lengths safely for final notification UI text updates
                unique_vessels_count = df['vessel_id'].nunique() if 'vessel_id' in df.columns else len(df)
                
                self.after(0, lambda: self.finish_report_ui(unique_vessels_count, output_file))
                
            except Exception as e:
                error_msg = str(e)  # Capture the string immediately
                self.after(0, lambda: self.handle_report_error(error_msg))

        # Fire off worker thread asynchronous context execution
        threading.Thread(target=worker, daemon=True).start()

    def update_report_ui(self, status_text, progress_fraction):
        """Thread-safe update handler for progress bar tracking adjustments."""
        self.report_status_label.configure(text=status_text, text_color="#FFB300")
        self.report_progress.set(progress_fraction)

    def finish_report_ui(self, vessel_count, filepath):
        """Locks application execution parameters and flags execution success."""
        self.report_progress.set(1.0)
        self.report_status_label.configure(text=f"Success! Saved for {vessel_count} vessels.", text_color="#4CAF50")
        self.run_report_btn.configure(
            text="Open Report", 
            state="normal", 
            fg_color="#2E7D32", 
            command=lambda: self.open_file(filepath)
        )

    def handle_report_error(self, error_message):
        """Safely surfaces pipeline structural failures or parsing issues."""
        print(error_message)
        self.report_status_label.configure(text=f"Report Error: {error_message[:80]}", text_color="#FF5252")
        self.report_progress.set(0)
        self.run_report_btn.configure(state="normal", text="Generate Vessel Report")


    # ALL VESSELS AIS GAP MAP
    def browse_bulk_file(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path: self.update_bulk_selection(path)

    def handle_bulk_drop(self, event):
        path = event.data.strip().strip('{}')
        if path.lower().endswith('.csv'): self.update_bulk_selection(path)

    def update_bulk_selection(self, path):
        self.selected_file = path
        self.bulk_status_label.configure(text=f"Selected: {os.path.basename(path)}", text_color="#4CAF50")

    # def handle_generate_bulk_map(self):
    #     if not self.selected_file:
    #         return

    #     self.bulk_progress.pack(pady=5)
    #     self.bulk_status_label.configure(text="Processing geospatial data...", text_color="#FFB300")

    #     def run_bulk_logic():
    #         df = pd.read_csv(self.selected_file)
    #         if 'timestamp' in df.columns and 'date' not in df.columns:
    #             df['date'] = df['timestamp']
    #         filter_choice = self.bulk_filter_var.get()
    #         buffer_choice = float(self.bulk_buffer_var.get())
    #         out_file = VP_bulk_map.create_bulk_map(df, buffer_dis=buffer_choice, filter_type=filter_choice)
    #         return out_file

    #     def finish_bulk(out_file):
    #         self.bulk_progress.set(1.0)
    #         self.bulk_status_label.configure(text="Bulk Map Ready!", text_color="#4CAF50")
    #         self.run_bulk_btn.configure(
    #             text="Open AIS Gap Map", state="normal", fg_color="#2E7D32", 
    #             command=lambda: self.open_file(out_file)
    #         )

    #     self.run_in_background(run_bulk_logic, self.bulk_progress, self.bulk_status_label, self.run_bulk_btn, finish_bulk)

    def update_bulk_progress(self, text, value):
        """Helper to safely update the specific Bulk Map UI widgets from the thread."""
        self.bulk_status_label.configure(text=text, text_color="#FFB300" if value < 1.0 else "#4CAF50")
        self.bulk_progress.set(value)

    def handle_generate_bulk_map(self):
        if not self.selected_file:
            # Optionally add a visual reminder if no file is selected
            self.bulk_status_label.configure(text="Please select a file first!", text_color="#FF5252")
            return

        # 1. Initialize the Progress UI State
        self.bulk_progress.pack(pady=5)
        self.bulk_progress.set(0.0)
        self.bulk_status_label.configure(text="Initializing bulk map generation thread...", text_color="#FFB300")
        self.run_bulk_btn.configure(state="disabled") # Disable button to prevent concurrent duplicate processes

        # 2. Define the worker that executes sequentially inside the background thread
        def run_bulk_logic_worker():
            try:
                df = pd.read_csv(self.selected_file)
                if 'timestamp' in df.columns and 'date' not in df.columns:
                    df['date'] = df['timestamp']
                    
                filter_choice = self.bulk_filter_var.get()
                buffer_choice = float(self.bulk_buffer_var.get())
                
                # Execute create_bulk_map passing our bulk UI progress updater directly
                out_file = VP_bulk_map.create_bulk_map(
                    df, 
                    buffer_dis=buffer_choice, 
                    filter_type=filter_choice,
                    progress_callback=self.update_bulk_progress
                )
                
                # Successfully completed processing and writing out file
                self.update_bulk_progress("Bulk Map Ready!", 1.0)
                self.run_bulk_btn.configure(
                    text="Open AIS Gap Map", 
                    state="normal", 
                    fg_color="#2E7D32", 
                    command=lambda: self.open_file(out_file)
                )
                
            except Exception as e:
                self.bulk_status_label.configure(text=f"Error: {str(e)[:60]}", text_color="#FF5252")
                self.bulk_progress.set(0)
                self.run_bulk_btn.configure(state="normal", text="Run Bulk Map", fg_color="#1f538d")

        # 3. Spawn the background thread to run the process
        threading.Thread(target=run_bulk_logic_worker, daemon=True).start()


    # SINGLE VESSEL AIS GAP MAP
    def handle_map_drop(self, event):
        path = event.data.strip().strip('{}')
        if path.lower().endswith('.csv'): self.update_map_selection(path)

    def browse_map_file(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path: self.update_map_selection(path)

    def update_map_selection(self, path):
        self.selected_file = path
        try:
            self.current_map_df = pd.read_csv(path)
            if 'timestamp' in self.current_map_df.columns and 'date' not in self.current_map_df.columns:
                self.current_map_df['date'] = self.current_map_df['timestamp']

            self.map_status_label.configure(text=f"File Loaded: {os.path.basename(path)}", text_color="#4CAF50")
            self.search_frame.pack(pady=10, padx=20, fill="x")
            self.run_map_btn.pack(pady=10)
            self.filter_vessels() 
        except Exception as e:
            self.map_status_label.configure(text=f"Error: {str(e)[:50]}", text_color="#FF5252")

    def filter_vessels(self, *args):
        for widget in self.vessel_list_frame.winfo_children():
            widget.destroy()
        if not hasattr(self, 'current_map_df'):
            return

        df = self.current_map_df
        if self.map_filter_var.get() == "Trawlers" and 'gear_type' in df.columns:
            df = df[df['gear_type'].astype(str).str.upper() == 'TRAWLERS']

        self.all_vessels = {}
        required_cols = ['vessel_id', 'ship_name', 'mmsi']
        if not all(col in df.columns for col in required_cols):
            return

        for _, row in df[required_cols].drop_duplicates().iterrows():
            name = str(row['ship_name']) if pd.notnull(row['ship_name']) and str(row['ship_name']) != "" else "Unknown"
            display_name = f"{name} (MMSI: {row['mmsi']})"
            self.all_vessels[display_name] = row['vessel_id']

        search_term = self.search_var.get().lower()
        matches = [name for name in self.all_vessels.keys() if search_term in name.lower()]

        for name in sorted(matches):
            btn = ctk.CTkButton(
                self.vessel_list_frame, text=name, fg_color="transparent", text_color="white",
                anchor="w", hover_color="#1f538d", command=lambda n=name: self.select_vessel(n)
            )
            btn.pack(fill="x", pady=1)
        
        self.map_status_label.configure(text=f"Found {len(matches)} vessels", text_color="#4CAF50")

    def select_vessel(self, name):
        self.current_selected_id = self.all_vessels[name]
        self.selected_vessel_label.configure(text=f"Selected: {name}")
        self.search_var.set(name)

    # def handle_generate_single_map(self):
    #     if not self.selected_file or not self.current_selected_id:
    #         self.map_status_label.configure(text="Select a file and vessel first!", text_color="#FF5252")
    #         return
        
    #     self.map_progress.pack(pady=5)
    #     self.map_status_label.configure(text="Plotting coordinates & layers...", text_color="#FFB300")

    #     def run_map_logic():
    #         buffer_val = float(self.buffer_dropdown.get().split(" ")[0])
    #         df = pd.read_csv(self.selected_file)
    #         if 'timestamp' in df.columns and 'date' not in df.columns:
    #             df['date'] = df['timestamp']
    #         v_data = VP_map.get_vessel_data(df, self.current_selected_id)
    #         out_file = VP_map.create_map(v_data, buffer_dis=buffer_val)
    #         return out_file

    #     def finish_map(out_file):
    #         self.map_progress.set(1.0)
    #         self.map_status_label.configure(text="Map Generated!", text_color="#4CAF50")
    #         self.run_map_btn.configure(
    #             text="Open Map", state="normal", fg_color="#2E7D32", 
    #             command=lambda: self.open_file(out_file)
    #         )

    #     self.run_in_background(run_map_logic, self.map_progress, self.map_status_label, self.run_map_btn, finish_map)

    def update_map_progress(self, text, value):
        """Helper to safely update the specific Map UI widgets from the thread."""
        self.map_status_label.configure(text=text, text_color="#FFB300" if value < 1.0 else "#4CAF50")
        self.map_progress.set(value)

    def handle_generate_single_map(self):
        if not self.selected_file or not self.current_selected_id:
            self.map_status_label.configure(text="Select a file and vessel first!", text_color="#FF5252")
            return
        
        # 1. Initialize the Progress UI State
        self.map_progress.pack(pady=5)
        self.map_progress.set(0.0)
        self.map_status_label.configure(text="Initializing map generation thread...", text_color="#FFB300")
        self.run_map_btn.configure(state="disabled") # Disable button to prevent double-clicks

        # 2. Define the isolated worker that executes sequentially in a background thread
        def run_map_logic_worker():
            try:
                buffer_val = float(self.buffer_dropdown.get().split(" ")[0])
                df = pd.read_csv(self.selected_file)
                if 'timestamp' in df.columns and 'date' not in df.columns:
                    df['date'] = df['timestamp']
                
                # Fetch target vessel data slice
                v_data = VP_map.get_vessel_data(df, self.current_selected_id)
                
                # Execute create_map passing our UI progress updater directly
                out_file = VP_map.create_map(
                    v_data, 
                    buffer_dis=buffer_val, 
                    progress_callback=self.update_map_progress
                )
                
                # Map successfully written out and returned filename string
                self.update_map_progress("Map Generated!", 1.0)
                self.run_map_btn.configure(
                    text="Open Map", 
                    state="normal", 
                    fg_color="#2E7D32", 
                    command=lambda: self.open_file(out_file)
                )
                
            except Exception as e:
                self.map_status_label.configure(text=f"Error: {str(e)[:60]}", text_color="#FF5252")
                self.map_progress.set(0)
                self.run_map_btn.configure(state="normal", text="Run Map", fg_color="#1f538d")

        # 3. Spawn a clean background thread to execute the workflow
        threading.Thread(target=run_map_logic_worker, daemon=True).start()


    # --- LOGIC: API DOWNLOADER ---
    def start_download_task(self, data_type="VP"):
        flag, start, end = self.flag_dropdown.get(), self.start_entry.get(), self.end_entry.get()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", start) or not re.match(r"^\d{4}-\d{2}-\d{2}$", end):
            self.status_label.configure(text="Error: Use YYYY-MM-DD", text_color="#FF5252")
            return
        
        self.load_btn.configure(state="disabled", text="Downloading...")
        self.progress_bar.pack(pady=10, after=self.status_label)
        threading.Thread(target=self.run_VP_gfw_logic, args=(flag, start, end, data_type), daemon=True).start()

    def run_VP_gfw_logic(self, flag, start, end, data_type):
        try:
            client = VP_gfw.get_gfw_client(self.api_key)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            if flag == "ALL":
                target_flag = ["ITA", "GRC", "TUR", "MLT", "TUN", "CYP", "DZA", "ALB", "FRA"]
            else:
                target_flag = flag

            df, actual_start, actual_end = loop.run_until_complete(
                VP_gfw.bulk_load_data(target_flag, start, end, client, self.update_ui_progress, data=data_type)
            )
            
            if not df.empty:
                flag_tag = "ALL_FLAGS" if flag == "ALL" else flag
                self.last_downloaded_file = f"{data_type}_{flag_tag}_{actual_start}-{actual_end}.csv"
                self.after(0, lambda: self.finish_download(len(df), actual_start, actual_end))
            else:
                self.after(0, lambda: self.handle_error("No data found for this period."))
        except Exception as e:
            # FIX: Bind the message string right now so 'e' isn't clean-deleted when the exception block closes
            err_msg = f"Download Aborted: {str(e)}"
            # print(str(e))
            self.after(0, lambda: self.handle_error(err_msg))

    def handle_error(self, msg):
        self.load_btn.configure(state="normal", text="Retry Download", fg_color="#1f538d")
        self.status_label.configure(text=f"Error: {msg[:100]}", text_color="#FF5252")
        self.progress_bar.set(0)

    def update_ui_progress(self, message, value):
        self.after(0, lambda: self.status_label.configure(text=message, text_color="white"))
        self.after(0, lambda: self.progress_bar.set(value))

    def finish_download(self, count, actual_start, actual_end):
        self.progress_bar.set(1)
        status_text = f"Data downloaded for period {actual_start} - {actual_end}\nSaved {count} rows."
        self.status_label.configure(text=status_text, text_color="#4CAF50")
        self.load_btn.configure(state="normal", text="Open CSV", fg_color="#2E7D32", command=lambda: self.open_file(self.last_downloaded_file))

    def open_file(self, path):
        if not os.path.exists(path): return
        if platform.system() == "Windows": os.startfile(path)
        elif platform.system() == "Darwin": subprocess.call(["open", path])
        else: subprocess.call(["xdg-open", path])

    def handle_reset(self):
        if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
        self.api_key = None; self.show_setup_view()

    def show_setup_view(self):
        self.clear_view()
        frame = ctk.CTkFrame(self, corner_radius=15)
        frame.pack(padx=20, pady=20, fill="both", expand=True)
        ctk.CTkLabel(frame, text="🔑 API Setup", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=40)
        self.key_entry = ctk.CTkEntry(frame, width=300, placeholder_text="Gfw-v1...", show="*")
        self.key_entry.pack(pady=15)
        ctk.CTkButton(frame, text="Activate", command=self.handle_api_save).pack()

    def handle_api_save(self):
        key = self.key_entry.get().strip()
        if key: save_api_key(key); self.api_key = key; self.show_main_menu()

if __name__ == "__main__":
    app = VesselTracker()
    app.mainloop()