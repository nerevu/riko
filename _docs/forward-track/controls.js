const SVG = 'http://www.w3.org/2000/svg';

function drawWires() {
  document.querySelectorAll('[data-edges]:not([data-shelf])').forEach((graph, index) => {
    const svg = graph.querySelector(':scope > .wires');
    const box = graph.getBoundingClientRect();
    const marker = `arrow-${index}`;
    svg.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
    svg.innerHTML = `<defs><marker id="${marker}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="currentColor"/></marker></defs>`;
    for (const pair of graph.dataset.edges.split(' ').filter(Boolean)) {
      const [a, b] = pair.split('>').map(id => document.getElementById(id).getBoundingClientRect());
      const x1 = a.left + a.width / 2 - box.left, y1 = a.bottom - box.top;
      const x2 = b.left + b.width / 2 - box.left, y2 = b.top - box.top;
      const mid = (y1 + y2) / 2;
      const path = document.createElementNS(SVG, 'path');
      path.setAttribute('d', Math.abs(x1 - x2) < 2 ? `M${x1} ${y1}V${y2 - 2}` : `M${x1} ${y1}V${mid}H${x2}V${y2 - 2}`);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', 'currentColor');
      path.setAttribute('stroke-width', '2');
      path.setAttribute('marker-end', `url(#${marker})`);
      svg.append(path);
    }
  });
}
new ResizeObserver(drawWires).observe(document.querySelector('main'));

function initShelf(graph, index) {
  const svg = graph.querySelector(':scope > .wires');
  const pairs = graph.dataset.edges.split(' ').filter(Boolean).map(pair => pair.split('>'));
  const cards = [...graph.querySelectorAll('.shelf-card')];
  const byId = new Map(cards.map(card => [card.id, card]));
  const label = id => byId.get(id).dataset.label;
  const marker = `shelf-tip-${index}`;
  const children = new Map();
  const parents = new Map();
  for (const [source, target] of pairs) {
    children.set(source, [...(children.get(source) ?? []), target]);
    parents.set(target, [...(parents.get(target) ?? []), source]);
  }
  const roots = cards.filter(card => !parents.has(card.id)).map(card => card.id);
  const expanded = new Set();
  let visible = new Set(roots);
  let wireFrame = 0;

  function reachable(collapsed) {
    const found = new Set(roots);
    for (const id of found) {
      if (id !== collapsed && expanded.has(id)) for (const child of children.get(id) ?? []) found.add(child);
    }
    return found;
  }

  function nearestVisible(source) {
    const found = [];
    const visit = (parent, via) => {
      for (const id of children.get(parent) ?? []) {
        if (visible.has(id)) found.push({id, via});
        else visit(id, [...via, id]);
      }
    };
    visit(source, []);
    return found;
  }

  function line(d, arrow, dashed) {
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', 'currentColor');
    path.setAttribute('stroke-width', '1.8');
    if (arrow) path.setAttribute('marker-end', `url(#${marker})`);
    if (dashed) path.setAttribute('stroke-dasharray', '5 4');
    svg.append(path);
  }

  function draw() {
    const frame = graph.getBoundingClientRect();
    if (!frame.width || !frame.height) return;
    svg.setAttribute('viewBox', `0 0 ${frame.width} ${frame.height}`);
    svg.innerHTML = `<defs><marker id="${marker}" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L8 4L0 8Z" fill="currentColor"/></marker></defs>`;
    const links = [...visible].flatMap(source => nearestVisible(source).map(end => ({source, ...end})));
    const rect = id => byId.get(id).getBoundingClientRect();
    const inputs = new Map();
    for (const link of links) inputs.set(link.id, [...(inputs.get(link.id) ?? []), link.source]);
    for (const sources of inputs.values()) sources.sort((a, b) => rect(a).left - rect(b).left);
    const gap = parseFloat(getComputedStyle(graph).rowGap);
    for (const source of visible) {
      const ends = links.filter(link => link.source === source);
      if (!ends.length) continue;
      const parent = rect(source);
      const x = parent.left + parent.width / 2 - frame.left;
      const y = parent.bottom - frame.top;
      const points = ends.map(({id, via}) => {
        const card = rect(id);
        const sources = inputs.get(id);
        const port = (sources.indexOf(source) + 1) / (sources.length + 1);
        return {via, x: card.left + card.width * port - frame.left, y: card.top - frame.top - 2};
      });
      const split = y + Math.min(gap, Math.min(...points.map(point => point.y)) - y) / 2;
      line(`M${x} ${y}V${split}`, false, points.every(point => point.via.length));
      for (const point of points) {
        line(`M${x} ${split}H${point.x}V${point.y}`, true, point.via.length > 0);
        if (!point.via.length) continue;
        const text = document.createElementNS(SVG, 'text');
        text.setAttribute('x', (x + point.x) / 2);
        text.setAttribute('y', split - 6);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('class', 'via-label');
        text.textContent = 'via ' + point.via.map(label).join(' → ');
        svg.append(text);
      }
    }
  }

  function compact() {
    const columns = [...new Set(cards.filter(card => visible.has(card.id)).map(card => Number(card.parentElement.dataset.column)))];
    columns.sort((a, b) => a - b);
    for (const card of cards) {
      const cell = card.parentElement;
      if (visible.has(card.id)) cell.style.gridColumn = String(columns.indexOf(Number(cell.dataset.column)) + 1);
    }
    graph.style.setProperty('--visible-columns', String(Math.max(1, columns.length)));
  }

  function refresh() {
    visible = reachable();
    compact();
    for (const card of cards) {
      card.parentElement.hidden = !visible.has(card.id);
      if (!visible.has(card.id)) expanded.delete(card.id);
      const button = card.querySelector('.reveal');
      if (button === null) continue;
      const open = expanded.has(card.id);
      const remaining = open ? reachable(card.id) : visible;
      const affected = open
        ? [...visible].filter(id => !remaining.has(id))
        : children.get(card.id).filter(id => !visible.has(id));
      button.setAttribute('aria-expanded', String(open));
      button.hidden = !affected.length;
      const verb = open ? 'Hide ' : 'Show ';
      button.textContent = verb + (affected.length === 1 ? label(affected[0]) : `${affected.length} dependent slices`);
    }
    draw();
  }

  function animate(change) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      change();
      return;
    }
    cancelAnimationFrame(wireFrame);
    graph.querySelectorAll('.exit-copy').forEach(node => node.remove());
    const before = new Map();
    for (const card of cards) {
      if (visible.has(card.id)) before.set(card, card.getBoundingClientRect());
      card.parentElement.classList.remove('moving', 'entering');
    }
    change();
    const frame = graph.getBoundingClientRect();
    for (const card of cards) {
      const old = before.get(card);
      const cell = card.parentElement;
      if (!visible.has(card.id)) {
        if (!old) continue;
        const copy = card.cloneNode(true);
        for (const node of [copy, ...copy.querySelectorAll('[id]')]) node.removeAttribute('id');
        copy.inert = true;
        copy.setAttribute('aria-hidden', 'true');
        copy.classList.add('exit-copy');
        Object.assign(copy.style, {left: `${old.left - frame.left}px`, top: `${old.top - frame.top}px`, width: `${old.width}px`, height: `${old.height}px`});
        graph.append(copy);
        copy.addEventListener('animationend', () => copy.remove(), {once: true});
      } else if (!old) {
        cell.classList.add('entering');
      } else {
        const now = card.getBoundingClientRect();
        cell.style.setProperty('--dx', `${old.left - now.left}px`);
        cell.style.setProperty('--dy', `${old.top - now.top}px`);
        cell.classList.add('moving');
      }
    }
    const follow = () => {
      draw();
      if (cards.some(card => card.parentElement.getAnimations().some(a => a.playState === 'running'))) wireFrame = requestAnimationFrame(follow);
    };
    follow();
  }

  for (const card of cards) {
    if (!children.has(card.id)) continue;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'reveal';
    button.setAttribute('aria-controls', children.get(card.id).join(' '));
    button.addEventListener('click', () => animate(() => {
      if (expanded.has(card.id)) expanded.delete(card.id);
      else expanded.add(card.id);
      refresh();
    }));
    card.append(button);
    card.classList.add('expandable');
    card.addEventListener('click', event => {
      if (!event.target.closest('a, button')) button.click();
    });
  }
  refresh();
  const observer = new ResizeObserver(draw);
  observer.observe(graph);
  cards.forEach(card => observer.observe(card));
  graph.closest('details')?.addEventListener('toggle', draw);
}
document.querySelectorAll('[data-shelf]').forEach(initShelf);

document.querySelectorAll('[data-open]').forEach(opener => {
  opener.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (link !== null && link !== opener) return;
    event.preventDefault();
    document.getElementById(opener.dataset.open).showModal();
  });
});
document.querySelectorAll('[data-open][role="button"]').forEach(card => {
  card.addEventListener('keydown', event => {
    if (event.target === card && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      card.click();
    }
  });
});
document.querySelectorAll('dialog').forEach(dialog => {
  dialog.addEventListener('click', event => {
    const box = dialog.getBoundingClientRect();
    const outside = event.clientX < box.left || event.clientX > box.right
      || event.clientY < box.top || event.clientY > box.bottom;
    if (event.target === dialog && outside) dialog.close();
  });
  dialog.querySelectorAll('a[href^="#"]').forEach(link => {
    link.addEventListener('click', () => dialog.close());
  });
});
const filters = document.querySelectorAll('.filters button');
filters.forEach(button => {
  button.addEventListener('click', () => {
    for (const other of filters) other.setAttribute('aria-pressed', other === button);
    for (const card of document.querySelectorAll('.cards .phase')) {
      card.hidden = button.dataset.filter !== 'all' && card.dataset.status !== button.dataset.filter;
    }
  });
});
