/*-------------------------------------------------------------------------
 * epwGrid.js
 * Small-multiple charts for a "rows of cities x columns of metrics" slide.
 *
 * Every chart here is drawn for ONE location, but always on a domain shared
 * across the whole set (pass it in via o.yMax / o.yDomain). That is the point
 * of the grid: Seattle's degree-day bars must look small next to Great Falls',
 * not fill their box the way a per-chart autoscale would make them.
 *
 * Aggregation reuses EpwDashboard (buildRecords, monthlyDegreeDays) and
 * EpwOTC (UTCI base case), so these numbers are the numbers on the
 * per-location appendix slides.
 *
 * Depends on: d3 v3, epw2json.js, utci.js, epwOTC.js, epwDashboard.js, usGeo.js
 *-------------------------------------------------------------------------*/
(function (global) {
  'use strict';

  var D = global.EpwDashboard;
  var P = D.PALETTE;
  var FONT = '"Open Sans", Helvetica, Arial, sans-serif';
  var MONTHS = D.MONTHS;

  // Sized for a ~3.6in x 1.8in slide cell: 12px here is ~8.5pt on the slide.
  var TICK = 12, LABEL = 12.5;

  function fmtInt(n) { return d3.format(',d')(Math.round(n)); }
  function fmtT(n)   { return (n < 0 ? '−' : '') + Math.abs(Math.round(n)); }

  function newSvg(container, W, H) {
    var sel = d3.select(container);
    sel.select('svg').remove();
    return sel.append('svg').attr('width', W).attr('height', H)
        .attr('viewBox', '0 0 ' + W + ' ' + H)
        .attr('class', 'epw-chart').style('background', P.surface);
  }

  function txt(g, x, y, s, o) {
    o = o || {};
    return g.append('text').attr('x', x).attr('y', y)
        .attr('text-anchor', o.anchor || 'start')
        .style('font-family', FONT).style('font-size', (o.size || LABEL) + 'px')
        .style('font-weight', o.bold ? 'bold' : 'normal')
        .style('fill', o.color || P.inkSoft).text(s);
  }

  function styleAxis(g) {
    g.selectAll('path.domain').style('fill', 'none').style('stroke', P.axis);
    g.selectAll('line').style('stroke', P.axis);
    g.selectAll('text').style('font-family', FONT).style('font-size', TICK + 'px')
        .style('fill', P.inkMuted);
  }

  function gridLines(g, y, ticks, iw) {
    g.selectAll('line.grid').data(ticks).enter().append('line')
        .attr('x1', 0).attr('x2', iw).attr('y1', y).attr('y2', y)
        .style('stroke', P.grid).style('stroke-width', 1);
  }

  // ---------------------------------------------------------------------
  //  STATISTICS
  // ---------------------------------------------------------------------

  /**
   * Everything the grid and the summary table need for one location.
   * Temperatures in the unit of `records` (IP when built with isIP=true).
   * Percentiles are over all readable hours (8,760 for a clean TMYx year):
   * p10 is the dry bulb the coldest 10% of hours fall below, p90 the one the
   * hottest 10% rise above.
   */
  function locationStats(epw, records, hBase, cBase) {
    var temps = records.filter(function (r) { return r.dbt !== null && isFinite(r.dbt); })
                       .map(function (r) { return r.dbt; })
                       .sort(d3.ascending);
    var n = temps.length;
    var tail = Math.max(1, Math.round(n * 0.10));

    var monthly = d3.range(1, 13).map(function (m) {
      var v = records.filter(function (r) { return r.month === m && r.dbt !== null; })
                     .map(function (r) { return r.dbt; }).sort(d3.ascending);
      return {
        month: m,
        min: v[0], max: v[v.length - 1],
        p10: d3.quantile(v, 0.10), p50: d3.quantile(v, 0.50), p90: d3.quantile(v, 0.90)
      };
    });

    // Where the annual extremes happened, for the marker on the chart.
    var iMin = 0, iMax = 0;
    records.forEach(function (r, i) {
      if (r.dbt === null) return;
      if (records[iMin].dbt === null || r.dbt < records[iMin].dbt) iMin = i;
      if (records[iMax].dbt === null || r.dbt > records[iMax].dbt) iMax = i;
    });

    var dd = D.monthlyDegreeDays(records, hBase, cBase);

    var cases = global.EpwOTC.defaultCases();
    var utci = global.EpwOTC.buildCounts(
        global.EpwOTC.computeAllHours(epw, cases[0]), global.EpwOTC.allIndices(epw));
    var uTot = d3.sum(utci) || 1;
    function pct(ix) { return d3.sum(ix, function (i) { return utci[i]; }) / uTot * 100; }

    return {
      hours: n,
      min: temps[0], max: temps[n - 1],
      minMonth: records[iMin].month, maxMonth: records[iMax].month,
      p01: d3.quantile(temps, 0.01), p10: d3.quantile(temps, 0.10),
      p50: d3.quantile(temps, 0.50), p90: d3.quantile(temps, 0.90),
      p99: d3.quantile(temps, 0.99),
      mean: d3.mean(temps),
      meanColdest10: d3.mean(temps.slice(0, tail)),
      meanHottest10: d3.mean(temps.slice(n - tail)),
      monthly: monthly,
      dd: dd,
      hdd: Math.round(d3.sum(dd, function (d) { return d.hdd; })),
      cdd: Math.round(d3.sum(dd, function (d) { return d.cdd; })),
      hBase: hBase, cBase: cBase,
      utci: utci,
      utciColdPct:    pct([0, 1, 2, 3, 4]),
      utciCoolPct:    pct([5]),
      utciComfortPct: pct([6]),
      utciNoStressPct: pct([5, 6]),
      utciHeatPct:    pct([7, 8, 9, 10])
    };
  }

  // ---------------------------------------------------------------------
  //  CHART A -- UTCI distribution, cold -> hot
  // ---------------------------------------------------------------------

  /**
   * Columns over the 11 UTCI categories in physical order, so the shape of
   * the distribution reads at a glance: a marine climate piles up in the cool
   * middle, a continental one leans left. Every category keeps its slot even
   * when empty, so the columns line up between rows. y is % of hours, shared.
   */
  function drawUTCIDistribution(container, counts, o) {
    o = o || {};
    var W = o.width || 400, H = o.height || 200;
    var m = { top: 26, right: 8, bottom: 30, left: 36 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;
    var total = d3.sum(counts) || 1;
    var pcts = counts.map(function (c) { return c / total * 100; });
    var yMax = o.yMax || d3.max(pcts);

    var svg = newSvg(container, W, H);
    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');
    var x = d3.scale.ordinal().domain(d3.range(11)).rangeBands([0, iw], 0.16, 0.05);
    var y = d3.scale.linear().domain([0, yMax]).range([ih, 0]).nice(4);

    gridLines(g, y, y.ticks(4), iw);
    var ramp = D.UTCI_RAMP, names = global.EpwOTC.utciCatNames;

    pcts.forEach(function (p, i) {
      var bx = x(i), bw = x.rangeBand(), by = y(p);
      g.append('path').attr('d', barPath(bx, by, bw, ih - by, 3))
          .style('fill', ramp[i])
          .append('title').text(names[i] + ': ' + fmtInt(counts[i]) + ' h (' + p.toFixed(1) + '%)');
      if (p >= 0.5) {
        txt(g, bx + bw / 2, by - 4, p < 1 ? '<1' : Math.round(p) + '', {
          anchor: 'middle', size: 11.5, color: P.inkSoft, bold: i === 6 });
      }
    });

    var gy = g.append('g').call(d3.svg.axis().scale(y).orient('left').ticks(4)
        .tickFormat(function (d) { return d + '%'; }).tickSize(0).tickPadding(5));
    styleAxis(gy);
    gy.select('path.domain').remove();
    g.append('line').attr('x1', 0).attr('x2', iw).attr('y1', ih).attr('y2', ih)
        .style('stroke', P.axis);

    // Group brackets instead of 11 unreadable tick labels.
    [[0, 4, 'cold stress', P.cdd], [5, 6, 'no stress', '#4a8b2c'],
     [7, 10, 'heat stress', P.hdd]].forEach(function (b) {
      var x0 = x(b[0]) + 1, x1 = x(b[1]) + x.rangeBand() - 1;
      g.append('line').attr('x1', x0).attr('x2', x1).attr('y1', ih + 6).attr('y2', ih + 6)
          .style('stroke', b[3]).style('stroke-width', 2.5);
      txt(g, (x0 + x1) / 2, ih + 21, b[2], { anchor: 'middle', size: TICK, color: P.inkSoft });
    });

    // Headline across the top: the three shares that sum to 100.
    var s = o.stats;
    if (s) {
      var line = svg.append('text').attr('x', m.left).attr('y', 15)
          .style('font-family', FONT).style('font-size', LABEL + 'px').style('fill', P.inkSoft);
      [['Cold ', s.utciColdPct, P.inkSoft], ['  ·  No stress ', s.utciNoStressPct, P.inkSoft],
       ['  ·  Heat ', s.utciHeatPct, P.inkSoft]].forEach(function (t) {
        line.append('tspan').text(t[0]);
        line.append('tspan').style('font-weight', 'bold').style('fill', P.ink)
            .text(Math.round(t[1]) + '%');
      });
    }
    return svg;
  }

  function barPath(x, y, w, h, r) {
    if (h <= 0) return '';
    r = Math.min(r, w / 2, h);
    return 'M' + x + ',' + (y + h) + 'L' + x + ',' + (y + r) +
           'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
           'L' + (x + w - r) + ',' + y +
           'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) +
           'L' + (x + w) + ',' + (y + h) + 'Z';
  }

  // ---------------------------------------------------------------------
  //  CHART B -- monthly degree days on a shared scale
  // ---------------------------------------------------------------------

  function drawDegreeDaysCompact(container, s, o) {
    o = o || {};
    var W = o.width || 400, H = o.height || 200;
    var m = { top: 26, right: 8, bottom: 22, left: 40 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;
    var dd = s.dd;
    var yMax = o.yMax || d3.max(dd, function (d) { return Math.max(d.hdd, d.cdd); });

    var svg = newSvg(container, W, H);
    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');
    var x = d3.scale.ordinal().domain(MONTHS).rangeBands([0, iw], 0.22, 0.05);
    var xs = d3.scale.ordinal().domain(['hdd', 'cdd']).rangeBands([0, x.rangeBand()], 0);
    var y = d3.scale.linear().domain([0, yMax]).range([ih, 0]).nice(4);

    gridLines(g, y, y.ticks(4), iw);
    var bw = Math.max(1, xs.rangeBand() - 1);

    [['hdd', P.hdd, 'Heating'], ['cdd', P.cdd, 'Cooling']].forEach(function (k) {
      dd.forEach(function (d, i) {
        var bx = x(MONTHS[i]) + xs(k[0]), by = y(d[k[0]]);
        g.append('path').attr('d', barPath(bx, by, bw, ih - by, 2.5))
            .style('fill', k[1])
            .append('title').text(D.MONTH_FULL[i] + ' ' + k[2].toLowerCase() +
                                  ' degree days: ' + fmtInt(d[k[0]]));
      });
    });

    var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')')
        .call(d3.svg.axis().scale(x).orient('bottom').tickSize(0).tickPadding(5)
              .tickFormat(function (d) { return d.charAt(0); }));
    styleAxis(gx);
    var gy = g.append('g').call(d3.svg.axis().scale(y).orient('left').ticks(4)
        .tickFormat(d3.format(',d')).tickSize(0).tickPadding(5));
    styleAxis(gy);
    gy.select('path.domain').remove();

    // Annual totals double as the legend: swatch + series name + number.
    var hx = m.left;
    [['HDD' + s.hBase, s.hdd, P.hdd], ['CDD' + s.cBase, s.cdd, P.cdd]].forEach(function (k) {
      svg.append('rect').attr('x', hx).attr('y', 6).attr('width', 11).attr('height', 11)
          .attr('rx', 2).style('fill', k[2]);
      var t = svg.append('text').attr('x', hx + 16).attr('y', 16)
          .style('font-family', FONT).style('font-size', LABEL + 'px').style('fill', P.inkSoft);
      t.append('tspan').text(k[0] + ' ');
      t.append('tspan').style('font-weight', 'bold').style('fill', P.ink).text(fmtInt(k[1]));
      hx += 16 + (k[0].length + String(fmtInt(k[1])).length + 1) * 7.6 + 18;
    });
    return svg;
  }

  // ---------------------------------------------------------------------
  //  CHART C -- monthly temperature range with the 10% tails
  // ---------------------------------------------------------------------

  /**
   * Per month: a thin bar from the coldest to the hottest hour, a thick bar
   * over the middle 80% of hours (p10..p90), a tick at the median. Two dashed
   * lines carry the ANNUAL p10 / p90 -- the threshold the coldest and hottest
   * 10% of the year's hours cross -- and the annual extremes are marked where
   * they happened. y domain shared across the set.
   */
  function drawTempExtremes(container, s, o) {
    o = o || {};
    var W = o.width || 400, H = o.height || 200;
    var m = { top: 16, right: 64, bottom: 22, left: 34 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;
    var dom = o.yDomain || [s.min, s.max];
    var unit = o.unit || '°F';

    var svg = newSvg(container, W, H);
    var g = svg.append('g').attr('transform', 'translate(' + m.left + ',' + m.top + ')');
    var x = d3.scale.ordinal().domain(d3.range(1, 13)).rangeBands([0, iw], 0.25, 0.1);
    var y = d3.scale.linear().domain(dom).range([ih, 0]);
    // Every 20 degrees: d3's ticks(5) jumps to 50s once the shared span passes ~140.
    var ticks = d3.range(Math.ceil(dom[0] / 20) * 20, dom[1] + 1, 20);

    gridLines(g, y, ticks, iw);
    if (dom[0] < 32 && dom[1] > 32) {
      g.append('line').attr('x1', 0).attr('x2', iw).attr('y1', y(32)).attr('y2', y(32))
          .style('stroke', P.axis).style('stroke-width', 1);
    }

    var COLD = P.tempLine, HOT = P.tempAccent;

    // Annual 10% / 90% thresholds, under the bars.
    [[s.p10, COLD, 'coldest 10%'], [s.p90, HOT, 'hottest 10%']].forEach(function (k) {
      g.append('line').attr('x1', 0).attr('x2', iw).attr('y1', y(k[0])).attr('y2', y(k[0]))
          .style('stroke', k[1]).style('stroke-width', 1.5).style('stroke-dasharray', '5,3');
    });

    s.monthly.forEach(function (mo) {
      var cx = x(mo.month) + x.rangeBand() / 2, bw = x.rangeBand();
      g.append('rect').attr('x', cx - 2).attr('width', 4)
          .attr('y', y(mo.max)).attr('height', Math.max(1, y(mo.min) - y(mo.max)))
          .attr('rx', 2).style('fill', P.tempBand);
      g.append('rect').attr('x', cx - bw / 2).attr('width', bw)
          .attr('y', y(mo.p90)).attr('height', Math.max(1, y(mo.p10) - y(mo.p90)))
          .attr('rx', 2.5).style('fill', '#5fb8c3')
          .append('title').text(D.MONTH_FULL[mo.month - 1] + ': min ' + fmtT(mo.min) +
              ', 10% ' + fmtT(mo.p10) + ', median ' + fmtT(mo.p50) + ', 90% ' +
              fmtT(mo.p90) + ', max ' + fmtT(mo.max) + unit);
      g.append('line').attr('x1', cx - bw / 2).attr('x2', cx + bw / 2)
          .attr('y1', y(mo.p50)).attr('y2', y(mo.p50))
          .style('stroke', P.ink).style('stroke-width', 1.5);
    });

    // Annual extremes, marked in the month they occurred.
    [[s.min, s.minMonth, COLD, 1], [s.max, s.maxMonth, HOT, -1]].forEach(function (k) {
      var cx = x(k[1]) + x.rangeBand() / 2, cy = y(k[0]);
      g.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 3.5)
          .style('fill', k[2]).style('stroke', P.surface).style('stroke-width', 1.5);
      // Above/below the dot when there is room, beside it when an axis is close.
      var ty = cy + (k[3] > 0 ? 15 : -7);
      var side = ty > ih - 2 || ty < 2;
      txt(g, side ? cx + 7 : cx, side ? cy + 4 : ty, fmtT(k[0]) + '°', {
        anchor: side ? 'start' : 'middle', size: LABEL, bold: true, color: P.ink })
        .style('paint-order', 'stroke').style('stroke', P.surface).style('stroke-width', '3px');
    });

    // Right-hand labels for the dashed thresholds; nudge apart if they collide.
    var ly = [y(s.p10), y(s.p90)];
    if (ly[0] - ly[1] < 30) { var mid = (ly[0] + ly[1]) / 2; ly = [mid + 15, mid - 15]; }
    [[s.p10, COLD, '10%', ly[0]], [s.p90, HOT, '90%', ly[1]]].forEach(function (k) {
      txt(g, iw + 6, k[3] - 1, k[2], { size: TICK, color: P.inkMuted });
      txt(g, iw + 6, k[3] + 12, fmtT(k[0]) + '°F', { size: LABEL, bold: true, color: k[1] });
    });

    var gx = g.append('g').attr('transform', 'translate(0,' + ih + ')')
        .call(d3.svg.axis().scale(x).orient('bottom').tickSize(0).tickPadding(5)
              .tickFormat(function (d) { return MONTHS[d - 1].charAt(0); }));
    styleAxis(gx);
    gx.select('path.domain').style('stroke', P.axis);
    var gy = g.append('g').call(d3.svg.axis().scale(y).orient('left').tickValues(ticks)
        .tickFormat(function (d) { return fmtT(d) + '°'; }).tickSize(0).tickPadding(5));
    styleAxis(gy);
    gy.select('path.domain').remove();
    return svg;
  }

  // ---------------------------------------------------------------------
  //  MAP -- the study region, every station placed
  // ---------------------------------------------------------------------

  var LABEL_SIDE = {
    'seattle-tacoma-intl-ap': 'left', 'portland-intl-ap': 'left',
    'eugene-ap-sweet-field': 'below', 'boise-ap-gowen-field-angb': 'right',
    'spokane-intl-ap': 'right', 'denver-intl-ap': 'right',
    'missoula-intl-ap': 'left', 'great-falls': 'right', 'helena-rgnl-ap': 'below',
    'redmond-muni-ap-roberts-field': 'right', 'yakima-af-mcallister-field': 'right'
  };

  /**
   * sites: [{ slug, short, lat, lon, zone, color, roleKind }]
   * roleKind: proposed (filled, large) | doe (diamond) | other (open circle)
   */
  function drawRegionMap(container, sites, o) {
    o = o || {};
    var W = o.width || 760, H = o.height || 560;
    var svg = newSvg(container, W, H);
    var feats = global.US_GEO.states.features;
    var NEEA = { Washington: 1, Oregon: 1, Idaho: 1, Montana: 1 };
    var FIT = { Washington: 1, Oregon: 1, Idaho: 1, Montana: 1, Colorado: 1, Wyoming: 1 };

    var proj = d3.geo.albers().rotate([112, 0]).center([0, 43.5])
        .parallels([40, 48]).scale(1).translate([0, 0]);
    var path = d3.geo.path().projection(proj);
    var fitF = { type: 'FeatureCollection',
                 features: feats.filter(function (f) { return FIT[f.properties.name]; }) };
    var b = path.bounds(fitF);
    var sc = 0.94 / Math.max((b[1][0] - b[0][0]) / W, (b[1][1] - b[0][1]) / H);
    proj.scale(sc).translate([W / 2 - sc * (b[0][0] + b[1][0]) / 2,
                              H / 2 - sc * (b[0][1] + b[1][1]) / 2]);

    svg.append('g').selectAll('path').data(feats).enter().append('path')
        .attr('d', path)
        .style('fill', function (d) { return NEEA[d.properties.name] ? '#e8ebe2' : '#f7f8f4'; })
        .style('stroke', function (d) { return NEEA[d.properties.name] ? '#9aa095' : '#d3d6cd'; })
        .style('stroke-width', function (d) { return NEEA[d.properties.name] ? 1.2 : 0.8; });

    // State names, quietly, at the centroid.
    feats.forEach(function (f) {
      if (!FIT[f.properties.name] && !{ Utah: 1, Nevada: 1 }[f.properties.name]) return;
      var c = path.centroid(f);
      if (!isFinite(c[0]) || c[0] < 10 || c[0] > W - 10 || c[1] < 10 || c[1] > H - 10) return;
      var dy = { Idaho: 95, Montana: -40, Oregon: 40, Washington: -45, Colorado: 30 }[f.properties.name] || 0;
      var dx = { Washington: 10 }[f.properties.name] || 0;
      txt(svg, c[0] + dx, c[1] + dy, f.properties.name.toUpperCase(), {
        anchor: 'middle', size: 13, color: NEEA[f.properties.name] ? '#8a9085' : '#b5bab0' })
        .style('letter-spacing', '2px');
    });

    sites.forEach(function (s) {
      var p = proj([s.lon, s.lat]);
      if (!p) return;
      var gg = svg.append('g').attr('transform', 'translate(' + p[0] + ',' + p[1] + ')')
          .attr('class', 'site').attr('data-slug', s.slug);
      if (s.roleKind === 'doe') {
        gg.append('rect').attr('x', -7).attr('y', -7).attr('width', 14).attr('height', 14)
            .attr('transform', 'rotate(45)').style('fill', s.color)
            .style('stroke', P.surface).style('stroke-width', 2);
      } else if (s.roleKind === 'proposed') {
        gg.append('circle').attr('r', 10).style('fill', s.color)
            .style('stroke', P.surface).style('stroke-width', 2.5);
      } else {
        gg.append('circle').attr('r', 6.5).style('fill', P.surface)
            .style('stroke', s.color).style('stroke-width', 3);
      }
      var side = LABEL_SIDE[s.slug] || 'right';
      var pos = { right: [15, 5, 'start'], left: [-15, 5, 'end'],
                  below: [0, 27, 'middle'], above: [0, -15, 'middle'] }[side];
      var t = txt(gg, pos[0], pos[1], s.short, {
        anchor: pos[2], size: 16, bold: s.roleKind === 'proposed', color: P.ink });
      // Halo so labels stay legible over borders.
      t.style('paint-order', 'stroke').style('stroke', P.surface)
       .style('stroke-width', '4px').style('stroke-linejoin', 'round');
    });
    return svg;
  }

  global.EpwGrid = {
    locationStats: locationStats,
    drawUTCIDistribution: drawUTCIDistribution,
    drawDegreeDaysCompact: drawDegreeDaysCompact,
    drawTempExtremes: drawTempExtremes,
    drawRegionMap: drawRegionMap
  };
})(window);
