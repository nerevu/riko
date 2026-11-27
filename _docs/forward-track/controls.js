const SVG = 'http://www.w3.org/2000/svg';

function drawWires() {
  document.querySelectorAll('[data-edges]').forEach((graph, index) => {
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
