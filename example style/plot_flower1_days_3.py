"""
plot_flower1_days_3.py
----------------------
Plots Flower Room 1 EnergyPlus results for 3 specific days.
Reads from eplusout.eso (no 256-column CSV truncation limit).

Each day produces 4 individual JPGs (one per chart) and one PowerPoint
with a slide per day showing all 4 charts in a 2x2 grid.

Charts per day:
  1. Zone temp + thermostat setpoints + RH
  2. Coil outlet temp + supply outlet temp + dewpoint setpoint + coil SHR  [integrated]
     Coil outlet temp + supply outlet temp + dewpoint setpoint + dehum outlet temp  [decoupled]
  3. Cooling/heating rates (sensible, latent, total)  [integrated]
     Coil total cooling + dehum sensible heating + dehum latent removal  [decoupled]
  4. Fan airflow (CFM) + fan power  [both]
     + dehumidifier electricity rate  [decoupled]

Usage:
    python plot_flower1_days_3.py eplusout.eso
    python plot_flower1_days_3.py eplusout.eso decoupled

    Or set SCENARIO and ESO_PATH in CONFIG below.
"""

import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

# ── CONFIG ────────────────────────────────────────────────────────────────────
ESO_PATH    = r"eplusout.eso"   # override with sys.argv[1] if passed
SCENARIO    = "integrated"      # "integrated" or "decoupled" — override with sys.argv[2]

TARGET_DATES = ["01/08", "01/29", "03/01", "07/27", "08/23", "09/16"]
OUTPUT_DIR   = "."

# Grow-phase labels for the two 3-day series (Jan and Jul)
GROW_PHASE = {
    "01/08": "Early Grow",
    "01/29": "Mid Grow",
    "03/01": "Late Grow",
    "07/27": "Early Grow",
    "08/23": "Mid Grow",
    "09/16": "Late Grow",
}
AIR_DENSITY  = 1.2              # kg/m³ standard air, for kg/s → CFM conversion
LATENT_HEAT  = 2501.0           # kJ/kg water, for dehum kg/hr → latent kW

# A2 Efficiency brand colors
C_ORANGE = "#BF4C00"
C_DARK   = "#2C2C2C"
C_BLUE   = "#2D6EA0"
C_GREEN  = "#3A7D44"
C_GREY   = "#888888"
C_AMBER  = "#D4860B"
C_TEAL   = "#1D7874"
C_RED    = "#A0192D"

# ── COLUMN ALIASES ────────────────────────────────────────────────────────────
# Shared columns — present in both scenarios
# Format matches EnergyPlus ESO: "KEY:Variable Name [units](Frequency)"
COLS_SHARED = {
    "zone_temp":          "FLOWERING_1:Zone Mean Air Temperature [C](Hourly)",
    "tstat_temp":         "FLOWERING_1:Zone Thermostat Air Temperature [C](Hourly)",
    "cool_setpt":         "FLOWERING_1:Zone Thermostat Cooling Setpoint Temperature [C](Hourly)",
    "heat_setpt":         "FLOWERING_1:Zone Thermostat Heating Setpoint Temperature [C](Hourly)",
    "rh":                 "FLOWERING_1:Zone Air Relative Humidity [%](Hourly)",
    "coil_outlet_t":      "FLOWERING_1_COOLING_COIL:Cooling Coil Air Outlet Temperature [C](Hourly)",
    "dewpt_setpt":        "EMS:Flower 1 Zone Dewpoint Setpoint [C](Hourly)",
    "fan_flow":           "FLOWERING_1_SUPPLY_FAN:Fan Air Mass Flow Rate [kg/s](Hourly)",
    "fan_power":          "FLOWERING_1_SUPPLY_FAN:Fan Electricity Rate [W](Hourly)",
    "coil_energy_j":      "FLOWERING_1_COOLING_COIL:Cooling Coil Electricity Energy [J](Hourly)",
    "coil_total_cool":    "FLOWERING_1_COOLING_COIL:Cooling Coil Total Cooling Rate [W](Hourly)",
    "zone_sens_cool":     "FLOWERING_1:Zone Air System Sensible Cooling Rate [W](Hourly)",
    "zone_sens_heat":     "FLOWERING_1:Zone Air System Sensible Heating Rate [W](Hourly)",
    "oat":                "ENVIRONMENT:Site Outdoor Air Drybulb Temperature [C](Hourly)",
    "net_heating_elec":   "EMS:Flower Rooms Net Heating Elec Hourly [J](Hourly)",
    "heating_coil_rate":  "FLOWERING_1_HEATING_COIL:Heating Coil Heating Rate [W](Hourly)",
    # Supply outlet node temperature — downstream of fan
    "supply_outlet_t":    "FLOWERING_1_SUPPLY_OUTLET:System Node Temperature [C](Hourly)",
}

# Integrated-only EMS columns
COLS_INTEGRATED = {
    "coil_shr":           "EMS:Flower 1 Coil SHR [](Hourly)",
    "ems_total":          "EMS:Flower 1 Total Heat Rate [](Hourly)",
    "ems_latent":         "EMS:Flower 1 Latent Heat Rate [](Hourly)",
    "ems_sensible":       "EMS:Flower 1 Sensible Heat Rate [](Hourly)",
}

# Decoupled-only dehumidifier columns
COLS_DECOUPLED = {
    "dehum_sens_heat":    "FLOWERING_1_DEHUMIDIFIER:Zone Dehumidifier Sensible Heating Rate [W](Hourly)",
    "dehum_water_kg":     "FLOWERING_1_DEHUMIDIFIER:Zone Dehumidifier Removed Water Mass [kg](Hourly)",
    "dehum_elec":         "FLOWERING_1_DEHUMIDIFIER:Zone Dehumidifier Electricity Rate [W](Hourly)",
    "dehum_outlet_t":     "FLOWERING_1_DEHUMIDIFIER:Zone Dehumidifier Outlet Air Temperature [C](Hourly)",
}


def build_cols(scenario):
    """Return merged column dict for the active scenario."""
    d = dict(COLS_SHARED)
    if scenario == "integrated":
        d.update(COLS_INTEGRATED)
    else:
        d.update(COLS_DECOUPLED)
    return d


# ── LOAD & PARSE ESO ──────────────────────────────────────────────────────────
def load_eso(path):
    """
    Parse an EnergyPlus .eso file and return a pandas DataFrame with
    the same structure that the rest of this script expects:
      - DatetimeIndex (hourly, year=2009)
      - Columns named "KEY:Variable Name [units](Hourly)"

    Uses the esoreader package; install with:
        pip install esoreader
    """
    try:
        import esoreader
    except ImportError:
        raise ImportError(
            "esoreader is required to read .eso files.\n"
            "Install it with:  pip install esoreader"
        )

    print(f"  Parsing ESO data dictionary...")
    eso = esoreader.read_from_path(path)
    eso.dd.build_index()

    # Collect all hourly variables into one wide DataFrame
    frames = []
    for (freq, key, variable), var_id in eso.dd.index.items():
        if freq.lower() != "hourly":
            continue
        if var_id not in eso.data:
            continue
        values = eso.data[var_id]
        unit_str = eso.dd.variables[var_id][3] or ""
        # Reconstruct column name matching the CSV convention: "KEY:Variable [unit](Hourly)"
        if key:
            col_name = f"{key.upper()}:{variable} [{unit_str}](Hourly)"
        else:
            col_name = f"{variable} [{unit_str}](Hourly)"
        frames.append(pd.Series(values, name=col_name))

    if not frames:
        raise ValueError("No hourly data found in ESO file.")

    print(f"  Assembling DataFrame from {len(frames)} hourly variables...")
    df = pd.concat(frames, axis=1)

    # Build a DatetimeIndex — ESO rows are 1-indexed hours starting Jan 1
    # Assign year 2009 to match original CSV convention
    n_hours = len(df)
    df.index = pd.date_range(start="2009-01-01 01:00:00", periods=n_hours, freq="h")

    # Coerce all columns to numeric
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    print(f"  Loaded {len(df)} rows, {len(df.columns)} columns from ESO")
    return df


def get_day(df, mmdd):
    month, day = int(mmdd.split("/")[0]), int(mmdd.split("/")[1])
    return df[(df.index.month == month) & (df.index.day == day)].copy()


def col(df, key, COLS):
    name = COLS.get(key, key)
    if name in df.columns:
        return df[name].values
    print(f"  WARNING: column not found: {name}")
    return np.zeros(len(df))


# ── UTILITIES ─────────────────────────────────────────────────────────────────
def c2f(arr):
    return arr * 9 / 5 + 32

def kgs_to_cfm(arr):
    return arr / AIR_DENSITY * 2118.88

def kg_per_hr_to_latent_kw(arr):
    """Dehumidifier removed water [kg/hr] → latent removal rate [kW]."""
    return arr * LATENT_HEAT / 3600.0
def calculate_dewpoint(temp_c, rh_percent):
    """
    Calculate dew point temperature [°C] from dry bulb temperature and relative humidity.
    Uses Magnus formula approximation: accurate to within 0.5°C for most HVAC conditions.
    
    Args:
        temp_c: Dry bulb temperature [°C]
        rh_percent: Relative humidity [%]
    
    Returns:
        Dew point temperature [°C]
    """
    # Magnus formula coefficients for T > 0°C
    a = 17.27
    b = 237.7  # [°C]
    
    # If RH is 0 or invalid, return very low value
    rh_frac = np.clip(rh_percent / 100.0, 0.01, 1.0)
    
    # Calculate alpha term
    alpha = ((a * temp_c) / (b + temp_c)) + np.log(rh_frac)
    
    # Calculate dew point
    dewpoint = (b * alpha) / (a - alpha)
    
    return dewpoint
def style_axes(ax):
    ax.tick_params(labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#CCCCCC")
    ax.grid(True, alpha=0.3)

def x_axis_hours(ax, hours):
    ax.set_xticks(hours)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):02d}:00"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=7)
    ax.set_xlabel("Hour of Day", color=C_DARK)

def save_jpg(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white",
                edgecolor="none", format="jpeg")
    print(f"  Saved: {path}")
    plt.close(fig)


# ── PLOT 1: Zone Temp + RH  (same for both scenarios) ────────────────────────
def plot_zone_temp(df_day, date_str, hours, COLS, scenario, grow_phase="", eso_stem=""):
    fig, ax = plt.subplots(figsize=(11, 4))
    axr = ax.twinx()
    ax.plot(hours, c2f(col(df_day, "zone_temp",  COLS)), color=C_ORANGE, lw=2,            label="Zone MAT [°F]")
    ax.plot(hours, c2f(col(df_day, "cool_setpt", COLS)), color=C_BLUE,   lw=1.5, ls="--", label="Cooling Setpt [°F]")
    ax.plot(hours, c2f(col(df_day, "heat_setpt", COLS)), color=C_AMBER,  lw=1.5, ls="--", label="Heating Setpt [°F]")
    ax.plot(hours, c2f(col(df_day, "oat",        COLS)), color=C_GREY,   lw=1,   ls=":",  label="OAT [°F]")
    axr.bar(hours,    col(df_day, "rh",          COLS),  color=C_TEAL,   alpha=0.2,        label="RH [%]")
    ax.set_ylabel("Temperature [°F]", color=C_DARK)
    axr.set_ylabel("Relative Humidity [%]", color=C_TEAL)
    ax.set_ylim(45, 90)
    axr.set_ylim(0, 100)
    lines, labels = ax.get_legend_handles_labels()
    linesr, labelsr = axr.get_legend_handles_labels()
    ax.legend(lines + linesr, labels + labelsr, fontsize=7, loc="upper right", ncol=3)
    ax.set_title(f"Flower Room 1 — {eso_stem}  |  {date_str} {grow_phase}  |  Zone Temperature & RH  [{scenario}]",
                 fontsize=10, fontweight="bold", color=C_DARK)
    style_axes(ax)
    x_axis_hours(ax, hours)
    fig.tight_layout()
    return fig


# ── PLOT 2: Coil / Dewpoint control ──────────────────────────────────────────
def plot_coil_temp(df_day, date_str, hours, COLS, scenario, grow_phase="", eso_stem=""):
    fig, ax = plt.subplots(figsize=(11, 4))
    axr = ax.twinx()

    ax.plot(hours, c2f(col(df_day, "coil_outlet_t",   COLS)), color=C_BLUE,   lw=2,            label="Coil Outlet Temp [°F]")
    ax.plot(hours, c2f(col(df_day, "dewpt_setpt",     COLS)), color=C_ORANGE, lw=1.5, ls="--", label="Dewpoint Setpt [°F]")

    # Room air dewpoint (integrated only) — calculated from zone temp and RH
    if scenario == "integrated":
        zone_temp_c = col(df_day, "zone_temp", COLS)
        rh_pct = col(df_day, "rh", COLS)
        room_dewpoint_c = calculate_dewpoint(zone_temp_c, rh_pct)
        ax.plot(hours, c2f(room_dewpoint_c), color=C_TEAL, lw=1.5, ls=":", label="Room Air Dewpoint [°F]")

    # Supply outlet temperature — downstream of fan (new)
    supply_t = col(df_day, "supply_outlet_t", COLS)
    if not np.all(supply_t == 0):
        ax.plot(hours, c2f(supply_t), color=C_GREEN, lw=1.5, ls="-.", label="Supply Outlet Temp [°F]")

    if scenario == "integrated":
        axr.plot(hours, col(df_day, "coil_shr", COLS), color=C_RED, lw=1.5, ls="-.", label="Coil SHR [-]")
        axr.set_ylabel("Coil SHR [-]", color=C_RED)
        axr.set_ylim(0, 1.0)
        subtitle = "Coil Outlet Temp, Room Dewpoint, Dewpoint Setpoint & Coil SHR"
    else:
        axr.plot(hours, c2f(col(df_day, "dehum_outlet_t", COLS)), color=C_RED, lw=1.5, ls="-.", label="Dehum Outlet Temp [°F]")
        axr.set_ylabel("Dehum Outlet Temp [°F]", color=C_RED)
        axr.set_ylim(75, 120)
        subtitle = "Coil Outlet Temp, Supply Outlet Temp, Dewpoint Setpoint & Dehum Outlet Temp"

    ax.set_ylabel("Temperature [°F]", color=C_DARK)
    ax.set_ylim(45, 90)
    lines, labels = ax.get_legend_handles_labels()
    linesr, labelsr = axr.get_legend_handles_labels()
    ax.legend(lines + linesr, labels + labelsr, fontsize=7, loc="upper right", ncol=3)
    ax.set_title(f"Flower Room 1 — {eso_stem}  |  {date_str} {grow_phase}  |  {subtitle}  [{scenario}]",
                 fontsize=10, fontweight="bold", color=C_DARK)
    style_axes(ax)
    x_axis_hours(ax, hours)
    fig.tight_layout()
    return fig


# ── PLOT 3: Cooling / Heating Rates ──────────────────────────────────────────
def plot_cooling_rates(df_day, date_str, hours, COLS, scenario, grow_phase="", eso_stem=""):
    fig, ax = plt.subplots(figsize=(11, 4))

    if scenario == "integrated":
        total    = col(df_day, "ems_total",    COLS)
        latent   = col(df_day, "ems_latent",   COLS)
        sensible = col(df_day, "ems_sensible", COLS)
        if np.all(total == 0):
            # Fallback to zone-level outputs if EMS sensors missing
            ax.plot(hours, col(df_day, "zone_sens_cool", COLS) / 1000, color=C_BLUE,  lw=2,            label="Zone Sensible Cooling [kW]")
            ax.plot(hours, col(df_day, "zone_sens_heat", COLS) / 1000, color=C_AMBER, lw=1.5, ls="--", label="Zone Sensible Heating [kW]")
        else:
            ax.plot(hours, total    / 1000, color=C_DARK,   lw=2,            label="Total Heat Rate [kW]")
            ax.plot(hours, latent   / 1000, color=C_TEAL,   lw=1.5, ls="--", label="Latent Heat Rate [kW]")
            ax.plot(hours, sensible / 1000, color=C_ORANGE, lw=1.5, ls="-.", label="Sensible Heat Rate [kW]")
        subtitle = "Cooling / Heating Rates"

    else:
        # Decoupled: coil total cooling, dehum sensible heat added back, dehum latent removal
        coil_cool    = col(df_day, "coil_total_cool", COLS) / 1000
        dehum_sens   = col(df_day, "dehum_sens_heat", COLS) / 1000
        dehum_latent = kg_per_hr_to_latent_kw(col(df_day, "dehum_water_kg", COLS))

        ax.plot(hours, coil_cool,    color=C_BLUE,  lw=2,            label="Coil Total Cooling [kW]")
        ax.plot(hours, dehum_latent, color=C_TEAL,  lw=1.5, ls="--", label="Dehum Latent Removal [kW]")
        ax.plot(hours, dehum_sens,   color=C_AMBER, lw=1.5, ls="-.", label="Dehum Sensible Heat Added [kW]")
        subtitle = "Coil Cooling & Dehumidifier Loads"

    # Shared additions — both scenarios
    # Heating coil rate [W → kW]
    heating_coil = col(df_day, "heating_coil_rate", COLS)
    if not np.all(heating_coil == 0):
        ax.plot(hours, heating_coil / 1000, color=C_RED,   lw=1.5, ls="--", label="Heating Coil Rate [kW]")

    # Net heating electricity [J/hr → kW: divide by 3600]
    net_heat_elec = col(df_day, "net_heating_elec", COLS)
    if not np.all(net_heat_elec == 0):
        ax.plot(hours, net_heat_elec / 3600 / 1000, color=C_AMBER, lw=1.5, ls=":", label="Net Heating Elec [kW]")

    ax.set_ylim(bottom=0, top=250)
    ax.set_ylabel("Rate [kW]", color=C_DARK)
    ax.legend(fontsize=7, loc="upper right", ncol=3)
    ax.set_title(f"Flower Room 1 — {eso_stem}  |  {date_str} {grow_phase}  |  {subtitle}  [{scenario}]",
                 fontsize=10, fontweight="bold", color=C_DARK)
    style_axes(ax)
    x_axis_hours(ax, hours)
    fig.tight_layout()
    return fig


# ── PLOT 4: Fan Airflow + Power (+ dehum electricity for decoupled) ───────────
def plot_fan_airflow(df_day, date_str, hours, COLS, scenario, grow_phase="", eso_stem=""):
    fig, ax = plt.subplots(figsize=(11, 4))
    axr = ax.twinx()

    fan_cfm = kgs_to_cfm(col(df_day, "fan_flow",  COLS))
    fan_kw  = col(df_day, "fan_power", COLS) / 1000

    ax.plot(hours, fan_cfm, color=C_BLUE, lw=2,            label="Fan Flow [CFM]")
    axr.plot(hours, fan_kw, color=C_GREY, lw=1.5, ls="--", label="Fan Power [kW]")

    if scenario == "decoupled":
        dehum_kw = col(df_day, "dehum_elec", COLS) / 1000
        axr.plot(hours, dehum_kw, color=C_RED, lw=1.5, ls="-.", label="Dehum Electricity [kW]")
        subtitle = "Fan Airflow, Fan Power & Dehum Electricity"
    else:
        subtitle = "Fan Airflow & Fan Power"
    axr.set_ylim(0, 60)

    ax.set_ylim(0, 40000)
    ax.set_ylabel("Fan Flow [CFM]", color=C_BLUE)
    axr.set_ylabel("Power [kW]", color=C_GREY)
    lines, labels = ax.get_legend_handles_labels()
    linesr, labelsr = axr.get_legend_handles_labels()
    ax.legend(lines + linesr, labels + labelsr, fontsize=7, loc="upper right", ncol=3)
    ax.set_title(f"Flower Room 1 — {eso_stem}  |  {date_str} {grow_phase}  |  {subtitle}  [{scenario}]",
                 fontsize=10, fontweight="bold", color=C_DARK)
    style_axes(ax)
    x_axis_hours(ax, hours)
    fig.tight_layout()
    return fig


# ── PLOT ONE DAY → 4 JPGs ─────────────────────────────────────────────────────
SUBPLOT_NAMES = ["ZoneTemp", "CoilTemp", "CoolingRates", "FanAirflow"]

def plot_day(df_day, date_str, output_dir, COLS, scenario, grow_phase="", eso_stem=""):
    hours     = np.arange(1, len(df_day) + 1)
    safe_date = date_str.replace("/", "-")

    figs = [
        plot_zone_temp(    df_day, date_str, hours, COLS, scenario, grow_phase, eso_stem),
        plot_coil_temp(    df_day, date_str, hours, COLS, scenario, grow_phase, eso_stem),
        plot_cooling_rates(df_day, date_str, hours, COLS, scenario, grow_phase, eso_stem),
        plot_fan_airflow(  df_day, date_str, hours, COLS, scenario, grow_phase, eso_stem),
    ]

    paths = []
    for fig, name in zip(figs, SUBPLOT_NAMES):
        path = os.path.join(output_dir, f"Flower1_{safe_date}_{name}.jpg")
        save_jpg(fig, path)
        paths.append(path)

    return paths


# ── ANNUAL PLOT GENERATORS ────────────────────────────────────────────────────
def generate_flower_db_annual(df, output_dir, eso_stem, COLS):
    """Generate annual Flower Room 1 DB (dry bulb) line plot."""
    try:
        line_path = os.path.join(output_dir, f"{eso_stem}_annual_flower_db_line.png")
        
        col_name = COLS.get("zone_temp")
        if col_name not in df.columns:
            print(f"WARNING: zone_temp not found in ESO file")
            return None
        
        values = c2f(df[col_name].values)
        
        # Plot line
        fig, ax = plt.subplots(figsize=(14, 4))
        x = np.arange(len(values))
        ax.plot(x, values, color=C_BLUE, lw=0.8, alpha=0.85, label="Zone DB [F]")
        rolling = pd.Series(values).rolling(24, center=True, min_periods=1).mean()
        ax.plot(x, rolling.values, color=C_ORANGE, lw=1.8, alpha=0.9, label="24-hr rolling mean")
        ax.set_ylabel("Temperature [°F]", color=C_DARK, fontsize=9)
        ax.set_xlabel("Hour of Year", color=C_DARK, fontsize=9)
        ax.set_title(f"Flower Room 1 Dry Bulb Temperature [°F]  —  {eso_stem}  (Annual)", 
                    fontsize=10, fontweight="bold", color=C_DARK)
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        fig.savefig(line_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        
        return {
            "label": "Flower Room 1 DB Temperature (°F)",
            "line_path": line_path,
        }
    except Exception as e:
        print(f"ERROR generating flower DB annual plot: {e}")
        return None


def generate_cooling_coil_lat_annual(df, output_dir, eso_stem, COLS):
    """Generate annual cooling coil LAT (leaving air temperature) line plot."""
    try:
        line_path = os.path.join(output_dir, f"{eso_stem}_annual_cooling_coil_lat_line.png")
        
        col_name = COLS.get("coil_outlet_t")
        if col_name not in df.columns:
            print(f"WARNING: coil_outlet_t not found in ESO file")
            return None
        
        values = c2f(df[col_name].values)
        
        # Plot line
        fig, ax = plt.subplots(figsize=(14, 4))
        x = np.arange(len(values))
        ax.plot(x, values, color=C_BLUE, lw=0.8, alpha=0.85, label="Coil Outlet [F]")
        rolling = pd.Series(values).rolling(24, center=True, min_periods=1).mean()
        ax.plot(x, rolling.values, color=C_ORANGE, lw=1.8, alpha=0.9, label="24-hr rolling mean")
        ax.set_ylabel("Temperature [°F]", color=C_DARK, fontsize=9)
        ax.set_xlabel("Hour of Year", color=C_DARK, fontsize=9)
        ax.set_title(f"Cooling Coil LAT (Leaving Air Temperature) [°F]  —  {eso_stem}  (Annual)", 
                    fontsize=10, fontweight="bold", color=C_DARK)
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        fig.savefig(line_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        
        return {
            "label": "Cooling Coil LAT (°F)",
            "line_path": line_path,
        }
    except Exception as e:
        print(f"ERROR generating cooling coil LAT annual plot: {e}")
        return None


def generate_fan_lat_annual(df, output_dir, eso_stem, COLS):
    """Generate annual fan LAT (supply outlet temperature) line plot."""
    try:
        line_path = os.path.join(output_dir, f"{eso_stem}_annual_fan_lat_line.png")
        
        col_name = COLS.get("supply_outlet_t")
        if col_name not in df.columns:
            print(f"WARNING: supply_outlet_t not found in ESO file")
            return None
        
        values = c2f(df[col_name].values)
        
        # Plot line
        fig, ax = plt.subplots(figsize=(14, 4))
        x = np.arange(len(values))
        ax.plot(x, values, color=C_BLUE, lw=0.8, alpha=0.85, label="Supply Outlet [F]")
        rolling = pd.Series(values).rolling(24, center=True, min_periods=1).mean()
        ax.plot(x, rolling.values, color=C_ORANGE, lw=1.8, alpha=0.9, label="24-hr rolling mean")
        ax.set_ylabel("Temperature [°F]", color=C_DARK, fontsize=9)
        ax.set_xlabel("Hour of Year", color=C_DARK, fontsize=9)
        ax.set_title(f"Fan LAT (Supply Outlet Temperature) [°F]  —  {eso_stem}  (Annual)", 
                    fontsize=10, fontweight="bold", color=C_DARK)
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        fig.savefig(line_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        
        return {
            "label": "Fan LAT (°F)",
            "line_path": line_path,
        }
    except Exception as e:
        print(f"ERROR generating fan LAT annual plot: {e}")
        return None


# ── POWERPOINT BUILDER ────────────────────────────────────────────────────────
def build_pptx(day_image_map, out_path, scenario, eso_stem="", annual_plots=None):
    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    img_w = Inches(6.4)
    img_h = Inches(3.4)
    positions = [
        (Inches(0.1),  Inches(0.5)),
        (Inches(6.83), Inches(0.5)),
        (Inches(0.1),  Inches(3.95)),
        (Inches(6.83), Inches(3.95)),
    ]

    for date_str, paths in day_image_map.items():
        grow_phase = GROW_PHASE.get(date_str, "")
        slide = prs.slides.add_slide(blank_layout)
        txb = slide.shapes.add_textbox(Inches(0.1), Inches(0.05), Inches(13), Inches(0.4))
        tf  = txb.text_frame
        tf.text = f"Flower Room 1 — {eso_stem}  |  {date_str} {grow_phase}  [{scenario}]"
        p = tf.paragraphs[0]
        p.runs[0].font.size      = Pt(16)
        p.runs[0].font.bold      = True
        p.runs[0].font.color.rgb = RGBColor(0x2C, 0x2C, 0x2C)

        for path, (left, top) in zip(paths, positions):
            if os.path.exists(path):
                slide.shapes.add_picture(path, left, top, width=img_w, height=img_h)

    # Annual plots (line only, centered on slide)
    if annual_plots:
        for plot_info in annual_plots:
            slide = prs.slides.add_slide(blank_layout)
            txb = slide.shapes.add_textbox(Inches(0.1), Inches(0.05), Inches(13), Inches(0.4))
            tf  = txb.text_frame
            tf.text = f"{plot_info['label']}  —  {eso_stem}  (Annual)"
            p = tf.paragraphs[0]
            p.runs[0].font.size      = Pt(16)
            p.runs[0].font.bold      = True
            p.runs[0].font.color.rgb = RGBColor(0x2C, 0x2C, 0x2C)
            
            # Line plot — middle of slide
            if plot_info["line_path"] and os.path.exists(plot_info["line_path"]):
                slide.shapes.add_picture(
                    plot_info["line_path"],
                    Inches(0.1), Inches(0.5),
                    width=Inches(13.1), height=Inches(3.2),
                )

    prs.save(out_path)
    print(f"PowerPoint saved: {out_path}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    eso_path = sys.argv[1] if len(sys.argv) > 1 else ESO_PATH
    scenario = sys.argv[2].lower() if len(sys.argv) > 2 else SCENARIO

    if scenario not in ("integrated", "decoupled"):
        print(f"ERROR: SCENARIO must be 'integrated' or 'decoupled', got '{scenario}'")
        sys.exit(1)

    print(f"Scenario: {scenario}")

    COLS = build_cols(scenario)

    eso_stem   = os.path.splitext(os.path.basename(eso_path))[0]
    output_dir = os.path.join(OUTPUT_DIR, f"{eso_stem}_{scenario}")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output folder: {output_dir}")

    print(f"Loading: {eso_path}")
    df = load_eso(eso_path)

    day_image_map = {}
    for date in TARGET_DATES:
        print(f"Plotting {date}...")
        df_day = get_day(df, date)
        if df_day.empty:
            print(f"  WARNING: no data found for {date} — skipping")
            continue
        grow_phase = GROW_PHASE.get(date, "")
        paths = plot_day(df_day, date, output_dir, COLS, scenario, grow_phase, eso_stem)
        day_image_map[date] = paths

    # Generate annual plots
    print(f"Generating annual plots...")
    annual_plots = []
    
    # Flower Room 1 DB
    print(f"  Generating Flower Room 1 DB annual plot...")
    db_plot = generate_flower_db_annual(df, output_dir, eso_stem, COLS)
    if db_plot:
        annual_plots.append(db_plot)
        print(f"    [OK] Flower Room 1 DB annual plot")
    
    # Cooling Coil LAT
    print(f"  Generating Cooling Coil LAT annual plot...")
    coil_lat_plot = generate_cooling_coil_lat_annual(df, output_dir, eso_stem, COLS)
    if coil_lat_plot:
        annual_plots.append(coil_lat_plot)
        print(f"    [OK] Cooling Coil LAT annual plot")
    
    # Fan LAT
    print(f"  Generating Fan LAT annual plot...")
    fan_lat_plot = generate_fan_lat_annual(df, output_dir, eso_stem, COLS)
    if fan_lat_plot:
        annual_plots.append(fan_lat_plot)
        print(f"    [OK] Fan LAT annual plot")

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pptx_path = os.path.join(output_dir, f"Flower1_{eso_stem}_{scenario}_{timestamp}.pptx")
    build_pptx(day_image_map, pptx_path, scenario, eso_stem, annual_plots=annual_plots)

    print("Done.")
