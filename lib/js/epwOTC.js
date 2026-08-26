/*-------------------------------------------------------------------------
 * epwOTC.js
 * Outdoor Thermal Comfort (UTCI) strategy computation.
 *
 * Pure computation only -- no DOM, no crossfilter, no globals beyond the
 * utci.js helpers. Extracted from index.html so that both the interactive
 * viewer and the reporting dashboard share one implementation.
 *
 * Depends on: utci.js (utci, utciSolarGainDeltaMrt)
 *-------------------------------------------------------------------------*/
(function (global) {
  'use strict';

  // === 5 CASES CONFIGURATION ===
  // Cases 0 and 4 are fixed; cases 1-3 are user-configurable.
  function defaultCases() {
    return [
      { label: 'Base Case',             desc: '', fixed: true,  shade: 'none',     block: 'none',     fans: 'none' },
      { label: 'Case 2 Shading',        desc: '', fixed: false, shade: 'full-var', block: 'none',     fans: 'none' },
      { label: 'Case 3 Wind Block',     desc: '', fixed: false, shade: 'none',     block: 'full-var', fans: 'none' },
      { label: 'Case 4 All Strategies', desc: '', fixed: false, shade: 'full-var', block: 'full-var', fans: 'low'  },
      { label: 'Ideal Case',            desc: '', fixed: true,  shade: 'ideal',    block: 'ideal',    fans: 'high' }
    ];
  }

  // === STRATEGY OPTION DEFINITIONS ===
  var shadeOptions = [
    { value: 'none',          label: 'No Shading',                    short: 'No Shade' },
    { value: 'partial-fixed', label: 'Partial Shading (fixed)',       short: 'Partial Shade (Fix)' },
    { value: 'partial-var',   label: 'Partial Shading (variable)',    short: 'Partial Shade (Var)' },
    { value: 'full-fixed',    label: 'Full Shading (fixed)',          short: 'Full Shade (Fix)' },
    { value: 'full-var',      label: 'Full Shading (variable)',       short: 'Full Shade (Var)' },
    { value: 'ideal',         label: 'Ideal Shading',                 short: 'Ideal Shade' }
  ];
  var blockOptions = [
    { value: 'none',          label: 'No Wind Block',                 short: 'No Wind Block' },
    { value: 'partial-fixed', label: 'Partial Wind Block (fixed)',    short: 'Partial Wind Block (Fix)' },
    { value: 'partial-var',   label: 'Partial Wind Block (variable)', short: 'Partial Wind Block (Var)' },
    { value: 'full-fixed',    label: 'Full Wind Block (fixed)',       short: 'Full Wind Block (Fix)' },
    { value: 'full-var',      label: 'Full Wind Block (variable)',    short: 'Full Wind Block (Var)' },
    { value: 'ideal',         label: 'Ideal Wind Block',              short: 'Ideal Wind Block' }
  ];
  var fanOptions = [
    { value: 'none', label: 'No Added Wind',                    short: 'No Fans' },
    { value: 'low',  label: 'Fans — Low (+0.25 m/s)', short: 'Fans Low' },
    { value: 'high', label: 'Fans — High (+0.8 m/s)', short: 'Fans High' }
  ];

  // === UTCI STRESS CATEGORY COLORS (standard UTCI RCB scheme) ===
  var utciColors = [
    '#7b2abf',  // 0: Extreme Cold (<-40 C)
    '#2e4dc2',  // 1: Very Strong Cold (-40 to -27)
    '#0088cc',  // 2: Strong Cold (-27 to -13)
    '#00b8d0',  // 3: Moderate Cold (-13 to 0)
    '#4dcfb0',  // 4: Slight Cold (0 to 9)
    '#00c880',  // 5: No Thermal Stress cool (9 to 18)
    '#00aa44',  // 6: Thermal Comfort Zone (18 to 26)
    '#88cc00',  // 7: Moderate Heat (26 to 32)
    '#eedd00',  // 8: Strong Heat (32 to 38)
    '#f07800',  // 9: Very Strong Heat (38 to 46)
    '#cc1122'   // 10: Extreme Heat (>46 C)
  ];
  var utciCatNames = [
    'Extreme Cold (<−40°C)',
    'Very Strong Cold (−40 to −27)',
    'Strong Cold (−27 to −13)',
    'Moderate Cold (−13 to 0)',
    'Slight Cold (0 to 9)',
    'No Thermal Stress (cool) (9–18)',
    'Thermal Comfort Zone (18–26)',
    'Moderate Heat (26–32)',
    'Strong Heat (32–38)',
    'Very Strong Heat (38–46)',
    'Extreme Heat (>46°C)'
  ];

  // Category indices that make up the two headline metrics.
  var COMFORT_CAT    = 6;         // 18-26 C UTCI
  var NO_STRESS_CATS = [5, 6];    // 9-26 C UTCI

  /** Return [shadeShort, blockShort, fansShort] display labels for a case. */
  function strategyLabels(shade, block, fans) {
    function find(arr, val) {
      for (var i = 0; i < arr.length; i++) { if (arr[i].value === val) return arr[i].short; }
      return val;
    }
    return [find(shadeOptions, shade), find(blockOptions, block), find(fanOptions, fans)];
  }

  /** Map UTCI value to stress category index 0-10; -1 for null/NaN. */
  function catIndex(u) {
    if (u === null || !isFinite(u)) return -1;
    if (u < -40) return 0;
    if (u < -27) return 1;
    if (u < -13) return 2;
    if (u <   0) return 3;
    if (u <   9) return 4;
    if (u <  18) return 5;
    if (u <  26) return 6;
    if (u <  32) return 7;
    if (u <  38) return 8;
    if (u <  46) return 9;
    return 10;
  }

  /**
   * Compute strategy-adjusted UTCI for a single hour.
   * Application order: (1) shading -> (2) wind block -> (3) fans.
   * Variable strategies apply only when they improve comfort (move UTCI toward 9-26 C).
   */
  function computeHour(tdb, rh, dnr_base, v_base, solAlt, shadeMode, blockMode, fanMode) {
    function calcU(dnr, v_phys) {
      var mrt = tdb + utciSolarGainDeltaMrt(solAlt, Math.max(0, dnr));
      var v   = Math.min(Math.max(v_phys, 0.5), 16.9);
      var r   = utci(tdb, mrt, v, rh, false);
      return (r !== null) ? r.utci : null;
    }
    function dist(u) {
      if (u === null || !isFinite(u)) return Infinity;
      return u > 26 ? u - 26 : u < 9 ? 9 - u : 0;
    }
    function better(u_new, u_old) { return dist(u_new) < dist(u_old); }

    // Step 1: Shading
    var u0 = calcU(dnr_base, v_base);
    var dnr_eff;
    switch (shadeMode) {
      case 'partial-fixed': dnr_eff = dnr_base * 0.5; break;
      case 'partial-var':   dnr_eff = better(calcU(dnr_base * 0.5, v_base), u0) ? dnr_base * 0.5 : dnr_base; break;
      case 'full-fixed':    dnr_eff = 0; break;
      case 'full-var':      dnr_eff = better(calcU(0, v_base), u0) ? 0 : dnr_base; break;
      case 'ideal': {
        var best_dnr = dnr_base, best_d_s = dist(u0);
        [dnr_base * 0.5, 0].forEach(function (d) {
          var dd = dist(calcU(d, v_base));
          if (dd < best_d_s) { best_d_s = dd; best_dnr = d; }
        });
        dnr_eff = best_dnr;
        break;
      }
      default: dnr_eff = dnr_base;
    }

    // Pre-compute MRT for fixed dnr_eff (shared for block+fan steps)
    var mrt_eff = tdb + utciSolarGainDeltaMrt(solAlt, Math.max(0, dnr_eff));
    function calcUv(v_phys) {
      var v = Math.min(Math.max(v_phys, 0.5), 16.9);
      var r = utci(tdb, mrt_eff, v, rh, false);
      return (r !== null) ? r.utci : null;
    }

    // Step 2: Wind Block
    var u_shade = calcUv(v_base);
    var v_blocked;
    switch (blockMode) {
      case 'partial-fixed': v_blocked = v_base * 0.5; break;
      case 'partial-var':   v_blocked = better(calcUv(v_base * 0.5), u_shade) ? v_base * 0.5 : v_base; break;
      case 'full-fixed':    v_blocked = 0.5; break;
      case 'full-var':      v_blocked = better(calcUv(0.5), u_shade) ? 0.5 : v_base; break;
      case 'ideal': {
        var best_v = v_base, best_d_b = dist(u_shade);
        [v_base * 0.5, 0.5].forEach(function (v) {
          var dd = dist(calcUv(v));
          if (dd < best_d_b) { best_d_b = dd; best_v = v; }
        });
        v_blocked = best_v;
        break;
      }
      default: v_blocked = v_base;
    }

    // Step 3: Fans (always only if beneficial)
    var u_blocked = calcUv(v_blocked);
    var v_final;
    switch (fanMode) {
      case 'low':  v_final = better(calcUv(v_blocked + 0.25), u_blocked) ? v_blocked + 0.25 : v_blocked; break;
      case 'high': v_final = better(calcUv(v_blocked + 0.8),  u_blocked) ? v_blocked + 0.8  : v_blocked; break;
      default: v_final = v_blocked;
    }

    return calcUv(v_final);
  }

  /** Compute strategy UTCI for all 8760 hours of an epw. */
  function computeAllHours(epw, c) {
    if (!epw || !epw.weatherData) return [];
    var altitudes = epw.getSolarPositionField('altitude');
    var results = [];
    epw.weatherData.forEach(function (row, i) {
      var tdb = +row[6], rh = +row[8], dnr = +row[14], v = +row[21];
      if (!isFinite(tdb) || tdb === 99.9 || !isFinite(rh) || rh === 999 || !isFinite(v) || v === 999) {
        results.push(null);
        return;
      }
      var dnrVal = (!isFinite(dnr) || dnr === 9999) ? 0 : Math.max(0, dnr);
      var solAlt = (altitudes && i < altitudes.length && isFinite(altitudes[i])) ? altitudes[i] : 0;
      results.push(computeHour(tdb, rh, dnrVal, v, solAlt, c.shade, c.block, c.fans));
    });
    return results;
  }

  /** Count UTCI category hours for one case using the provided index array. */
  function buildCounts(utciArr, filteredIndices) {
    var counts = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    for (var j = 0; j < filteredIndices.length; j++) {
      var ci = catIndex(utciArr[filteredIndices[j]]);
      if (ci >= 0) counts[ci]++;
    }
    return counts;
  }

  /** Every hour index of an epw -- the "no filter applied" case. */
  function allIndices(epw) {
    var n = (epw && epw.weatherData) ? epw.weatherData.length : 0;
    var idx = new Array(n);
    for (var i = 0; i < n; i++) { idx[i] = i; }
    return idx;
  }

  /**
   * Headline comfort metrics for one set of category counts.
   * Returns { total, comfort, comfortPct, noStress, noStressPct }.
   */
  function summarize(counts) {
    var total = 0;
    for (var i = 0; i < counts.length; i++) { total += counts[i]; }
    var comfort  = counts[COMFORT_CAT];
    var noStress = NO_STRESS_CATS.reduce(function (s, c) { return s + counts[c]; }, 0);
    return {
      total:       total,
      comfort:     comfort,
      comfortPct:  total > 0 ? (comfort  / total * 100) : 0,
      noStress:    noStress,
      noStressPct: total > 0 ? (noStress / total * 100) : 0
    };
  }

  global.EpwOTC = {
    defaultCases:    defaultCases,
    shadeOptions:    shadeOptions,
    blockOptions:    blockOptions,
    fanOptions:      fanOptions,
    utciColors:      utciColors,
    utciCatNames:    utciCatNames,
    COMFORT_CAT:     COMFORT_CAT,
    NO_STRESS_CATS:  NO_STRESS_CATS,
    strategyLabels:  strategyLabels,
    catIndex:        catIndex,
    computeHour:     computeHour,
    computeAllHours: computeAllHours,
    buildCounts:     buildCounts,
    allIndices:      allIndices,
    summarize:       summarize
  };
})(window);
