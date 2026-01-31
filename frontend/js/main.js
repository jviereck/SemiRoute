/**
 * Main application entry point.
 */
(function() {
    'use strict';

    // Global state
    let viewer = null;
    let selectedNetId = null;

    // Trace mode state
    let appMode = 'select';  // 'select' | 'trace'
    let userTraces = [];  // Confirmed traces (persistent across sessions)

    // Continuous routing session state
    // - Mouse move: continuously routes to cursor position (debounced)
    // - Single click: commits segment, clicked point becomes new start
    // - 1-4 keys: place via at cursor, switch layer, cursor becomes new start
    // - Double click: commits and ends routing
    // - Escape: removes all traces added in this session
    let routingSession = null;
    // {
    //   startNet: number,              // Net ID from initial pad
    //   startPoint: {x, y},            // Current start point
    //   cursorPoint: {x, y},           // Current cursor position
    //   pendingPath: array,            // Current route preview to cursor
    //   sessionSegments: [],           // Segments added in this session (for undo)
    //   sessionVias: [],               // Vias added in this session (for undo)
    //   currentLayer: string,
    //   width: number
    // }

    // Routing state for continuous updates
    let isRouting = false;  // True while a routing request is in progress
    let pendingCursorUpdate = false;  // True if cursor moved while routing

    // Expose state for debugging/testing
    window.getRoutingState = () => ({
        isRouting,
        routingSession,
        appMode,
        pendingCursorUpdate
    });

    /**
     * Initialize the application.
     */
    async function init() {
        // Create viewer instance
        const container = document.getElementById('svg-container');
        viewer = new SVGViewer(container);

        // Load board info
        await loadBoardInfo();

        // Load SVG
        await loadSVG();

        // Setup event listeners
        setupLayerControls();
        setupPadClickHandler();
        setupKeyboardShortcuts();
        setupTraceModeControls();
    }

    /**
     * Load and display board info.
     */
    async function loadBoardInfo() {
        try {
            const response = await fetch('/api/pcb/info');
            const data = await response.json();

            const infoEl = document.getElementById('board-info');
            infoEl.innerHTML = `
                <p>Size: <span class="value">${data.bounds.width.toFixed(1)} x ${data.bounds.height.toFixed(1)} mm</span></p>
                <p>Footprints: <span class="value">${data.counts.footprints}</span></p>
                <p>Pads: <span class="value">${data.counts.pads}</span></p>
                <p>Traces: <span class="value">${data.counts.traces}</span></p>
                <p>Vias: <span class="value">${data.counts.vias}</span></p>
                <p>Nets: <span class="value">${data.counts.nets}</span></p>
            `;
        } catch (error) {
            console.error('Failed to load board info:', error);
        }
    }

    /**
     * Load the SVG from the API.
     */
    async function loadSVG() {
        try {
            const response = await fetch('/api/svg');
            const svgContent = await response.text();
            viewer.loadSVG(svgContent);
        } catch (error) {
            console.error('Failed to load SVG:', error);
        }
    }

    /**
     * Setup layer visibility controls.
     */
    function setupLayerControls() {
        const checkboxes = document.querySelectorAll('#layer-controls input[type="checkbox"]');

        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const layer = e.target.dataset.layer;
                viewer.toggleLayer(layer, e.target.checked);
            });
        });
    }

    /**
     * Find the best pad/via match at click coordinates.
     */
    function findBestMatchAtPoint(clickX, clickY) {
        // Get all elements at click point
        const elements = document.elementsFromPoint(clickX, clickY);

        // Find all pads and vias at this point
        const padsAtPoint = elements.filter(el => el.classList.contains('pad'));
        const viasAtPoint = elements.filter(el => el.classList.contains('via'));

        // Find the pad/via whose center is closest to click point
        let bestMatch = null;
        let bestDistance = Infinity;

        for (const pad of padsAtPoint) {
            const rect = pad.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2;
            const centerY = rect.y + rect.height / 2;
            const distance = Math.sqrt((clickX - centerX) ** 2 + (clickY - centerY) ** 2);
            if (distance < bestDistance) {
                bestDistance = distance;
                bestMatch = pad;
            }
        }

        for (const via of viasAtPoint) {
            const rect = via.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2;
            const centerY = rect.y + rect.height / 2;
            const distance = Math.sqrt((clickX - centerX) ** 2 + (clickY - centerY) ** 2);
            if (distance < bestDistance) {
                bestDistance = distance;
                bestMatch = via;
            }
        }

        return bestMatch;
    }

    /**
     * Setup click handler for pad and via selection.
     */
    function setupPadClickHandler() {
        const container = document.getElementById('svg-container');

        // Mouse move: continuous routing preview
        container.addEventListener('mousemove', (e) => {
            if (appMode === 'trace' && routingSession) {
                handleTraceMouseMove(e);
            }
        });

        // Single click: commit segment, make click point the new start
        container.addEventListener('click', (e) => {
            const bestMatch = findBestMatchAtPoint(e.clientX, e.clientY);

            if (appMode === 'trace') {
                handleTraceClick(e, bestMatch);
            } else if (bestMatch) {
                const netId = parseInt(bestMatch.dataset.net, 10);
                selectNet(netId, bestMatch.dataset.netName);
            }
        });

        // Double-click: commit and end routing
        container.addEventListener('dblclick', (e) => {
            if (appMode === 'trace' && routingSession) {
                e.preventDefault();
                e.stopPropagation();
                handleTraceDoubleClick(e);
            }
        });
    }

    /**
     * Get target coordinates from a click event and optional element.
     */
    function getTargetCoordinates(e, clickedElement) {
        const svgPoint = viewer.screenToSVG(e.clientX, e.clientY);
        let targetX = svgPoint.x;
        let targetY = svgPoint.y;

        if (clickedElement) {
            // Try data attributes first, then SVG attributes
            const dataX = clickedElement.dataset.x;
            const dataY = clickedElement.dataset.y;
            const cx = clickedElement.getAttribute('cx');
            const cy = clickedElement.getAttribute('cy');

            if (dataX && dataY) {
                targetX = parseFloat(dataX);
                targetY = parseFloat(dataY);
            } else if (cx && cy) {
                targetX = parseFloat(cx);
                targetY = parseFloat(cy);
            }
        }

        return { x: targetX, y: targetY };
    }

    /**
     * Handle mouse move in trace mode.
     * Continuously routes to cursor position.
     */
    function handleTraceMouseMove(e) {
        if (!routingSession) return;

        const svgPoint = viewer.screenToSVG(e.clientX, e.clientY);
        routingSession.cursorPoint = { x: svgPoint.x, y: svgPoint.y };

        // If currently routing, mark that we have a pending update
        if (isRouting) {
            pendingCursorUpdate = true;
            return;
        }

        // Start routing immediately
        routeToCursor();
    }

    /**
     * Route from start point to current cursor position.
     * Chains requests: starts next route as soon as previous completes.
     */
    async function routeToCursor() {
        if (!routingSession || !routingSession.cursorPoint) return;
        if (isRouting) return;  // Already routing

        const { startPoint, cursorPoint } = routingSession;

        // Don't route if start and cursor are the same
        const dist = Math.sqrt(
            (cursorPoint.x - startPoint.x) ** 2 +
            (cursorPoint.y - startPoint.y) ** 2
        );
        if (dist < 0.1) {
            return;
        }

        isRouting = true;
        pendingCursorUpdate = false;

        try {
            const response = await fetch('/api/route', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_x: startPoint.x,
                    start_y: startPoint.y,
                    end_x: cursorPoint.x,
                    end_y: cursorPoint.y,
                    layer: routingSession.currentLayer,
                    width: routingSession.width,
                    net_id: routingSession.startNet
                })
            });

            const data = await response.json();

            // Only update if we still have an active session
            if (routingSession) {
                if (data.success && data.path.length > 0) {
                    routingSession.pendingPath = data.path;

                    // Clear and render new preview
                    viewer.clearPendingTrace();
                    viewer.renderPendingTrace(data.path, routingSession.currentLayer, routingSession.width);

                    hideTraceError();
                } else {
                    routingSession.pendingPath = null;
                    viewer.clearPendingTrace();
                }
            }
        } catch (error) {
            console.error('Routing error:', error);
            if (routingSession) {
                routingSession.pendingPath = null;
            }
        } finally {
            isRouting = false;

            // If cursor moved while we were routing, immediately start another route
            if (pendingCursorUpdate && routingSession) {
                pendingCursorUpdate = false;
                routeToCursor();
            }
        }
    }

    /**
     * Handle single click in trace mode.
     * - First click: sets start point
     * - Subsequent clicks: commits current segment, click point becomes new start
     */
    async function handleTraceClick(e, clickedElement) {
        const layer = document.getElementById('trace-layer').value;
        const width = parseFloat(document.getElementById('trace-width').value);
        const target = getTargetCoordinates(e, clickedElement);

        if (!routingSession) {
            // First click - start routing session
            const startNet = clickedElement ? parseInt(clickedElement.dataset.net, 10) : null;

            // Detect layer from clicked element
            let startLayer = layer;
            if (clickedElement) {
                const elementLayer = clickedElement.dataset.layer;
                if (elementLayer && ['F.Cu', 'B.Cu', 'In1.Cu', 'In2.Cu'].includes(elementLayer)) {
                    startLayer = elementLayer;
                    document.getElementById('trace-layer').value = startLayer;
                }
            }

            routingSession = {
                startNet: startNet,
                startPoint: { x: target.x, y: target.y },
                cursorPoint: { x: target.x, y: target.y },
                pendingPath: null,
                sessionSegments: [],
                sessionVias: [],
                currentLayer: startLayer,
                width: width
            };

            // Highlight all elements of the same net
            if (startNet && startNet > 0) {
                viewer.highlightRoutingNet(startNet);
            }

            viewer.showStartMarker(target.x, target.y);
            updateTraceStatus('Move mouse to route, click to commit, 1-4 for via+layer, dbl-click to end', 'routing');
            document.getElementById('trace-actions').classList.remove('hidden');
        } else {
            // Subsequent click - commit segment at click point, make it new start
            routingSession.cursorPoint = { x: target.x, y: target.y };

            // Route to click point and commit
            await routeToCursor();
            await commitCurrentSegment(target.x, target.y);
        }
    }

    /**
     * Handle double-click in trace mode.
     * Commits current segment and ends routing.
     */
    async function handleTraceDoubleClick(e) {
        if (!routingSession) return;

        const bestMatch = findBestMatchAtPoint(e.clientX, e.clientY);
        const target = getTargetCoordinates(e, bestMatch);

        // Route to double-click point
        routingSession.cursorPoint = { x: target.x, y: target.y };
        await routeToCursor();

        // Commit if there's a path
        if (routingSession.pendingPath) {
            await commitCurrentSegment(target.x, target.y);
        }

        // End routing session (keep committed traces)
        finishRoutingSession();
    }

    /**
     * Commit the current pending segment and move start to new point.
     */
    async function commitCurrentSegment(newStartX, newStartY) {
        if (!routingSession || !routingSession.pendingPath) return;

        // Confirm the pending segment
        const segment = {
            path: routingSession.pendingPath,
            layer: routingSession.currentLayer,
            width: routingSession.width
        };
        routingSession.sessionSegments.push(segment);
        userTraces.push({ ...segment });

        // Render as confirmed
        viewer.confirmPendingTrace(segment.path, segment.layer, segment.width);

        // Move start point to new position
        routingSession.startPoint = { x: newStartX, y: newStartY };
        routingSession.cursorPoint = { x: newStartX, y: newStartY };
        routingSession.pendingPath = null;

        // Update start marker
        viewer.showStartMarker(newStartX, newStartY);

        updateTraceStatus('Segment committed! Move mouse to continue', 'success');
    }

    /**
     * Handle layer switching with via placement.
     * Places via at current cursor position and makes it the new start point.
     */
    async function handleLayerSwitch(newLayer) {
        if (!routingSession || !routingSession.cursorPoint) return;
        if (newLayer === routingSession.currentLayer) return;

        const { x, y } = routingSession.cursorPoint;
        const viaSize = 0.8;

        // Check via placement
        try {
            const response = await fetch('/api/check-via', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    x: x,
                    y: y,
                    size: viaSize,
                    drill: 0.4,
                    net_id: routingSession.startNet
                })
            });

            const data = await response.json();

            if (!data.valid) {
                showTraceError(data.message);
                return;
            }

            // Commit pending path if we have one
            if (routingSession.pendingPath) {
                const path = routingSession.pendingPath;
                const lastPoint = path[path.length - 1];
                await commitCurrentSegment(lastPoint[0], lastPoint[1]);
            }

            // Add via at cursor position
            routingSession.sessionVias.push({ x, y, size: viaSize });
            viewer.renderUserVia(x, y, viaSize, false);

            // Switch layer and set via location as new start point
            routingSession.currentLayer = newLayer;
            routingSession.startPoint = { x, y };
            routingSession.cursorPoint = { x, y };
            routingSession.pendingPath = null;

            document.getElementById('trace-layer').value = newLayer;

            // Stop any ongoing routing
            pendingCursorUpdate = false;

            // Update start marker
            viewer.clearPendingTrace();
            viewer.showStartMarker(x, y);

            updateTraceStatus(`Via placed, now on ${newLayer}`, 'success');
            hideTraceError();
        } catch (error) {
            console.error('Via check error:', error);
            showTraceError('Failed to check via placement');
        }
    }

    /**
     * Finish routing session - keep all committed traces.
     */
    function finishRoutingSession() {
        if (!routingSession) return;

        viewer.clearPendingElements();

        const segmentCount = routingSession.sessionSegments.length;
        const viaCount = routingSession.sessionVias.length;

        updateTraceStatus(`Done: ${segmentCount} segment(s), ${viaCount} via(s)`, 'success');
        resetTraceState();
    }

    /**
     * Cancel routing session - remove ALL traces added since start.
     */
    function cancelRoutingSession() {
        if (!routingSession) return;

        // Remove all segments added in this session from userTraces
        for (const segment of routingSession.sessionSegments) {
            const idx = userTraces.indexOf(segment);
            if (idx >= 0) {
                userTraces.splice(idx, 1);
            }
        }

        // Remove visual elements - clear user traces group and rebuild
        viewer.clearPendingElements();
        viewer.removeSessionTraces(routingSession.sessionSegments, routingSession.sessionVias);

        updateTraceStatus('Routing cancelled - all changes undone', '');
        resetTraceState();
    }

    /**
     * Update trace status message.
     */
    function updateTraceStatus(message, className) {
        const statusEl = document.getElementById('trace-status');
        statusEl.textContent = message;
        statusEl.className = className || '';
    }

    /**
     * Show trace error message.
     */
    function showTraceError(message) {
        const errorEl = document.getElementById('trace-error');
        errorEl.textContent = message;
        errorEl.classList.remove('hidden');

        // Auto-hide after 3 seconds
        setTimeout(() => hideTraceError(), 3000);
    }

    /**
     * Hide trace error message.
     */
    function hideTraceError() {
        const errorEl = document.getElementById('trace-error');
        errorEl.classList.add('hidden');
    }

    /**
     * Reset trace mode state (internal).
     */
    function resetTraceState() {
        isRouting = false;
        pendingCursorUpdate = false;
        // Clear routing net highlight
        viewer.clearRoutingHighlight();
        routingSession = null;
        document.getElementById('trace-actions').classList.add('hidden');
        hideTraceError();
        updateTraceStatus('Click a pad to start', '');
    }

    /**
     * Confirm button: finish routing and keep traces.
     */
    function confirmTrace() {
        finishRoutingSession();
    }

    /**
     * Cancel button: undo all traces from this session.
     */
    function cancelTrace() {
        cancelRoutingSession();
    }

    /**
     * Toggle trace mode.
     */
    function toggleTraceMode() {
        const toggleBtn = document.getElementById('trace-mode-toggle');
        const optionsEl = document.getElementById('trace-options');

        if (appMode === 'select') {
            appMode = 'trace';
            toggleBtn.textContent = 'Disable Trace Mode';
            toggleBtn.classList.add('active');
            optionsEl.classList.remove('hidden');
            document.body.classList.add('trace-mode-active');
            clearSelection();
        } else {
            appMode = 'select';
            toggleBtn.textContent = 'Enable Trace Mode';
            toggleBtn.classList.remove('active');
            optionsEl.classList.add('hidden');
            document.body.classList.remove('trace-mode-active');
            resetTraceState();
        }
    }

    /**
     * Setup trace mode controls.
     */
    function setupTraceModeControls() {
        document.getElementById('trace-mode-toggle').addEventListener('click', toggleTraceMode);
        document.getElementById('trace-confirm').addEventListener('click', confirmTrace);
        document.getElementById('trace-cancel').addEventListener('click', cancelTrace);
    }

    /**
     * Select a net and highlight its pads.
     */
    async function selectNet(netId, netName) {
        selectedNetId = netId;
        viewer.highlightNet(netId);

        // Update selection info
        const selectionEl = document.getElementById('selection-info');

        if (netId === 0) {
            selectionEl.innerHTML = '<p class="hint">Unconnected pad</p>';
            return;
        }

        try {
            const response = await fetch(`/api/net/${netId}`);
            const data = await response.json();

            const padList = data.pads.map(p =>
                `<div class="pad-item">${p.footprint}.${p.pad}</div>`
            ).join('');

            selectionEl.innerHTML = `
                <div class="net-name">${data.name || `Net ${netId}`}</div>
                <p>Pads: ${data.pads.length}</p>
                <div class="pad-list">${padList}</div>
            `;
        } catch (error) {
            console.error('Failed to load net info:', error);
        }
    }

    /**
     * Clear the current selection.
     */
    function clearSelection() {
        selectedNetId = null;
        viewer.highlightNet(null);

        const selectionEl = document.getElementById('selection-info');
        selectionEl.innerHTML = '<p class="hint">Click a pad to see its net</p>';
    }

    /**
     * Setup keyboard shortcuts.
     */
    function setupKeyboardShortcuts() {
        const layerMap = { '1': 'F.Cu', '2': 'B.Cu', '3': 'In1.Cu', '4': 'In2.Cu' };

        document.addEventListener('keydown', (e) => {
            // Ignore if typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
                return;
            }

            if (e.key === 'Escape') {
                if (appMode === 'trace' && routingSession) {
                    // Cancel routing - remove all traces from this session
                    cancelRoutingSession();
                } else if (appMode === 'trace') {
                    toggleTraceMode();
                } else {
                    clearSelection();
                }
            } else if (e.key === 't' || e.key === 'T') {
                toggleTraceMode();
            } else if (appMode === 'trace' && routingSession && layerMap[e.key]) {
                // Layer switching with via (1=F.Cu, 2=B.Cu, 3=In1.Cu, 4=In2.Cu)
                handleLayerSwitch(layerMap[e.key]);
            }
        });
    }

    // Start the application when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
