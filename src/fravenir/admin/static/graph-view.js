/* A typed graph projection: filtering, neighborhoods and the canvas share one model. */
class GraphModel {
  constructor(elements) {
    this.nodes = elements.nodes.map(n => n.data);
    this.edges = elements.edges.map(e => e.data);
  }

  project(filters, predicate = '') {
    let nodes = this.nodes.filter(n => filters.type[n.type] !== false && (
      n.type !== 'episode' || (filters.kind[n.kind] !== false
        && n.importance >= filters.importance)));
    let ids = new Set(nodes.map(n => n.id));
    let edges = this.edges.filter(e => ids.has(e.source) && ids.has(e.target)
      && filters.type[e.type] !== false && (!predicate || e.predicate === predicate));
    if (filters.degree > 0) {
      const degrees = new Map();
      edges.forEach(e => {
        degrees.set(e.source, (degrees.get(e.source) || 0) + 1);
        degrees.set(e.target, (degrees.get(e.target) || 0) + 1);
      });
      nodes = nodes.filter(n => (degrees.get(n.id) || 0) >= filters.degree);
      ids = new Set(nodes.map(n => n.id));
      edges = edges.filter(e => ids.has(e.source) && ids.has(e.target));
    }
    return { nodes, edges };
  }

  matches(nodes, query) {
    const normalize = s => String(s || '').normalize('NFKC').toLowerCase();
    const tokens = normalize(query).trim().split(/\s+/).filter(Boolean);
    return tokens.length ? nodes.filter(n => tokens.every(t =>
      normalize(`${n.search_text || n.label} ${n.type} ${n.id}`).includes(t))) : [];
  }

  neighborhood(projected, seeds, hops, direction = 'both') {
    const ids = new Set(seeds);
    let frontier = new Set(seeds);
    for (let i = 0; i < hops; i++) {
      const next = new Set();
      projected.edges.forEach(e => {
        if (direction !== 'incoming' && frontier.has(e.source) && !ids.has(e.target)) next.add(e.target);
        if (direction !== 'outgoing' && frontier.has(e.target) && !ids.has(e.source)) next.add(e.source);
      });
      next.forEach(id => ids.add(id));
      frontier = next;
    }
    return {
      nodes: projected.nodes.filter(n => ids.has(n.id)),
      edges: projected.edges.filter(e => ids.has(e.source) && ids.has(e.target)),
    };
  }
}

class GraphView {
  constructor(elements, state, onDetail) {
    this.state = state;
    this.onDetail = onDetail;
    this.model = new GraphModel(elements);
    this.predicate = '';
    this.direction = 'both';
    this.isolate = true;
    this.layout = 'fcose';
    this.cy = cytoscape({
      container: document.getElementById('cy'), elements, minZoom: 0.04, maxZoom: 4,
      layout: { name: 'preset' },
      style: [
        { selector: 'node', style: {
          label: 'data(label)', color: '#e6edf3', 'font-size': 16,
          'text-wrap': 'wrap', 'text-overflow-wrap': 'anywhere',
          'text-max-width': 120, 'text-valign': 'bottom',
          'text-margin-y': 7, 'text-background-color': '#161b22',
          'text-background-opacity': 0.85, 'text-background-padding': 3,
          'background-color': '#58a6ff', width: 28, height: 28,
          'border-width': 1.5, 'border-color': '#a5cfff',
        } },
        { selector: 'node[kind="state"]', style: { 'background-color': '#7ED321' } },
        { selector: 'node[kind="emo"]', style: { 'background-color': '#ef5872' } },
        { selector: 'node[type="entity"]', style: { shape: 'diamond', 'background-color': '#f5a623', width: 42, height: 42 } },
        { selector: 'node[type="entity"][entity_type="person"][!is_self]', style: { 'background-color': '#9013FE' } },
        { selector: 'node[type="entity"][entity_type="place"][!is_self]', style: { 'background-color': '#8B572A' } },
        { selector: 'node[type="entity"][entity_type="concept"][!is_self]', style: { 'background-color': '#50E3C2' } },
        { selector: 'node[type="thread"]', style: { shape: 'round-rectangle', 'background-color': '#a371f7', width: 46, height: 30 } },
        { selector: 'node[type="post"]', style: { shape: 'rectangle', 'background-color': '#50c8bc' } },
        { selector: 'edge', style: {
          'curve-style': 'bezier', width: 'mapData(strength, 0, 1, 1, 2.5)',
          'line-color': '#72849a', 'target-arrow-color': '#72849a',
          'target-arrow-shape': 'triangle', 'arrow-scale': 1,
          'font-size': 11, color: '#c9d1d9', 'text-rotation': 'autorotate',
          'text-background-color': '#161b22', 'text-background-opacity': 0.95,
          'text-background-padding': 3, 'text-margin-y': -9,
        } },
        { selector: 'edge[predicate="part_of"]', style: { 'line-color': '#9d83ce', 'target-arrow-color': '#9d83ce' } },
        { selector: 'edge[predicate="derived_from"]', style: { 'line-color': '#50c8bc', 'target-arrow-color': '#50c8bc' } },
        { selector: 'edge[predicate="related_to"]', style: { 'line-style': 'dashed' } },
        { selector: '[!is_active]', style: { opacity: 0.4, 'line-style': 'dashed' } },
        { selector: '.hidden', style: { display: 'none' } },
        { selector: '.dimmed', style: { opacity: 0.08, 'text-opacity': 0 } },
        { selector: 'node.overview', style: { label: '' } },
        { selector: 'node.match, node:selected', style: { label: 'data(label)', 'border-width': 4, 'border-color': '#ffab70', 'z-index': 20 } },
        { selector: 'edge.inspect', style: { label: 'data(predicate)', width: 3, 'line-color': '#ffab70', 'target-arrow-color': '#ffab70', 'z-index': 15 } },
      ],
    });
    this.cy.on('tap', 'node', e => this.select(e.target.id()));
    this.cy.on('tap', 'edge', e => {
      this.cy.edges().removeClass('inspect');
      e.target.addClass('inspect');
      this.onDetail(e.target.id(), 'relation');
    });
    this.cy.on('tap', e => {
      if (e.target === this.cy) this.clearFocus();
    });
    this.cy.on('zoom', () => this.updateLabels());
    this.bindControls();
    this.populatePredicates();
  }

  bindControls() {
    const on = (id, event, fn) => document.getElementById(id).addEventListener(event, fn);
    on('graph-fit', 'click', () => this.fit());
    on('graph-reflow', 'click', () => this.runLayout());
    on('graph-overview', 'click', () => {
      this.state.search.query = '';
      document.getElementById('search-input').value = '';
      document.getElementById('search-clear').hidden = true;
      this.clearFocus();
    });
    on('graph-layout', 'change', e => { this.layout = e.target.value; this.runLayout(); });
    on('graph-predicate', 'change', e => { this.predicate = e.target.value; this.refresh(true); });
    on('graph-direction', 'change', e => { this.direction = e.target.value; this.refresh(true); });
    on('graph-hops', 'change', e => { this.state.focus.hops = Number(e.target.value); this.refresh(true); });
    on('graph-isolate', 'change', e => { this.isolate = e.target.checked; this.refresh(true); });
    document.addEventListener('click', e => {
      const button = e.target.closest('[data-graph-node]');
      if (button) this.select(button.dataset.graphNode);
      const relation = e.target.closest('[data-graph-edge]');
      if (relation) {
        this.cy.edges().removeClass('inspect');
        this.cy.getElementById(relation.dataset.graphEdge).addClass('inspect');
        this.onDetail(relation.dataset.graphEdge, 'relation');
      }
    });
    new ResizeObserver(() => this.fit()).observe(document.getElementById('cy'));
  }

  populatePredicates() {
    const select = document.getElementById('graph-predicate');
    select.replaceChildren(new Option('すべての関係', ''));
    const counts = new Map();
    this.model.edges.forEach(e => counts.set(e.predicate, (counts.get(e.predicate) || 0) + 1));
    [...counts].sort(([a], [b]) => a.localeCompare(b)).forEach(([p, n]) =>
      select.add(new Option(`${p} (${n})`, p)));
    if (!counts.has(this.predicate)) this.predicate = '';
    select.value = this.predicate;
  }

  replace(elements) {
    this.cy.elements().remove();
    this.cy.add(elements);
    this.model = new GraphModel(elements);
    this.populatePredicates();
    this.state.focus.nodeId = null;
    this.state.selected = null;
    document.getElementById('detail-panel').replaceChildren();
    this.refresh(true);
  }

  select(id) {
    if (!this.cy.getElementById(id).length) return;
    this.state.focus.nodeId = id;
    this.cy.$(':selected').unselect();
    this.cy.getElementById(id).select();
    this.refresh(true);
    this.onDetail(id);
  }

  clearFocus() {
    this.state.focus.nodeId = null;
    this.state.selected = null;
    this.cy.$(':selected').unselect();
    document.getElementById('popover').hidden = true;
    document.getElementById('detail-panel').replaceChildren();
    this.refresh(true);
  }

  refresh(reflow = false) {
    const projected = this.model.project(this.state.filters, this.predicate);
    const matches = this.model.matches(projected.nodes, this.state.search.query);
    const focus = this.state.focus.nodeId;
    const focused = projected.nodes.some(n => n.id === focus);
    const searching = Boolean(this.state.search.query.trim());
    const seeds = focused ? [focus] : matches.map(n => n.id);
    const local = focused || searching;
    this.local = local;
    const visible = local ? this.model.neighborhood(projected, seeds, this.state.focus.hops, this.direction) : projected;
    const shown = this.isolate && local ? visible : projected;
    const ids = new Set([...shown.nodes, ...shown.edges].map(n => n.id));
    const nearIds = new Set([...visible.nodes, ...visible.edges].map(n => n.id));
    this.cy.batch(() => {
      this.cy.elements().forEach(e => {
        e.toggleClass('hidden', !ids.has(e.id()));
        e.toggleClass('dimmed', local && !nearIds.has(e.id()));
      });
      this.cy.nodes().removeClass('match');
      matches.forEach(n => this.cy.getElementById(n.id).addClass('match'));
      this.cy.edges().removeClass('inspect');
      if (focused) this.cy.getElementById(focus).connectedEdges().filter(e => !e.hasClass('hidden')).addClass('inspect');
    });
    document.getElementById('graph-status').textContent =
      `${shown.nodes.length} / ${this.model.nodes.length} ノード · ${shown.edges.length} / ${this.model.edges.length} 関係` +
      (local ? ` · ${this.state.focus.hops} ホップ` : ' · 全体表示');
    document.getElementById('graph-empty').hidden = shown.nodes.length > 0;
    if (this.state.selected) {
      document.querySelectorAll('#detail-panel .graph-connections, #popover .graph-connections')
        .forEach(el => { el.outerHTML = this.detailLinks(this.state.selected); });
    }
    const results = document.getElementById('graph-results');
    results.replaceChildren();
    if (searching) {
      const count = document.createElement('p');
      count.textContent = `${matches.length} 件一致（本文全体を検索）`;
      results.append(count);
      matches.slice(0, 30).forEach(n => {
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.graphNode = n.id;
        button.textContent = `${n.id} · ${n.label}`;
        results.append(button);
      });
    } else {
      const heading = document.createElement('p');
      heading.textContent = '接続の多いノードから辿る';
      results.append(heading);
      const degree = new Map();
      projected.edges.forEach(e => {
        degree.set(e.source, (degree.get(e.source) || 0) + 1);
        degree.set(e.target, (degree.get(e.target) || 0) + 1);
      });
      [...projected.nodes].filter(n => degree.has(n.id))
        .sort((a, b) => degree.get(b.id) - degree.get(a.id)).slice(0, 6).forEach(n => {
          const button = document.createElement('button');
          button.type = 'button'; button.dataset.graphNode = n.id;
          button.textContent = `${n.label} · ${degree.get(n.id)} 接続`;
          results.append(button);
        });
    }
    if (reflow) this.runLayout();
    else this.updateLabels();
  }

  updateLabels() {
    const zoom = this.cy.zoom();
    this.cy.nodes().toggleClass('overview', !this.local && zoom < 0.65);
  }

  fit() {
    const visible = this.cy.elements().filter(e => !e.hasClass('hidden'));
    if (visible.length) { this.cy.resize(); this.cy.fit(visible, 50); this.updateLabels(); }
  }

  runLayout() {
    if (this.runningLayout) this.runningLayout.stop();
    const visible = this.cy.elements().filter(e => !e.hasClass('hidden'));
    if (!visible.nodes().length) return;
    const k = Math.sqrt(this.state.spread / 3);
    this.runningLayout = visible.layout({
      name: this.layout, animate: false, randomize: true, fit: true, padding: 50,
      quality: 'default', nodeDimensionsIncludeLabels: true,
      idealEdgeLength: 60 * k, nodeSeparation: 20 * k,
      nodeRepulsion: 3500, gravity: 0.25, packComponents: true,
      directed: true, spacingFactor: 1.2,
      stop: () => this.updateLabels(),
    });
    this.runningLayout.run();
  }

  detailLinks(id) {
    const data = this.cy.getElementById(id);
    if (!data.length) return '';
    const escape = escapeHtml;
    const button = n => `<button type="button" data-graph-node="${escape(n.id())}">${escape(n.data('label'))}</button>`;
    if (data.isEdge()) return `<section class="graph-connections"><h4>関係を辿る</h4>${button(data.source())}<p>→ ${escape(data.data('predicate'))} →</p>${button(data.target())}</section>`;
    const edges = data.connectedEdges().filter(e => !e.hasClass('hidden'));
    return `<section class="graph-connections"><h4>接続先 (${edges.length})</h4>` + edges.map(e => {
      const outgoing = e.source().id() === id;
      const other = outgoing ? e.target() : e.source();
      return `<div><button type="button" data-graph-edge="${escape(e.id())}">${outgoing ? '→' : '←'} ${escape(e.data('predicate'))} · #${e.data('relation_id')}</button>${button(other)}</div>`;
    }).join('') + '</section>';
  }
}

if (typeof module !== 'undefined') module.exports = { GraphModel };
