(() => {
  const frame = document.getElementById('appFrame');
  const canvas = document.getElementById('boardCanvas');
  const title = document.getElementById('boardTitle');
  const connection = document.getElementById('boardConnection');
  const showChat = document.getElementById('showChat');
  const showBoard = document.getElementById('showBoard');
  const colors = ['#21e6c1', '#49a8ff', '#a879ff', '#f4c95d', '#ff7185', '#43e899'];
  let controller;
  let revision = 0;
  let connectionToken = 0;
  let scrollTimer;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function componentShell(component, extra = '') {
    const node = element('section', `board-component ${component.type.replaceAll('_', '-')}-component ${extra}`.trim());
    node.dataset.componentId = component.id;
    node.dataset.componentType = component.type;
    return node;
  }

  function addTitle(node, text) {
    if (text) node.append(element('h3', 'component-title', text));
  }

  function renderHeading(component) {
    const node = componentShell(component, 'wide board-heading-component');
    const heading = element(`h${component.data.level || 2}`, '', component.data.text);
    node.append(heading);
    if (component.data.subtitle) node.append(element('p', '', component.data.subtitle));
    return node;
  }

  function renderRichText(component) {
    const node = componentShell(component);
    addTitle(node, component.data.title);
    node.append(element('p', 'rich-text-body', component.data.text));
    return node;
  }

  function renderMetricCards(component) {
    const node = componentShell(component, 'wide');
    const grid = element('div', 'metric-grid');
    for (const item of component.data.items) {
      const card = element('div', 'metric-card');
      card.append(element('strong', 'metric-value', item.value));
      card.append(element('span', 'metric-label', item.label));
      if (item.detail) card.append(element('span', 'metric-detail', item.detail));
      grid.append(card);
    }
    node.append(grid);
    return node;
  }

  function renderListItems(node, items) {
    const list = element('div', 'visual-list');
    for (const item of items) {
      const row = element('div', 'visual-list-item');
      const top = element('div', 'item-row');
      top.append(element('span', 'item-title', item.title));
      if (item.badge) top.append(element('span', 'item-badge', item.badge));
      row.append(top);
      if (item.subtitle) row.append(element('div', 'item-subtitle', item.subtitle));
      list.append(row);
    }
    node.append(list);
  }

  function renderList(component) {
    const node = componentShell(component);
    addTitle(node, component.data.title);
    renderListItems(node, component.data.items);
    return node;
  }

  function renderTaskList(component) {
    const node = componentShell(component);
    addTitle(node, component.data.title || 'Tasks');
    const items = component.data.tasks.map(task => ({
      title: task.title,
      subtitle: [task.project, task.due].filter(Boolean).join(' · '),
      badge: task.status,
    }));
    renderListItems(node, items);
    return node;
  }

  function renderKnowledgeList(component) {
    const node = componentShell(component);
    addTitle(node, component.data.title || 'Knowledge');
    const items = component.data.items.map(item => ({
      title: item.title,
      subtitle: [item.excerpt, item.updated].filter(Boolean).join(' · '),
      badge: item.kind.replace('_', ' '),
    }));
    renderListItems(node, items);
    return node;
  }

  function renderKnowledgeDetail(component) {
    const data = component.data;
    const node = componentShell(component, 'wide');
    node.append(element('h3', 'component-title', data.title));
    const meta = [data.kind.replace('_', ' '), ...data.tags, data.updated].filter(Boolean);
    if (meta.length) node.append(element('div', 'item-subtitle', meta.join(' · ')));
    node.append(element('p', 'rich-text-body', data.content));
    if (data.source_url) node.append(element('div', 'item-subtitle', `Source: ${data.source_url}`));
    return node;
  }

  function renderEmailList(component) {
    const node = componentShell(component);
    addTitle(node, component.data.title || 'Mail');
    const list = element('div', 'visual-list');
    for (const message of component.data.messages) {
      const row = element('div', `email-item${message.unread ? ' unread' : ''}`);
      const line = element('div', 'email-line');
      const subject = element('div');
      subject.append(element('div', 'email-subject', message.subject));
      subject.append(element('div', 'item-subtitle', message.sender));
      line.append(subject);
      if (message.time) line.append(element('span', 'email-time', message.time));
      row.append(line);
      if (message.preview) row.append(element('div', 'email-preview', message.preview));
      list.append(row);
    }
    node.append(list);
    return node;
  }

  function renderEmailDetail(component) {
    const data = component.data;
    const node = componentShell(component, 'wide');
    node.append(element('h3', 'email-detail-subject', data.subject));
    const meta = element('div', 'email-meta');
    meta.append(element('span', '', `From ${data.sender}`));
    if (data.recipients.length) meta.append(element('span', '', `To ${data.recipients.join(', ')}`));
    if (data.date) meta.append(element('span', '', data.date));
    node.append(meta, element('p', 'email-body', data.body));
    return node;
  }

  function renderAgenda(component) {
    const node = componentShell(component);
    addTitle(node, component.data.title || component.data.date || 'Agenda');
    const list = element('div', 'agenda-list');
    for (const event of component.data.events) {
      const row = element('div', 'agenda-item');
      row.append(element('span', 'agenda-time', event.time));
      const details = element('div');
      details.append(element('div', 'agenda-title', event.title));
      const meta = [event.duration, event.location].filter(Boolean).join(' · ');
      if (meta) details.append(element('div', 'agenda-meta', meta));
      row.append(details);
      list.append(row);
    }
    node.append(list);
    return node;
  }

  function renderEventDetail(component) {
    const data = component.data;
    const node = componentShell(component);
    node.append(element('h3', 'event-detail-title', data.title));
    const meta = element('div', 'event-meta');
    meta.append(element('span', '', [data.start, data.end].filter(Boolean).join(' – ')));
    if (data.location) meta.append(element('span', '', data.location));
    if (data.attendees.length) meta.append(element('span', '', `${data.attendees.length} attendees`));
    node.append(meta);
    if (data.description) node.append(element('p', 'event-description', data.description));
    return node;
  }

  function renderTimeline(component) {
    const node = componentShell(component);
    addTitle(node, component.data.title || 'Timeline');
    const list = element('div', 'timeline-list');
    for (const item of component.data.items) {
      const row = element('div', 'timeline-item');
      row.append(element('div', 'timeline-time', item.time));
      const top = element('div', 'item-row');
      top.append(element('span', 'item-title', item.title));
      if (item.status) top.append(element('span', 'item-badge', item.status));
      row.append(top);
      if (item.description) row.append(element('div', 'timeline-description', item.description));
      list.append(row);
    }
    node.append(list);
    return node;
  }

  function renderTable(component) {
    const node = componentShell(component, 'wide');
    addTitle(node, component.data.title);
    const scroll = element('div', 'table-scroll');
    const table = element('table', 'board-table');
    const head = element('thead');
    const headRow = element('tr');
    component.data.columns.forEach(column => headRow.append(element('th', '', column)));
    head.append(headRow);
    const body = element('tbody');
    for (const values of component.data.rows) {
      const row = element('tr');
      component.data.columns.forEach((_, index) => row.append(element('td', '', values[index] ?? '')));
      body.append(row);
    }
    table.append(head, body);
    scroll.append(table);
    node.append(scroll);
    return node;
  }

  function renderKeyValue(component) {
    const node = componentShell(component);
    addTitle(node, component.data.title);
    const list = element('div', 'key-value-list');
    for (const item of component.data.items) {
      const row = element('div', 'key-value-item');
      row.append(element('span', '', item.label), element('span', '', item.value));
      list.append(row);
    }
    node.append(list);
    return node;
  }

  function renderBarChart(data) {
    const chart = element('div', 'bar-chart');
    const maximum = Math.max(1, ...data.series.flatMap(series => series.values.map(value => Math.abs(value))));
    data.labels.forEach((label, index) => {
      const group = element('div', 'bar-group');
      const stack = element('div', 'bar-stack');
      data.series.forEach((series, seriesIndex) => {
        const bar = element('div', 'bar');
        bar.style.height = `${Math.max(2, Math.abs(series.values[index] || 0) / maximum * 100)}%`;
        bar.style.background = colors[seriesIndex % colors.length];
        bar.title = `${series.name}: ${series.values[index] || 0}`;
        stack.append(bar);
      });
      group.append(stack, element('span', 'chart-label', label));
      chart.append(group);
    });
    return chart;
  }

  function renderLineChart(data) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.classList.add('line-chart');
    svg.setAttribute('viewBox', '0 0 600 200');
    const values = data.series.flatMap(series => series.values);
    const minimum = Math.min(0, ...values);
    const maximum = Math.max(1, ...values);
    const range = maximum - minimum || 1;
    data.series.forEach((series, seriesIndex) => {
      const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      const denominator = Math.max(1, series.values.length - 1);
      const points = series.values.map((value, index) => {
        const x = index / denominator * 580 + 10;
        const y = 185 - ((value - minimum) / range * 165);
        return `${x},${y}`;
      }).join(' ');
      polyline.setAttribute('points', points);
      polyline.style.stroke = colors[seriesIndex % colors.length];
      svg.append(polyline);
    });
    return svg;
  }

  function renderDonutChart(data) {
    const wrap = element('div', 'donut-wrap');
    const chart = element('div', 'donut-chart');
    const values = data.series[0].values.map(value => Math.max(0, value));
    const total = values.reduce((sum, value) => sum + value, 0) || 1;
    let cursor = 0;
    const stops = values.map((value, index) => {
      const start = cursor;
      cursor += value / total * 100;
      return `${colors[index % colors.length]} ${start}% ${cursor}%`;
    });
    chart.style.background = `conic-gradient(${stops.join(',')})`;
    chart.append(element('div', 'donut-hole', String(values.reduce((sum, value) => sum + value, 0))));
    wrap.append(chart);
    return wrap;
  }

  function renderChart(component) {
    const node = componentShell(component, 'wide');
    addTitle(node, component.data.title);
    const area = element('div', 'chart-area');
    if (component.data.kind === 'line') area.append(renderLineChart(component.data));
    else if (component.data.kind === 'donut') area.append(renderDonutChart(component.data));
    else area.append(renderBarChart(component.data));
    const legend = element('div', 'chart-legend');
    component.data.series.forEach(series => legend.append(element('span', '', series.name)));
    area.append(legend);
    node.append(area);
    return node;
  }

  function renderImage(component) {
    const node = componentShell(component, 'wide');
    const image = element('img', 'board-image');
    image.src = component.data.src;
    image.alt = component.data.alt;
    image.loading = 'lazy';
    node.append(image);
    if (component.data.caption) node.append(element('p', 'image-caption', component.data.caption));
    return node;
  }

  function renderCallout(component) {
    const node = componentShell(component);
    node.dataset.tone = component.data.tone;
    addTitle(node, component.data.title);
    node.append(element('p', 'callout-text', component.data.text));
    return node;
  }

  function renderLoading(component) {
    const node = componentShell(component);
    node.append(element('span', 'board-spinner'));
    node.append(element('span', '', component.data.text));
    return node;
  }

  function renderEmptyState(component) {
    const node = componentShell(component);
    node.append(element('div', 'board-orb'));
    node.append(element('h3', '', component.data.title));
    if (component.data.text) node.append(element('p', 'component-subtitle', component.data.text));
    return node;
  }

  const renderers = {
    heading: renderHeading,
    rich_text: renderRichText,
    metric_cards: renderMetricCards,
    list: renderList,
    task_list: renderTaskList,
    knowledge_list: renderKnowledgeList,
    knowledge_detail: renderKnowledgeDetail,
    email_list: renderEmailList,
    email_detail: renderEmailDetail,
    calendar_agenda: renderAgenda,
    event_detail: renderEventDetail,
    timeline: renderTimeline,
    table: renderTable,
    key_value: renderKeyValue,
    chart: renderChart,
    image: renderImage,
    callout: renderCallout,
    loading: renderLoading,
    empty_state: renderEmptyState,
  };

  function renderBoard(board, fromStream = false) {
    const previousRevision = revision;
    revision = board.revision;
    title.textContent = board.title;
    canvas.className = `board-canvas layout-${board.layout}`;
    canvas.replaceChildren();
    if (!board.components.length) {
      const empty = element('div', 'board-empty');
      const orb = element('div', 'board-orb');
      orb.append(element('span'));
      empty.append(orb, element('h3', '', 'Nancy’s canvas'));
      empty.append(element('p', '', 'Ask Nancy to show you something. The visual result will appear here.'));
      canvas.append(empty);
    } else {
      for (const component of board.components) {
        const renderer = renderers[component.type];
        if (renderer) canvas.append(renderer(component));
      }
    }
    if (fromStream && previousRevision && board.revision > previousRevision && innerWidth <= 800) {
      reveal('board');
    }
  }

  function setConnection(label, live = false) {
    connection.lastChild.textContent = ` ${label}`;
    connection.classList.toggle('live', live);
  }

  function reveal(view) {
    const left = view === 'board' ? frame.clientWidth : 0;
    frame.scrollTo({left, behavior: 'smooth'});
  }

  function updateSwitcher() {
    if (innerWidth > 800) return;
    const boardVisible = frame.scrollLeft > frame.clientWidth / 2;
    showChat.classList.toggle('active', !boardVisible);
    showBoard.classList.toggle('active', boardVisible);
  }

  async function loadCurrent(key, conversation) {
    const response = await fetch(`/board?conversation=${encodeURIComponent(conversation)}`, {
      headers: {Authorization: `Bearer ${key}`},
    });
    if (response.status === 404) return;
    if (!response.ok) throw new Error(`Board request failed (${response.status})`);
    renderBoard(await response.json());
  }

  async function consumeEvents(key, conversation, token) {
    while (token === connectionToken) {
      try {
        setConnection('Connecting');
        controller = new AbortController();
        const response = await fetch(
          `/board/events?conversation=${encodeURIComponent(conversation)}&after=${revision}`,
          {headers: {Authorization: `Bearer ${key}`}, signal: controller.signal},
        );
        if (!response.ok || !response.body) throw new Error(`Board stream failed (${response.status})`);
        setConnection('Live', true);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (token === connectionToken) {
          const {value, done} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {stream: true});
          const events = buffer.split('\n\n');
          buffer = events.pop() || '';
          for (const event of events) {
            const data = event.split('\n').filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n');
            if (data) renderBoard(JSON.parse(data), true);
          }
        }
      } catch (error) {
        if (token !== connectionToken || error.name === 'AbortError') return;
        console.warn('Board stream disconnected', error);
        setConnection('Retrying');
      }
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
  }

  async function connect({key, conversation}) {
    disconnect();
    const token = connectionToken;
    setConnection('Loading');
    try {
      await loadCurrent(key, conversation);
    } catch (error) {
      console.warn('Could not load visual board', error);
    }
    consumeEvents(key, conversation, token);
  }

  function disconnect() {
    connectionToken += 1;
    controller?.abort();
    controller = undefined;
    setConnection('Waiting');
  }

  showChat.addEventListener('click', () => reveal('chat'));
  showBoard.addEventListener('click', () => reveal('board'));
  frame.addEventListener('scroll', () => {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(updateSwitcher, 60);
  }, {passive: true});
  window.addEventListener('resize', updateSwitcher);

  window.nancyBoard = {connect, disconnect, render: renderBoard, reveal};
})();
