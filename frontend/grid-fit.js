// Self-fitting room grid: picks a column count for each .floor container so
// its .room cards use the available panel space (instead of a permanently
// fixed cell size that leaves empty space at low room counts, or overflows
// at high ones). Purely a layout helper - it never touches room state,
// severity, nurse markers, or any application data.
(function () {
  const CARD_ASPECT = 1.3; // target width:height ratio for a room card

  function bestColumnCount(width, height, count) {
    if (count <= 0 || width <= 0 || height <= 0) return 1;
    let bestCols = 1;
    let bestCellArea = 0;
    for (let cols = 1; cols <= count; cols++) {
      const rows = Math.ceil(count / cols);
      const cellW = width / cols;
      const cellH = height / rows;
      const capByHeight = cellH * CARD_ASPECT;
      const usedW = Math.min(cellW, capByHeight);
      const usedH = usedW / CARD_ASPECT;
      const area = usedW * usedH;
      if (area > bestCellArea) {
        bestCellArea = area;
        bestCols = cols;
      }
    }
    return bestCols;
  }

  function fit(container) {
    const count = container.querySelectorAll(":scope > .room").length;
    if (!count) return;
    const width = container.clientWidth - 16;
    const height = container.clientHeight - 32;
    if (width <= 0 || height <= 0) return;
    const cols = bestColumnCount(width, height, count);
    container.style.setProperty("--fit-cols", String(cols));
  }

  function fitAll() {
    document.querySelectorAll(".floor").forEach(fit);
  }

  const resizeObserver = new ResizeObserver(fitAll);
  const mutationObserver = new MutationObserver(fitAll);

  function watch(container) {
    resizeObserver.observe(container);
    mutationObserver.observe(container, { childList: true });
  }

  document.querySelectorAll(".floor").forEach(watch);
  window.addEventListener("load", fitAll);
  document.addEventListener("DOMContentLoaded", fitAll);
  requestAnimationFrame(fitAll);
})();
