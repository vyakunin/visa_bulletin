/**
 * Client-side sortable tables.
 *
 * Tables with class "sortable-table" get:
 * - Initial sort by the column specified in data-initial-sort-col (0-based),
 *   direction data-initial-sort-dir ("asc" or "desc"). Default: column 1 desc (filings).
 * - Click on <th> to sort by that column; click again to toggle asc/desc.
 *
 * Each <th> may have data-sort-col (0-based index) and data-sort-type ("number" or "text").
 * If data-sort-type is omitted, values are parsed as number when possible.
 */
(function () {
    'use strict';

    function parseCellValue(text, type) {
        const t = (text || '').trim().replace(/,/g, '');
        if (type === 'number') {
            const n = parseFloat(t.replace(/[^0-9.-]/g, ''));
            return isNaN(n) ? 0 : n;
        }
        if (type === 'text') {
            return t.toLowerCase();
        }
        const n = parseFloat(t.replace(/[^0-9.-]/g, ''));
        return isNaN(n) ? t.toLowerCase() : n;
    }

    function getCellValue(row, colIndex) {
        const cell = row.cells[colIndex];
        return cell ? cell.textContent : '';
    }

    function sortTableBody(table, colIndex, dir, sortType) {
        const tbody = table.querySelector('tbody');
        if (!tbody) return;
        const rows = Array.from(tbody.querySelectorAll('tr'));
        if (rows.length === 0) return;

        const isAsc = dir === 'asc';
        rows.sort(function (a, b) {
            const aVal = parseCellValue(getCellValue(a, colIndex), sortType);
            const bVal = parseCellValue(getCellValue(b, colIndex), sortType);
            if (typeof aVal === 'number' && typeof bVal === 'number') {
                return isAsc ? aVal - bVal : bVal - aVal;
            }
            const cmp = String(aVal).localeCompare(String(bVal));
            return isAsc ? cmp : -cmp;
        });

        rows.forEach(function (row) {
            tbody.appendChild(row);
        });
    }

    function setHeaderIndicator(thead, sortCol, dir) {
        thead.querySelectorAll('th').forEach(function (th, i) {
            const span = th.querySelector('.sort-indicator');
            if (span) span.remove();
            th.classList.remove('sortable-sorted');
            if (i === sortCol) {
                th.classList.add('sortable-sorted');
                const s = document.createElement('span');
                s.className = 'sort-indicator ms-1';
                s.setAttribute('aria-hidden', 'true');
                s.textContent = dir === 'asc' ? '\u25b2' : '\u25bc';
                th.appendChild(s);
            }
        });
    }

    function initSortableTable(table) {
        const thead = table.querySelector('thead');
        const tbody = table.querySelector('tbody');
        if (!thead || !tbody) return;

        const initialCol = parseInt(table.dataset.initialSortCol, 10);
        const initialDir = (table.dataset.initialSortDir || 'desc').toLowerCase() === 'asc' ? 'asc' : 'desc';
        let currentCol = isNaN(initialCol) ? 1 : initialCol;
        let currentDir = initialDir;

        const ths = thead.querySelectorAll('th');
        ths.forEach(function (th, i) {
            const colIndex = th.dataset.sortCol !== undefined ? parseInt(th.dataset.sortCol, 10) : i;
            const sortType = th.dataset.sortType || '';

            th.style.cursor = 'pointer';
            th.setAttribute('role', 'button');
            th.setAttribute('tabindex', '0');
            th.title = 'Sort by this column';

            function doSort(col, dir) {
                sortTableBody(table, col, dir, sortType);
                setHeaderIndicator(thead, col, dir);
                currentCol = col;
                currentDir = dir;
            }

            function handleClick() {
                if (currentCol === colIndex) {
                    currentDir = currentDir === 'asc' ? 'desc' : 'asc';
                } else {
                    currentDir = 'desc';
                }
                doSort(colIndex, currentDir);
            }

            th.addEventListener('click', handleClick);
            th.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleClick();
                }
            });
        });

        sortTableBody(table, currentCol, currentDir, ths[currentCol] ? ths[currentCol].dataset.sortType : '');
        setHeaderIndicator(thead, currentCol, currentDir);
    }

    function init() {
        document.querySelectorAll('.sortable-table').forEach(initSortableTable);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.initSortableTables = init;
})();
