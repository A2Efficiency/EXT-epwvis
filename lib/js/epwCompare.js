/*-------------------------------------------------------------------------
 * epwCompare.js
 * Cross-location comparison charts for the A2E deck's summary slide.
 *
 * The per-location charts in epwDashboard.js answer "what is this climate
 * like". These two answer "how do these climates differ", which is a different
 * question and needs every location on one pair of axes:
 *
 *   drawLoadBalance()  back-to-back occupied HDD / CDD, one shared scale,
 *                      sorted by heating-to-cooling ratio. Shows that all of
 *                      these are heating-dominated but by very different
 *                      margins.
 *   drawDesignRange()  the ASHRAE 99.6% heating to 0.4% cooling span per
 *                      location, plus mean daily swing and mild-band hours.
 *                      Shows that winter design scatters while summer design
 *                      barely moves.
 *
 * Palette and type are epwDashboard's, so the summary slide sits in the same
 * deck as the per-location ones without a clash.
 *
 * Depends on: d3 v3, epwDashboard.js (for PALETTE)
 *-----------------------------------------------------------------------*/
(function (global) {
  'use strict';

  var P = (global.EpwDashboard && global.EpwDashboard.PALETTE) || {
    hdd: '#ff6600', cdd: '#00a3b4', tempBand: '#cdeaee', tempLine: '#007a88',
    ink: '#1a1f16', inkSoft: '#4a5245', inkMuted: '#7a8075',
    grid: '#e6e8e1', axis: '#b5bab0', surface: '#ffffff'
  };

  var FONT = '"Open Sans", "Helvetica Neue", Helvetica, Arial, sans-serif';
  var BAR_H = 15;          // thin marks; the skill's spec, not a chunky block
  var RADIUS = 4;          // rounded data-end only, square against the baseline

  function fmt(n) { return d3.format(',')(Math.round(n)); }

  /** Typographic minus, not a hyphen: these are temperatures, not compounds. */
  function temp(n, unit) {
    return String(Math.round(n)).replace('-', '−') + (unit || '');
  }

  /**
   * Left gutter wide enough for the longest location name, so long station
   * names are never clipped. Measured in the real font, floored at 168 px.
   * Both charts call this with the same rows, so their rows stay aligned.
   */
  function nameGutter(svg, rows) {
    var probe = svg.append('text').style('font-size', '11.5px');
    var w = 0;
    rows.forEach(function (d) {
      probe.text(d.name);
      w = Math.max(w, probe.node().getComputedTextLength());
    });
    probe.remove();
    return Math.max(168, Math.ceil(w) + 24);
  }

  /** "4.5 : 1 heating" or, when cooling dominates, "5.0 : 1 cooling". */
  function ratioLabel(d) {
    var r = d.hdd / Math.max(d.cdd, 1);
    return r >= 1 ? r.toFixed(1) + ' : 1 heating'
                  : (d.cdd / Math.max(d.hdd, 1)).toFixed(1) + ' : 1 cooling';
  }

  function svgRoot(sel, o) {
    d3.select(sel).selectAll('*').remove();
    // A viewBox matters here: epwDashboard.css caps figures at 100% width, and
    // without one a narrow container crops the chart instead of scaling it.
    return d3.select(sel).append('svg')
      .attr('width', o.width).attr('height', o.height)
      .attr('viewBox', '0 0 ' + o.width + ' ' + o.height)
      .attr('preserveAspectRatio', 'xMinYMin meet')
      .style('font-family', FONT)
      .style('background', P.surface);
  }

  function text(g, x, y, s, opts) {
    opts = opts || {};
    return g.append('text')
      .attr('x', x).attr('y', y)
      .attr('text-anchor', opts.anchor || 'start')
      .style('font-size', (opts.size || 11) + 'px')
      .style('font-weight', opts.weight || 'normal')
      .style('fill', opts.fill || P.ink)
      .text(s);
  }

  /**
   * A bar rounded on its data end only. `dir` is +1 (grows right) or -1 (left).
   * Drawn as a path so the baseline end stays square against the axis.
   */
  function barPath(x0, y, len, h, dir) {
    var r = Math.min(RADIUS, len);
    if (len <= 0.5) return 'M' + x0 + ',' + y + 'h0';
    if (dir > 0) {
      return 'M' + x0 + ',' + y
           + 'h' + (len - r)
           + 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + r
           + 'v' + (h - 2 * r)
           + 'a' + r + ',' + r + ' 0 0 1 ' + (-r) + ',' + r
           + 'h' + (-(len - r)) + 'z';
    }
    return 'M' + x0 + ',' + y
         + 'h' + (-(len - r))
         + 'a' + r + ',' + r + ' 0 0 0 ' + (-r) + ',' + r
         + 'v' + (h - 2 * r)
         + 'a' + r + ',' + r + ' 0 0 0 ' + r + ',' + r
         + 'h' + (len - r) + 'z';
  }

  function legend(g, x, y, items) {
    var cx = x;
    items.forEach(function (it) {
      g.append('rect').attr('x', cx).attr('y', y - 8)
        .attr('width', 10).attr('height', 10).attr('rx', 2)
        .style('fill', it.color);
      var t = text(g, cx + 15, y, it.label, { size: 11, fill: P.inkSoft });
      cx += 15 + t.node().getComputedTextLength() + 22;
    });
  }

  // ---------------------------------------------------------------------
  //  Chart 1 -- load balance
  // ---------------------------------------------------------------------
  /**
   * rows: [{ name, hdd, cdd }]  (occupied-hours degree days, already in the
   * deck's display units). o.unit is the degree-day unit label.
   *
   * Both sides share ONE scale in degree-days per pixel -- the two halves are
   * only sized differently so the plot is not half empty. Reading a heating bar
   * against a cooling bar is therefore valid, which is the whole point.
   */
  function drawLoadBalance(sel, rows, o) {
    o = o || {};
    var W = o.width || 1220, H = o.height || 300;
    // Header stack, top down: title, subtitle, legend -- each on its own line,
    // so a long subtitle can never land under the legend swatches.
    var m = { top: o.title ? 66 : 48, right: 16, bottom: 14, left: 168 };

    var data = rows.slice().sort(function (a, b) {
      return (a.hdd / Math.max(a.cdd, 1)) - (b.hdd / Math.max(b.cdd, 1));
    });

    var svg = svgRoot(sel, { width: W, height: H });
    var g = svg.append('g');
    m.left = nameGutter(svg, data);

    if (o.title) text(g, m.left, 18, o.title, { size: 14, weight: '600' });
    if (o.subtitle) {
      text(g, m.left, o.title ? 35 : 13, o.subtitle, { size: 10.5, fill: P.inkMuted });
    }
    legend(g, m.left, o.title ? 54 : 32, [
      { color: P.hdd, label: 'Heating degree days (occupied)' },
      { color: P.cdd, label: 'Cooling degree days (occupied)' }
    ]);

    var plotW = W - m.left - m.right;
    var plotH = H - m.top - m.bottom;
    var rowH = plotH / data.length;

    // One px-per-unit for both sides, then split the width by the two maxima.
    var maxH = d3.max(data, function (d) { return d.hdd; });
    var maxC = d3.max(data, function (d) { return d.cdd; });
    var labelPad = 58;                        // room for the value at each end
    var usable = plotW - 2 * labelPad;
    var k = usable / (maxH + maxC);           // px per degree-day
    var zeroX = m.left + labelPad + maxH * k;

    // Centre rule: the only axis this chart needs, since every bar is labelled.
    g.append('line')
      .attr('x1', zeroX).attr('x2', zeroX)
      .attr('y1', m.top - 4).attr('y2', m.top + plotH)
      .style('stroke', P.axis).style('stroke-width', 1);

    var row = g.selectAll('.cmp-row').data(data).enter().append('g')
      .attr('transform', function (d, i) {
        return 'translate(0,' + (m.top + i * rowH) + ')';
      });

    var yBar = function () { return (rowH - BAR_H) / 2 - 4; };

    row.append('path')
      .attr('d', function (d) {
        return barPath(zeroX - 1, yBar(), d.hdd * k, BAR_H, -1);
      })
      .style('fill', P.hdd);

    row.append('path')
      .attr('d', function (d) {
        return barPath(zeroX + 1, yBar(), d.cdd * k, BAR_H, 1);
      })
      .style('fill', P.cdd);

    // Direct labels: 12 bars is few enough that an axis would say less.
    row.append('text')
      .attr('x', function (d) { return zeroX - 6 - d.hdd * k; })
      .attr('y', yBar() + BAR_H - 2)
      .attr('text-anchor', 'end')
      .style('font-size', '11px').style('fill', P.ink)
      .text(function (d) { return fmt(d.hdd); });

    row.append('text')
      .attr('x', function (d) { return zeroX + 6 + d.cdd * k; })
      .attr('y', yBar() + BAR_H - 2)
      .style('font-size', '11px').style('fill', P.ink)
      .text(function (d) { return fmt(d.cdd); });

    // Name, and the ratio that sets the sort order.
    row.append('text')
      .attr('x', m.left - 14).attr('y', yBar() + BAR_H - 3)
      .attr('text-anchor', 'end')
      .style('font-size', '11.5px').style('fill', P.ink)
      .text(function (d) { return d.name; });

    row.append('text')
      .attr('x', m.left - 14).attr('y', yBar() + BAR_H + 11)
      .attr('text-anchor', 'end')
      .style('font-size', '10px').style('fill', P.inkMuted)
      .text(ratioLabel);

    return svg;
  }

  // ---------------------------------------------------------------------
  //  Chart 2 -- design temperature span
  // ---------------------------------------------------------------------
  /**
   * rows: [{ name, heat, cool, swing, freeHours }] in display units; heat/cool
   * are the published 99.6% / 0.4% design dry bulbs and may be null.
   *
   * One series, one colour: the bars are nominal categories, so a value ramp
   * would double-encode length as hue. The two numeric columns ride the same
   * rows so the location name is not printed a third time.
   */
  function drawDesignRange(sel, rows, o) {
    o = o || {};
    var W = o.width || 1220, H = o.height || 240;
    var m = { top: o.title ? 58 : 40, right: 16, bottom: 22, left: 168 };
    var COL_W = 150;                          // each of the two numeric columns
    var unit = o.unit || '';

    var data = rows.slice().sort(function (a, b) {
      return (a.hdd / Math.max(a.cdd, 1)) - (b.hdd / Math.max(b.cdd, 1));
    });

    var svg = svgRoot(sel, { width: W, height: H });
    var g = svg.append('g');
    m.left = nameGutter(svg, data);

    if (o.title) text(g, m.left, 18, o.title, { size: 14, weight: '600' });
    if (o.subtitle) {
      text(g, m.left, o.title ? 35 : 13, o.subtitle, { size: 10.5, fill: P.inkMuted });
    }

    var plotH = H - m.top - m.bottom;
    var rowH = plotH / data.length;
    var colsX = W - m.right - 2 * COL_W;
    var plotW = colsX - m.left - 24;

    var vals = [];
    data.forEach(function (d) {
      if (d.heat !== null && d.heat !== undefined) vals.push(d.heat);
      if (d.cool !== null && d.cool !== undefined) vals.push(d.cool);
    });
    var pad = 12;
    var x = d3.scale.linear()
      .domain([d3.min(vals) - pad, d3.max(vals) + pad])
      .range([m.left + 34, m.left + plotW - 34]);

    // Freezing is the one reference on this axis that changes a design choice.
    var freeze = o.isIP ? 32 : 0;
    if (freeze > x.domain()[0] && freeze < x.domain()[1]) {
      g.append('line')
        .attr('x1', x(freeze)).attr('x2', x(freeze))
        .attr('y1', m.top - 6).attr('y2', m.top + plotH)
        .style('stroke', P.axis).style('stroke-width', 1);
      text(g, x(freeze), m.top - 10, 'freezing', {
        size: 9.5, fill: P.inkMuted, anchor: 'middle'
      });
    }

    // Column headers.
    text(g, colsX + COL_W - 20, m.top - 10, 'Mean daily swing',
         { size: 10, fill: P.inkMuted, anchor: 'end' });
    text(g, colsX + 2 * COL_W - 20, m.top - 10, 'Occupied h, ' + (o.band || 'mild band'),
         { size: 10, fill: P.inkMuted, anchor: 'end' });

    var row = g.selectAll('.cmp-row').data(data).enter().append('g')
      .attr('transform', function (d, i) {
        return 'translate(0,' + (m.top + i * rowH) + ')';
      });

    var yBar = (rowH - BAR_H) / 2 - 2;

    row.append('text')
      .attr('x', m.left - 14).attr('y', yBar + BAR_H - 3)
      .attr('text-anchor', 'end')
      .style('font-size', '11.5px').style('fill', P.ink)
      .text(function (d) { return d.name; });

    row.each(function (d) {
      var r = d3.select(this);
      if (d.heat === null || d.heat === undefined ||
          d.cool === null || d.cool === undefined) {
        text(r, x(x.domain()[0]) , yBar + BAR_H - 3,
             'no published design conditions in this .stat',
             { size: 10.5, fill: P.inkMuted });
      } else {
        var x0 = x(d.heat), x1 = x(d.cool);
        r.append('rect')
          .attr('x', x0).attr('y', yBar)
          .attr('width', Math.max(x1 - x0, 1)).attr('height', BAR_H)
          .attr('rx', RADIUS)
          .style('fill', P.tempBand)
          .style('stroke', P.tempLine).style('stroke-width', 1.5);
        r.append('text')
          .attr('x', x0 - 7).attr('y', yBar + BAR_H - 2)
          .attr('text-anchor', 'end')
          .style('font-size', '11px').style('fill', P.ink)
          .text(temp(d.heat, unit));
        r.append('text')
          .attr('x', x1 + 7).attr('y', yBar + BAR_H - 2)
          .style('font-size', '11px').style('fill', P.ink)
          .text(temp(d.cool, unit));
      }

      r.append('text')
        .attr('x', colsX + COL_W - 20).attr('y', yBar + BAR_H - 2)
        .attr('text-anchor', 'end')
        .style('font-size', '11px').style('fill', P.ink)
        .text(d.swing === null || d.swing === undefined
              ? '—' : d.swing.toFixed(1) + unit);

      r.append('text')
        .attr('x', colsX + 2 * COL_W - 20).attr('y', yBar + BAR_H - 2)
        .attr('text-anchor', 'end')
        .style('font-size', '11px').style('fill', P.ink)
        .text(d.freeHours === null || d.freeHours === undefined
              ? '—' : fmt(d.freeHours));
    });

    // A light axis under the span bars; the end labels carry the precision.
    var axis = d3.svg.axis().scale(x).orient('bottom').ticks(6)
      .tickFormat(function (v) { return temp(v, unit); });
    var gx = g.append('g')
      .attr('transform', 'translate(0,' + (m.top + plotH + 2) + ')')
      .call(axis);
    gx.select('path').style('display', 'none');
    gx.selectAll('line').style('stroke', P.axis);
    gx.selectAll('text').style('font-size', '9.5px').style('fill', P.inkMuted);
    gx.selectAll('.tick').filter(function (v) {
      return x(v) > colsX - 30;
    }).style('display', 'none');

    return svg;
  }

  global.EpwCompare = {
    drawLoadBalance: drawLoadBalance,
    drawDesignRange: drawDesignRange
  };
})(window);
