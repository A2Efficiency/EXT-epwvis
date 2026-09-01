/*-------------------------------------------------------------------------
 * epwLocatorMap.js
 * US locator map showing where a weather station sits in the country.
 *
 * Renders an SVG with d3.geo.albersUsa (bundled with d3 v3, so Alaska and
 * Hawaii are placed as insets automatically). Geometry comes from the
 * US_GEO global in data/usGeo.js, so the map works offline and over file://
 * -- no tile server and no API key.
 *
 * Depends on: d3 v3, data/usGeo.js
 *-------------------------------------------------------------------------*/
(function (global) {
  'use strict';

  // albersUsa ships with a scale of 1070 tuned for a 960x500 canvas; every
  // other size is derived from that ratio so the whole country always fits.
  var REF_W = 960, REF_H = 500, REF_SCALE = 1070;

  var DEFAULTS = {
    width:        560,
    height:       340,
    landFill:     '#f4f5f0',   // brand lt2
    landStroke:   '#ffffff',
    homeFill:     '#cdeaee',   // light step of the brand teal ramp
    homeStroke:   '#00a3b4',   // brand accent3
    borderStroke: '#b5bab0',
    markerColor:  '#ff6600',   // brand accent1
    label:        '',
    showLabel:    true
  };

  /**
   * Ray-casting point-in-ring test in lon/lat space. Accurate enough to pick
   * out which state a station sits in; state polygons are small relative to
   * the projection so planar treatment is fine here.
   */
  function pointInRing(lon, lat, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1];
      var xj = ring[j][0], yj = ring[j][1];
      var intersects = ((yi > lat) !== (yj > lat)) &&
                       (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi);
      if (intersects) inside = !inside;
    }
    return inside;
  }

  /** True when the point falls inside a polygon (outer ring minus holes). */
  function pointInPolygon(lon, lat, rings) {
    if (!rings.length || !pointInRing(lon, lat, rings[0])) return false;
    for (var h = 1; h < rings.length; h++) {
      if (pointInRing(lon, lat, rings[h])) return false;   // inside a hole
    }
    return true;
  }

  /** Name of the state containing lon/lat, or null. */
  function findState(lon, lat, states) {
    for (var i = 0; i < states.features.length; i++) {
      var f = states.features[i], g = f.geometry;
      var polys = (g.type === 'Polygon') ? [g.coordinates] : g.coordinates;
      for (var p = 0; p < polys.length; p++) {
        if (pointInPolygon(lon, lat, polys[p])) return f.properties.name;
      }
    }
    return null;
  }

  /**
   * Render the locator map.
   *
   * @param {string|Element} container  selector or element to render into
   * @param {object} opts  { lat, lon, label, width, height, ... }
   * @returns {object} { svg, projected, stateName, inRange }
   */
  function render(container, opts) {
    var o = {};
    Object.keys(DEFAULTS).forEach(function (k) { o[k] = DEFAULTS[k]; });
    Object.keys(opts || {}).forEach(function (k) {
      if (opts[k] !== undefined && opts[k] !== null) o[k] = opts[k];
    });

    var sel = (typeof container === 'string') ? d3.select(container) : d3.select(container);
    sel.select('svg').remove();

    var svg = sel.append('svg')
        .attr('width', o.width)
        .attr('height', o.height)
        .attr('viewBox', '0 0 ' + o.width + ' ' + o.height)
        .attr('class', 'epw-locator-map');

    if (typeof global.US_GEO === 'undefined') {
      svg.append('text').attr('x', 12).attr('y', 24)
         .style('font-size', '12px').style('fill', '#c0392b')
         .text('data/usGeo.js not loaded');
      return { svg: svg, projected: null, stateName: null, inRange: false };
    }

    var lat = parseFloat(o.lat), lon = parseFloat(o.lon);
    var scale = REF_SCALE * Math.min(o.width / REF_W, o.height / REF_H);

    var projection = d3.geo.albersUsa()
        .scale(scale)
        .translate([o.width / 2, o.height / 2]);
    var path = d3.geo.path().projection(projection);

    var stateName = (isFinite(lat) && isFinite(lon))
        ? findState(lon, lat, global.US_GEO.states) : null;

    // --- Land: every state, with the station's own state picked out ---
    svg.append('g').attr('class', 'epw-map-states')
      .selectAll('path')
      .data(global.US_GEO.states.features)
      .enter().append('path')
        .attr('d', path)
        .style('fill', function (d) {
          return (stateName && d.properties.name === stateName) ? o.homeFill : o.landFill;
        })
        .style('stroke', o.landStroke)
        .style('stroke-width', 0.6);

    // --- The highlighted state redrawn on top so its outline is unclipped ---
    if (stateName) {
      svg.append('g').attr('class', 'epw-map-home')
        .selectAll('path')
        .data(global.US_GEO.states.features.filter(function (d) {
          return d.properties.name === stateName;
        }))
        .enter().append('path')
          .attr('d', path)
          .style('fill', 'none')
          .style('stroke', o.homeStroke)
          .style('stroke-width', 1.2);
    }

    // --- National outline ---
    svg.append('g').attr('class', 'epw-map-nation')
      .selectAll('path')
      .data(global.US_GEO.nation.features)
      .enter().append('path')
        .attr('d', path)
        .style('fill', 'none')
        .style('stroke', o.borderStroke)
        .style('stroke-width', 1);

    // --- Station marker ---
    // albersUsa returns null for anything outside the 50 states + DC.
    var xy = (isFinite(lat) && isFinite(lon)) ? projection([lon, lat]) : null;

    if (!xy) {
      svg.append('text')
          .attr('x', o.width / 2).attr('y', o.height - 10)
          .attr('text-anchor', 'middle')
          .style('font-size', '11px').style('fill', '#888')
          .text('Station outside US map extent');
      return { svg: svg, projected: null, stateName: stateName, inRange: false };
    }

    var marker = svg.append('g').attr('class', 'epw-map-marker')
        .attr('transform', 'translate(' + xy[0] + ',' + xy[1] + ')');

    marker.append('circle')
        .attr('r', 9)
        .style('fill', o.markerColor).style('fill-opacity', 0.18)
        .style('stroke', o.markerColor).style('stroke-opacity', 0.5)
        .style('stroke-width', 1);
    marker.append('circle')
        .attr('r', 4)
        .style('fill', o.markerColor)
        .style('stroke', '#ffffff').style('stroke-width', 1.4);

    if (o.showLabel && o.label) {
      // Flip the label to the left near the right edge so it never runs off.
      var flip   = xy[0] > o.width * 0.72;
      var dx     = flip ? -13 : 13;
      var anchor = flip ? 'end' : 'start';
      var g = marker.append('g').attr('class', 'epw-map-label');

      // Halo first, real text over it -- keeps the label readable on any fill
      // and survives SVG serialisation (paint-order is not widely supported).
      [true, false].forEach(function (isHalo) {
        g.append('text')
            .attr('x', dx).attr('y', 4)
            .attr('text-anchor', anchor)
            .style('font-family', '"Open Sans", Helvetica, Arial, sans-serif')
            .style('font-size', '12px')
            .style('font-weight', 'bold')
            .style('fill', isHalo ? '#ffffff' : '#1a1f16')
            .style('stroke', isHalo ? '#ffffff' : 'none')
            .style('stroke-width', isHalo ? 3.5 : 0)
            .style('stroke-linejoin', 'round')
            .text(o.label);
      });
    }

    return { svg: svg, projected: xy, stateName: stateName, inRange: true };
  }

  global.EpwLocatorMap = {
    render:      render,
    findState:   findState,
    _defaults:   DEFAULTS
  };
})(window);
