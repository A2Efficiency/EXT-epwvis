"""
plot_dehumidifier_ef.py
Reads EnergyPlus ESO output and generates two plots:
  1. EF Frequency Distribution — hours per year at each operating EF bin
  2. EF Intensity — moisture removed (L) per EF bin (energy-weighted story)

Usage:
    python plot_dehumidifier_ef.py eplusout.eso
    python plot_dehumidifier_ef.py eplusout.eso --rated-ef 2.41 --output ./plots
"""

import re
import sys
import argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from pathlib import Path
from collections import defaultdict


# ── ESO Parser ────────────────────────────────────────────────────────────────

def parse_eso(filepath):
    """
    Minimal ESO parser. Returns dict of {variable_name: [float, ...]}
    Handles hourly reporting frequency.
    """
    data = defaultdict(list)
    var_map = {}  # report_code -> variable_label

    with open(filepath, "r") as f:
        lines = f.readlines()

    # Phase 1: read data dictionary (lines before "End of Data Dictionary")
    dict_end = 0
    for i, line in enumerate(lines):
        if "End of Data Dictionary" in line:
            dict_end = i
            break
        parts = line.strip().split(",")
        if len(parts) >= 3:
            try:
                code = int(parts[0].strip())
                # Variable label is last meaningful field
                label = parts[-1].strip().rstrip(";").strip()
                var_map[code] = label
            except ValueError:
                pass

    # Phase 2: read data records
    for line in lines[dict_end + 1:]:
        line = line.strip()
        if not line or line.startswith("End"):
            continue
        parts = line.split(",")
        try:
            code = int(parts[0].strip())
            value = float(parts[1].strip())
            if code in var_map:
                data[var_map[code]].append(value)
        except (ValueError, IndexError):
            pass

    return dict(data)


def find_variable(data, keywords):
    """Case-insensitive search for variable containing all keywords."""
    keywords_lower = [k.lower() for k in keywords]
    for key in data:
        key_lower = key.lower()
        if all(kw in key_lower for kw in keywords_lower):
            return data[key]
    return None


# ── Main Analysis ─────────────────────────────────────────────────────────────

def compute_operating_ef(data):
    """Back-calculate hourly operating EF from water removal and electric power."""
    # Try multiple variable name variations (different EnergyPlus versions may use different names)
    water = find_variable(data, ["removed water mass"]) or find_variable(data, ["water removal"])
    power = find_variable(data, ["electricity rate"]) or find_variable(data, ["electric power"])

    if water is None or power is None:
        print("\n  Available variables in ESO:")
        for key in sorted(data.keys()):
            print(f"    - {key}")
        raise ValueError(
            "Could not find Removed Water Mass or Electricity Rate variables in ESO.\n"
            "Check that Output:Variable entries are present in the IDF and ESO contains them."
        )

    water = np.array(water)   # kg/hr (removed water mass per hour)
    power = np.array(power)   # W

    # Convert water mass to volume: ~1 kg water ≈ 1 L (at room temp)
    water_liters = water * 1.0  # kg/hr to L/hr (density ~ 1 kg/L)

    # Only compute EF when unit is actually running (power > threshold)
    threshold_w = 100  # watts — filters timesteps when unit is fully off
    mask = power > threshold_w

    ef = np.full(len(water), np.nan)
    ef[mask] = (water_liters[mask]) / (power[mask] / 1000.0)  # L/kWh

    plr = find_variable(data, ["part load ratio"])
    moisture_removal = water_liters  # L/hr — one value per hour

    return ef, moisture_removal, mask, plr, np.array(power)


# ── Plot 1: EF Frequency Distribution ─────────────────────────────────────────

def plot_ef_frequency(ef, rated_ef, output_dir, model_name):
    """Histogram of hours per year at each EF bin."""
    ef_clean = ef[~np.isnan(ef)]

    # Bin edges — span comfortably around expected range
    ef_min = max(0, np.floor(ef_clean.min() * 4) / 4)
    ef_max = np.ceil(ef_clean.max() * 4) / 4
    bins = np.arange(ef_min, ef_max + 0.25, 0.25)

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("#F8F9FA")
    ax.set_facecolor("#F8F9FA")

    counts, edges, patches = ax.hist(
        ef_clean, bins=bins, color="#2E75B6", edgecolor="white",
        linewidth=0.5, alpha=0.85, zorder=3
    )

    # Color bars above rated EF differently
    for patch, left_edge in zip(patches, edges[:-1]):
        if left_edge >= rated_ef:
            patch.set_facecolor("#C00000")
            patch.set_alpha(0.75)

    # Rated EF reference line
    ax.axvline(rated_ef, color="#C00000", linewidth=2, linestyle="--",
               zorder=4, label=f"Rated EF = {rated_ef} L/kWh")

    # Median operating EF
    median_ef = np.median(ef_clean)
    ax.axvline(median_ef, color="#375623", linewidth=1.5, linestyle=":",
               zorder=4, label=f"Median operating EF = {median_ef:.2f} L/kWh")

    # Annotations
    pct_above = 100 * np.sum(ef_clean >= rated_ef) / len(ef_clean)
    ax.text(0.97, 0.95,
            f"{pct_above:.0f}% of operating hours\nabove rated EF (red bars)",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=9, color="#C00000",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="#C00000", alpha=0.8))

    ax.set_xlabel("Operating Energy Factor (L/kWh)", fontsize=11)
    ax.set_ylabel("Hours per Year", fontsize=11)
    ax.set_title(
        "Dehumidifier Operating EF — Frequency Distribution\n"
        "Flowering_1 Zone  |  Hourly Simulation Output",
        fontsize=12, fontweight="bold", color="#1F3864"
    )
    ax.legend(fontsize=9, framealpha=0.9)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.grid(axis="y", color="white", linewidth=0.8, zorder=2)
    ax.spines[["top", "right"]].set_visible(False)
    
    # Display model name
    ax.text(0.01, 0.99, model_name, transform=ax.transAxes,
            ha='left', va='top', fontsize=8,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                     alpha=0.7, edgecolor='gray', linewidth=0.5))

    plt.tight_layout()
    out_path = Path(output_dir) / "ef_frequency_distribution.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Saved: {out_path}")
    return out_path


# ── Plot 2: EF Intensity (Moisture-Weighted) ──────────────────────────────────

def plot_ef_intensity(ef, moisture_removal, rated_ef, output_dir, model_name):
    """Total liters removed per EF bin — shows where the actual work happens."""
    ef_clean = ef[~np.isnan(ef)]
    moisture_clean = moisture_removal[~np.isnan(ef)]

    ef_min = max(0, np.floor(ef_clean.min() * 4) / 4)
    ef_max = np.ceil(ef_clean.max() * 4) / 4
    bins = np.arange(ef_min, ef_max + 0.25, 0.25)

    # Sum moisture removal by EF bin
    bin_indices = np.digitize(ef_clean, bins) - 1
    bin_indices = np.clip(bin_indices, 0, len(bins) - 2)
    moisture_per_bin = np.zeros(len(bins) - 1)
    for i, idx in enumerate(bin_indices):
        moisture_per_bin[idx] += moisture_clean[i]

    bin_centers = (bins[:-1] + bins[1:]) / 2
    bar_colors = ["#C00000" if c >= rated_ef else "#2E75B6" for c in bin_centers]

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("#F8F9FA")
    ax.set_facecolor("#F8F9FA")

    bars = ax.bar(
        bin_centers, moisture_per_bin / 1000,  # convert L to kL
        width=0.22, color=bar_colors, edgecolor="white",
        linewidth=0.5, alpha=0.85, zorder=3
    )

    ax.axvline(rated_ef, color="#C00000", linewidth=2, linestyle="--",
               zorder=4, label=f"Rated EF = {rated_ef} L/kWh")

    # Weighted mean EF (energy-weighted, not hour-weighted)
    weighted_ef = np.average(ef_clean, weights=moisture_clean)
    ax.axvline(weighted_ef, color="#375623", linewidth=1.5, linestyle=":",
               zorder=4,
               label=f"Moisture-weighted mean EF = {weighted_ef:.2f} L/kWh")

    total_removal = moisture_per_bin.sum() / 1000
    above_rated = moisture_per_bin[bin_centers >= rated_ef].sum() / 1000
    pct_above = 100 * above_rated / total_removal if total_removal > 0 else 0

    ax.text(0.97, 0.95,
            f"{pct_above:.0f}% of annual moisture\nremoved above rated EF",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=9, color="#C00000",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="#C00000", alpha=0.8))

    ax.set_xlabel("Operating Energy Factor (L/kWh)", fontsize=11)
    ax.set_ylabel("Annual Moisture Removal (kL)", fontsize=11)
    ax.set_title(
        "Dehumidifier Operating EF — Moisture Removal Intensity\n"
        "Flowering_1 Zone  |  Total Annual Liters Removed per EF Bin",
        fontsize=12, fontweight="bold", color="#1F3864"
    )
    ax.legend(fontsize=9, framealpha=0.9)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.grid(axis="y", color="white", linewidth=0.8, zorder=2)
    ax.spines[["top", "right"]].set_visible(False)
    
    # Display model name
    ax.text(0.01, 0.99, model_name, transform=ax.transAxes,
            ha='left', va='top', fontsize=8,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                     alpha=0.7, edgecolor='gray', linewidth=0.5))

    plt.tight_layout()
    out_path = Path(output_dir) / "ef_intensity_moisture_weighted.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Saved: {out_path}")
    return out_path


# ── Plot 2b: Energy Use by EF Bin ──────────────────────────────────────────────

def plot_energy_use_by_ef(ef, power, rated_ef, output_dir, model_name):
    """Bar chart showing annual electricity consumption (kWh) per EF bin."""
    ef_clean = ef[~np.isnan(ef)]
    power_clean = power[~np.isnan(ef)]  # only power values corresponding to valid EF

    ef_min = max(0, np.floor(ef_clean.min() * 4) / 4)
    ef_max = np.ceil(ef_clean.max() * 4) / 4
    bins = np.arange(ef_min, ef_max + 0.25, 0.25)

    # Sum electricity consumption (kWh) by EF bin
    bin_indices = np.digitize(ef_clean, bins) - 1
    bin_indices = np.clip(bin_indices, 0, len(bins) - 2)
    energy_per_bin = np.zeros(len(bins) - 1)
    for i, idx in enumerate(bin_indices):
        energy_per_bin[idx] += power_clean[i]  # W; sum these per bin
    
    energy_per_bin = energy_per_bin / 1000.0  # convert W to kWh (assuming hourly data)

    bin_centers = (bins[:-1] + bins[1:]) / 2
    bar_colors = ["#C00000" if c >= rated_ef else "#2E75B6" for c in bin_centers]

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("#F8F9FA")
    ax.set_facecolor("#F8F9FA")

    bars = ax.bar(
        bin_centers, energy_per_bin,
        width=0.22, color=bar_colors, edgecolor="white",
        linewidth=0.5, alpha=0.85, zorder=3
    )

    ax.axvline(rated_ef, color="#C00000", linewidth=2, linestyle="--",
               zorder=4, label=f"Rated EF = {rated_ef} L/kWh")

    total_energy = energy_per_bin.sum()
    above_rated = energy_per_bin[bin_centers >= rated_ef].sum()
    pct_above = 100 * above_rated / total_energy if total_energy > 0 else 0

    ax.text(0.97, 0.95,
            f"{pct_above:.0f}% of annual energy\nconsumed above rated EF",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=9, color="#C00000",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="#C00000", alpha=0.8))

    ax.set_xlabel("Operating Energy Factor (L/kWh)", fontsize=11)
    ax.set_ylabel("Annual Energy Consumption (kWh)", fontsize=11)
    ax.set_title(
        "Dehumidifier Energy Use by Operating EF\n"
        "Flowering Rooms Combined  |  Total Annual Electricity per EF Bin",
        fontsize=12, fontweight="bold", color="#1F3864"
    )
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.grid(axis="y", color="white", linewidth=0.8, zorder=2)
    ax.spines[["top", "right"]].set_visible(False)
    
    # Display model name
    ax.text(0.01, 0.99, model_name, transform=ax.transAxes,
            ha='left', va='top', fontsize=8,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                     alpha=0.7, edgecolor='gray', linewidth=0.5))

    plt.tight_layout()
    out_path = Path(output_dir) / "energy_use_by_ef.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Saved: {out_path}")
    return out_path


# ── Plot 3: PLR Distribution (Bonus) ─────────────────────────────────────────

def plot_plr_distribution(plr_data, output_dir, model_name):
    """Histogram of PLR values — shows how often units are lightly vs heavily loaded."""
    if plr_data is None:
        print("  PLR data not found; skipping PLR distribution plot")
        return
    plr = np.array(plr_data)
    plr_running = plr[plr > 0.01]  # exclude off timesteps

    if len(plr_running) == 0:
        print("  No operating PLR data found")
        return

    bins = np.arange(0, 1.05, 0.05)
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#F8F9FA")
    ax.set_facecolor("#F8F9FA")

    ax.hist(plr_running, bins=bins, color="#2E75B6", edgecolor="white",
            linewidth=0.5, alpha=0.85, zorder=3)

    median_plr = np.median(plr_running)
    ax.axvline(median_plr, color="#C00000", linewidth=1.5, linestyle="--",
               zorder=4, label=f"Median PLR = {median_plr:.2f}")

    ax.set_xlabel("Part Load Ratio", fontsize=11)
    ax.set_ylabel("Hours per Year", fontsize=11)
    ax.set_title(
        "Dehumidifier Part Load Ratio Distribution\n"
        "Flowering_1 Zone  |  Operating Hours Only",
        fontsize=12, fontweight="bold", color="#1F3864"
    )
    ax.legend(fontsize=9)
    ax.grid(axis="y", color="white", linewidth=0.8, zorder=2)
    ax.spines[["top", "right"]].set_visible(False)
    
    # Display model name
    ax.text(0.01, 0.99, model_name, transform=ax.transAxes,
            ha='left', va='top', fontsize=8,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                     alpha=0.7, edgecolor='gray', linewidth=0.5))

    plt.tight_layout()
    ax.grid(axis="y", color="white", linewidth=0.8, zorder=2)
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    out_path = Path(output_dir) / "plr_distribution.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(), model_name
    print(f"✓ Saved: {out_path}")


# ── Plot 4: Weekly Dehumidifier Energy (52-week overview) ──────────────────

def plot_weekly_dehumidifier_energy(data, output_dir, model_name):
    """
    Bar chart of dehumidifier electricity consumption per week,
    color-coded by grow phase.
    From EnergyPlus Zone Dehumidifier Electricity Rate (includes all 3 zones).
    """
    # Extract Zone Dehumidifier Electricity Rate (26,280 values = 8760 hrs × 3 zones, interleaved)
    zone_dehum_power = find_variable(data, ["zone dehumidifier electricity rate"])
    
    if zone_dehum_power is None:
        print("  Zone Dehumidifier Electricity Rate not found; skipping weekly energy plot")
        return
    
    zone_dehum_power = np.array(zone_dehum_power)  # W
    
    # De-interleave the data: indices 0,3,6,9... are Zone 1; 1,4,7,10... are Zone 2; 2,5,8,11... are Zone 3
    # Sum across all three zones for each hour: indices [i*3:(i+1)*3]
    total_dehum_hourly = np.array([np.sum(zone_dehum_power[i*3:(i+1)*3]) 
                                   for i in range(8760)])  # 8760 hourly totals
    
    # Aggregate into 52 weekly values (kWh/week)
    hours_per_week = 24 * 7
    weeks = 52
    weekly_energy = []
    
    for week in range(weeks):
        start_hr = week * hours_per_week
        end_hr = min((week + 1) * hours_per_week, len(total_dehum_hourly))
        if start_hr < len(total_dehum_hourly):
            week_hours = total_dehum_hourly[start_hr:end_hr]
            kwh = np.sum(week_hours) / 1000.0  # Sum of W·hours / 1000 = kWh
            weekly_energy.append(kwh)
    
    # Define grow phases (10-week cycle starting week 0)
    # Early: weeks 0-1, Mid: weeks 2-6, Late: weeks 7-8, then repeat
    def get_phase_color(week):
        cycle_week = week % 9  # 9-week cycle (0-8)
        if cycle_week < 2:
            return "#1F77B4"  # Early — blue
        elif cycle_week < 7:
            return "#FF7F0E"  # Mid — orange
        else:
            return "#2CA02C"  # Late — green
    
    week_labels = [f"W{i+1}" for i in range(len(weekly_energy))]
    colors = [get_phase_color(i) for i in range(len(weekly_energy))]
    
    fig, ax = plt.subplots(figsize=(16, 6))
    fig.patch.set_facecolor("#F8F9FA")
    ax.set_facecolor("#F8F9FA")
    
    bars = ax.bar(range(len(weekly_energy)), weekly_energy, color=colors, 
                   edgecolor="white", linewidth=0.5, alpha=0.85, zorder=3)
    
    # Legend for grow phases
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#1F77B4", label="Early Phase (Wk 1-2)")  ,
        Patch(facecolor="#FF7F0E", label="Mid Phase (Wk 3-7)"),
        Patch(facecolor="#2CA02C", label="Late Phase (Wk 8-9)")
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=9)
    
    ax.set_xlabel("Week of Year", fontsize=11)
    ax.set_ylabel("Dehumidifier Energy (kWh)", fontsize=11)
    ax.set_title(
        "Annual Dehumidifier Energy Consumption by Week\n"
        "Flowering Rooms Combined  |  10-Week Grow Cycle",
        fontsize=12, fontweight="bold", color="#1F3864"
    )
    ax.grid(axis="y", color="white", linewidth=0.8, zorder=2)
    ax.spines[["top", "right"]].set_visible(False)
    
    # X-axis: show every 4 weeks
    ax.set_xticks(range(0, len(weekly_energy), 4))
    ax.set_xticklabels([f"W{i+1}" for i in range(0, len(weekly_energy), 4)])
    
    # Display model name
    ax.text(0.01, 0.99, model_name, transform=ax.transAxes,
            ha='left', va='top', fontsize=8,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                     alpha=0.7, edgecolor='gray', linewidth=0.5))

    plt.tight_layout()
    out_path = Path(output_dir) / "weekly_dehumidifier_energy.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Saved: {out_path}")
    return out_path


# ── Plot 5: Weekly Moisture Removal + Operating Hours ─────────────────────

def plot_weekly_moisture_operating_hours(moisture_removal, mask, output_dir, model_name):
    """
    Dual-axis plot: bars for moisture removal per week, line for cumulative operating hours.
    """
    moisture_removal = np.array(moisture_removal)  # L/hr
    mask = np.array(mask)  # boolean: operating hours
    
    # Aggregate into 52 weekly values
    hours_per_week = 24 * 7
    weeks = 52
    weekly_moisture = []
    weekly_operating_hrs = []
    
    for week in range(weeks):
        start_hr = week * hours_per_week
        end_hr = min((week + 1) * hours_per_week, len(moisture_removal))
        if start_hr < len(moisture_removal):
            week_moisture = np.sum(moisture_removal[start_hr:end_hr])  # total L
            week_op_hrs = np.sum(mask[start_hr:end_hr])  # operating hours
            weekly_moisture.append(week_moisture / 1000.0)  # convert to kL
            weekly_operating_hrs.append(week_op_hrs)
    
    fig, ax1 = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor("#F8F9FA")
    ax1.set_facecolor("#F8F9FA")
    
    # Bars for moisture removal
    bars = ax1.bar(range(len(weekly_moisture)), weekly_moisture, 
                   color="#2E75B6", edgecolor="white", linewidth=0.5, 
                   alpha=0.75, zorder=3, label="Moisture Removed")
    ax1.set_ylabel("Weekly Moisture Removal (kL)", fontsize=11, color="#2E75B6")
    ax1.tick_params(axis="y", labelcolor="#2E75B6")
    
    # Line for operating hours (secondary axis)
    ax2 = ax1.twinx()
    ax2.plot(range(len(weekly_operating_hrs)), weekly_operating_hrs,
             color="#C00000", linewidth=2, marker="o", markersize=4,
             label="Operating Hours", zorder=4)
    ax2.set_ylabel("Weekly Operating Hours", fontsize=11, color="#C00000")
    ax2.tick_params(axis="y", labelcolor="#C00000")
    
    ax1.set_xlabel("Week of Year", fontsize=11)
    ax1.set_title(
        "Weekly Moisture Removal and Dehumidifier Operating Hours\n"
        "Flowering Rooms Combined",
        fontsize=12, fontweight="bold", color="#1F3864"
    )
    ax1.grid(axis="y", color="white", linewidth=0.8, zorder=2)
    ax1.spines[["top", "right"]].set_visible(False)
    ax1.spines["right"].set_visible(True)
    
    # X-axis: show every 4 weeks
    ax1.set_xticks(range(0, len(weekly_moisture), 4))
    ax1.set_xticklabels([f"W{i+1}" for i in range(0, len(weekly_moisture), 4)])
    
    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    
    # Display model name
    ax1.text(0.01, 0.99, model_name, transform=ax1.transAxes,
             ha='left', va='top', fontsize=8,
             bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                      alpha=0.7, edgecolor='gray', linewidth=0.5))

    plt.tight_layout()
    out_path = Path(output_dir) / "weekly_moisture_operating_hours.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Saved: {out_path}")
    return out_path


# ── Plot 6: Weekly Fan vs Compressor Power Breakdown ────────────────────────

def plot_weekly_fan_compressor_breakdown(data, output_dir, model_name):
    """
    Stacked bar chart showing weekly energy split:
    - Fan power (bottom, blue) — "Flowering Room X Dehumidifier Power"
    - Compressor power (top, red) — "Flowering Room X Dehumidifier Compressor Power"
    Color-coded by grow phase.
    """
    # Search for EMS OutputVariable names
    fan_1 = find_variable(data, ["flowering room 1", "dehumidifier power"]) or find_variable(data, ["flowering room 1 dehumidifier", "power"])
    fan_2 = find_variable(data, ["flowering room 2", "dehumidifier power"]) or find_variable(data, ["flowering room 2 dehumidifier", "power"])
    fan_3 = find_variable(data, ["flowering room 3", "dehumidifier power"]) or find_variable(data, ["flowering room 3 dehumidifier", "power"])
    
    comp_1 = find_variable(data, ["flowering room 1", "dehumidifier compressor power"])
    comp_2 = find_variable(data, ["flowering room 2", "dehumidifier compressor power"])
    comp_3 = find_variable(data, ["flowering room 3", "dehumidifier compressor power"])
    
    if fan_1 is None or comp_1 is None:
        print("  Fan/Compressor power variables not found; skipping breakdown plot")
        return
    
    # Convert to arrays and sum across all three zones
    fan_1 = np.array(fan_1)
    fan_2 = np.array(fan_2) if fan_2 is not None else np.zeros_like(fan_1)
    fan_3 = np.array(fan_3) if fan_3 is not None else np.zeros_like(fan_1)
    total_fan = fan_1 + fan_2 + fan_3  # W
    
    comp_1 = np.array(comp_1)
    comp_2 = np.array(comp_2) if comp_2 is not None else np.zeros_like(comp_1)
    comp_3 = np.array(comp_3) if comp_3 is not None else np.zeros_like(comp_1)
    total_comp = comp_1 + comp_2 + comp_3  # W
    
    # Aggregate into 52 weekly values (kWh/week)
    hours_per_week = 24 * 7
    weeks = 52
    weekly_fan_energy = []
    weekly_comp_energy = []
    
    for week in range(weeks):
        start_hr = week * hours_per_week
        end_hr = min((week + 1) * hours_per_week, len(total_fan))
        if start_hr < len(total_fan):
            fan_kwh = np.sum(total_fan[start_hr:end_hr]) / 1000.0  # Sum of W·hours / 1000 = kWh
            comp_kwh = np.sum(total_comp[start_hr:end_hr]) / 1000.0  # Sum of W·hours / 1000 = kWh
            weekly_fan_energy.append(fan_kwh)
            weekly_comp_energy.append(comp_kwh)
    
    # Define grow phases for coloring
    def get_phase_color(week):
        cycle_week = week % 9  # 9-week cycle (0-8)
        if cycle_week < 2:
            return "#B0D0E8"  # Early — light blue
        elif cycle_week < 7:
            return "#FFD4A3"  # Mid — light orange
        else:
            return "#B8E6B8"  # Late — light green
    
    colors = [get_phase_color(i) for i in range(len(weekly_fan_energy))]
    
    fig, ax = plt.subplots(figsize=(16, 6))
    fig.patch.set_facecolor("#F8F9FA")
    ax.set_facecolor("#F8F9FA")
    
    # Stacked bars: fan (bottom), compressor (top)
    x_pos = np.arange(len(weekly_fan_energy))
    
    bars1 = ax.bar(x_pos, weekly_fan_energy, label="Fan Power", 
                   color="#2E75B6", edgecolor="white", linewidth=0.5, 
                   alpha=0.85, zorder=3)
    bars2 = ax.bar(x_pos, weekly_comp_energy, bottom=weekly_fan_energy,
                   label="Compressor Power", color="#C00000", 
                   edgecolor="white", linewidth=0.5, alpha=0.85, zorder=3)
    
    # Apply phase-based shading by adding semi-transparent background
    for i, (bar_x, color) in enumerate(zip(x_pos, colors)):
        rect = plt.Rectangle((bar_x - 0.4, 0), 0.8, 
                            weekly_fan_energy[i] + weekly_comp_energy[i],
                            facecolor=color, alpha=0.15, zorder=1)
        ax.add_patch(rect)
    
    ax.set_ylabel("Weekly Energy (kWh)", fontsize=11)
    ax.set_xlabel("Week of Year", fontsize=11)
    ax.set_title(
        "Weekly Dehumidifier Energy Breakdown: Fan vs Compressor Power\n"
        "Flowering Rooms Combined  |  Stacked by End Use",
        fontsize=12, fontweight="bold", color="#1F3864"
    )
    ax.legend(fontsize=10, framealpha=0.95, loc="upper right")
    ax.grid(axis="y", color="white", linewidth=0.8, zorder=2)
    ax.spines[["top", "right"]].set_visible(False)
    
    # X-axis: show every 4 weeks
    ax.set_xticks(range(0, len(weekly_fan_energy), 4))
    ax.set_xticklabels([f"W{i+1}" for i in range(0, len(weekly_fan_energy), 4)])
    
    # Display model name
    ax.text(0.01, 0.99, model_name, transform=ax.transAxes,
            ha='left', va='top', fontsize=8,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                     alpha=0.7, edgecolor='gray', linewidth=0.5))

    plt.tight_layout()
    out_path = Path(output_dir) / "weekly_fan_compressor_breakdown.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Saved: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Plot dehumidifier EF distribution from EnergyPlus ESO file"
    )
    parser.add_argument("eso_file", help="Path to eplusout.eso")
    parser.add_argument("--rated-ef", type=float, default=2.41,
                        help="Rated Energy Factor for reference line (default: 2.41 L/kWh)")
    parser.add_argument("--output", default=None,
                        help="Output directory for plot images (default: plot_dehumid_{filename})")
    args = parser.parse_args()

    # Auto-generate output directory name from ESO filename if not specified
    if args.output is None:
        eso_stem = Path(args.eso_file).stem  # filename without extension
        args.output = f"plot_dehumid_{eso_stem}"

    Path(args.output).mkdir(parents=True, exist_ok=True)

    print(f"Parsing ESO: {args.eso_file}")
    data = parse_eso(args.eso_file)
    print(f"  Found {len(data)} variables")

    print("Computing operating EF...")
    ef, moisture_removal, mask, plr, power = compute_operating_ef(data)

    operating_hours = np.sum(mask)
    ef_clean = ef[~np.isnan(ef)]
    print(f"  Operating hours: {operating_hours:,}")
    print(f"  EF range: {ef_clean.min():.2f} – {ef_clean.max():.2f} L/kWh")
    print(f"  Median EF: {np.median(ef_clean):.2f} L/kWh")
    print(f"  Rated EF:  {args.rated_ef:.2f} L/kWh")
    print(f"  % hours above rated: {100*np.sum(ef_clean >= args.rated_ef)/len(ef_clean):.0f}%")

    # Extract model name for displaying on plots
    model_name = Path(args.eso_file).stem
    
    print("Generating plots...")
    plot_ef_frequency(ef, args.rated_ef, args.output, model_name)
    plot_ef_intensity(ef, moisture_removal, args.rated_ef, args.output, model_name)
    plot_energy_use_by_ef(ef, power, args.rated_ef, args.output, model_name)
    plot_plr_distribution(plr, args.output, model_name)
    plot_weekly_dehumidifier_energy(data, args.output, model_name)
    plot_weekly_moisture_operating_hours(moisture_removal, mask, args.output, model_name)
    plot_weekly_fan_compressor_breakdown(data, args.output, model_name)

    print("\n✓ Done. Plots saved to: " + str(Path(args.output).absolute()))


if __name__ == "__main__":
    main()
