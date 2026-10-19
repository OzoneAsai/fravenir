/* fravenir admin UI — vanilla JS */

// ─── Theme constants ────────────────────────────────────────────────────────
const THEMES = {
  dark: {
    nodeText: '#e6edf3',
    mentions: '#8b949e',
    relation: '#c9d1d9',
  },
  light: {
    nodeText: '#1f2328',
    mentions: '#C0C0C0',
    relation: '#333',
  },
};

// ─── Util ───────────────────────────────────────────────────────────────────
// SEC-1 HIGH-5-1: LLM 出力 / DB 文字列を innerHTML 経路に流す前に必ず通す。
// バッチ③ MEDIUM-2 の表示側責務をフロント側で担保する。
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ─── State ──────────────────────────────────────────────────────────────────
const SPREAD_DEFAULT = 3.0;
const state = {
  scope: 'active',
  surface: new URLSearchParams(window.location.search).get('surface') || localStorage.getItem('admin_surface') || 'graph',
  view: localStorage.getItem('admin_view') || 'panel',
  theme: localStorage.getItem('admin_theme') || 'dark',
  spread: parseFloat(localStorage.getItem('admin_spread')) || SPREAD_DEFAULT,
  filters: {
    kind: { facts: true, state: true, emo: true },
    type: { episode: true, entity: true, relation: true, mentions: true },
    importance: 1,
    degree: 0,
  },
  search: { query: '', hops: 1 },
  focus: { nodeId: null, hops: 1 },
  selected: null,
  graphData: null,
  stats: null,
  cy: null,
  board: {
    author: localStorage.getItem('board_author') || 'admin',
    spaces: [],
    threads: [],
    thread: null,
    selectedSpaceId: null,
    selectedThreadId: null,
    threadStatus: 'open',
    trashMode: false,
    trashItems: [],
  },
};

// ─── API ────────────────────────────────────────────────────────────────────
async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${body ? ' — ' + body : ''}`);
  }
  return res.json();
}

async function apiJson(path, method, payload) {
  return api(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ─── Graph canvas ───────────────────────────────────────────────────────────
let graphView = null;
function initCytoscape(elements) {
  graphView = new GraphView(elements, state, showDetail);
  return graphView.cy;
}
function runLayout() { graphView?.runLayout(); }
function applyFilters() { graphView?.refresh(true); }
function applyHighlight() { graphView?.refresh(true); }
function applyFocus() { graphView?.refresh(true); }
let searchTimer = null;
function setSearchQuery(q) {
  state.search.query = q;
  state.focus.nodeId = null;
  document.getElementById('search-clear').hidden = !q;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(applyHighlight, 150);
}
let spreadTimer = null;
function setSpread(v) {
  state.spread = v;
  localStorage.setItem('admin_spread', String(v));
  document.getElementById('spread-value').textContent = v.toFixed(1);
  clearTimeout(spreadTimer);
  spreadTimer = setTimeout(runLayout, 300);
}
function applyGraphTheme() {
  if (!state.cy) return;
  const light = state.theme === 'light';
  state.cy.style().selector('node').style('color', light ? '#1f2328' : '#e6edf3')
    .style('text-background-color', light ? '#ffffff' : '#161b22')
    .selector('edge').style('color', light ? '#1f2328' : '#c9d1d9')
    .style('text-background-color', light ? '#ffffff' : '#161b22').update();
}

// ─── Stats Bar ──────────────────────────────────────────────────────────────
function renderStatsBar() {
  const s = state.stats;
  if (!s) return;
  const parts = [];

  const makeBadge = (name, value, warn, modal) => {
    const cls = warn ? 'stat-item stat-warning' : 'stat-item';
    const click = modal ? ' clickable' : '';
    const data = modal ? ` data-modal="${modal}"` : '';
    return `<span class="${cls}${click}"${data}><span class="stat-name">${name}</span><span class="stat-value">${value}</span></span>`;
  };

  parts.push(makeBadge('Episodes', s.episodes.active));
  parts.push(makeBadge('Entities', s.entities.active));
  parts.push(makeBadge('Relations', s.relations.active));

  const mergeWarn = s.merge_candidates.pending > 0;
  parts.push(makeBadge('Merge', s.merge_candidates.pending, mergeWarn, 'merge'));

  if (s.doc_status_failed > 0) {
    parts.push(makeBadge('Failed', '⚠ ' + s.doc_status_failed, true, 'failed'));
  }

  const orphanTotal = (s.orphans.episodes || 0) + (s.orphans.entities || 0);
  if (orphanTotal > 0) {
    parts.push(makeBadge('Orphans', orphanTotal, false, 'orphan'));
  }

  const target = document.getElementById('stats-items') || document.getElementById('stats-bar');
  target.innerHTML = parts.join('');
}

// ─── Detail rendering ───────────────────────────────────────────────────────
function renderDetail(data) {
  if (!data) return '<div class="empty-state">データがありません</div>';

  const rows = [];
  const pushRow = (label, value, wrap) => {
    const v = value === null || value === undefined ? '—' : String(value);
    rows.push(`<div class="detail-row"><span class="detail-label">${label}</span><span class="detail-value ${wrap ? 'wrap' : ''}">${escapeHtml(v)}</span></div>`);
  };

  if (data.content !== undefined) {
    // episode
    pushRow('ID', data.id);
    pushRow('Type', 'episode');
    pushRow('Kind', data.kind);
    pushRow('Importance', data.importance);
    pushRow('Content', data.content, true);
    pushRow('Session', data.session_id);
    pushRow('Valid from', data.valid_from);
    pushRow('Valid to', data.valid_to);
    pushRow('Supersedes', data.supersedes);
    pushRow('Suppressed', data.is_suppressed);
    pushRow('Activated', data.activation_count);
    pushRow('Last activated', data.last_activated_at);
    pushRow('Created', data.created_at);
    if (data.doc_status) {
      pushRow('Doc stage', data.doc_status.stage);
      pushRow('Doc error', data.doc_status.error);
      pushRow('Doc updated', data.doc_status.updated_at);
    }
    if (data.mentions && data.mentions.length) {
      rows.push('<div class="detail-section"><h4>Mentions</h4><ul class="detail-list">' +
        data.mentions.map(m => `<li>${escapeHtml(m.canonical_name)}${m.is_self ? ' (self)' : ''}</li>`).join('') +
        '</ul></div>');
    }
  } else if (data.canonical_name !== undefined) {
    // entity
    pushRow('ID', data.id);
    pushRow('Type', 'entity');
    pushRow('Name', data.canonical_name);
    pushRow('Entity type', data.entity_type);
    // Description: edit ボタン付き。archived (valid_to が立った) entity は編集不可。
    const editable = data.valid_to == null;
    const descVal = data.description === null || data.description === undefined ? '—' : String(data.description);
    const descEditBtn = editable ? `<button type="button" class="edit-btn" data-edit-field="description" data-entity-id="${data.id}" aria-label="Description を編集">✎</button>` : '';
    rows.push(`<div class="detail-row" data-field-row="description"><span class="detail-label">Description${descEditBtn}</span><span class="detail-value wrap">${escapeHtml(descVal)}</span></div>`);
    if (data.curated_at) {
      pushRow('Curated at', data.curated_at);
    }
    pushRow('Self', data.is_self);
    pushRow('Self weight', data.self_weight);
    pushRow('Decay rate', data.decay_rate);
    pushRow('Valid from', data.valid_from);
    pushRow('Valid to', data.valid_to);
    pushRow('Supersedes', data.supersedes);
    pushRow('Activated', data.activation_count);
    pushRow('Last activated', data.last_activated_at);
    pushRow('Created', data.created_at);
    // Aliases: edit ボタン付き。常に行を出す (空でも編集できるように)。
    const aliasesVal = data.aliases && data.aliases.length ? data.aliases.join(', ') : '—';
    const aliasesEditBtn = editable ? `<button type="button" class="edit-btn" data-edit-field="aliases" data-entity-id="${data.id}" aria-label="Aliases を編集">✎</button>` : '';
    rows.push(`<div class="detail-row" data-field-row="aliases"><span class="detail-label">Aliases${aliasesEditBtn}</span><span class="detail-value wrap">${escapeHtml(aliasesVal)}</span></div>`);
    if (data.in_relations && data.in_relations.length) {
      rows.push('<div class="detail-section"><h4>In relations</h4><ul class="detail-list">' +
        data.in_relations.map(r => `<li>${escapeHtml(r.predicate)} from ${escapeHtml(r.src_type)}:${r.src_id}</li>`).join('') +
        '</ul></div>');
    }
    if (data.out_relations && data.out_relations.length) {
      rows.push('<div class="detail-section"><h4>Out relations</h4><ul class="detail-list">' +
        data.out_relations.map(r => `<li>${escapeHtml(r.predicate)} to ${escapeHtml(r.dst_type)}:${r.dst_id}${r.strength != null ? ` (strength ${r.strength})` : ''}</li>`).join('') +
        '</ul></div>');
    }
  } else if (data.predicate !== undefined) {
    // relation
    pushRow('ID', data.id);
    pushRow('Type', 'relation');
    pushRow('Predicate', data.predicate);
    pushRow('Source', `${data.src_type}:${data.src_id} (${data.src_label || '?'})`);
    pushRow('Target', `${data.dst_type}:${data.dst_id} (${data.dst_label || '?'})`);
    pushRow('Strength', data.strength);
    pushRow('Fan out', data.fan_out);
    pushRow('Description', data.description, true);
    pushRow('Valid from', data.valid_from);
    pushRow('Valid to', data.valid_to);
    pushRow('Supersedes', data.supersedes);
    pushRow('Created', data.created_at);
  }

  return rows.join('');
}

function showDetail(cyId, typeHint) {
  state.selected = cyId;
  const prefix = cyId.split('_')[0];
  const dbId = parseInt(cyId.split('_')[1], 10);
  let path = null;

  if (prefix === 'ep') {
    path = `/api/episodes/${dbId}`;
  } else if (prefix === 'en') {
    path = `/api/entities/${dbId}`;
  } else if (prefix === 'th' || prefix === 'po') {
    const node = state.cy.getElementById(cyId).data();
    const html = '<h3>' + escapeHtml(node.type) + '</h3><p class="graph-node-content">'
      + escapeHtml(node.search_text || node.label) + '</p>' + graphView.detailLinks(cyId);
    document.getElementById('detail-panel').innerHTML = html;
    if (state.view !== 'panel') {
      state.view = 'panel';
      document.body.classList.add('view-panel');
      document.body.classList.remove('view-popover');
      document.getElementById('view-toggle').checked = false;
      hidePopover();
    }
    return;
  } else if (prefix === 'men' || prefix === 'rel' || typeHint === 'relation') {
    path = `/api/relations/${dbId}`;
  }

  if (!path) return;

  api(path)
    .then((data) => {
      if (state.selected !== cyId || state.surface !== 'graph') return;
      const html = renderDetail(data) + (graphView?.detailLinks(cyId) || '');
      if (state.view === 'panel') {
        document.getElementById('detail-panel').innerHTML = html;
      } else {
        const popover = document.getElementById('popover');
        popover.innerHTML = '<button class="popover-close">&times;</button>' + html;
        popover.querySelector('.popover-close').addEventListener('click', hidePopover);
        popover.hidden = false;
        if (state.cy) {
          const ele = state.cy.getElementById(cyId);
          if (ele.length) {
            const pos = ele.isEdge() ? ele.renderedMidpoint() : ele.renderedPosition();
            const container = document.getElementById('cy');
            const rect = container.getBoundingClientRect();
            let left = rect.left + pos.x + 12;
            let top = rect.top + pos.y + 12;
            if (left + 320 > window.innerWidth) left -= 344;
            if (top + 220 > window.innerHeight) top -= 244;
            popover.style.left = Math.max(4, left) + 'px';
            popover.style.top = Math.max(4, top) + 'px';
          }
        }
      }
    })
    .catch((err) => {
      if (state.selected !== cyId || state.surface !== 'graph') return;
      console.error('detail fetch failed', err);
      const msg = '<div class="empty-state">詳細の取得に失敗しました</div>';
      if (state.view === 'panel') {
        document.getElementById('detail-panel').innerHTML = msg;
      } else {
        document.getElementById('popover').innerHTML = msg;
        document.getElementById('popover').hidden = false;
      }
    });
}

function hidePopover() {
  const popover = document.getElementById('popover');
  popover.hidden = true;
  popover.innerHTML = '';
}

// ─── Modal ──────────────────────────────────────────────────────────────────
let modalReturnFocus = null;
function openModal(title, bodyHtml) {
  modalReturnFocus = document.activeElement;
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  document.getElementById('modal-root').hidden = false;
}

function closeModal() {
  if (document.querySelector('#board-editor-form [type="submit"]:disabled')) return;
  document.getElementById('modal-root').hidden = true;
  document.getElementById('modal-body').innerHTML = '';
  if (modalReturnFocus && modalReturnFocus.isConnected) modalReturnFocus.focus();
  modalReturnFocus = null;
}

async function openMergeModal() {
  const data = await api('/api/merge_candidates?status=pending');
  if (!data.candidates || !data.candidates.length) {
    openModal('Merge candidates', '<div class="empty-state">pending はありません</div>');
    return;
  }
  const rows = data.candidates.map((c) =>
    `<tr class="clickable" data-node-id="en_${c.entity_a.id}">` +
    `<td>${escapeHtml(c.entity_a.canonical_name)}</td>` +
    `<td>${escapeHtml(c.entity_b.canonical_name)}</td>` +
    `<td>${(c.similarity * 100).toFixed(1)}%</td>` +
    `</tr>`
  ).join('');
  const html =
    '<table><thead><tr><th>Entity A</th><th>Entity B</th><th>Similarity</th></tr></thead>' +
    '<tbody>' + rows + '</tbody></table>';
  openModal('Merge candidates', html);
  document.querySelectorAll('#modal-body tr[data-node-id]').forEach((tr) => {
    tr.addEventListener('click', () => {
      const id = tr.dataset.nodeId;
      closeModal();
      if (state.cy) {
        state.cy.$(`#${id}`).select();
        showDetail(id, 'entity');
      }
    });
  });
}

async function openFailedModal() {
  const data = await api('/api/doc_status?status=failed');
  if (!data.items || !data.items.length) {
    openModal('Failed doc_status', '<div class="empty-state">失敗はありません</div>');
    return;
  }
  const rows = data.items.map((item) =>
    `<tr class="clickable" data-node-id="ep_${item.episode_id}">` +
    `<td>${escapeHtml(item.episode_label || '—')}</td>` +
    `<td>${escapeHtml(item.error || '—')}</td>` +
    `<td>${escapeHtml(item.stage)}</td>` +
    `</tr>`
  ).join('');
  const html =
    '<table><thead><tr><th>Episode</th><th>Error</th><th>Stage</th></tr></thead>' +
    '<tbody>' + rows + '</tbody></table>';
  openModal('Failed doc_status', html);
  document.querySelectorAll('#modal-body tr[data-node-id]').forEach((tr) => {
    tr.addEventListener('click', () => {
      const id = tr.dataset.nodeId;
      closeModal();
      if (state.cy) {
        state.cy.$(`#${id}`).select();
        showDetail(id, 'episode');
      }
    });
  });
}

async function openOrphanModal() {
  const data = await api('/api/orphans?scope=active');
  let html = '';
  if (data.episodes && data.episodes.length) {
    html += '<h4>Orphan episodes</h4>';
    const rows = data.episodes.map((e) =>
      `<tr class="clickable" data-node-id="ep_${e.id}">` +
      `<td>${e.id}</td><td>${escapeHtml(e.label || '—')}</td><td>${escapeHtml(e.kind || '—')}</td><td>${escapeHtml(e.created_at || '—')}</td>` +
      `</tr>`
    ).join('');
    html += '<table><thead><tr><th>ID</th><th>Label</th><th>Kind</th><th>Created</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }
  if (data.entities && data.entities.length) {
    html += '<h4>Orphan entities</h4>';
    const rows = data.entities.map((e) =>
      `<tr class="clickable" data-node-id="en_${e.id}">` +
      `<td>${e.id}</td><td>${escapeHtml(e.canonical_name || '—')}</td><td>${e.is_self ? 'self' : '—'}</td><td>${escapeHtml(e.created_at || '—')}</td>` +
      `</tr>`
    ).join('');
    html += '<table><thead><tr><th>ID</th><th>Name</th><th>Self</th><th>Created</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }
  if (!html) {
    html = '<div class="empty-state">orphan はありません</div>';
  }
  openModal('Orphans', html);
  document.querySelectorAll('#modal-body tr[data-node-id]').forEach((tr) => {
    tr.addEventListener('click', () => {
      const id = tr.dataset.nodeId;
      closeModal();
      if (state.cy) {
        state.cy.$(`#${id}`).select();
        showDetail(id, id.startsWith('ep_') ? 'episode' : 'entity');
      }
    });
  });
}

// ─── Board ──────────────────────────────────────────────────────────────────
let boardMenuTrigger = null;
let boardMenuContext = null;

const BOARD_ITEM_MODELS = {
  space: {
    actions: ['edit', 'trash'], editLabel: '名前を変更…',
    editorTitle: '掲示板名を変更', field: 'name', fieldLabel: '名前', maxLength: 128,
    save: (item, value) => apiJson(`/api/board/spaces/${item.id}`, 'PATCH', {
      name: value, expected_name: item.name,
    }),
  },
  thread: {
    actions: ['edit', 'status', 'trash'], editLabel: 'タイトルを変更…',
    editorTitle: 'スレッドのタイトルを変更', field: 'title', fieldLabel: 'タイトル', maxLength: 300,
    save: (item, value) => apiJson(`/api/board/threads/${item.id}`, 'PATCH', {
      title: value, expected_version: item.version,
    }),
  },
  post: {
    actions: ['edit', 'trash'], editLabel: '本文を編集…',
    editorTitle: '投稿を編集', field: 'body', fieldLabel: '本文', maxLength: 20000, multiline: true,
    save: (item, value) => apiJson(`/api/board/posts/${item.id}`, 'PATCH', {
      body: value, expected_revision: item.revision,
      editor_kind: 'human', editor_display_name: state.board.author,
    }),
  },
};

const BOARD_ACTIONS = {
  edit: {
    label: (kind) => BOARD_ITEM_MODELS[kind].editLabel,
    run: (kind, item) => openBoardEditor(kind, item),
  },
  status: {
    label: (_, item) => item.status === 'closed' ? '再開する' : 'Close（アーカイブ）',
    run: (_, item) => changeBoardThreadStatus(item.status === 'closed' ? 'open' : 'closed', item),
  },
  trash: {
    label: () => '削除…', danger: true,
    run: (kind, item) => trashBoardItem(kind, item.id, item.name || item.title || `投稿 #${item.id}`),
  },
};

function getBoardItem(kind, id) {
  const detail = state.board.thread;
  const items = {
    space: state.board.spaces,
    thread: [...(detail ? [detail.thread] : []), ...state.board.threads],
    post: detail ? detail.posts : [],
  };
  return (items[kind] || []).find((item) => Number(item.id) === Number(id));
}

function openBoardEditor(kind, item) {
  const model = BOARD_ITEM_MODELS[kind];
  const value = escapeHtml(item[model.field]);
  const attributes = `id="board-editor-value" required maxlength="${model.maxLength}"`;
  const field = model.multiline
    ? `<textarea ${attributes} rows="10">${value}</textarea>`
    : `<input type="text" ${attributes} value="${value}" autocomplete="off">`;
  openModal(model.editorTitle,
    '<form id="board-editor-form" class="board-editor-form">' +
    `<label for="board-editor-value">${model.fieldLabel}</label>${field}` +
    '<p id="board-editor-error" class="board-editor-error" role="alert" hidden></p>' +
    '<div class="board-editor-actions"><button type="button" id="board-editor-cancel">キャンセル</button>' +
    '<button type="submit" class="board-editor-save">保存</button></div></form>');
  const form = document.getElementById('board-editor-form');
  const editor = document.getElementById('board-editor-value');
  const error = document.getElementById('board-editor-error');
  const save = form.querySelector('[type="submit"]');
  document.getElementById('board-editor-cancel').addEventListener('click', closeModal);
  editor.addEventListener('input', () => editor.setCustomValidity(''));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (save.disabled) return;
    const nextValue = editor.value.trim();
    if (!nextValue) {
      editor.setCustomValidity('入力してください。');
      editor.reportValidity();
      return;
    }
    save.disabled = true;
    error.hidden = true;
    try {
      await model.save(item, nextValue);
    } catch (err) {
      error.textContent = `保存できませんでした: ${err.message}`;
      error.hidden = false;
      return;
    } finally {
      save.disabled = false;
    }
    closeModal();
    if (kind === 'thread') {
      state.board.selectedThreadId = item.id;
      state.board.selectedSpaceId = item.space_id;
      state.board.threadStatus = item.status;
    }
    const threadId = state.board.selectedThreadId;
    try {
      await reloadBoardSpaces();
      if (threadId != null) await loadBoardThread(threadId);
      document.querySelector(`[data-board-menu-kind="${kind}"][data-board-menu-id="${item.id}"]`)?.focus();
    } catch (err) {
      window.alert(`変更は保存しましたが、画面を更新できませんでした: ${err.message}`);
    }
  });
  editor.focus();
  if (!model.multiline) editor.select();
}

function boardItemMenuButton(kind, id, label) {
  return `<button type="button" class="board-menu-trigger" data-board-menu-kind="${kind}" ` +
    `data-board-menu-id="${id}" data-board-menu-label="${escapeHtml(label)}" ` +
    `aria-label="${escapeHtml(label)}の操作" title="操作" aria-haspopup="menu" ` +
    'aria-expanded="false" aria-controls="board-action-menu">' +
    '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">' +
    '<circle cx="3" cy="8" r="1.5" fill="currentColor"/>' +
    '<circle cx="8" cy="8" r="1.5" fill="currentColor"/>' +
    '<circle cx="13" cy="8" r="1.5" fill="currentColor"/></svg></button>';
}

function closeBoardActionMenu(restoreFocus = false) {
  const menu = document.getElementById('board-action-menu');
  if (menu) menu.hidden = true;
  if (boardMenuTrigger) {
    boardMenuTrigger.setAttribute('aria-expanded', 'false');
    if (restoreFocus && boardMenuTrigger.isConnected) boardMenuTrigger.focus();
  }
  boardMenuTrigger = null;
  boardMenuContext = null;
}

function toggleBoardActionMenu(trigger) {
  const wasOpen = boardMenuTrigger === trigger;
  closeBoardActionMenu();
  if (wasOpen) return;
  const menu = document.getElementById('board-action-menu');
  if (!menu) return;
  const { boardMenuKind: kind, boardMenuId: id } = trigger.dataset;
  const item = getBoardItem(kind, id);
  const model = BOARD_ITEM_MODELS[kind];
  if (!item || !model) return;
  menu.innerHTML = model.actions.map((actionId) => {
    const action = BOARD_ACTIONS[actionId];
    const separator = action.danger ? '<div class="board-menu-separator" role="separator"></div>' : '';
    return separator + `<button type="button" role="menuitem" ` +
      `class="${action.danger ? 'board-menu-danger' : ''}" data-board-action="${actionId}">` +
      `${escapeHtml(action.label(kind, item))}</button>`;
  }).join('');
  boardMenuContext = { kind, item };
  boardMenuTrigger = trigger;
  trigger.setAttribute('aria-expanded', 'true');
  menu.hidden = false;
  const anchor = trigger.getBoundingClientRect();
  const bounds = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(anchor.right - bounds.width, window.innerWidth - bounds.width - 8))}px`;
  menu.style.top = `${anchor.bottom + bounds.height + 8 > window.innerHeight
    ? Math.max(8, anchor.top - bounds.height - 4) : anchor.bottom + 4}px`;
  menu.querySelector('[role="menuitem"]').focus();
}

function formatBoardTimestamp(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const formatted = new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).format(date);
  return `${formatted} JST`;
}
function renderBoardSpaces() {
  closeBoardActionMenu();
  const target = document.getElementById('board-spaces');
  if (!target) return;
  if (!state.board.spaces.length) {
    target.innerHTML = '<div class="empty-state">掲示板がありません</div>';
    return;
  }
  target.innerHTML = state.board.spaces.map((space) => {
    const selected = Number(space.id) === Number(state.board.selectedSpaceId) ? ' selected' : '';
    return '<div class="board-list-row">' +
      `<button type="button" class="board-list-item board-list-select${selected}" data-space-id="${space.id}">` +
      `<span class="board-list-title">${escapeHtml(space.name)}</span>` +
      `<span class="board-list-meta">${space.thread_count} スレ</span>` +
      '</button>' +
      (state.board.trashMode ? '' : boardItemMenuButton('space', space.id, space.name)) +
      '</div>';
  }).join('');
}

function renderBoardThreads() {
  closeBoardActionMenu();
  const target = document.getElementById('board-threads');
  if (!target) return;
  if (state.board.trashMode) {
    if (!state.board.trashItems.length) {
      target.innerHTML = '<div class="empty-state">ゴミ箱は空です</div>';
      return;
    }
    const kindLabels = { space: '掲示板', thread: 'スレッド', post: '投稿' };
    target.innerHTML = state.board.trashItems.map((item) => {
      const kindLabel = kindLabels[item.kind] || item.kind;
      const parent = item.kind === 'space'
        ? (item.detail || `#${item.item_id}`)
        : `掲示板: ${item.space_name || '不明'}`;
      const detail = item.kind === 'post' ? ` · #${item.thread_id}` : '';
      return '<div class="board-list-row board-trash-row">' +
        '<div class="board-trash-label">' +
        `<strong>${escapeHtml(item.title)}</strong>` +
        `<span class="board-list-meta">${escapeHtml(kindLabel)} · ${escapeHtml(parent)}${detail} · ${escapeHtml(formatBoardTimestamp(item.deleted_at))}</span>` +
        '</div>' +
        `<button type="button" class="board-item-action board-restore-action" data-restore-kind="${item.kind}" data-restore-id="${item.item_id}">元に戻す</button>` +
        '</div>';
    }).join('');
    return;
  }
  if (!state.board.threads.length) {
    target.innerHTML = '<div class="empty-state">スレッドがありません</div>';
    return;
  }
  target.innerHTML = state.board.threads.map((thread) => {
    const selected = Number(thread.id) === Number(state.board.selectedThreadId) ? ' selected' : '';
    const statusLabel = thread.status === 'closed' ? ' · アーカイブ' : '';
    return '<div class="board-list-row">' +
      `<button type="button" class="board-list-item board-list-select${selected}" data-thread-id="${thread.id}">` +
      `<span class="board-list-title">${escapeHtml(thread.title)}</span>` +
      `<span class="board-list-meta">v${thread.version} · ${thread.post_count} 投稿${statusLabel}</span>` +
      '</button>' +
      boardItemMenuButton('thread', thread.id, thread.title) +
      '</div>';
  }).join('');
}

function renderBoardThread() {
  closeBoardActionMenu();
  const target = document.getElementById('board-thread');
  if (!target) return;
  if (state.board.trashMode) {
    target.innerHTML = '<div class="empty-state">ゴミ箱の項目は、一覧から元に戻せます。</div>';
    return;
  }
  const data = state.board.thread;
  if (!data) {
    target.innerHTML = '<div class="empty-state">スレッドを選択してください</div>';
    return;
  }

  const thread = data.thread;
  const closed = thread.status === 'closed';
  const posts = data.posts || [];
  const postHtml = posts.map((post) => {
    const allowedKind = ['summary', 'decision', 'note'].includes(post.kind) ? post.kind : 'message';
    const className = allowedKind === 'message'
      ? 'board-post'
      : `board-post board-post-${allowedKind}`;
    const author = post.author_name || post.author_kind || 'unknown';
    const postedAt = post.created_at || '';
    return `<article class="${className}" id="board-post-${post.id}">` +
      '<div class="board-post-head">' +
      `<strong>${escapeHtml(author)}</strong>` +
      `<span class="board-post-kind">${escapeHtml(post.kind)}</span>` +
      `<span>r${post.revision}</span>` +
      `<time datetime="${escapeHtml(postedAt)}">${escapeHtml(formatBoardTimestamp(postedAt))}</time>` +
      boardItemMenuButton('post', post.id, `投稿 #${post.id}`) +
      '</div>' +
      `<div class="board-post-body">${escapeHtml(post.body)}</div>` +
      '</article>';
  }).join('');
  const composer = closed
    ? '<div class="board-closed-note">このスレッドはアーカイブされています。再開すると投稿できます。</div>'
    : '<div class="board-composer">' +
      '<textarea id="board-post-body" maxlength="20000" placeholder="このスレッドへ投稿..."></textarea>' +
      '<div class="board-composer-actions"><button type="button" id="board-post-submit">投稿</button></div></div>';

  target.innerHTML =
    '<div class="board-thread-header">' +
    '<div>' + `<h2>${escapeHtml(thread.title)}</h2>` +
    `<span class="board-list-meta">thread #${thread.id} · v${thread.version} · ${closed ? 'アーカイブ済み' : 'Open'}</span>` +
    '</div>' +
    '<div class="board-thread-actions">' +
    boardItemMenuButton('thread', thread.id, thread.title) +
    '</div></div>' +
    (postHtml || '<div class="empty-state">投稿がありません</div>') +
    composer;
}

async function reloadBoardSpaces() {
  const data = await api('/api/board/spaces');
  state.board.spaces = data.spaces || [];
  if (
    state.board.selectedSpaceId == null ||
    !state.board.spaces.some((space) => Number(space.id) === Number(state.board.selectedSpaceId))
  ) {
    state.board.selectedSpaceId = state.board.spaces.length ? state.board.spaces[0].id : null;
  }
  renderBoardSpaces();
  await reloadBoardThreads();
}

function renderBoardModeControls() {
  const archive = document.getElementById('board-archive-toggle');
  if (archive) {
    archive.hidden = state.board.trashMode;
    archive.textContent = state.board.threadStatus === 'open' ? 'アーカイブを見る' : 'Openスレを見る';
    archive.setAttribute('aria-pressed', state.board.threadStatus === 'closed' ? 'true' : 'false');
  }
  const trash = document.getElementById('board-trash-toggle');
  if (trash) {
    trash.textContent = state.board.trashMode ? '掲示板へ戻る' : 'ゴミ箱';
    trash.setAttribute('aria-pressed', state.board.trashMode ? 'true' : 'false');
  }
  const createSpace = document.getElementById('board-create-space');
  const createThread = document.getElementById('board-create-thread');
  if (createSpace) createSpace.hidden = state.board.trashMode;
  if (createThread) createThread.hidden = state.board.trashMode;
}

async function reloadBoardThreads() {
  renderBoardModeControls();
  if (state.board.trashMode) {
    const data = await api('/api/board/trash');
    state.board.trashItems = data.items || [];
    state.board.threads = [];
    state.board.thread = null;
    state.board.selectedThreadId = null;
    renderBoardThreads();
    renderBoardThread();
    return;
  }
  if (state.board.selectedSpaceId == null) {
    state.board.threads = [];
    state.board.thread = null;
    state.board.selectedThreadId = null;
    renderBoardThreads();
    renderBoardThread();
    return;
  }
  const data = await api(
    `/api/board/threads?space_id=${encodeURIComponent(state.board.selectedSpaceId)}&status=${encodeURIComponent(state.board.threadStatus)}`
  );
  state.board.threads = data.threads || [];
  if (
    state.board.selectedThreadId != null &&
    !state.board.threads.some((thread) => Number(thread.id) === Number(state.board.selectedThreadId))
  ) {
    state.board.selectedThreadId = null;
    state.board.thread = null;
  }
  renderBoardThreads();
  renderBoardThread();
}

async function loadBoardThread(threadId) {
  const data = await api(`/api/board/threads/${threadId}`);
  state.board.trashMode = false;
  state.board.selectedThreadId = Number(threadId);
  state.board.thread = data;
  state.board.selectedSpaceId = data.thread.space_id;
  state.board.threadStatus = data.thread.status === 'closed' ? 'closed' : 'open';
  renderBoardModeControls();
  renderBoardSpaces();
  renderBoardThreads();
  renderBoardThread();
}

async function searchBoard() {
  state.board.trashMode = false;
  renderBoardModeControls();
  const input = document.getElementById('board-search-input');
  const q = input ? input.value.trim() : '';
  if (!q) {
    await reloadBoardThreads();
    return;
  }
  const data = await api(`/api/board/search?q=${encodeURIComponent(q)}`);
  const target = document.getElementById('board-threads');
  if (!target) return;
  const results = data.results || [];
  if (!results.length) {
    target.innerHTML = '<div class="empty-state">一致なし</div>';
    return;
  }
  target.innerHTML = results.map((item) =>
    `<button type="button" class="board-list-item board-search-result" data-thread-id="${item.thread_id}">` +
    `<span class="board-list-title">${escapeHtml(item.title)}</span>` +
    `<span class="board-list-meta">${escapeHtml(item.result_type)} · ${escapeHtml(item.body || '')}</span>` +
    '</button>'
  ).join('');
}

async function changeBoardThreadStatus(status, thread) {
  if (!thread) return;
  const result = await apiJson(`/api/board/threads/${thread.id}/status`, 'PATCH', {
    status,
    expected_version: thread.version,
  });
  state.board.threadStatus = result.status;
  state.board.selectedSpaceId = thread.space_id;
  state.board.selectedThreadId = thread.id;
  await reloadBoardThreads();
  await loadBoardThread(thread.id);
  document.querySelector(`[data-board-menu-kind="thread"][data-board-menu-id="${thread.id}"]`)?.focus();
}

async function trashBoardItem(kind, itemId, label) {
  const names = { space: '掲示板', thread: 'スレッド', post: '投稿' };
  if (!window.confirm(`${names[kind] || kind}「${label || `#${itemId}`}」をゴミ箱に移します。あとで復元できます。`)) return;
  await apiJson(`/api/board/items/${encodeURIComponent(kind)}/${itemId}/trash`, 'POST', {});
  await reloadBoardSpaces();
  if (kind === 'post' && state.board.selectedThreadId != null && !state.board.trashMode) {
    await loadBoardThread(state.board.selectedThreadId);
  }
}

async function restoreBoardItem(kind, itemId) {
  await apiJson(`/api/board/items/${encodeURIComponent(kind)}/${itemId}/restore`, 'POST', {});
  await reloadBoardSpaces();
}

async function toggleBoardArchive() {
  state.board.threadStatus = state.board.threadStatus === 'open' ? 'closed' : 'open';
  state.board.selectedThreadId = null;
  state.board.thread = null;
  renderBoardModeControls();
  await reloadBoardThreads();
}

async function toggleBoardTrash() {
  state.board.trashMode = !state.board.trashMode;
  state.board.selectedThreadId = null;
  state.board.thread = null;
  renderBoardModeControls();
  await reloadBoardThreads();
}

async function createBoardSpace() {
  const name = window.prompt('Space name');
  if (!name || !name.trim()) return;
  const description = window.prompt('Description (optional)') || null;
  const created = await apiJson('/api/board/spaces', 'POST', {
    name: name.trim(),
    description,
  });
  state.board.selectedSpaceId = created.space_id;
  await reloadBoardSpaces();
}

async function createBoardThread() {
  if (state.board.selectedSpaceId == null) {
    window.alert('先にspaceを作成してください');
    return;
  }
  const title = window.prompt('Thread title');
  if (!title || !title.trim()) return;
  const initialPost = window.prompt('Initial post (optional)') || null;
  const created = await apiJson('/api/board/threads', 'POST', {
    space_id: state.board.selectedSpaceId,
    title: title.trim(),
    author_display_name: state.board.author,
    author_kind: 'human',
    initial_post: initialPost,
  });
  state.board.threadStatus = 'open';
  await reloadBoardThreads();
  await loadBoardThread(created.thread_id);
}

async function submitBoardPost() {
  if (state.board.selectedThreadId == null) return;
  const input = document.getElementById('board-post-body');
  if (!input) return;
  const body = input.value.trim();
  if (!body) return;
  await apiJson(
    `/api/board/threads/${state.board.selectedThreadId}/posts`,
    'POST',
    {
      body,
      author_display_name: state.board.author,
      author_kind: 'human',
      kind: 'message',
    }
  );
  input.value = '';
  await reloadBoardThreads();
  await loadBoardThread(state.board.selectedThreadId);
}

async function setSurface(surface) {
  state.surface = ['graph', 'board', 'activity'].includes(surface) ? surface : 'graph';
  localStorage.setItem('admin_surface', state.surface);
  document.body.classList.toggle('surface-board', state.surface === 'board');
  document.body.classList.toggle('surface-activity', state.surface === 'activity');
  document.getElementById('activity-view').hidden = state.surface !== 'activity';
  if (state.surface !== 'graph') hidePopover();

  const cyEl = document.getElementById('cy');
  const boardEl = document.getElementById('board-view');
  if (cyEl) cyEl.hidden = state.surface !== 'graph';
  if (boardEl) boardEl.hidden = state.surface !== 'board';

  document.querySelectorAll('[data-surface]').forEach((btn) => {
    const active = btn.dataset.surface === state.surface;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });

  if (state.surface === 'board') {
    try {
      await reloadBoardSpaces();
    } catch (err) {
      console.error('board load failed', err);
      const target = document.getElementById('board-thread');
      if (target) target.innerHTML = '<div class="empty-state">Boardの読み込みに失敗しました</div>';
    }
  } else if (state.surface === 'activity') {
    await activityView.show();
  } else if (state.cy) {
    state.cy.resize();
  }
}

// ─── View / Scope / Theme ───────────────────────────────────────────────────
function setView(mode) {
  state.view = mode;
  localStorage.setItem('admin_view', mode);
  document.body.classList.toggle('view-panel', mode === 'panel');
  document.body.classList.toggle('view-popover', mode === 'popover');

  const toggle = document.getElementById('view-toggle');
  if (toggle) toggle.checked = mode === 'popover';

  if (mode === 'panel') {
    hidePopover();
  }
  if (state.selected) {
    showDetail(state.selected);
  } else {
    hidePopover();
    if (mode === 'panel') {
      document.getElementById('detail-panel').innerHTML = '';
    }
  }
}

function setTheme(theme) {
  state.theme = theme;
  localStorage.setItem('admin_theme', theme);
  document.body.setAttribute('data-theme', theme);

  const toggle = document.getElementById('theme-toggle');
  if (toggle) toggle.checked = theme === 'light';

  applyGraphTheme();
}

async function setScope(scope) {
  if (scope === 'all') {
    const total = ((state.stats?.episodes?.total) || 0) + ((state.stats?.entities?.total) || 0);
    if (!confirm(`現役以外も含めて ${total} 件のノードが描画されます。重くなる可能性があります。続行しますか？`)) {
      const radio = document.querySelector(`input[name="scope"][value="${state.scope}"]`);
      if (radio) radio.checked = true;
      return;
    }
  }
  state.scope = scope;
  await reloadGraph();
}

async function reloadGraph() {
  try {
    state.graphData = await api(`/api/graph?scope=${state.scope}`);
    if (state.cy) {
      graphView.replace(state.graphData.elements);
    }
  } catch (err) {
    console.error('reloadGraph failed', err);
  }
}

async function reloadAll() {
  try {
    state.stats = await api('/api/stats');
    renderStatsBar();
  } catch (err) {
    console.error('stats fetch failed', err);
  }
  await reloadGraph();
}

// ─── Events ─────────────────────────────────────────────────────────────────
function setupEventListeners() {
  // Surface switch
  const surfaceSwitch = document.getElementById('surface-switch');
  if (surfaceSwitch) {
    surfaceSwitch.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-surface]');
      if (btn) setSurface(btn.dataset.surface);
    });
  }

  const boardAuthor = document.getElementById('board-author');
  if (boardAuthor) {
    boardAuthor.value = state.board.author;
    boardAuthor.addEventListener('change', (e) => {
      const value = e.target.value.trim() || 'admin';
      state.board.author = value;
      e.target.value = value;
      localStorage.setItem('board_author', value);
    });
  }

  const boardView = document.getElementById('board-view');
  if (boardView) {
    boardView.addEventListener('click', (e) => {
      const menuTrigger = e.target.closest('[data-board-menu-kind]');
      if (menuTrigger) {
        e.preventDefault();
        toggleBoardActionMenu(menuTrigger);
        return;
      }
      const itemAction = e.target.closest('[data-board-action]');
      if (itemAction && boardMenuContext) {
        e.preventDefault();
        const { kind, item } = boardMenuContext;
        const action = BOARD_ACTIONS[itemAction.dataset.boardAction];
        closeBoardActionMenu(true);
        Promise.resolve().then(() => action.run(kind, item))
          .catch((err) => window.alert(`操作に失敗しました: ${err.message}`));
        return;
      }
      const restoreAction = e.target.closest('[data-restore-kind][data-restore-id]');
      if (restoreAction) {
        e.preventDefault();
        e.stopPropagation();
        restoreBoardItem(restoreAction.dataset.restoreKind, Number(restoreAction.dataset.restoreId))
          .catch((err) => window.alert(`復元に失敗しました: ${err.message}`));
        return;
      }
      const space = e.target.closest('[data-space-id]');
      if (space) {
        state.board.selectedSpaceId = Number(space.dataset.spaceId);
        state.board.selectedThreadId = null;
        state.board.thread = null;
        renderBoardSpaces();
        reloadBoardThreads().catch((err) => console.error('board threads failed', err));
        return;
      }
      const thread = e.target.closest('[data-thread-id]');
      if (thread) {
        loadBoardThread(Number(thread.dataset.threadId))
          .catch((err) => console.error('board thread failed', err));
        return;
      }
      if (e.target.closest('#board-post-submit')) {
        submitBoardPost().catch((err) => {
          console.error('board post failed', err);
          window.alert('投稿に失敗しました');
        });
      }
    });
  }

  document.addEventListener('click', (e) => {
    if (!e.target.closest('#board-action-menu, [data-board-menu-kind]')) {
      closeBoardActionMenu();
    }
  });
  document.addEventListener('keydown', (e) => {
    const editorForm = document.getElementById('board-editor-form');
    if (editorForm) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
      } else if (e.key === 'Tab') {
        const controls = [...document.querySelectorAll('#modal-root button, #modal-root input, #modal-root textarea')]
          .filter((control) => !control.disabled);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
      return;
    }
    if (!boardMenuTrigger) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      closeBoardActionMenu(true);
    } else if (e.key === 'Tab') {
      closeBoardActionMenu(true);
    } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
      e.preventDefault();
      const items = [...document.querySelectorAll('#board-action-menu [role="menuitem"]')];
      const current = items.indexOf(document.activeElement);
      const index = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1
        : (current + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items[index].focus();
    }
  });
  document.addEventListener('scroll', () => closeBoardActionMenu(), true);
  window.addEventListener('resize', () => closeBoardActionMenu());

  const boardRefresh = document.getElementById('board-refresh');
  if (boardRefresh) {
    boardRefresh.addEventListener('click', () => {
      reloadBoardSpaces().then(() => {
        if (state.board.selectedThreadId != null) return loadBoardThread(state.board.selectedThreadId);
      }).catch((err) => console.error('board refresh failed', err));
    });
  }
  const boardArchiveToggle = document.getElementById('board-archive-toggle');
  if (boardArchiveToggle) {
    boardArchiveToggle.addEventListener('click', () => {
      toggleBoardArchive().catch((err) => window.alert(`スレッド一覧を切り替えられません: ${err.message}`));
    });
  }
  const boardTrashToggle = document.getElementById('board-trash-toggle');
  if (boardTrashToggle) {
    boardTrashToggle.addEventListener('click', () => {
      toggleBoardTrash().catch((err) => window.alert(`ゴミ箱を開けません: ${err.message}`));
    });
  }
  const boardCreateSpace = document.getElementById('board-create-space');
  if (boardCreateSpace) {
    boardCreateSpace.addEventListener('click', () => {
      createBoardSpace().catch((err) => {
        console.error('space create failed', err);
        window.alert('space作成に失敗しました');
      });
    });
  }
  const boardCreateThread = document.getElementById('board-create-thread');
  if (boardCreateThread) {
    boardCreateThread.addEventListener('click', () => {
      createBoardThread().catch((err) => {
        console.error('thread create failed', err);
        window.alert('thread作成に失敗しました');
      });
    });
  }
  const boardSearchBtn = document.getElementById('board-search-btn');
  if (boardSearchBtn) {
    boardSearchBtn.addEventListener('click', () => {
      searchBoard().catch((err) => console.error('board search failed', err));
    });
  }
  const boardSearchInput = document.getElementById('board-search-input');
  if (boardSearchInput) {
    boardSearchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        searchBoard().catch((err) => console.error('board search failed', err));
      }
    });
  }

  // Scope
  document.querySelectorAll('input[name="scope"]').forEach((el) => {
    el.addEventListener('change', (e) => {
      if (e.target.checked) setScope(e.target.value);
    });
  });

  // View toggle
  const viewToggle = document.getElementById('view-toggle');
  if (viewToggle) {
    viewToggle.addEventListener('change', (e) => {
      setView(e.target.checked ? 'popover' : 'panel');
    });
  }

  // Theme toggle
  const themeToggle = document.getElementById('theme-toggle');
  if (themeToggle) {
    themeToggle.addEventListener('change', (e) => {
      setTheme(e.target.checked ? 'light' : 'dark');
    });
  }

  // Kind filters
  document.querySelectorAll('input[name="kind"]').forEach((el) => {
    el.addEventListener('change', (e) => {
      state.filters.kind[e.target.value] = e.target.checked;
      applyFilters();
    });
  });

  // Type filters
  document.querySelectorAll('input[name="type"]').forEach((el) => {
    el.addEventListener('change', (e) => {
      state.filters.type[e.target.value] = e.target.checked;
      applyFilters();
    });
  });

  // Spread slider
  const spreadSlider = document.getElementById('spread-slider');
  if (spreadSlider) {
    spreadSlider.value = String(state.spread);
    const valueEl = document.getElementById('spread-value');
    if (valueEl) valueEl.textContent = state.spread.toFixed(1);
    spreadSlider.addEventListener('input', (e) => {
      setSpread(parseFloat(e.target.value));
    });
  }

  // Importance filter
  const impSlider = document.getElementById('importance-slider');
  if (impSlider) {
    impSlider.addEventListener('input', (e) => {
      const v = parseInt(e.target.value, 10);
      state.filters.importance = v;
      const label = document.getElementById('importance-value');
      if (label) label.textContent = v === 1 ? 'all' : `≥ ${v}`;
      applyFilters();
    });
  }

  // Degree filter
  const degSlider = document.getElementById('degree-slider');
  if (degSlider) {
    degSlider.addEventListener('input', (e) => {
      const v = parseInt(e.target.value, 10);
      state.filters.degree = v;
      const label = document.getElementById('degree-value');
      if (label) label.textContent = v === 0 ? 'all' : `≥ ${v}`;
      applyFilters();
    });
  }

  // Reload
  document.getElementById('reload').addEventListener('click', reloadAll);

  // Stats bar clicks (delegate)
  document.getElementById('stats-bar').addEventListener('click', (e) => {
    const item = e.target.closest('[data-modal]');
    if (!item) return;
    const modal = item.dataset.modal;
    if (modal === 'merge') openMergeModal();
    else if (modal === 'failed') openFailedModal();
    else if (modal === 'orphan') openOrphanModal();
  });

  // Search box
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => setSearchQuery(e.target.value));
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        searchInput.value = '';
        setSearchQuery('');
      }
    });
  }
  const searchClear = document.getElementById('search-clear');
  if (searchClear) {
    searchClear.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      setSearchQuery('');
      if (searchInput) searchInput.focus();
    });
  }

  // Modal close
  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.querySelector('.modal-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  // Entity inline edit (delegation on document.body — covers both panel and popover)
  document.body.addEventListener('click', (e) => {
    const editBtn = e.target.closest('.edit-btn[data-edit-field]');
    if (editBtn) {
      e.preventDefault();
      enterEntityEditMode(editBtn);
      return;
    }
    const saveBtn = e.target.closest('.edit-save');
    if (saveBtn) {
      e.preventDefault();
      submitEntityEdit(saveBtn);
      return;
    }
    const cancelBtn = e.target.closest('.edit-cancel');
    if (cancelBtn) {
      e.preventDefault();
      // 取り直しで素の表示に戻す (ローカル復元より確実)
      if (state.selected) showDetail(state.selected, 'entity');
      return;
    }
  });
}

function enterEntityEditMode(btn) {
  const field = btn.dataset.editField;
  const entityId = btn.dataset.entityId;
  const row = btn.closest('[data-field-row]');
  if (!row || !field || !entityId) return;
  if (row.dataset.editing === 'true') return;
  row.dataset.editing = 'true';

  const currentValueEl = row.querySelector('.detail-value');
  const currentText = currentValueEl ? currentValueEl.textContent : '';
  const isDescription = field === 'description';
  const isPlaceholder = currentText === '—';
  const initial = isPlaceholder ? '' : currentText;

  const inputHtml = isDescription
    ? `<textarea class="edit-input" rows="4" maxlength="4000">${escapeHtml(initial)}</textarea>`
    : `<input class="edit-input" type="text" value="${escapeHtml(initial)}" placeholder="comma-separated">`;
  const helperHtml = isDescription
    ? '<div class="edit-helper">最大 4000 文字</div>'
    : '<div class="edit-helper">カンマ区切り (空にすると alias を全削除)</div>';

  currentValueEl.innerHTML =
    inputHtml +
    helperHtml +
    `<div class="edit-actions">` +
    `<button type="button" class="edit-save" data-edit-field="${field}" data-entity-id="${entityId}">保存</button>` +
    `<button type="button" class="edit-cancel">キャンセル</button>` +
    `</div>`;

  const input = currentValueEl.querySelector('.edit-input');
  if (input) input.focus();
}

async function submitEntityEdit(btn) {
  const field = btn.dataset.editField;
  const entityId = btn.dataset.entityId;
  const row = btn.closest('[data-field-row]');
  if (!row || !field || !entityId) return;
  const input = row.querySelector('.edit-input');
  if (!input) return;

  let payload;
  if (field === 'description') {
    payload = { description: input.value };
  } else if (field === 'aliases') {
    const aliases = input.value
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    payload = { aliases };
  } else {
    return;
  }

  btn.disabled = true;
  const cancelBtn = row.querySelector('.edit-cancel');
  if (cancelBtn) cancelBtn.disabled = true;

  try {
    const res = await fetch(`/api/entities/${entityId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const text = await res.text();
      alert(`更新に失敗しました (${res.status}): ${text}`);
      btn.disabled = false;
      if (cancelBtn) cancelBtn.disabled = false;
      return;
    }
    // 成功 → detail を再取得して再描画 (curated_at の更新も反映される)
    if (state.selected) showDetail(state.selected, 'entity');
  } catch (err) {
    console.error('entity update failed', err);
    alert('更新に失敗しました (network error)');
    btn.disabled = false;
    if (cancelBtn) cancelBtn.disabled = false;
  }
}

// ─── Boot ───────────────────────────────────────────────────────────────────
let activityView;
async function openActivityTarget(event) {
  if (event.category === 'board') {
    await setSurface('board');
    if (event.thread_id) {
      await loadBoardThread(event.thread_id);
      await reloadBoardThreads();
      if (event.target_type === 'post') {
        document.querySelectorAll('.activity-target').forEach(el => el.classList.remove('activity-target'));
        const post = document.getElementById(`board-post-${event.target_id}`);
        post?.classList.add('activity-target');
        post?.scrollIntoView({block: 'center'});
      }
    } else {
      state.board.selectedSpaceId = event.space_id;
      state.board.selectedThreadId = null;
      state.board.thread = null;
      state.board.trashMode = false;
      renderBoardSpaces();
      renderBoardThread();
      await reloadBoardThreads();
    }
    return;
  }
  await setSurface('graph');
  const prefixes = {episode: 'ep', entity: 'en', relation: 'rel'};
  const id = `${prefixes[event.target_type]}_${event.target_id}`;
  const node = state.cy?.getElementById(id);
  if (node?.length && event.target_type !== 'relation') graphView.select(id);
  else {
    const paths = {episode: 'episodes', entity: 'entities', relation: 'relations'};
    const data = await api(`/api/${paths[event.target_type]}/${event.target_id}`);
    openModal('Activity · 現在の詳細', renderDetail(data));
  }
}

async function main() {
  activityView = new ActivityView(api, openActivityTarget);
  setupEventListeners();
  try {
    state.stats = await api('/api/stats');
    renderStatsBar();
  } catch (err) {
    console.error('initial stats fetch failed', err);
  }

  try {
    state.graphData = await api(`/api/graph?scope=${state.scope}`);
    await import('/static/cytoscape-bootstrap.js');
    state.cy = initCytoscape(state.graphData.elements);
    applyFilters();
  } catch (err) {
    console.error('initial graph fetch failed', err);
    document.getElementById('cy').innerHTML = '<div class="empty-state">グラフの読み込みに失敗しました</div>';
  }

  setView(state.view);
  setTheme(state.theme);
  await setSurface(state.surface);
}

main();
