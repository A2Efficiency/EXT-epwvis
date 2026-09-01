/*-------------------------------------------------------------------------
 * epwDashboard.js
 * Presentation charts for the weather-file reporting dashboard.
 *
 * These are deliberately NOT the interactive charts from epwCharts.js. That
 * module renders an "all data" ghost layer under a crossfilter-filtered
 * overlay, plus brush handles and "% selected" labels -- all meaningless in a
 * static deck -- and it hard-binds to ~40 DOM ids and a global unitSystem.
 * The charts here take data in and draw one clean, slide-shaped figure.
 *
 * The aggregation math is deliberately identical to epwCharts.js so the deck
 * and the interactive viewer never disagree.
 *
 * Depends on: d3 v3, epw2json.js, utci.js, epwOTC.js
 *-------------------------------------------------------------------------*/
(function (global) {
  'use strict';

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MONTH_FULL = ['January', 'February', 'March', 'April', 'May', 'June',
                    'July', 'August', 'September', 'October', 'November', 'December'];

  // Cumulative day-of-year at the start of each month (non-leap), for axis ticks.
  var MONTH_START_DOY = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];

  // ---------------------------------------------------------------------
  //  PALETTE
  //  Validated with the dataviz skill validator (see scripts/validate_palette.js).
  // ---------------------------------------------------------------------
  // Colours are the A2E brand theme pulled straight from the PowerPoint
  // template (accent1 #ff6600, accent3 #00a3b4, dk1 #1a1f16, lt2 #f4f5f0), so
  // the exported charts sit in the deck without a palette clash.
  var PALETTE = {
    // Single-series temperature charts. One hue: the band is the light step,
    // the mean line the dark step of the same brand teal ramp.
    tempBand:   '#cdeaee',
    tempLine:   '#007a88',
    tempAccent: '#e55a00',   // brand accent2, for the annual extremes

    // Dew point. Dry bulb is already teal everywhere in the deck, so dew point
    // takes the brand's warm accent rather than a second teal nobody could
    // separate. Same one-hue logic: light step for the band, dark for the line.
    dewBand:    '#ffddc2',
    dewLine:    '#e55a00',   // brand accent2

    // Two-series (dry bulb + dew point) day charts. Validated as a CATEGORICAL
    // PAIR with scripts/validate_palette.js: all six checks pass -- CVD dE 17.4
    // (protan) / 33.8 (tritan), normal dE 29.4, both >= 3:1 on white. The teal
    // is one step lighter than tempLine because #007a88 misses the chroma floor
    // (0.091 < 0.100) and reads grey as a categorical slot; the existing
    // single-series charts keep #007a88, where that check does not apply.
    // Rejected on evidence: brand green #4a8b2c vs the teal is dE 4.3 under
    // tritanopia -- indistinguishable.
    dbtPair:    '#0090a2',
    dewPair:    '#e55a00',

    // Degree days. Two series -> validated brand pair: CVD dE 18.7 (protan),
    // normal dE 31.7. Orange reads heating, teal reads cooling.
    hdd: '#ff6600',          // brand accent1
    cdd: '#00a3b4',          // brand accent3

    // Ink, keyed to the template's dk1 and accent5
    ink:      '#1a1f16',
    inkSoft:  '#4a5245',
    inkMuted: '#7a8075',
    grid:     '#e6e8e1',
    axis:     '#b5bab0',
    surface:  '#ffffff'
  };

  /**
   * UTCI stress categories, as an ORDERED DIVERGING ramp around the comfort
   * zone rather than the rainbow used in the interactive viewer.
   *
   * The viewer's scheme fails basic separation: #2e4dc2 vs #7b2abf is dE 1.6
   * under deuteranopia, and #00c880 vs #4dcfb0 is dE 7.3 for NORMAL vision --
   * two adjacent categories that most people cannot tell apart. Here each pole
   * is strictly monotonic in lightness (cold 0.297 -> 0.869, heat 0.854 ->
   * 0.443) so the eye can order the steps, worst adjacent CVD separation is
   * dE 9.8, and the comfort green is far darker than both its neighbours so
   * the headline category reads first. Anchored on the brand teal and orange.
   *
   * Pass { utciColors: EpwOTC.utciColors } to render() to fall back to the
   * viewer's scheme if deck/tool consistency matters more.
   */
  var UTCI_RAMP = [
    '#00343a',  //  0 Extreme Cold
    '#005b66',  //  1 Very Strong Cold
    '#007a88',  //  2 Strong Cold
    '#00a3b4',  //  3 Moderate Cold        <- brand accent3
    '#4fc3d0',  //  4 Slight Cold
    '#a5e0e7',  //  5 No Thermal Stress (cool)
    '#4a8b2c',  //  6 Thermal Comfort Zone <- headline
    '#ffc27a',  //  7 Moderate Heat
    '#ff8c1a',  //  8 Strong Heat
    '#e55a00',  //  9 Very Strong Heat     <- brand accent2
    '#8f2f00'   // 10 Extreme Heat
  ];

  // Open Sans is the template's minor (body) font. DM Sans, the major font,
  // is used by PowerPoint for slide headings -- charts stay on the body face.
  var FONT = '"Open Sans", Helvetica, Arial, sans-serif';

  // ---------------------------------------------------------------------
  //  SMALL HELPERS
  // ---------------------------------------------------------------------

  function cToF(c) { return c === null || !isFinite(c) ? null : 32 + c * 1.8; }

  /** Bar path with only the two data-end corners rounded, anchored to baseline. */
  function barPathUp(x, y, w, h, r) {
    if (h <= 0) return '';
    r = Math.min(r, w / 2, h);
    return 'M' + x + ',' + (y + h) +
           'L' + x + ',' + (y + r) +
           'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
           'L' + (x + w - r) + ',' + y +
           'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) +
           'L' + (x + w) + ',' + (y + h) + 'Z';
  }

  /**
   * Ink for a label sitting on a coloured fill. The UTCI ramp spans very dark
   * to very light steps, so a fixed white would vanish on Moderate Heat and the
   * pale teals; pick by the fill's own relative luminance instead.
   */
  function labelInkOn(hex) {
    function lin(c) {
      c = parseInt(c, 16) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }
    var L = 0.2126 * lin(hex.slice(1, 3)) +
            0.7152 * lin(hex.slice(3, 5)) +
            0.0722 * lin(hex.slice(5, 7));
    return L > 0.5 ? PALETTE.ink : '#ffffff';
  }

  function fmtInt(n) { return d3.format(',d')(Math.round(n)); }
  function fmt1(n)   { return d3.format(',.1f')(n); }

  /** Apply the shared axis look: recessive line, muted labels. */
  function styleAxis(g) {
    g.selectAll('path.domain')
      .style('fill', 'none').style('stroke', PALETTE.axis).style('stroke-width', 1);
    g.selectAll('line')
      .style('stroke', PALETTE.axis).style('stroke-width', 1);
    g.selectAll('text')
      .style('font-family', FONT).style('font-size', '10px').style('fill', PALETTE.inkMuted);
  }

  /** Estimated advance width of one legend entry, swatch + gap included. */
  function legendItemWidth(label, gap) {
    return 19 + (String(label).length * 5.6) + gap;
  }

  /**
   * Horizontal legend row of {color,label} swatches. Returns the <g>.
   * With opts.anchorRight, `x` is the RIGHT edge and the row is laid out back
   * from it -- a fixed left offset silently runs long labels off the canvas.
   */
  function addLegend(svg, x, y, items, opts) {
    opts = opts || {};
    var gap = opts.gap || 20;
    if (opts.anchorRight) {
      var total = 0;
      items.forEach(function (it) { total += legendItemWidth(it.label, gap); });
      x = Math.max(0, x - (total - gap));
    }
    var g = svg.append('g').attr('class', 'epw-legend')
        .attr('transform', 'translate(' + x + ',' + y + ')');
    var cx = 0;
    items.forEach(function (it) {
      var row = g.append('g').attr('transform', 'translate(' + cx + ',0)');
      row.append('rect')
          .attr('width', 14).attr('height', 9).attr('y', -7).attr('rx', 2)
          .style('fill', it.color)
          .style('fill-opacity', it.opacity === undefined ? 1 : it.opacity);
      row.append('text')
          .attr('x', 19).attr('y', 0)
          .style('font-family', FONT).style('font-size', '10.5px')
          .style('fill', PALETTE.inkSoft)
          .text(it.label);
      cx += legendItemWidth(it.label, gap);
    });
    return g;
  }

  /**
   * Work out where the title, subtitle and legend sit, and how much vertical
   * room the block needs. Any of the three may be absent -- the deck suppresses
   * chart titles because the PowerPoint layout supplies a branded one, and the
   * plot area must then reclaim that space rather than leave a gap.
   */
  function headerLayout(hasTitle, hasSub, hasLegend) {
    var out = {}, y = 0;
    if (hasTitle)  { out.titleY = 20;                 y = out.titleY; }
    if (hasSub)    { out.subY   = y ? y + 16 : 16;    y = out.subY;   }
    if (hasLegend) { out.legY   = y ? y + 18 : 14;    y = out.legY;   }
    out.height = y ? y + (hasLegend ? 16 : 12) : 8;
    return out;
  }

  function drawHeader(svg, x, hdr, title, subtitle, legendItems) {
    if (title && hdr.titleY !== undefined) {
      svg.append('text')
          .attr('data-epv-title', '1')
          .attr('x', x).attr('y', hdr.titleY)
          .style('font-family', FONT).style('font-size', '13px')
          .style('font-weight', 'bold').style('fill', PALETTE.ink)
          .text(title);
    }
    if (subtitle && hdr.subY !== undefined) {
      svg.append('text')
          .attr('x', x).attr('y', hdr.subY)
          .style('font-family', FONT).style('font-size', '11px')
          .style('fill', PALETTE.inkMuted)
          .text(subtitle);
    }
    if (legendItems && legendItems.length && hdr.legY !== undefined) {
      addLegend(svg, x, hdr.legY, legendItems);
    }
  }

  /** Rotated unit caption down the left edge of the plot area. */
  function addYUnit(svg, marginTop, innerH, text) {
    if (!text) return;
    svg.append('text')
        .attr('transform', 'rotate(-90)')
        .attr('x', -(marginTop + innerH / 2)).attr('y', 14)
        .attr('text-anchor', 'middle')
        .style('font-family', FONT).style('font-size', '10.5px')
        .style('fill', PALETTE.inkMuted)
        .text(text);
  }

  // ---------------------------------------------------------------------
  //  DATA PREP  (mirrors epwCharts.js epwDataDefault / computeDailyStats)
  // ---------------------------------------------------------------------

  var DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday',
                   'Thursday', 'Friday', 'Saturday'];
  var DAY_ABBR  = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  /**
   * Day of week for day 1 of the file, from the EPW's DATA PERIODS header
   * (field 4, e.g. "Sunday"). 0 = Sunday.
   *
   * This is the ONLY defensible source. A TMYx year splices months from
   * different real years -- chicago-ohare-intl-ap.epw carries 2011 through
   * 2022 -- so the year column cannot give a calendar weekday, and the file's
   * own dates are a synthetic 1/1-12/31. EnergyPlus itself takes the weekday
   * from this header when it simulates the file, so a weekday/weekend split
   * built on it agrees with the schedules a model would actually run.
   * Defaults to Sunday, which is what every OneBuilding file we handle states.
   */
  function startDayOfWeek(epw) {
    var row = epw && epw.dataPeriod;
    var name = (row && row[4] ? String(row[4]) : '').trim().toLowerCase();
    for (var i = 0; i < DAY_NAMES.length; i++) {
      if (DAY_NAMES[i].toLowerCase() === name) return i;
    }
    return 0;
  }

  /**
   * Flatten an epw into hourly records with temperatures in the display unit.
   * @returns {Array} [{ index, month, day, hour, dayOfYear, dow, isWeekend,
   *                     dbt, dpt }]
   */
  function buildRecords(epw, isIP) {
    var months = epw.month(), days = epw.day(), hours = epw.hour();
    var dbt = epw.dryBulbTemperature();
    var dpt = epw.dewPointTemperature();
    var dow0 = startDayOfWeek(epw);
    var out = [];
    var lastMonth = null, doy = 0, lastDay = null;

    for (var i = 0; i < months.length; i++) {
      var v = dbt[i];
      if (v === 99.9) v = null;                       // EPW missing sentinel
      if (isIP && v !== null) v = cToF(v);

      // Field 7 shares the dry-bulb sentinel and range (-70..70 C).
      var w = dpt[i];
      if (w === 99.9 || !isFinite(w) || w < -70 || w > 70) w = null;
      if (isIP && w !== null) w = cToF(w);

      // Day-of-year, counted by day boundaries so it survives non-Jan-1 starts.
      if (days[i] !== lastDay || months[i] !== lastMonth) {
        doy++;
        lastDay = days[i];
        lastMonth = months[i];
      }
      var dow = (dow0 + doy - 1) % 7;
      out.push({
        index:     i,
        month:     months[i],
        day:       days[i],
        hour:      hours[i],
        dayOfYear: doy,
        dow:       dow,
        isWeekend: dow === 0 || dow === 6,
        dbt:       v,
        dpt:       w
      });
    }
    return out;
  }

  /**
   * 365 daily {day, avg, min, max}. Same shape as epwCharts computeDailyStats.
   * `key` selects the record field, defaulting to dry bulb.
   */
  function dailyStats(records, key) {
    key = key || 'dbt';
    var groups = {};
    records.forEach(function (d) {
      if (d[key] === null || !isFinite(d[key])) return;
      (groups[d.dayOfYear] = groups[d.dayOfYear] || []).push(d[key]);
    });
    var result = [];
    for (var day = 1; day <= 365; day++) {
      var arr = groups[day];
      if (!arr || !arr.length) {
        result.push({ day: day, avg: null, min: null, max: null });
      } else {
        var sum = 0;
        for (var k = 0; k < arr.length; k++) sum += arr[k];
        result.push({
          day: day,
          avg: sum / arr.length,
          min: Math.min.apply(Math, arr),
          max: Math.max.apply(Math, arr)
        });
      }
    }
    return result;
  }

  /**
   * result[month][hour] = {avg,min,max}. Mirrors computeHourlyProfileByMonth.
   * `key` selects the record field, defaulting to dry bulb.
   */
  function hourlyProfileByMonth(records, key) {
    key = key || 'dbt';
    var groups = {};
    records.forEach(function (d) {
      if (d[key] === null || !isFinite(d[key])) return;
      var gk = d.month + '_' + d.hour;
      (groups[gk] = groups[gk] || []).push(d[key]);
    });
    var result = {};
    for (var m = 1; m <= 12; m++) {
      result[m] = {};
      for (var h = 1; h <= 24; h++) {
        var arr = groups[m + '_' + h];
        if (!arr || !arr.length) {
          result[m][h] = { avg: null, min: null, max: null };
        } else {
          var sum = 0;
          for (var k = 0; k < arr.length; k++) sum += arr[k];
          result[m][h] = {
            avg: sum / arr.length,
            min: Math.min.apply(Math, arr),
            max: Math.max.apply(Math, arr)
          };
        }
      }
    }
    return result;
  }

  /** Monthly HDD/CDD. Identical accumulation to epwCharts.js calcDD. */
  function monthlyDegreeDays(records, hBase, cBase) {
    var months = d3.range(0, 12).map(function () { return { hdd: 0, cdd: 0 }; });
    records.forEach(function (d) {
      if (d.dbt === null || !isFinite(d.dbt)) return;
      months[d.month - 1].hdd += Math.max(0, hBase - d.dbt) / 24;
      months[d.month - 1].cdd += Math.max(0, d.dbt - cBase) / 24;
    });
    return months;
  }

  /** Degree days binned by dry-bulb. Identical to epwCharts.js accumBins. */
  function degreeDaysByTemp(records, hBase, cBase, binSize) {
    var temps = records.filter(function (d) { return d.dbt !== null && isFinite(d.dbt); })
                       .map(function (d) { return d.dbt; });
    if (!temps.length) return { bins: [], hdd: {}, cdd: {}, binSize: binSize };

    var tMin = Math.floor(d3.min(temps) / binSize) * binSize;
    var tMax = Math.ceil(d3.max(temps) / binSize) * binSize;

    var bins = [], hdd = {}, cdd = {};
    for (var t = tMin; t < tMax; t += binSize) { bins.push(t); hdd[t] = 0; cdd[t] = 0; }

    records.forEach(function (d) {
      if (d.dbt === null || !isFinite(d.dbt)) return;
      var bin = Math.floor(d.dbt / binSize) * binSize;
      if (hdd[bin] === undefined) return;
      hdd[bin] += Math.max(0, hBase - d.dbt) / 24;
      cdd[bin] += Math.max(0, d.dbt - cBase) / 24;
    });
    return { bins: bins, hdd: hdd, cdd: cdd, binSize: binSize };
  }

  /**
   * Occupied-hours subset. An EPW hour h covers (h-1):01 to h:00, so its
   * midpoint is h-0.5; the hour counts as occupied when that midpoint falls in
   * [startClock, endClock). 7->19 therefore selects EPW hours 8..19 -- twelve
   * hours a day, exactly half the year, which is what the deck reports.
   */
  function occupiedFilter(records, startClock, endClock) {
    return records.filter(function (d) {
      var mid = d.hour - 0.5;
      return mid >= startClock && mid < endClock;
    });
  }

  /**
   * Day-type subset. 'all' | 'weekday' (Mon-Fri) | 'weekend' (Sat-Sun).
   * Weekdays come from the DATA PERIODS header -- see startDayOfWeek.
   */
  function dayTypeFilter(records, mode) {
    if (mode === 'weekday') {
      return records.filter(function (d) { return !d.isWeekend; });
    }
    if (mode === 'weekend') {
      return records.filter(function (d) { return d.isWeekend; });
    }
    return records;
  }

  var DAY_TYPE_LABEL = {
    all:     'All days',
    weekday: 'Weekdays only (Mon–Fri)',
    weekend: 'Weekends only (Sat–Sun)'
  };

  /**
   * Every calendar day as { dayOfYear, month, day, dow, hours[24], stats }.
   * hours[h-1] = { hour, t, dbt, dpt }; t is the clock midpoint h-0.5, so the
   * points land where the reading actually applies (EPW hour h covers
   * (h-1):01 to h:00) and match the profile chart's x placement.
   */
  function dailySeries(records) {
    var byDay = {};
    records.forEach(function (d) {
      var day = byDay[d.dayOfYear];
      if (!day) {
        day = byDay[d.dayOfYear] = {
          dayOfYear: d.dayOfYear, month: d.month, day: d.day,
          dow: d.dow, isWeekend: d.isWeekend,
          hours: []
        };
      }
      day.hours.push({ hour: d.hour, t: d.hour - 0.5, dbt: d.dbt, dpt: d.dpt });
    });

    return Object.keys(byDay).map(function (k) { return byDay[k]; })
      .sort(function (a, b) { return a.dayOfYear - b.dayOfYear; })
      .map(function (day) {
        day.hours.sort(function (a, b) { return a.hour - b.hour; });
        day.stats = { dbt: daySummary(day.hours, 'dbt'),
                      dpt: daySummary(day.hours, 'dpt') };
        return day;
      });
  }

  function daySummary(hours, key) {
    var v = hours.map(function (h) { return h[key]; })
                 .filter(function (x) { return x !== null && isFinite(x); });
    if (!v.length) return { mean: null, min: null, max: null, n: 0 };
    var sum = 0;
    for (var i = 0; i < v.length; i++) sum += v[i];
    return {
      mean: sum / v.length,
      min:  Math.min.apply(Math, v),
      max:  Math.max.apply(Math, v),
      n:    v.length
    };
  }

  /**
   * Pick the low / median / peak day of every month.
   *
   * Days are ranked by one statistic of one variable -- `basis` is 'mean',
   * 'max' or 'min' and `key` is 'dpt' or 'dbt' -- and the three picks are real
   * days from the file, never an interpolated composite: "the median day" has
   * to be a date you can point at and plot.
   *
   * On an even-sized month the median takes the lower of the two middle days
   * (index floor((n-1)/2)) so the choice is deterministic and reproducible
   * rather than depending on sort stability.
   *
   * @returns {Array} 12 entries (month 1-12), each
   *   { month, n, low, median, peak } where each pick is a dailySeries day
   *   decorated with { rank, value }, or null when the month has no data.
   */
  function monthlyRepresentativeDays(days, key, basis) {
    key = key || 'dpt';
    basis = basis || 'mean';

    var out = [];
    for (var m = 1; m <= 12; m++) {
      var pool = days.filter(function (d) {
        return d.month === m && d.stats[key][basis] !== null;
      });
      pool.sort(function (a, b) {
        var va = a.stats[key][basis], vb = b.stats[key][basis];
        // Tie-break on date so the ordering is total and stable.
        return va === vb ? a.dayOfYear - b.dayOfYear : va - vb;
      });

      if (!pool.length) {
        out.push({ month: m, n: 0, low: null, median: null, peak: null });
        continue;
      }
      var pick = function (i) {
        var d = pool[i];
        return {
          dayOfYear: d.dayOfYear, month: d.month, day: d.day,
          dow: d.dow, isWeekend: d.isWeekend, hours: d.hours, stats: d.stats,
          rank: i + 1, of: pool.length, value: d.stats[key][basis]
        };
      };
      out.push({
        month:  m,
        n:      pool.length,
        low:    pick(0),
        median: pick(Math.floor((pool.length - 1) / 2)),
        peak:   pick(pool.length - 1)
      });
    }
    return out;
  }

  /** "N of M hours (x%) selected" caption, optionally prefixed with totals. */
  function addFooter(svg, x, y, nSel, nAll, prefix) {
    var pct = nAll > 0 ? (nSel / nAll * 100).toFixed(1) : '0.0';
    svg.append('text')
        .attr('x', x).attr('y', y)
        .style('font-family', FONT).style('font-size', '10px')
        .style('fill', PALETTE.inkMuted)
        .text((prefix ? prefix + '  |  ' : '') + fmtInt(nSel) + ' of ' +
              fmtInt(nAll) + ' hours (' + pct + '%) selected');
  }

  // ---------------------------------------------------------------------
  //  TOOLTIP (HTML review layer; absent from exported PNGs)
  // ---------------------------------------------------------------------

  function tip() {
    var t = d3.select('body').select('.epw-dash-tip');
    if (t.empty()) {
      t = d3.select('body').append('div').attr('class', 'epw-dash-tip');
    }
    return t;
  }
  function tipShow(html) {
    tip().style('display', 'block').html(html);
  }
  function tipMove() {
    tip().style('left', (d3.event.pageX + 14) + 'px')
         .style('top',  (d3.event.pageY - 12) + 'px');
  }
  function tipHide() { tip().style('display', 'none'); }

  function hoverable(sel, htmlFn) {
    sel.on('mouseover', function (d, i) { tipShow(htmlFn(d, i)); tipMove(); })
       .on('mousemove', tipMove)
       .on('mouseout', tipHide);
  }

  // ---------------------------------------------------------------------
  //  CHART 1 -- ANNUAL TIMESERIES (daily min/mean/max band)
  // ---------------------------------------------------------------------

  function drawAnnualTimeseries(container, stats, o) {
    o = o || {};
    var W = o.width || 960, H = o.height || 300;
    var hdr = headerLayout(!!o.title, !!o.subtitle, true);
    var m = { top: hdr.height, right: 20, bottom: 34, left: 56 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;

    var sel = d3.select(container);
    sel.select('svg').remove();
    var svg = sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', PALETTE.surface);

    var valid = stats.filter(function (d) { return d.min !== null; });
    if (!valid.length) return svg;

    var yMin = d3.min(valid, function (d) { return d.min; });
    var yMax = d3.max(valid, function (d) { return d.max; });
    var pad  = Math.max((yMax - yMin) * 0.06, 0.5);

    var x = d3.scale.linear().domain([1, 365]).range([0, iw]);
    var y = d3.scale.linear().domain([yMin - pad, yMax + pad]).range([ih, 0]);

    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');

    // Recessive gridlines
    g.selectAll('line.grid').data(y.ticks(6)).enter().append('line')
        .attr('class', 'grid')
        .attr('x1', 0).attr('x2', iw)
        .attr('y1', y).attr('y2', y)
        .style('stroke', PALETTE.grid).style('stroke-width', 1);

    var area = d3.svg.area()
        .x(function (d) { return x(d.day); })
        .y0(function (d) { return y(d.min); })
        .y1(function (d) { return y(d.max); })
        .defined(function (d) { return d.min !== null; });

    var line = d3.svg.line()
        .x(function (d) { return x(d.day); })
        .y(function (d) { return y(d.avg); })
        .defined(function (d) { return d.avg !== null; });

    g.append('path').datum(stats)
        .attr('d', area)
        .style('fill', PALETTE.tempBand).style('fill-opacity', 0.9);

    g.append('path').datum(stats)
        .attr('d', line)
        .style('fill', 'none')
        .style('stroke', PALETTE.tempLine).style('stroke-width', 2)
        .style('stroke-linejoin', 'round');

    // Axes
    var xAxis = d3.svg.axis().scale(x).orient('bottom')
        .tickValues(MONTH_START_DOY)
        .tickFormat(function (d, i) { return MONTHS[i]; });
    var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')').call(xAxis);
    styleAxis(gx);

    var gy = g.append('g').call(d3.svg.axis().scale(y).orient('left').ticks(6));
    styleAxis(gy);
    gy.selectAll('path.domain').style('stroke', 'none');

    // Selective direct labels: the year's extremes, not a number on every point.
    var hottest = valid.reduce(function (a, b) { return b.max > a.max ? b : a; });
    var coldest = valid.reduce(function (a, b) { return b.min < a.min ? b : a; });
    [{ d: hottest, v: hottest.max, dy: -8, txt: 'peak ' + fmt1(hottest.max) + (o.unit || '') },
     { d: coldest, v: coldest.min, dy: 14, txt: 'low ' + fmt1(coldest.min) + (o.unit || '') }
    ].forEach(function (a) {
      g.append('circle')
          .attr('cx', x(a.d.day)).attr('cy', y(a.v)).attr('r', 3)
          .style('fill', PALETTE.tempAccent)
          .style('stroke', PALETTE.surface).style('stroke-width', 1.5);
      g.append('text')
          .attr('x', x(a.d.day)).attr('y', y(a.v) + a.dy)
          .attr('text-anchor', x(a.d.day) > iw * 0.85 ? 'end' : 'middle')
          .style('font-family', FONT).style('font-size', '10px')
          .style('font-weight', 'bold').style('fill', PALETTE.tempAccent)
          .text(a.txt);
    });

    drawHeader(svg, m.left, hdr, o.title, o.subtitle, [
      { color: PALETTE.tempBand, label: 'Daily range (min–max)' },
      { color: PALETTE.tempLine, label: 'Daily mean' }
    ]);
    addYUnit(svg, m.top, ih, o.unit);

    // Hover crosshair over the nearest day
    var focus = g.append('g').style('display', 'none');
    focus.append('line').attr('y1', 0).attr('y2', ih)
        .style('stroke', PALETTE.inkMuted).style('stroke-width', 1)
        .style('stroke-dasharray', '3,3');
    g.append('rect')
        .attr('width', iw).attr('height', ih)
        .style('fill', 'none').style('pointer-events', 'all')
        .on('mouseover', function () { focus.style('display', null); })
        .on('mouseout', function () { focus.style('display', 'none'); tipHide(); })
        .on('mousemove', function () {
          var day = Math.round(x.invert(d3.mouse(this)[0]));
          var d = stats[day - 1];
          if (!d || d.avg === null) return;
          focus.select('line').attr('x1', x(d.day)).attr('x2', x(d.day));
          var u = o.unit || '';
          tipShow('<b>Day ' + d.day + '</b><br>mean ' + fmt1(d.avg) + u +
                  '<br>min ' + fmt1(d.min) + u + ' · max ' + fmt1(d.max) + u);
          tipMove();
        });

    return svg;
  }

  // ---------------------------------------------------------------------
  //  CHART 2 -- DAILY PROFILE BY MONTH (twelve panels in one row)
  // ---------------------------------------------------------------------

  /**
   * Twelve months side by side in a single row, matching the reference export.
   * profiles = { all, filtered }; when filtered is present it is drawn over a
   * grey "all data" ghost so the occupied-hours subset reads against the year.
   */
  function drawDailyProfiles(container, profiles, o) {
    o = o || {};
    var pAll = profiles.all || profiles;
    var pFil = profiles.filtered || null;
    var hasGhost = !!pFil;
    // One hue per variable, so dry bulb and dew point stay tellable apart when
    // their two strips sit above one another on the same page.
    var bandColor = o.bandColor || PALETTE.tempBand;
    var lineColor = o.lineColor || PALETTE.tempLine;

    var W = o.width || 1180, H = o.height || 300;
    var hdr = headerLayout(!!o.title, !!o.subtitle, false);
    var m = { top: hdr.height + 16, right: 12, bottom: 46, left: 60 };
    var gap = 5;
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;
    var pw = (iw - gap * 11) / 12;

    var sel = d3.select(container);
    sel.select('svg').remove();
    var svg = sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', PALETTE.surface);

    // ONE shared y domain across all twelve panels -- per-panel scales would
    // make every month look alike and destroy the comparison.
    var lo = Infinity, hi = -Infinity;
    for (var mm = 1; mm <= 12; mm++) {
      for (var hh = 1; hh <= 24; hh++) {
        var c = pAll[mm][hh];
        if (c.min === null) continue;
        if (c.min < lo) lo = c.min;
        if (c.max > hi) hi = c.max;
      }
    }
    if (!isFinite(lo)) return svg;
    var pad = Math.max((hi - lo) * 0.05, 0.5);

    // Plot against clock time (EPW hour h spans h-1 to h, midpoint h-0.5) so
    // the 6a / 12p / 6p ticks land where they actually belong.
    var x = d3.scale.linear().domain([0, 24]).range([0, pw]);
    var y = d3.scale.linear().domain([lo - pad, hi + pad]).range([ih, 0]);

    function series(profile, mi) {
      var out = [];
      for (var h = 1; h <= 24; h++) {
        var cell = profile[mi + 1][h];
        out.push({ t: h - 0.5, avg: cell.avg, min: cell.min, max: cell.max });
      }
      return out;
    }
    var area = d3.svg.area()
        .x(function (d) { return x(d.t); })
        .y0(function (d) { return y(d.min); })
        .y1(function (d) { return y(d.max); })
        .defined(function (d) { return d.min !== null; });
    var line = d3.svg.line()
        .x(function (d) { return x(d.t); })
        .y(function (d) { return y(d.avg); })
        .defined(function (d) { return d.avg !== null; });

    for (var mi = 0; mi < 12; mi++) {
      var px = m.left + mi * (pw + gap);
      var g = svg.append('g').attr('transform', 'translate(' + px + ',' + m.top + ')');

      g.append('rect')
          .attr('width', pw).attr('height', ih)
          .style('fill', '#fafaf8')
          .style('stroke', PALETTE.grid).style('stroke-width', 1);

      if (hasGhost) {
        g.append('path').datum(series(pAll, mi)).attr('d', area)
            .style('fill', '#d9dcd6').style('fill-opacity', 0.9);
        g.append('path').datum(series(pAll, mi)).attr('d', line)
            .style('fill', 'none').style('stroke', '#9aa096').style('stroke-width', 1.1);
      }
      var front = series(hasGhost ? pFil : pAll, mi);
      g.append('path').datum(front).attr('d', area)
          .style('fill', bandColor).style('fill-opacity', hasGhost ? 0.85 : 0.95);
      g.append('path').datum(front).attr('d', line)
          .style('fill', 'none')
          .style('stroke', lineColor).style('stroke-width', 1.4)
          .style('stroke-linejoin', 'round');

      svg.append('text')
          .attr('x', px + pw / 2).attr('y', m.top - 6)
          .attr('text-anchor', 'middle')
          .style('font-family', FONT).style('font-size', '10.5px')
          .style('font-weight', 'bold').style('fill', PALETTE.ink)
          .text(MONTHS[mi]);

      var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')')
          .call(d3.svg.axis().scale(x).orient('bottom')
                .tickValues([6, 12, 18])
                .tickFormat(function (d) { return d === 6 ? '6a' : d === 12 ? '12p' : '6p'; }));
      styleAxis(gx);
      gx.selectAll('text').style('font-size', '9px');
      gx.selectAll('path.domain').style('stroke', 'none');

      (function (monthIdx, ref) {
        g.append('rect')
            .attr('width', pw).attr('height', ih)
            .style('fill', 'none').style('pointer-events', 'all')
            .on('mouseout', tipHide)
            .on('mousemove', function () {
              var hr = Math.max(1, Math.min(24, Math.round(x.invert(d3.mouse(this)[0]) + 0.5)));
              var c2 = ref[hr - 1];
              if (!c2 || c2.avg === null) return;
              var u = o.unit || '';
              tipShow('<b>' + MONTH_FULL[monthIdx] + ' &middot; hour ' + hr + '</b><br>' +
                      'avg ' + fmt1(c2.avg) + u + '<br>' +
                      'min ' + fmt1(c2.min) + u + ' &middot; max ' + fmt1(c2.max) + u);
              tipMove();
            });
      })(mi, front);
    }

    var gy = svg.append('g')
        .attr('transform', 'translate(' + m.left + ',' + m.top + ')')
        .call(d3.svg.axis().scale(y).orient('left').ticks(5));
    styleAxis(gy);
    gy.selectAll('path.domain').style('stroke', 'none');
    addYUnit(svg, m.top, ih, o.yLabel || o.unit);

    drawHeader(svg, m.left, hdr, o.title, o.subtitle, null);
    if (hasGhost) {
      addLegend(svg, W - m.right, 12, [
        { color: '#d9dcd6', label: o.ghostLabel || 'All data (min-max + avg)' },
        { color: bandColor, label: o.frontLabel || 'Occupied hours (min-max + avg)' }
      ], { anchorRight: true });
    }
    if (o.footer) {
      addFooter(svg, m.left, H - 6, o.footer.selected, o.footer.total);
    }
    return svg;
  }

  // ---------------------------------------------------------------------
  //  CHART 3 -- UTCI STRESS CATEGORIES (stacked bars, 5 strategy cases)
  // ---------------------------------------------------------------------

  function drawUTCIChart(container, cases, caseCounts, o) {
    o = o || {};
    var colors = o.utciColors || UTCI_RAMP;
    var names  = global.EpwOTC.utciCatNames;
    var W = o.width || 900, H = o.height || 430;
    // +16 of headroom for the per-bar evaluated-hours label.
    var hdr = headerLayout(!!o.title, !!o.subtitle, false);
    var m = { top: hdr.height + 16, right: 232, bottom: 62, left: 62 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;

    var sel = d3.select(container);
    sel.select('svg').remove();
    var svg = sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', PALETTE.surface);

    var maxHrs = 0;
    caseCounts.forEach(function (counts) {
      var t = 0; counts.forEach(function (n) { t += n; });
      if (t > maxHrs) maxHrs = t;
    });
    maxHrs = maxHrs || 1;

    var x = d3.scale.ordinal()
        .domain(cases.map(function (c) { return c.label; }))
        .rangeRoundBands([0, iw], 0.34);
    var y = d3.scale.linear().domain([0, maxHrs]).range([ih, 0]);

    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');

    g.selectAll('line.grid').data(y.ticks(6)).enter().append('line')
        .attr('class', 'grid')
        .attr('x1', 0).attr('x2', iw).attr('y1', y).attr('y2', y)
        .style('stroke', PALETTE.grid).style('stroke-width', 1);

    var bw = x.rangeBand();

    var COMFORT = global.EpwOTC.COMFORT_CAT;

    cases.forEach(function (c, ci) {
      var counts = caseCounts[ci];
      var bx = x(c.label);
      var acc = 0;
      var comfortBox = null;

      for (var k = 0; k < counts.length; k++) {
        var hrs = counts[k];
        if (hrs <= 0) { acc += hrs; continue; }
        var y0 = y(acc), y1 = y(acc + hrs);
        var h = y0 - y1;
        // 2px surface gap between stacked segments -- doubles as the secondary
        // encoding that keeps adjacent ramp steps separable.
        var drawH = Math.max(0.5, h - 2);
        if (k === COMFORT) comfortBox = { y: y1, h: drawH };

        (function (catIdx, hours) {
          var r = g.append('rect')
              .attr('x', bx).attr('y', y1)
              .attr('width', bw).attr('height', drawH)
              .style('fill', colors[catIdx]);
          hoverable(r, function () {
            return '<b>' + c.label + '</b><br>' + names[catIdx] +
                   '<br>' + fmtInt(hours) + ' hrs (' +
                   fmt1(hours / (maxHrs || 1) * 100) + '%)';
          });
        })(k, hrs);

        acc += hrs;
      }

      var s = global.EpwOTC.summarize(counts);

      // Headline number sits inside the comfort band itself, so it is never
      // mistaken for the bar total.
      if (comfortBox && comfortBox.h >= 20) {
        g.append('text')
            .attr('x', bx + bw / 2).attr('y', comfortBox.y + comfortBox.h / 2 + 4)
            .attr('text-anchor', 'middle')
            .style('font-family', FONT).style('font-size', '11.5px')
            .style('font-weight', 'bold').style('fill', labelInkOn(colors[COMFORT]))
            .text(fmtInt(s.comfort) + ' hrs');
      } else if (comfortBox) {
        g.append('text')
            .attr('x', bx + bw + 5).attr('y', comfortBox.y + comfortBox.h / 2 + 4)
            .style('font-family', FONT).style('font-size', '10.5px')
            .style('font-weight', 'bold').style('fill', PALETTE.ink)
            .text(fmtInt(s.comfort) + ' hrs');
      }

      // Bar tops sit a few px apart because each stacked segment gives up 2px
      // to its gap and the cases do not all span the same number of
      // categories. Stating the evaluated total makes that unambiguous, and
      // surfaces it honestly if a case ever does drop hours (a strategy can
      // push an hour outside the UTCI model's validity range).
      g.append('text')
          .attr('x', bx + bw / 2).attr('y', y(acc) - 7)
          .attr('text-anchor', 'middle')
          .style('font-family', FONT).style('font-size', '9.5px')
          .style('fill', PALETTE.inkMuted)
          .text(fmtInt(s.total) + ' hrs evaluated');
    });

    var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')')
        .call(d3.svg.axis().scale(x).orient('bottom'));
    styleAxis(gx);
    gx.selectAll('text')
        .style('font-size', '10px').style('fill', PALETTE.inkSoft)
        .call(function (t) {
          // Wrap two-word case labels onto a second line.
          t.each(function () {
            var self = d3.select(this), words = self.text().split(/\s+/);
            if (words.length < 3) return;
            self.text(null);
            self.append('tspan').attr('x', 0).attr('dy', '0.9em')
                .text(words.slice(0, 2).join(' '));
            self.append('tspan').attr('x', 0).attr('dy', '1.1em')
                .text(words.slice(2).join(' '));
          });
        });

    var gy = g.append('g').call(d3.svg.axis().scale(y).orient('left').ticks(6)
                                 .tickFormat(d3.format(',d')));
    styleAxis(gy);
    gy.selectAll('path.domain').style('stroke', 'none');

    addYUnit(svg, m.top, ih, 'Hours per year');

    // Legend: all 11 categories, ordered cold -> hot, comfort marked.
    var lg = svg.append('g')
        .attr('transform', 'translate(' + (W - m.right + 16) + ',' + (m.top - 6) + ')');
    names.forEach(function (nm, i) {
      var row = lg.append('g').attr('transform', 'translate(0,' + (i * 16) + ')');
      row.append('rect')
          .attr('width', 13).attr('height', 11).attr('rx', 2)
          .style('fill', colors[i]);
      row.append('text')
          .attr('x', 18).attr('y', 9.5)
          .style('font-family', FONT)
          .style('font-size', i === global.EpwOTC.COMFORT_CAT ? '10px' : '9.5px')
          .style('font-weight', i === global.EpwOTC.COMFORT_CAT ? 'bold' : 'normal')
          .style('fill', i === global.EpwOTC.COMFORT_CAT ? PALETTE.ink : PALETTE.inkSoft)
          .text(nm);
    });

    drawHeader(svg, m.left, hdr, o.title, o.subtitle, null);
    return svg;
  }

  /** The UTCI summary table that accompanies the stacked-bar chart. */
  function drawUTCISummary(container, cases, caseCounts, o) {
    o = o || {};
    var sel = d3.select(container);
    sel.html('');

    var base = global.EpwOTC.summarize(caseCounts[0]);
    var tbl = sel.append('table').attr('class', 'epw-otc-summary');

    var thead = tbl.append('thead');
    var r0 = thead.append('tr');
    r0.append('th').attr('class', 'lbl').text('');
    r0.append('th').attr('colspan', 3).text('Thermal Comfort Zone (18–26 °C UTCI)');
    r0.append('th').attr('class', 'spacer').text('');
    r0.append('th').attr('colspan', 3).text('No Thermal Stress (9–26 °C UTCI)');

    var tbody = tbl.append('tbody');
    cases.forEach(function (c, ci) {
      var s = global.EpwOTC.summarize(caseCounts[ci]);
      var tr = tbody.append('tr').attr('class', ci === 0 ? 'base' : null);
      tr.append('td').attr('class', 'lbl')
        .text(c.label + (c.desc ? ' — ' + c.desc : ''));

      tr.append('td').attr('class', 'num').text(fmtInt(s.comfort));
      tr.append('td').attr('class', 'pct').text('hrs (' + fmt1(s.comfortPct) + '%)');
      var dC = s.comfort - base.comfort;
      tr.append('td').attr('class', 'delta ' + (dC >= 0 ? 'pos' : 'neg'))
        .text(ci === 0 ? '' : (dC >= 0 ? '+' : '') + fmtInt(dC) + ' vs base');

      tr.append('td').attr('class', 'spacer').text('');

      tr.append('td').attr('class', 'num').text(fmtInt(s.noStress));
      tr.append('td').attr('class', 'pct').text('hrs (' + fmt1(s.noStressPct) + '%)');
      var dN = s.noStress - base.noStress;
      tr.append('td').attr('class', 'delta ' + (dN >= 0 ? 'pos' : 'neg'))
        .text(ci === 0 ? '' : (dN >= 0 ? '+' : '') + fmtInt(dN) + ' vs base');
    });
    return tbl;
  }

  // ---------------------------------------------------------------------
  //  CHART 4 -- MONTHLY DEGREE DAYS
  // ---------------------------------------------------------------------

  /**
   * dd = { all: [...], filtered: [...] } (filtered optional). Grouped heating
   * vs cooling; within each slot the occupied-hours bar sits over a pale
   * all-data bar, so the occupied share is read directly off the column.
   */
  function drawMonthlyDegreeDays(container, dd, o) {
    o = o || {};
    var mAll = dd.all || dd;
    var mFil = dd.filtered || null;
    var hasGhost = !!mFil;

    var W = o.width || 1000, H = o.height || 355;
    var hdr = headerLayout(!!o.title, !!o.subtitle, true);
    var m = { top: hdr.height, right: 18, bottom: 40, left: 62 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;

    var sel = d3.select(container);
    sel.select('svg').remove();
    var svg = sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', PALETTE.surface);

    var yMax = d3.max(mAll, function (d) { return Math.max(d.hdd, d.cdd); }) || 1;

    var x  = d3.scale.ordinal().domain(MONTHS).rangeRoundBands([0, iw], 0.24);
    var y  = d3.scale.linear().domain([0, yMax * 1.12]).range([ih, 0]);
    var xs = d3.scale.ordinal().domain(['hdd', 'cdd']).rangeRoundBands([0, x.rangeBand()], 0);

    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');

    g.selectAll('line.grid').data(y.ticks(6)).enter().append('line')
        .attr('class', 'grid')
        .attr('x1', 0).attr('x2', iw).attr('y1', y).attr('y2', y)
        .style('stroke', PALETTE.grid).style('stroke-width', 1);

    var bw = Math.max(1, xs.rangeBand() - 2);   // 2px gap between adjacent bars

    // Grouped, never stacked: heating and cooling share a unit but their sum
    // is not a quantity anyone reports.
    [['hdd', PALETTE.hdd], ['cdd', PALETTE.cdd]].forEach(function (pair) {
      var key = pair[0], color = pair[1];

      if (hasGhost) {
        g.selectAll('path.ghost-' + key).data(mAll).enter().append('path')
            .attr('class', 'ghost-' + key)
            .attr('d', function (d, i) {
              var bx = x(MONTHS[i]) + xs(key) + 1, by = y(d[key]);
              return barPathUp(bx, by, bw, ih - by, 4);
            })
            .style('fill', color).style('fill-opacity', 0.28);
      }

      var front = hasGhost ? mFil : mAll;
      g.selectAll('path.bar-' + key).data(front).enter().append('path')
          .attr('class', 'bar-' + key)
          .attr('d', function (d, i) {
            var bx = x(MONTHS[i]) + xs(key) + 1, by = y(d[key]);
            return barPathUp(bx, by, bw, ih - by, 4);
          })
          .style('fill', color)
          .call(hoverable, function (d, i) {
            var label = key === 'hdd' ? 'Heating' : 'Cooling';
            var txt = '<b>' + MONTH_FULL[i] + '</b><br>' + label + ' degree days: ' +
                      fmtInt(d[key]) + ' ' + (o.unit || '');
            if (hasGhost) txt += '<br>all hours: ' + fmtInt(mAll[i][key]);
            return txt;
          });
    });

    var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')')
        .call(d3.svg.axis().scale(x).orient('bottom'));
    styleAxis(gx);
    var gy = g.append('g').call(d3.svg.axis().scale(y).orient('left').ticks(6)
                                 .tickFormat(d3.format(',d')));
    styleAxis(gy);
    gy.selectAll('path.domain').style('stroke', 'none');

    var src = hasGhost ? mFil : mAll;
    var totH = d3.sum(src, function (d) { return d.hdd; });
    var totC = d3.sum(src, function (d) { return d.cdd; });

    var legend = hasGhost
      ? [{ color: PALETTE.hdd, label: 'Heating, occupied (' + fmtInt(totH) + ')' },
         { color: PALETTE.hdd, label: 'Heating, all hours', opacity: 0.28 },
         { color: PALETTE.cdd, label: 'Cooling, occupied (' + fmtInt(totC) + ')' },
         { color: PALETTE.cdd, label: 'Cooling, all hours', opacity: 0.28 }]
      : [{ color: PALETTE.hdd, label: 'Heating (' + fmtInt(totH) + ' annual)' },
         { color: PALETTE.cdd, label: 'Cooling (' + fmtInt(totC) + ' annual)' }];

    drawHeader(svg, m.left, hdr, o.title, o.subtitle, legend);
    addYUnit(svg, m.top, ih, o.unit);
    return svg;
  }

  // ---------------------------------------------------------------------
  //  CHART 5 -- DEGREE DAYS BY TEMPERATURE BIN
  // ---------------------------------------------------------------------

  /**
   * ddt = { all, filtered } from degreeDaysByTemp (filtered optional).
   * Occupied-hours bars sit over pale all-data bars in the same slot -- a bin
   * is either below the heating base or above the cooling base, never both, so
   * heating and cooling never collide.
   */
  function drawDegreeDaysByTemp(container, ddt, o) {
    o = o || {};
    var dAll = ddt.all || ddt;
    var dFil = ddt.filtered || null;
    var hasGhost = !!dFil;

    var W = o.width || 1100, H = o.height || 370;
    var hdr = headerLayout(!!o.title, !!o.subtitle, true);
    var m = { top: hdr.height, right: 18, bottom: 74, left: 66 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;

    var sel = d3.select(container);
    sel.select('svg').remove();
    var svg = sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', PALETTE.surface);

    if (!dAll.bins.length) return svg;

    var yMax = d3.max(dAll.bins, function (b) {
      return Math.max(dAll.hdd[b] || 0, dAll.cdd[b] || 0);
    }) || 1;

    var x = d3.scale.ordinal().domain(dAll.bins).rangeRoundBands([0, iw], 0.18);
    var y = d3.scale.linear().domain([0, yMax * 1.16]).range([ih, 0]);

    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');

    g.selectAll('line.grid').data(y.ticks(6)).enter().append('line')
        .attr('class', 'grid')
        .attr('x1', 0).attr('x2', iw).attr('y1', y).attr('y2', y)
        .style('stroke', PALETTE.grid).style('stroke-width', 1);

    var bw = Math.max(1, x.rangeBand());
    var front = hasGhost ? dFil : dAll;
    var totH = d3.sum(dAll.bins, function (b) { return front.hdd[b] || 0; });
    var totC = d3.sum(dAll.bins, function (b) { return front.cdd[b] || 0; });

    [['hdd', PALETTE.hdd, totH], ['cdd', PALETTE.cdd, totC]].forEach(function (trio) {
      var key = trio[0], color = trio[1], total = trio[2];

      if (hasGhost) {
        g.selectAll('path.dtg-' + key).data(dAll.bins).enter().append('path')
            .attr('class', 'dtg-' + key)
            .attr('d', function (b) {
              var v = dAll[key][b] || 0;
              if (v <= 0) return '';
              var by = y(v);
              return barPathUp(x(b), by, bw, ih - by, 3);
            })
            .style('fill', color).style('fill-opacity', 0.28);
      }

      g.selectAll('path.dt-' + key).data(dAll.bins).enter().append('path')
          .attr('class', 'dt-' + key)
          .attr('d', function (b) {
            var v = front[key][b] || 0;
            if (v <= 0) return '';
            var by = y(v);
            return barPathUp(x(b), by, bw, ih - by, 3);
          })
          .style('fill', color)
          .call(hoverable, function (b) {
            var label = key === 'hdd' ? 'Heating' : 'Cooling';
            var txt = '<b>' + b + '-' + (b + dAll.binSize) + (o.unit || '') + '</b><br>' +
                      label + ': ' + fmt1(front[key][b] || 0);
            if (hasGhost) txt += '<br>all hours: ' + fmt1(dAll[key][b] || 0);
            return txt;
          });

      // Value plus share of the series total, on bins worth naming.
      g.selectAll('text.dtl-' + key).data(dAll.bins).enter().append('text')
          .attr('class', 'dtl-' + key)
          .attr('x', function (b) { return x(b) + bw / 2; })
          .attr('y', function (b) { return y(front[key][b] || 0) - 4; })
          .attr('text-anchor', 'middle')
          .style('font-family', FONT).style('font-size', '8.5px')
          .style('fill', color)
          .text(function (b) {
            var v = front[key][b] || 0;
            if (v <= 0 || total <= 0) return '';
            var pct = v / total * 100;
            return pct < 1.5 ? '' : fmtInt(v) + ' (' + Math.round(pct) + '%)';
          });
    });

    // Base temperature markers -- the pivot the whole chart is built around.
    // A single base is the common case; two labels on one line would collide.
    var baseRefs = (o.hBase === o.cBase)
      ? [[o.hBase, PALETTE.inkSoft, 'Base']]
      : [[o.hBase, PALETTE.hdd, 'Heat base'], [o.cBase, PALETTE.cdd, 'Cool base']];
    baseRefs.forEach(function (ref, i) {
        if (ref[0] === undefined || ref[0] === null) return;
        var bin = Math.floor(ref[0] / dAll.binSize) * dAll.binSize;
        var px = x(bin);
        if (px === undefined) return;
        g.append('line')
            .attr('x1', px).attr('x2', px).attr('y1', 0).attr('y2', ih)
            .style('stroke', ref[1]).style('stroke-width', 1.2)
            .style('stroke-dasharray', '4,3').style('stroke-opacity', 0.75);
        g.append('text')
            .attr('x', px + 4).attr('y', 10 + i * 12)
            .style('font-family', FONT).style('font-size', '9px')
            .style('fill', ref[1])
            .text(ref[2] + ' ' + ref[0] + (o.unit || ''));
      });

    var step = dAll.bins.length > 26 ? 2 : 1;
    var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')')
        .call(d3.svg.axis().scale(x).orient('bottom')
              .tickValues(dAll.bins.filter(function (b, i) { return i % step === 0; }))
              .tickFormat(function (b) { return b + '-' + (b + dAll.binSize); }));
    styleAxis(gx);
    gx.selectAll('text')
        .style('font-size', '8.5px')
        .attr('transform', 'rotate(-45)')
        .attr('dx', '-0.7em').attr('dy', '0.1em')
        .style('text-anchor', 'end');

    var gy = g.append('g').call(d3.svg.axis().scale(y).orient('left').ticks(6));
    styleAxis(gy);
    gy.selectAll('path.domain').style('stroke', 'none');

    drawHeader(svg, m.left, hdr, o.title, o.subtitle, hasGhost ? [
      { color: PALETTE.hdd, label: 'Heating (occupied)' },
      { color: PALETTE.hdd, label: 'Heating (all hours)', opacity: 0.28 },
      { color: PALETTE.cdd, label: 'Cooling (occupied)' },
      { color: PALETTE.cdd, label: 'Cooling (all hours)', opacity: 0.28 }
    ] : [
      { color: PALETTE.hdd, label: 'Heating degree days' },
      { color: PALETTE.cdd, label: 'Cooling degree days' }
    ]);
    addYUnit(svg, m.top, ih, o.ddUnit || '');

    if (o.footer) {
      addFooter(svg, m.left, H - 6, o.footer.selected, o.footer.total,
                'HDD(' + o.hBase + (o.unit || '') + '): ' + fmtInt(totH) +
                '  |  CDD(' + o.cBase + (o.unit || '') + '): ' + fmtInt(totC));
    }
    return svg;
  }

  // ---------------------------------------------------------------------
  //  CHART 6 -- UTCI STRESS CATEGORY BREAKDOWN (horizontal bars)
  // ---------------------------------------------------------------------

  /**
   * One horizontal bar per occupied stress category, hottest at the top.
   * Empty categories are dropped rather than drawn as slivers, so a mild
   * climate does not waste half the chart on rows that read as zero.
   */
  function drawUTCICategoryBars(container, counts, o) {
    o = o || {};
    var colors = o.utciColors || UTCI_RAMP;
    var names  = global.EpwOTC.utciCatNames;

    var rows = [];
    for (var i = counts.length - 1; i >= 0; i--) {
      if (counts[i] > 0) rows.push({ i: i, n: counts[i] });
    }
    var total = counts.reduce(function (a, b) { return a + b; }, 0) || 1;

    var W = o.width || 470, H = o.height || 250;
    var hdr = headerLayout(!!o.title, !!o.subtitle, false);
    var m = { top: hdr.height, right: 58, bottom: 26, left: 132 };
    var iw = W - m.left - m.right;
    var ih = H - m.top - m.bottom;

    var sel = d3.select(container);
    sel.select('svg').remove();
    var svg = sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', PALETTE.surface);
    if (!rows.length) return svg;

    var x = d3.scale.linear()
        .domain([0, d3.max(rows, function (d) { return d.n; })]).range([0, iw]);
    var yb = d3.scale.ordinal()
        .domain(rows.map(function (d) { return d.i; }))
        .rangeRoundBands([0, ih], 0.24);

    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');
    var bh = yb.rangeBand();

    rows.forEach(function (r) {
      var w = x(r.n);
      g.append('rect')
          .attr('x', 0).attr('y', yb(r.i)).attr('width', w).attr('height', bh)
          .attr('rx', 2)
          .style('fill', colors[r.i])
          .call(hoverable, function () {
            return '<b>' + names[r.i] + '</b><br>' + fmtInt(r.n) + ' hrs (' +
                   fmt1(r.n / total * 100) + '%)';
          });

      // Category name on the left, always in ink -- never the series colour.
      g.append('text')
          .attr('x', -8).attr('y', yb(r.i) + bh / 2 + 3.5)
          .attr('text-anchor', 'end')
          .style('font-family', FONT).style('font-size', '9px')
          .style('fill', PALETTE.inkSoft)
          .text(names[r.i].replace(/\s*\([^)]*\)\s*$/, ''));

      // Value inside the bar when it fits, just outside when it does not.
      var label = fmtInt(r.n) + ' (' + Math.round(r.n / total * 100) + '%)';
      var inside = w > label.length * 6.2 + 12;
      g.append('text')
          .attr('x', inside ? w - 6 : w + 5)
          .attr('y', yb(r.i) + bh / 2 + 3.5)
          .attr('text-anchor', inside ? 'end' : 'start')
          .style('font-family', FONT).style('font-size', '9px')
          .style('font-weight', 'bold')
          .style('fill', inside ? labelInkOn(colors[r.i]) : PALETTE.inkSoft)
          .text(label);
    });

    var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')')
        .call(d3.svg.axis().scale(x).orient('bottom').ticks(4)
              .tickFormat(d3.format(',d')));
    styleAxis(gx);
    gx.selectAll('text').style('font-size', '9px');

    drawHeader(svg, 4, hdr, o.title, o.subtitle, null);
    return svg;
  }

  // ---------------------------------------------------------------------
  //  CHART 7 -- REPRESENTATIVE DAY (dry bulb + dew point over 24 h)
  // ---------------------------------------------------------------------

  /** Shared y domain over both variables across a set of days. */
  function dayDomain(days) {
    var lo = Infinity, hi = -Infinity;
    days.forEach(function (d) {
      if (!d) return;
      d.hours.forEach(function (h) {
        ['dbt', 'dpt'].forEach(function (k) {
          if (h[k] === null || !isFinite(h[k])) return;
          if (h[k] < lo) lo = h[k];
          if (h[k] > hi) hi = h[k];
        });
      });
    });
    return isFinite(lo) ? [lo, hi] : null;
  }

  function dayLabel(d) {
    return MONTHS[d.month - 1] + ' ' + d.day + ' (' + DAY_ABBR[d.dow] + ')';
  }

  /** The two line generators every day plot uses. */
  function dayLines(x, y) {
    function mk(k) {
      return d3.svg.line()
          .x(function (h) { return x(h.t); })
          .y(function (h) { return y(h[k]); })
          .defined(function (h) { return h[k] !== null && isFinite(h[k]); });
    }
    return { dbt: mk('dbt'), dpt: mk('dpt') };
  }

  /**
   * Twelve representative days, one per month, as a 4x3 grid of 24-hour plots
   * with dry bulb over dew point.
   *
   * ONE y domain across all twelve panels, for the same reason the profile
   * strip shares one: per-panel scales would flatten January into July.
   * `picks` is a 12-long array of day objects (see monthlyRepresentativeDays)
   * with nulls allowed. `o.onSelect(day)` fires when a panel is clicked.
   */
  function drawRepresentativeDays(container, picks, o) {
    o = o || {};
    var cols = o.cols || 4, rows = Math.ceil(12 / cols);
    var W = o.width || 1180, H = o.height || 520;
    var hdr = headerLayout(!!o.title, !!o.subtitle, true);
    var m = { top: hdr.height + 18, right: 14, bottom: 34, left: 52 };
    var gapX = 16, gapY = 34;
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;
    var pw = (iw - gapX * (cols - 1)) / cols;
    var ph = (ih - gapY * (rows - 1)) / rows;

    var sel = d3.select(container);
    sel.select('svg').remove();
    var svg = sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', PALETTE.surface);

    var dom = dayDomain(picks);
    if (!dom) return svg;
    var pad = Math.max((dom[1] - dom[0]) * 0.08, 0.5);

    var x = d3.scale.linear().domain([0, 24]).range([0, pw]);
    var y = d3.scale.linear().domain([dom[0] - pad, dom[1] + pad]).range([ph, 0]);
    var yTicks = y.ticks(4);
    var ln = dayLines(x, y);
    var u = o.unit || '';

    picks.forEach(function (d, mi) {
      var cx = mi % cols, cy = Math.floor(mi / cols);
      var px = m.left + cx * (pw + gapX);
      var py = m.top + cy * (ph + gapY);
      var g = svg.append('g').attr('transform', 'translate(' + px + ',' + py + ')');

      g.append('rect').attr('width', pw).attr('height', ph)
          .style('fill', '#fafaf8')
          .style('stroke', PALETTE.grid).style('stroke-width', 1);

      // Panel caption: the month, then the actual date this is.
      svg.append('text')
          .attr('x', px).attr('y', py - 6)
          .style('font-family', FONT).style('font-size', '10.5px')
          .style('font-weight', 'bold').style('fill', PALETTE.ink)
          .text(MONTH_FULL[mi].slice(0, 3));
      if (d) {
        svg.append('text')
            .attr('x', px + 26).attr('y', py - 6)
            .style('font-family', FONT).style('font-size', '10px')
            .style('fill', PALETTE.inkMuted)
            .text(d.day + ' ' + DAY_ABBR[d.dow] +
                  (d.value !== undefined && d.value !== null
                    ? '  ·  ' + fmt1(d.value) + u : ''));
      }
      if (!d) {
        g.append('text').attr('x', pw / 2).attr('y', ph / 2)
            .attr('text-anchor', 'middle')
            .style('font-family', FONT).style('font-size', '10px')
            .style('fill', PALETTE.inkMuted).text('no data');
        return;
      }

      // Gridlines behind the data, recessive. Same tick set as the row axis
      // below, or the labelled values would not sit on the lines.
      g.selectAll('line.grid').data(yTicks).enter().append('line')
          .attr('class', 'grid')
          .attr('x1', 0).attr('x2', pw).attr('y1', y).attr('y2', y)
          .style('stroke', PALETTE.grid).style('stroke-width', 1);

      // The gap between the two lines IS the dew-point depression, so fill it
      // rather than leaving the reader to measure it by eye.
      var band = d3.svg.area()
          .x(function (h) { return x(h.t); })
          .y0(function (h) { return y(h.dpt); })
          .y1(function (h) { return y(h.dbt); })
          .defined(function (h) {
            return h.dbt !== null && h.dpt !== null &&
                   isFinite(h.dbt) && isFinite(h.dpt);
          });
      g.append('path').datum(d.hours).attr('d', band)
          .style('fill', PALETTE.dbtPair).style('fill-opacity', 0.10);

      g.append('path').datum(d.hours).attr('d', ln.dpt)
          .style('fill', 'none').style('stroke', PALETTE.dewPair)
          .style('stroke-width', 1.6).style('stroke-linejoin', 'round');
      g.append('path').datum(d.hours).attr('d', ln.dbt)
          .style('fill', 'none').style('stroke', PALETTE.dbtPair)
          .style('stroke-width', 1.6).style('stroke-linejoin', 'round');

      var gx = g.append('g').attr('transform', 'translate(0,' + ph + ')')
          .call(d3.svg.axis().scale(x).orient('bottom')
                .tickValues([6, 12, 18])
                .tickFormat(function (t) { return t === 6 ? '6a' : t === 12 ? '12p' : '6p'; }));
      styleAxis(gx);
      gx.selectAll('text').style('font-size', '9px');
      gx.selectAll('path.domain').style('stroke', 'none');

      // Hit target spans the panel, not the 1.6px strokes.
      g.append('rect')
          .attr('width', pw).attr('height', ph)
          .style('fill', 'none').style('pointer-events', 'all')
          .style('cursor', o.onSelect ? 'pointer' : 'default')
          .on('mouseout', tipHide)
          .on('click', function () { if (o.onSelect) o.onSelect(d); })
          .on('mousemove', function () {
            var hr = Math.max(1, Math.min(24, Math.round(x.invert(d3.mouse(this)[0]) + 0.5)));
            var h = d.hours[hr - 1];
            if (!h) return;
            tipShow('<b>' + dayLabel(d) + ' &middot; hour ' + hr + '</b><br>' +
                    'dry bulb ' + (h.dbt === null ? '—' : fmt1(h.dbt) + u) + '<br>' +
                    'dew point ' + (h.dpt === null ? '—' : fmt1(h.dpt) + u));
            tipMove();
          });
    });

    // One y axis per ROW, not one for the whole grid: the panels share a
    // domain, but a single axis beside row 1 leaves rows 2 and 3 unlabelled
    // and unreadable.
    var yAxis = d3.svg.axis().scale(y).orient('left').tickValues(yTicks);
    for (var r = 0; r < rows; r++) {
      var gy = svg.append('g')
          .attr('transform', 'translate(' + m.left + ',' +
                (m.top + r * (ph + gapY)) + ')')
          .call(yAxis);
      styleAxis(gy);
      gy.selectAll('text').style('font-size', '9px');
      gy.selectAll('path.domain').style('stroke', 'none');
    }
    addYUnit(svg, m.top, ih, o.yLabel || o.unit);

    drawHeader(svg, m.left, hdr, o.title, o.subtitle, [
      { color: PALETTE.dbtPair, label: 'Dry bulb' },
      { color: PALETTE.dewPair, label: 'Dew point' }
    ]);
    return svg;
  }

  /**
   * One day, full width: dry bulb and dew point hour by hour, direct-labelled.
   * This is the detail view behind a panel of drawRepresentativeDays.
   */
  function drawDayDetail(container, day, o) {
    o = o || {};
    var W = o.width || 620, H = o.height || 300;
    var hdr = headerLayout(!!o.title, !!o.subtitle, true);
    var m = { top: hdr.height, right: 78, bottom: 36, left: 56 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;

    var sel = d3.select(container);
    sel.select('svg').remove();
    var svg = sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', PALETTE.surface);
    if (!day) return svg;

    var dom = dayDomain([day]);
    if (!dom) return svg;
    var pad = Math.max((dom[1] - dom[0]) * 0.12, 1);

    var x = d3.scale.linear().domain([0, 24]).range([0, iw]);
    var y = d3.scale.linear().domain([dom[0] - pad, dom[1] + pad]).range([ih, 0]);
    var ln = dayLines(x, y);
    var u = o.unit || '';

    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');

    g.selectAll('line.grid').data(y.ticks(6)).enter().append('line')
        .attr('class', 'grid')
        .attr('x1', 0).attr('x2', iw).attr('y1', y).attr('y2', y)
        .style('stroke', PALETTE.grid).style('stroke-width', 1);

    var band = d3.svg.area()
        .x(function (h) { return x(h.t); })
        .y0(function (h) { return y(h.dpt); })
        .y1(function (h) { return y(h.dbt); })
        .defined(function (h) {
          return h.dbt !== null && h.dpt !== null && isFinite(h.dbt) && isFinite(h.dpt);
        });
    g.append('path').datum(day.hours).attr('d', band)
        .style('fill', PALETTE.dbtPair).style('fill-opacity', 0.10);

    g.append('path').datum(day.hours).attr('d', ln.dpt)
        .style('fill', 'none').style('stroke', PALETTE.dewPair)
        .style('stroke-width', 2).style('stroke-linejoin', 'round');
    g.append('path').datum(day.hours).attr('d', ln.dbt)
        .style('fill', 'none').style('stroke', PALETTE.dbtPair)
        .style('stroke-width', 2).style('stroke-linejoin', 'round');

    // Direct labels at the right-hand end, so identity is never colour-alone.
    [{ k: 'dbt', c: PALETTE.dbtPair, t: 'Dry bulb' },
     { k: 'dpt', c: PALETTE.dewPair, t: 'Dew point' }].forEach(function (sPec) {
      var last = null;
      for (var i = day.hours.length - 1; i >= 0; i--) {
        var v = day.hours[i][sPec.k];
        if (v !== null && isFinite(v)) { last = day.hours[i]; break; }
      }
      if (!last) return;
      g.append('circle')
          .attr('cx', x(last.t)).attr('cy', y(last[sPec.k])).attr('r', 3.5)
          .style('fill', sPec.c)
          .style('stroke', PALETTE.surface).style('stroke-width', 2);
      g.append('text')
          .attr('x', x(last.t) + 8).attr('y', y(last[sPec.k]) + 3.5)
          .style('font-family', FONT).style('font-size', '10.5px')
          .style('font-weight', 'bold').style('fill', PALETTE.inkSoft)
          .text(sPec.t);
    });

    var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')')
        .call(d3.svg.axis().scale(x).orient('bottom')
              .tickValues([0, 3, 6, 9, 12, 15, 18, 21, 24])
              .tickFormat(function (t) {
                if (t === 0 || t === 24) return '12a';
                if (t === 12) return '12p';
                return t < 12 ? t + 'a' : (t - 12) + 'p';
              }));
    styleAxis(gx);

    var gy = g.append('g').call(d3.svg.axis().scale(y).orient('left').ticks(6));
    styleAxis(gy);
    gy.selectAll('path.domain').style('stroke', 'none');
    addYUnit(svg, m.top, ih, o.yLabel || o.unit);

    drawHeader(svg, m.left, hdr, o.title, o.subtitle, [
      { color: PALETTE.dbtPair, label: 'Dry bulb' },
      { color: PALETTE.dewPair, label: 'Dew point' }
    ]);

    // Crosshair over the whole plot, reading both series at once.
    var focus = g.append('g').style('display', 'none');
    focus.append('line').attr('y1', 0).attr('y2', ih)
        .style('stroke', PALETTE.inkMuted).style('stroke-width', 1)
        .style('stroke-dasharray', '3,3');
    g.append('rect')
        .attr('width', iw).attr('height', ih)
        .style('fill', 'none').style('pointer-events', 'all')
        .on('mouseover', function () { focus.style('display', null); })
        .on('mouseout', function () { focus.style('display', 'none'); tipHide(); })
        .on('mousemove', function () {
          var hr = Math.max(1, Math.min(24, Math.round(x.invert(d3.mouse(this)[0]) + 0.5)));
          var h = day.hours[hr - 1];
          if (!h) return;
          focus.select('line').attr('x1', x(h.t)).attr('x2', x(h.t));
          var dep = (h.dbt !== null && h.dpt !== null) ? fmt1(h.dbt - h.dpt) + u : '—';
          tipShow('<b>' + dayLabel(day) + ' &middot; hour ' + hr + '</b><br>' +
                  'dry bulb ' + (h.dbt === null ? '—' : fmt1(h.dbt) + u) + '<br>' +
                  'dew point ' + (h.dpt === null ? '—' : fmt1(h.dpt) + u) + '<br>' +
                  'depression ' + dep);
          tipMove();
        });
    return svg;
  }

  global.EpwDashboard = {
    PALETTE:               PALETTE,
    UTCI_RAMP:             UTCI_RAMP,
    MONTHS:                MONTHS,
    MONTH_FULL:            MONTH_FULL,
    DAY_NAMES:             DAY_NAMES,
    DAY_ABBR:              DAY_ABBR,
    DAY_TYPE_LABEL:        DAY_TYPE_LABEL,
    cToF:                  cToF,
    buildRecords:          buildRecords,
    startDayOfWeek:        startDayOfWeek,
    dailyStats:            dailyStats,
    hourlyProfileByMonth:  hourlyProfileByMonth,
    monthlyDegreeDays:     monthlyDegreeDays,
    degreeDaysByTemp:      degreeDaysByTemp,
    occupiedFilter:        occupiedFilter,
    dayTypeFilter:         dayTypeFilter,
    dailySeries:           dailySeries,
    monthlyRepresentativeDays: monthlyRepresentativeDays,
    dayLabel:              dayLabel,
    drawRepresentativeDays: drawRepresentativeDays,
    drawDayDetail:         drawDayDetail,
    drawAnnualTimeseries:  drawAnnualTimeseries,
    drawDailyProfiles:     drawDailyProfiles,
    drawUTCIChart:         drawUTCIChart,
    drawUTCICategoryBars:  drawUTCICategoryBars,
    drawUTCISummary:       drawUTCISummary,
    drawMonthlyDegreeDays: drawMonthlyDegreeDays,
    drawDegreeDaysByTemp:  drawDegreeDaysByTemp
  };
})(window);
