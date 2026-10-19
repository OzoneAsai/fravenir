/* Activity reads stored events. Viewing and filtering never records an access. */
const ACTIVITY_LABELS = {
  'post.created': '投稿', 'post.edited': '投稿を編集', 'thread.created': 'スレッドを作成',
  'space.created': '掲示板を作成', 'episode.created': '記憶を作成',
  'episode.expired': '記憶の有効期限', 'entity.created': 'Entityを作成',
  'relation.created': '関係を追加', 'relation.expired': '関係の有効期限',
};
const ACTIVITY_CATEGORIES = { board: '掲示板', memory: 'メモリー', graph: 'グラフ' };

function activityDateRange(from, until) {
  const result = {};
  if (from) result.start = new Date(`${from}T00:00:00`).toISOString();
  if (until) {
    const end = new Date(`${until}T00:00:00`);
    end.setDate(end.getDate() + 1);
    result.end = end.toISOString();
  }
  if (result.start && result.end && result.start >= result.end) throw new Error('日付の範囲を確認してください');
  return result;
}

class ActivityView {
  constructor(fetchPage, openTarget) {
    this.fetchPage = fetchPage;
    this.openTarget = openTarget;
    this.events = new Map();
    this.cursor = null;
    this.generation = 0;
    this.filters = { category: 'all', q: '' };
    this.loaded = false;
    this.busy = false;
    this.more = false;
    document.getElementById('activity-filter').addEventListener('submit', e => {
      e.preventDefault();
      this.applyFilters();
    });
    document.getElementById('activity-reset').addEventListener('click', () => {
      document.getElementById('activity-filter').reset();
      this.applyFilters();
    });
    document.getElementById('activity-refresh').addEventListener('click', () => this.load(true));
    document.getElementById('activity-more').addEventListener('click', () => this.load(false));
    document.getElementById('activity-category').addEventListener('change', () => this.applyFilters());
    document.getElementById('activity-timeline').addEventListener('click', async e => {
      const button = e.target.closest('[data-activity-event]');
      if (!button) return;
      const event = this.events.get(button.dataset.activityEvent);
      if (!event) return;
      button.disabled = true;
      try { await this.openTarget(event); }
      catch (error) { this.status(`移動できませんでした: ${error.message}`, true); }
      finally { button.disabled = false; }
    });
  }

  async show() {
    if (!this.loaded && !this.busy) await this.load(true);
  }

  applyFilters() {
    try {
      this.filters = {
        category: document.getElementById('activity-category').value,
        q: document.getElementById('activity-query').value.trim(),
        ...activityDateRange(document.getElementById('activity-from').value,
          document.getElementById('activity-until').value),
      };
      this.load(true);
    } catch (error) {
      ++this.generation;
      this.busy = false;
      this.setBusy();
      this.status(error.message, true);
    }
  }

  status(message, error = false) {
    const status = document.getElementById('activity-status');
    status.textContent = message;
    status.classList.toggle('activity-error', error);
  }

  async load(reset) {
    if (!reset && (this.busy || !this.cursor)) return;
    const generation = ++this.generation;
    if (reset) { this.cursor = null; this.more = false; }
    this.busy = true;
    this.setBusy();
    this.status(reset ? '履歴を読み込んでいます…' : '過去の履歴を読み込んでいます…');
    const params = new URLSearchParams({ ...this.filters, limit: '50' });
    if (!reset) params.set('cursor', this.cursor);
    try {
      const page = await this.fetchPage(`/api/activity?${params}`);
      if (generation !== this.generation) return;
      if (reset) { this.events.clear(); this.lastDay = null; document.getElementById('activity-timeline').replaceChildren(); }
      for (const event of page.events) {
        if (this.events.has(event.id)) continue;
        this.events.set(event.id, event);
        this.append(event);
      }
      this.cursor = page.next_cursor;
      this.more = page.has_more;
      this.loaded = true;
      document.getElementById('activity-empty').hidden = this.events.size > 0;
      this.status(this.events.size ? `${this.events.size} 件を表示${this.more ? ' · さらに過去の履歴があります' : ' · すべて表示しました'}` : '条件に一致する履歴はありません');
      document.getElementById('activity-updated').textContent = `取得: ${new Date(page.as_of).toLocaleString('ja-JP')}`;
    } catch (error) {
      if (generation !== this.generation) return;
      this.status(`読み込めませんでした。更新して再試行してください。${error.message}`, true);
    } finally {
      if (generation === this.generation) { this.busy = false; this.setBusy(); }
    }
  }

  setBusy() {
    document.getElementById('activity-timeline').setAttribute('aria-busy', String(this.busy));
    document.getElementById('activity-refresh').disabled = this.busy;
    const more = document.getElementById('activity-more');
    more.disabled = this.busy;
    more.hidden = !this.more;
    more.textContent = this.busy ? '読み込み中…' : 'さらに過去を表示';
  }

  append(event) {
    const date = new Date(event.occurred_at);
    const day = date.toLocaleDateString('ja-JP', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' });
    const list = document.getElementById('activity-timeline');
    if (day !== this.lastDay) {
      const divider = document.createElement('li');
      divider.className = 'activity-day';
      const heading = document.createElement('h2');
      heading.textContent = day;
      divider.append(heading); list.append(divider); this.lastDay = day;
    }
    const item = document.createElement('li');
    item.className = 'activity-item'; item.dataset.category = event.category;
    const time = document.createElement('time');
    time.dateTime = event.occurred_at;
    time.textContent = date.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    time.title = date.toLocaleString('ja-JP'); item.append(time);
    const article = document.createElement('article');
    const meta = document.createElement('div'); meta.className = 'activity-meta';
    const badge = document.createElement('span'); badge.className = 'activity-badge';
    badge.textContent = ACTIVITY_CATEGORIES[event.category] || event.category; meta.append(badge);
    const action = document.createElement('span');
    action.textContent = ACTIVITY_LABELS[event.action] || event.action; meta.append(action);
    if (event.actor) {
      const actor = document.createElement('span'); actor.className = 'activity-actor';
      actor.textContent = `${event.actor}${event.actor_kind ? ` · ${event.actor_kind}` : ''}`; meta.append(actor);
    }
    if (event.revision) {
      const revision = document.createElement('span'); revision.textContent = `rev ${event.revision}`; meta.append(revision);
    }
    article.append(meta);
    const title = document.createElement('h3'); title.textContent = event.title; article.append(title);
    if (event.context) {
      const context = document.createElement('p'); context.className = 'activity-context';
      context.textContent = event.context; article.append(context);
    }
    if (event.preview) {
      const preview = document.createElement('p'); preview.className = 'activity-preview';
      preview.textContent = event.preview; article.append(preview);
      const details = document.createElement('details');
      const summary = document.createElement('summary'); summary.textContent = '記録された本文を表示';
      const body = document.createElement('p'); body.className = 'activity-body'; body.textContent = event.preview;
      details.append(summary, body); article.append(details);
    }
    const footer = document.createElement('div'); footer.className = 'activity-item-footer';
    const target = document.createElement('button'); target.type = 'button'; target.dataset.activityEvent = event.id;
    target.textContent = event.category === 'board' ? '掲示板で開く（現在）' : 'グラフ・詳細を開く';
    footer.append(target);
    const identity = document.createElement('span'); identity.textContent = `${event.target_type} #${event.target_id}`;
    footer.append(identity); article.append(footer);
    if (event.note) {
      const note = document.createElement('p'); note.className = 'activity-note'; note.textContent = event.note; article.append(note);
    }
    item.append(article); list.append(item);
  }
}

if (typeof module !== 'undefined') module.exports = { activityDateRange };
