/**
 * Main application entry point.
 */
(function() {
    'use strict';

    // Global state
    let viewer = null;
    let selectedNetId = null;

    // Segment selection state
    let selectedSegments = [];  // [{routeId, segmentIndex}, ...]

    // Routes: { id, segments: [{path, layer, width}], netId, visible }
    // Each route groups all segments from one routing session (start to double-click)
    let userRoutes = [];
    let nextRouteId = 1;
    let lastHoveredNetId = null;

    // Layer colors for route list indicators
    const LAYER_COLORS = {
        'F.Cu': '#C83232',
        'B.Cu': '#3232C8',
        'In1.Cu': '#C8C832',
        'In2.Cu': '#32C8C8'
    };

    /**
     * Generate a unique route ID.
     */
    function generateRouteId() {
        return `route-${nextRouteId++}`;
    }

    /**
     * Get the primary layer for a route (most common layer among segments).
     */
    function getRoutePrimaryLayer(route) {
        if (!route.segments || route.segments.length === 0) return 'F.Cu';
        // Return the layer of the first segment
        return route.segments[0].layer;
    }

    /**
     * Get the primary width for a route.
     */
    function getRoutePrimaryWidth(route) {
        if (!route.segments || route.segments.length === 0) return 0.25;
        return route.segments[0].width;
    }

    /**
     * Add a route to the routes list UI.
     */
    function addRouteToList(route) {
        const listEl = document.getElementById('routes-list');
        const hintEl = listEl.querySelector('.hint');

        // Remove the "No routes yet" hint
        if (hintEl) {
            hintEl.remove();
        }

        // Create route item
        const item = document.createElement('div');
        item.className = 'route-item';
        item.dataset.routeId = route.id;

        const layer = getRoutePrimaryLayer(route);
        const width = getRoutePrimaryWidth(route);
        const color = LAYER_COLORS[layer] || '#888888';
        const routeNum = route.id.replace('route-', '');
        const segCount = route.segments.length;

        item.innerHTML = `
            <button class="toggle-btn" title="Toggle visibility">&#128065;</button>
            <span class="layer-indicator" style="background: ${color}"></span>
            <span class="route-label">Route ${routeNum} - ${layer} (${segCount} seg)</span>
            <button class="remove-btn" title="Remove route">&times;</button>
        `;

        // Toggle visibility handler
        item.querySelector('.toggle-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            toggleRouteVisibility(route.id);
        });

        // Remove handler
        item.querySelector('.remove-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            removeRoute(route.id);
        });

        listEl.appendChild(item);
        updateRouteCount();
        updateClearAllButton();

        // Notify backend about each segment in this route
        registerRouteWithBackend(route);
    }

    /**
     * Remove a route from the list and SVG.
     */
    function removeRoute(routeId) {
        // Find the route first to get segment count for backend cleanup
        const idx = userRoutes.findIndex(r => r.id === routeId);
        const segmentCount = idx >= 0 ? userRoutes[idx].segments.length : 0;

        // Remove from userRoutes array
        if (idx >= 0) {
            userRoutes.splice(idx, 1);
        }

        // Remove all SVG elements for this route
        viewer.removeTraceById(routeId);

        // Remove from list UI
        const item = document.querySelector(`.route-item[data-route-id="${routeId}"]`);
        if (item) {
            item.remove();
        }

        // Show hint if list is empty
        const listEl = document.getElementById('routes-list');
        if (listEl.children.length === 0) {
            listEl.innerHTML = '<p class="hint">No routes yet</p>';
        }

        updateRouteCount();
        updateClearAllButton();

        // Notify backend to remove all segments of this route
        unregisterRouteFromBackend(routeId, segmentCount);
    }

    /**
     * Toggle visibility of a route (all its segments).
     */
    function toggleRouteVisibility(routeId) {
        const route = userRoutes.find(r => r.id === routeId);
        if (!route) return;

        route.visible = !route.visible;
        viewer.setTraceVisible(routeId, route.visible);

        // Update UI
        const item = document.querySelector(`.route-item[data-route-id="${routeId}"]`);
        if (item) {
            item.classList.toggle('hidden-route', !route.visible);
            const toggleBtn = item.querySelector('.toggle-btn');
            toggleBtn.classList.toggle('hidden-icon', !route.visible);
        }
    }

    /**
     * Update the route count display.
     */
    function updateRouteCount() {
        const countEl = document.getElementById('route-count');
        countEl.textContent = `(${userRoutes.length})`;
    }

    /**
     * Update the Clear All button state.
     */
    function updateClearAllButton() {
        const btn = document.getElementById('clear-all-routes');
        btn.disabled = userRoutes.length === 0;
    }

    /**
     * Clear all user routes.
     */
    function clearAllRoutes() {
        // Clear SVG
        viewer.clearAllUserTraces();

        // Clear backend
        clearAllTracesFromBackend();

        // Clear state
        userRoutes = [];

        // Reset UI
        const listEl = document.getElementById('routes-list');
        listEl.innerHTML = '<p class="hint">No routes yet</p>';

        updateRouteCount();
        updateClearAllButton();
    }

    /**
     * Register a route with the backend for clearance checking.
     * Each segment is registered separately with unique IDs.
     */
    async function registerRouteWithBackend(route) {
        for (let i = 0; i < route.segments.length; i++) {
            const seg = route.segments[i];
            const segmentId = `${route.id}-seg${i}`;
            try {
                await fetch('/api/traces', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: segmentId,
                        segments: seg.path,
                        width: seg.width,
                        layer: seg.layer,
                        net_id: route.netId || null
                    })
                });
            } catch (error) {
                console.error('Failed to register segment with backend:', error);
            }
        }
    }

    /**
     * Unregister a route from the backend (all its segments).
     */
    async function unregisterRouteFromBackend(routeId, segmentCount) {
        for (let i = 0; i < segmentCount; i++) {
            const segmentId = `${routeId}-seg${i}`;
            try {
                await fetch(`/api/traces/${segmentId}`, {
                    method: 'DELETE'
                });
            } catch (error) {
                // Ignore errors for non-existent segments
            }
        }
    }

    /**
     * Clear all traces from backend.
     */
    async function clearAllTracesFromBackend() {
        try {
            await fetch('/api/traces', {
                method: 'DELETE'
            });
        } catch (error) {
            console.error('Failed to clear traces from backend:', error);
        }
    }

    /**
     * Clear segment selection and highlights.
     */
    function clearSegmentSelection() {
        selectedSegments = [];
        viewer.clearSegmentHighlights();
    }

    /**
     * Select a single segment (clears previous selection).
     * @param {string} routeId - The route ID
     * @param {number} segmentIndex - The segment index
     */
    function selectSegment(routeId, segmentIndex) {
        clearSegmentSelection();
        selectedSegments = [{ routeId, segmentIndex }];
        viewer.highlightSegments(selectedSegments);
    }

    /**
     * Toggle a segment in the selection (for shift+click multi-select).
     * @param {string} routeId - The route ID
     * @param {number} segmentIndex - The segment index
     */
    function toggleSegmentSelection(routeId, segmentIndex) {
        const idx = selectedSegments.findIndex(
            s => s.routeId === routeId && s.segmentIndex === segmentIndex
        );

        if (idx >= 0) {
            // Already selected - remove it
            selectedSegments.splice(idx, 1);
        } else {
            // Not selected - add it
            selectedSegments.push({ routeId, segmentIndex });
        }

        // Update highlights
        viewer.clearSegmentHighlights();
        viewer.highlightSegments(selectedSegments);
    }

    /**
     * Select all segments in a route (for double-click).
     * @param {string} routeId - The route ID
     */
    function selectFullRoute(routeId) {
        const route = userRoutes.find(r => r.id === routeId);
        if (!route) return;

        clearSegmentSelection();

        // Add all segments from this route
        for (let i = 0; i < route.segments.length; i++) {
            selectedSegments.push({ routeId, segmentIndex: i });
        }

        viewer.highlightSegments(selectedSegments);
    }

    /**
     * Delete all selected segments.
     */
    async function deleteSelectedSegments() {
        if (selectedSegments.length === 0) return;

        // Group selected segments by route
        const segmentsByRoute = {};
        for (const seg of selectedSegments) {
            if (!segmentsByRoute[seg.routeId]) {
                segmentsByRoute[seg.routeId] = [];
            }
            segmentsByRoute[seg.routeId].push(seg.segmentIndex);
        }

        // Process each route
        for (const routeId of Object.keys(segmentsByRoute)) {
            const route = userRoutes.find(r => r.id === routeId);
            if (!route) continue;

            // Sort indices in descending order to remove from end first
            const indices = segmentsByRoute[routeId].sort((a, b) => b - a);

            for (const segmentIndex of indices) {
                // Remove from SVG
                viewer.removeSegment(routeId, segmentIndex);

                // Delete from backend
                const segmentId = `${routeId}-seg${segmentIndex}`;
                try {
                    await fetch(`/api/traces/${segmentId}`, { method: 'DELETE' });
                } catch (error) {
                    // Ignore errors for non-existent segments
                }

                // Remove from route.segments array
                if (segmentIndex < route.segments.length) {
                    route.segments.splice(segmentIndex, 1);
                }
            }

            // If route is now empty, remove it entirely
            if (route.segments.length === 0) {
                const idx = userRoutes.findIndex(r => r.id === routeId);
                if (idx >= 0) {
                    userRoutes.splice(idx, 1);
                }

                // Remove from list UI
                const item = document.querySelector(`.route-item[data-route-id="${routeId}"]`);
                if (item) {
                    item.remove();
                }
            } else {
                // Re-index remaining segments
                reindexRouteSegments(routeId);
                updateRouteListItem(routeId);
            }
        }

        // Show hint if list is empty
        const listEl = document.getElementById('routes-list');
        if (listEl.children.length === 0) {
            listEl.innerHTML = '<p class="hint">No routes yet</p>';
        }

        updateRouteCount();
        updateClearAllButton();
        clearSegmentSelection();
    }

    /**
     * Re-index route segments after deletion.
     * Updates both SVG data attributes and backend IDs.
     * @param {string} routeId - The route ID
     */
    async function reindexRouteSegments(routeId) {
        const route = userRoutes.find(r => r.id === routeId);
        if (!route) return;

        // Update SVG attributes for each remaining segment
        for (let i = 0; i < route.segments.length; i++) {
            // Find elements that might have wrong indices and update them
            // We need to find elements by route ID and then fix their indices
            const traces = document.querySelectorAll(`.user-trace[data-trace-id="${routeId}"]`);
            const vias = document.querySelectorAll(`.user-via[data-trace-id="${routeId}"]`);
            const holes = document.querySelectorAll(`.user-via-hole[data-trace-id="${routeId}"]`);

            // Collect all elements and sort by their current index to maintain order
            const allElements = [...traces, ...vias, ...holes];
            const elementsByIndex = {};
            for (const el of allElements) {
                const idx = el.getAttribute('data-segment-index');
                if (!elementsByIndex[idx]) {
                    elementsByIndex[idx] = [];
                }
                elementsByIndex[idx].push(el);
            }

            // Reassign indices sequentially
            const sortedIndices = Object.keys(elementsByIndex).map(Number).sort((a, b) => a - b);
            for (let newIdx = 0; newIdx < sortedIndices.length; newIdx++) {
                const oldIdx = sortedIndices[newIdx];
                if (oldIdx !== newIdx) {
                    for (const el of elementsByIndex[oldIdx]) {
                        el.setAttribute('data-segment-index', newIdx.toString());
                    }
                }
            }
        }

        // Re-register all segments with backend with correct IDs
        for (let i = 0; i < route.segments.length; i++) {
            const seg = route.segments[i];
            const segmentId = `${routeId}-seg${i}`;
            try {
                await fetch('/api/traces', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: segmentId,
                        segments: seg.path,
                        width: seg.width,
                        layer: seg.layer,
                        net_id: route.netId || null
                    })
                });
            } catch (error) {
                console.error('Failed to re-register segment:', error);
            }
        }
    }

    /**
     * Update a route's list item to reflect current segment count.
     * @param {string} routeId - The route ID
     */
    function updateRouteListItem(routeId) {
        const route = userRoutes.find(r => r.id === routeId);
        if (!route) return;

        const item = document.querySelector(`.route-item[data-route-id="${routeId}"]`);
        if (!item) return;

        const layer = getRoutePrimaryLayer(route);
        const color = LAYER_COLORS[layer] || '#888888';
        const routeNum = route.id.replace('route-', '');
        const segCount = route.segments.length;

        const label = item.querySelector('.route-label');
        if (label) {
            label.textContent = `Route ${routeNum} - ${layer} (${segCount} seg)`;
        }

        const indicator = item.querySelector('.layer-indicator');
        if (indicator) {
            indicator.style.background = color;
        }
    }

    // Continuous routing session state
    // - Mouse move: continuously routes to cursor position (debounced)
    // - Single click: commits segment, clicked point becomes new start
    // - 1-4 keys: place via at cursor, switch layer, cursor becomes new start
    // - Double click: commits and ends routing
    // - Escape: removes all traces added in this session
    let routingSession = null;
    // {
    //   routeId: string,               // Unique ID for this route (all segments share this)
    //   startNet: number,              // Net ID from initial pad
    //   startPoint: {x, y},            // Current start point
    //   cursorPoint: {x, y},           // Current cursor position
    //   pendingPath: array,            // Current route preview to cursor
    //   sessionSegments: [],           // Segments added in this session: [{path, layer, width}]
    //   sessionVias: [],               // Vias added in this session (for undo)
    //   currentLayer: string,
    //   width: number
    // }

    // Routing state for continuous updates
    let isRouting = false;  // True while a routing request is in progress
    let pendingCursorUpdate = false;  // True if cursor moved while routing
    let routeDebounceTimer = null;    // Timer for debouncing route requests
    let routeAbortController = null;  // AbortController for canceling in-flight requests
    const ROUTE_DEBOUNCE_MS = 0;      // Route immediately (no delay)

    // Expose state for debugging/testing
    window.getRoutingState = () => ({
        isRouting,
        routingSession,
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
        setupControls();

        // Load any persisted pending traces
        await loadPendingTraces();
    }

    /**
     * Load pending traces from the backend and render them.
     */
    async function loadPendingTraces() {
        try {
            const response = await fetch('/api/traces');
            const data = await response.json();

            if (!data.traces || data.traces.length === 0) {
                return;
            }

            // Group traces by route ID (strip segment suffix like "-seg0")
            const routeGroups = new Map();
            for (const trace of data.traces) {
                // Extract base route ID (e.g., "route-1-seg0" -> "route-1")
                const match = trace.id.match(/^(route-\d+)/);
                const baseRouteId = match ? match[1] : trace.id;

                if (!routeGroups.has(baseRouteId)) {
                    routeGroups.set(baseRouteId, {
                        id: baseRouteId,
                        netId: trace.net_id,
                        segments: [],
                        visible: true
                    });
                }

                const route = routeGroups.get(baseRouteId);
                route.segments.push({
                    path: trace.segments,
                    layer: trace.layer,
                    width: trace.width,
                    backendId: trace.id  // Keep track of backend ID for deletion
                });
            }

            // Add each route to userRoutes and render
            for (const [routeId, route] of routeGroups) {
                // Extract route number to update nextRouteId
                const numMatch = routeId.match(/route-(\d+)/);
                if (numMatch) {
                    const num = parseInt(numMatch[1], 10);
                    if (num >= nextRouteId) {
                        nextRouteId = num + 1;
                    }
                }

                userRoutes.push(route);

                // Render each segment
                route.segments.forEach((seg, idx) => {
                    viewer.confirmPendingTrace(
                        seg.path,
                        seg.layer,
                        seg.width,
                        route.id,
                        idx,
                        route.netId
                    );
                });

                // Add to UI list
                addRouteToList(route);
            }

            console.log(`Loaded ${routeGroups.size} pending routes from backend`);
        } catch (error) {
            console.error('Failed to load pending traces:', error.message || error);
            console.error('Stack:', error.stack);
        }
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
     * Find the best pad/via/trace/user-trace match at click coordinates.
     * @returns {Object|null} { type: 'pad'|'via'|'trace'|'user-trace'|'user-via', element: Element } or null
     */
    function findBestMatchAtPoint(clickX, clickY) {
        // Get all elements at click point
        const elements = document.elementsFromPoint(clickX, clickY);

        // Find all element types at this point
        const padsAtPoint = elements.filter(el => el.classList.contains('pad'));
        const viasAtPoint = elements.filter(el => el.classList.contains('via') && !el.classList.contains('user-via'));
        const tracesAtPoint = elements.filter(el => el.classList.contains('trace'));
        const userTracesAtPoint = elements.filter(el => el.classList.contains('user-trace'));
        const userViasAtPoint = elements.filter(el => el.classList.contains('user-via'));

        // Find the element whose center is closest to click point
        let bestMatch = null;
        let bestDistance = Infinity;
        let bestType = null;

        // Check user traces first (they're on top)
        for (const trace of userTracesAtPoint) {
            // For paths, use a small fixed distance since they're lines
            const distance = 5;  // Prioritize if clicked directly
            if (distance < bestDistance) {
                bestDistance = distance;
                bestMatch = trace;
                bestType = 'user-trace';
            }
        }

        // Check user vias
        for (const via of userViasAtPoint) {
            const rect = via.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2;
            const centerY = rect.y + rect.height / 2;
            const distance = Math.sqrt((clickX - centerX) ** 2 + (clickY - centerY) ** 2);
            if (distance < bestDistance) {
                bestDistance = distance;
                bestMatch = via;
                bestType = 'user-via';
            }
        }

        // Check pads
        for (const pad of padsAtPoint) {
            const rect = pad.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2;
            const centerY = rect.y + rect.height / 2;
            const distance = Math.sqrt((clickX - centerX) ** 2 + (clickY - centerY) ** 2);
            if (distance < bestDistance) {
                bestDistance = distance;
                bestMatch = pad;
                bestType = 'pad';
            }
        }

        // Check vias
        for (const via of viasAtPoint) {
            const rect = via.getBoundingClientRect();
            const centerX = rect.x + rect.width / 2;
            const centerY = rect.y + rect.height / 2;
            const distance = Math.sqrt((clickX - centerX) ** 2 + (clickY - centerY) ** 2);
            if (distance < bestDistance) {
                bestDistance = distance;
                bestMatch = via;
                bestType = 'via';
            }
        }

        // Check board traces (lowest priority - they're background elements)
        for (const trace of tracesAtPoint) {
            // For paths, use a moderate fixed distance
            const distance = 10;
            if (distance < bestDistance) {
                bestDistance = distance;
                bestMatch = trace;
                bestType = 'trace';
            }
        }

        if (bestMatch) {
            return { type: bestType, element: bestMatch };
        }
        return null;
    }

    /**
     * Setup click handler for pad and via selection.
     */
    function setupPadClickHandler() {
        const container = document.getElementById('svg-container');

        // Mouse move: continuous routing preview when routing
        container.addEventListener('mousemove', (e) => {
            if (routingSession) {
                handleRoutingMouseMove(e);
            }
            handleNetHover(e);
        });

        container.addEventListener('mouseleave', () => {
            viewer.highlightHoverNet(null);
            lastHoveredNetId = null;
        });

        // Single click: select net/segment, or commit segment when routing
        container.addEventListener('click', (e) => {
            const match = findBestMatchAtPoint(e.clientX, e.clientY);

            if (routingSession) {
                // When routing, click commits segment
                const element = match ? match.element : null;
                handleRoutingClick(e, element);
            } else {
                // Not routing - handle selection
                if (match) {
                    if (match.type === 'user-trace' || match.type === 'user-via') {
                        // Clicked on a user-created segment
                        const routeId = match.element.dataset.traceId;
                        const segmentIndex = parseInt(match.element.dataset.segmentIndex, 10);

                        if (routeId && !isNaN(segmentIndex)) {
                            if (e.shiftKey) {
                                // Shift+click: toggle selection
                                toggleSegmentSelection(routeId, segmentIndex);
                            } else {
                                // Regular click: select only this segment
                                selectSegment(routeId, segmentIndex);
                                const netId = parseInt(match.element.dataset.net, 10);
                                if (netId > 0) {
                                    selectNet(netId, match.element.dataset.netName);
                                }
                            }
                        }
                    } else if (match.type === 'pad' || match.type === 'via' || match.type === 'trace') {
                        // Clicked on a pad, via, or trace - clear segment selection and show net
                        clearSegmentSelection();
                        const netId = parseInt(match.element.dataset.net, 10);
                        selectNet(netId, match.element.dataset.netName);
                    }
                } else {
                    // Clicked on empty space - clear selection
                    clearSegmentSelection();
                    clearSelection();
                }
            }
        });

        // Double-click: start routing or finish routing
        container.addEventListener('dblclick', (e) => {
            e.preventDefault();
            e.stopPropagation();
            handleDoubleClick(e);
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
     * Handle mouse move when routing.
     * Continuously routes to cursor position.
     */
    function handleRoutingMouseMove(e) {
        if (!routingSession) return;

        let svgPoint = viewer.screenToSVG(e.clientX, e.clientY);

        // Snap to pad or via center if mouse is over one
        const match = findBestMatchAtPoint(e.clientX, e.clientY);
        if (match && (match.type === 'pad' || match.type === 'via')) {
            const element = match.element;
            const dataX = element.dataset.x;
            const dataY = element.dataset.y;
            const cx = element.getAttribute('cx');
            const cy = element.getAttribute('cy');

            if (dataX && dataY) {
                svgPoint = { x: parseFloat(dataX), y: parseFloat(dataY) };
            } else if (cx && cy) {
                svgPoint = { x: parseFloat(cx), y: parseFloat(cy) };
            }
        }

        routingSession.cursorPoint = { x: svgPoint.x, y: svgPoint.y };

        // If currently routing, mark that we have a pending update
        if (isRouting) {
            pendingCursorUpdate = true;
            return;
        }

        // Route immediately - chaining handles continuous updates
        routeToCursor(true);  // Skip endpoint check for mouse move preview
    }

    /**
     * Handle mouse hovering over elements to highlight same-net items.
     */
    function handleNetHover(e) {
        // Don't show hover highlight when actively routing
        if (routingSession) {
            if (lastHoveredNetId !== null) {
                viewer.highlightHoverNet(null);
                lastHoveredNetId = null;
            }
            return;
        }

        const match = findBestMatchAtPoint(e.clientX, e.clientY);
        let netId = null;
        if (match && (match.type === 'pad' || match.type === 'via' || match.type === 'trace')) {
            const parsed = parseInt(match.element.dataset.net, 10);
            if (!isNaN(parsed) && parsed > 0) {
                netId = parsed;
            }
        }

        if (netId !== lastHoveredNetId) {
            viewer.highlightHoverNet(netId);
            lastHoveredNetId = netId;
        }
    }

    /**
     * Route from start point to current cursor position.
     * Chains requests: starts next route as soon as previous completes.
     */
    /**
     * Route from current start point to cursor position.
     * @param {boolean} skipEndpointCheck - If true, skip the different-net endpoint check
     */
    async function routeToCursor(skipEndpointCheck = false) {
        if (!routingSession || !routingSession.cursorPoint) return;
        if (isRouting) return;  // Already routing
        if (viewer.isZooming) return;  // Don't route while zooming (prevents lag)

        const { startPoint, cursorPoint } = routingSession;

        // Don't route if start and cursor are the same
        const dist = Math.sqrt(
            (cursorPoint.x - startPoint.x) ** 2 +
            (cursorPoint.y - startPoint.y) ** 2
        );
        if (dist < 0.1) {
            return;
        }

        // Cancel any existing request
        if (routeAbortController) {
            routeAbortController.abort();
        }
        routeAbortController = new AbortController();

        isRouting = true;
        pendingCursorUpdate = false;

        try {
            const routeStart = performance.now();
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
                    net_id: routingSession.startNet,
                    skip_endpoint_check: skipEndpointCheck
                }),
                signal: routeAbortController.signal
            });

            const data = await response.json();
            const routeTime = performance.now() - routeStart;
            if (routeTime > 100) {
                console.log(`Route took ${routeTime.toFixed(0)}ms`);
            }

            // Only update if we still have an active session
            if (routingSession) {
                if (data.success && data.path.length > 0) {
                    routingSession.pendingPath = data.path;

                    // Clear and render new preview
                    viewer.clearPendingTrace();
                    viewer.renderPendingTrace(data.path, routingSession.currentLayer, routingSession.width);

                    hideTraceError();
                } else {
                    console.log('Route failed:', {
                        from: startPoint,
                        to: cursorPoint,
                        layer: routingSession.currentLayer,
                        net: routingSession.startNet,
                        message: data.message
                    });
                    routingSession.pendingPath = null;
                    viewer.clearPendingTrace();

                    // Show error message for routing failures
                    if (data.message) {
                        showTraceError(data.message);
                    }
                }
            }
        } catch (error) {
            // Ignore abort errors (expected when canceling)
            if (error.name !== 'AbortError') {
                console.error('Routing error:', error);
                if (routingSession) {
                    routingSession.pendingPath = null;
                }
            }
        } finally {
            isRouting = false;
            routeAbortController = null;

            // If cursor moved while we were routing, start another route immediately
            if (pendingCursorUpdate && routingSession) {
                pendingCursorUpdate = false;
                routeToCursor(true);  // Skip endpoint check for mouse move preview
            }
        }
    }

    /**
     * Handle single click when routing - commits current segment.
     */
    async function handleRoutingClick(e, clickedElement) {
        if (!routingSession) return;

        const match = findBestMatchAtPoint(e.clientX, e.clientY);

        // When routing, only snap to same-net pads (avoid snapping to different-net pads)
        let snapElement = clickedElement;
        if (routingSession.startNet) {
            const clickedNet = clickedElement ? parseInt(clickedElement.dataset.net, 10) : null;
            if (clickedNet && clickedNet !== routingSession.startNet) {
                // Different net - don't snap to this pad, use raw cursor position
                snapElement = null;
            }
        }
        const target = getTargetCoordinates(e, snapElement);

        routingSession.cursorPoint = { x: target.x, y: target.y };

        // Route to click point and commit
        // Skip endpoint check if we didn't snap to a pad (snapElement is null)
        const skipEndpointCheck = (snapElement === null);
        await routeToCursor(skipEndpointCheck);
        await commitCurrentSegment(target.x, target.y);
    }

    /**
     * Handle double-click - starts or finishes routing.
     */
    async function handleDoubleClick(e) {
        const layer = document.getElementById('trace-layer').value;
        const width = parseFloat(document.getElementById('trace-width').value);
        const match = findBestMatchAtPoint(e.clientX, e.clientY);

        if (!routingSession) {
            // Not routing - check if we should start a routing session or select a route
            const validTypes = ['pad', 'via', 'trace', 'user-trace', 'user-via'];
            if (match && validTypes.includes(match.type)) {
                // Start routing session
                const clickedElement = match.element;
                const target = getTargetCoordinates(e, clickedElement);
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

                // Generate route ID for this entire routing session
                const routeId = generateRouteId();

                routingSession = {
                    routeId: routeId,
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
            } else if (match && (match.type === 'user-trace' || match.type === 'user-via')) {
                // Double-click on user trace/via selects full route
                const routeId = match.element.dataset.traceId;
                if (routeId) {
                    selectFullRoute(routeId);
                }
            }
            return;
        }

        // Already routing - double-click finishes the routing session
        // Only snap to same-net pads when ending route
        let snapElement = match ? match.element : null;
        if (routingSession.startNet && snapElement) {
            const matchNet = parseInt(snapElement.dataset.net, 10);
            if (matchNet && matchNet !== routingSession.startNet) {
                // Different net - don't snap, use raw cursor position
                snapElement = null;
            }
        }
        const target = getTargetCoordinates(e, snapElement);

        // Route to double-click point
        // Skip endpoint check if we didn't snap to a pad (snapElement is null)
        const skipEndpointCheck = (snapElement === null);
        routingSession.cursorPoint = { x: target.x, y: target.y };
        await routeToCursor(skipEndpointCheck);

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

        // Get the segment index (current length of sessionSegments)
        const segmentIndex = routingSession.sessionSegments.length;

        // Store segment info (all segments share the session's routeId)
        const segment = {
            path: routingSession.pendingPath,
            layer: routingSession.currentLayer,
            width: routingSession.width
        };
        routingSession.sessionSegments.push(segment);

        // Render as confirmed with the session's route ID and segment index
        viewer.confirmPendingTrace(segment.path, segment.layer, segment.width, routingSession.routeId, segmentIndex, routingSession.startNet);

        // Move start point to new position
        routingSession.startPoint = { x: newStartX, y: newStartY };
        routingSession.cursorPoint = { x: newStartX, y: newStartY };
        routingSession.pendingPath = null;

        // Update start marker
        viewer.showStartMarker(newStartX, newStartY);

        updateTraceStatus('Segment committed! Move mouse to continue', 'success');
    }

    /**
     * Auto-route to a destination pad using the /api/auto-route endpoint.
     * Places vias automatically if needed to reach the destination.
     *
     * @param {Element} padElement - The destination pad element
     * @param {number} padX - X coordinate of pad center
     * @param {number} padY - Y coordinate of pad center
     */
    async function autoRouteToPad(padElement, padX, padY) {
        if (!routingSession) return;

        const viaSize = 0.8;

        try {
            updateTraceStatus('Auto-routing to pad...', 'routing');

            const response = await fetch('/api/auto-route', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_x: routingSession.startPoint.x,
                    start_y: routingSession.startPoint.y,
                    end_x: padX,
                    end_y: padY,
                    preferred_layer: routingSession.currentLayer,
                    width: routingSession.width,
                    net_id: routingSession.startNet,
                    via_size: viaSize
                })
            });

            const data = await response.json();

            if (!data.success) {
                showTraceError(data.message || 'Auto-route failed');
                updateTraceStatus('Auto-route failed - try manual routing', '');
                return;
            }

            // Process each segment and via from the auto-route result
            let currentLayer = routingSession.currentLayer;

            for (let i = 0; i < data.segments.length; i++) {
                const segment = data.segments[i];

                // If layer changed, we need to place a via first
                if (segment.layer !== currentLayer && i > 0) {
                    // Find the via that connects these layers
                    // The via should be at the end of the previous segment
                    const prevSegment = data.segments[i - 1];
                    const prevPath = prevSegment.path;
                    const viaPoint = prevPath[prevPath.length - 1];

                    // Find matching via from the response
                    const via = data.vias.find(v =>
                        Math.abs(v.x - viaPoint[0]) < 0.01 &&
                        Math.abs(v.y - viaPoint[1]) < 0.01
                    );

                    if (via) {
                        const viaSegmentIndex = routingSession.sessionSegments.length;
                        routingSession.sessionVias.push({ x: via.x, y: via.y, size: via.size });
                        viewer.renderUserVia(via.x, via.y, via.size, false, routingSession.routeId, viaSegmentIndex, routingSession.startNet);
                    }

                    currentLayer = segment.layer;
                }

                // Add the segment
                const segmentIndex = routingSession.sessionSegments.length;
                const segmentData = {
                    path: segment.path,
                    layer: segment.layer,
                    width: routingSession.width
                };
                routingSession.sessionSegments.push(segmentData);
                viewer.confirmPendingTrace(segment.path, segment.layer, routingSession.width, routingSession.routeId, segmentIndex, routingSession.startNet);
            }

            // Update routing session state
            routingSession.currentLayer = currentLayer;
            document.getElementById('trace-layer').value = currentLayer;

            // Finish the routing session
            finishRoutingSession();

            updateTraceStatus(`Auto-routed with ${data.segments.length} segment(s), ${data.vias.length} via(s)`, 'success');

        } catch (error) {
            console.error('Auto-route error:', error);
            showTraceError('Failed to auto-route');
            updateTraceStatus('Auto-route failed - try manual routing', '');
        }
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

            // Get the segment index for the via (matches the last committed segment)
            const viaSegmentIndex = routingSession.sessionSegments.length - 1;

            // Add via at cursor position
            routingSession.sessionVias.push({ x, y, size: viaSize });
            viewer.renderUserVia(x, y, viaSize, false, routingSession.routeId, viaSegmentIndex, routingSession.startNet);

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

        // If we have segments, create a route entry
        if (segmentCount > 0) {
            const route = {
                id: routingSession.routeId,
                segments: [...routingSession.sessionSegments],
                netId: routingSession.startNet,
                visible: true
            };
            userRoutes.push(route);
            addRouteToList(route);

            // Log full trace details with all waypoints
            const allWaypoints = [];
            for (const segment of route.segments) {
                for (const point of segment.path) {
                    // Avoid duplicating connection points between segments
                    const last = allWaypoints[allWaypoints.length - 1];
                    if (!last || last.x !== point[0] || last.y !== point[1]) {
                        allWaypoints.push({ x: point[0], y: point[1], layer: segment.layer });
                    }
                }
            }
            console.log('Trace committed:', {
                routeId: route.id,
                netId: route.netId,
                segmentCount: segmentCount,
                viaCount: viaCount,
                waypoints: allWaypoints
            });
        }

        updateTraceStatus(`Done: ${segmentCount} segment(s), ${viaCount} via(s)`, 'success');
        resetTraceState();
    }

    /**
     * Cancel routing session - remove ALL traces added since start.
     */
    function cancelRoutingSession() {
        if (!routingSession) return;

        // Remove all SVG elements with this route ID (segments haven't been added to list yet)
        if (routingSession.sessionSegments.length > 0) {
            viewer.removeTraceById(routingSession.routeId);
        }

        // Remove visual elements - clear pending elements and session vias
        viewer.clearPendingElements();
        viewer.removeSessionTraces([], routingSession.sessionVias);

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
        // Clear debounce timer
        if (routeDebounceTimer) {
            clearTimeout(routeDebounceTimer);
            routeDebounceTimer = null;
        }
        // Cancel any in-flight request
        if (routeAbortController) {
            routeAbortController.abort();
            routeAbortController = null;
        }
        // Clear routing net highlight and pending elements (start marker, preview)
        viewer.clearRoutingHighlight();
        viewer.clearPendingElements();
        routingSession = null;
        document.getElementById('trace-actions').classList.add('hidden');
        hideTraceError();
        updateTraceStatus('Double-click pad/via to start routing', '');
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
     * Setup controls.
     */
    function setupControls() {
        document.getElementById('trace-confirm').addEventListener('click', confirmTrace);
        document.getElementById('trace-cancel').addEventListener('click', cancelTrace);
        document.getElementById('clear-all-routes').addEventListener('click', clearAllRoutes);

        // Zoom controls
        document.getElementById('zoom-in').addEventListener('click', () => viewer.zoomBy(0.8));
        document.getElementById('zoom-out').addEventListener('click', () => viewer.zoomBy(1.25));

        setupDownloadControls();
    }

    function setupDownloadControls() {
        const downloadBtn = document.getElementById('download-pcb');
        const dialog = document.getElementById('download-dialog');
        const filenameInput = document.getElementById('download-filename');
        const confirmBtn = document.getElementById('download-confirm');
        const cancelBtn = document.getElementById('download-cancel');

        downloadBtn.addEventListener('click', () => {
            dialog.classList.remove('hidden');
            filenameInput.focus();
            filenameInput.select();
        });

        cancelBtn.addEventListener('click', () => {
            dialog.classList.add('hidden');
        });

        confirmBtn.addEventListener('click', async () => {
            await downloadPCB(filenameInput.value);
            dialog.classList.add('hidden');
        });

        // Close on Escape
        dialog.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                dialog.classList.add('hidden');
            }
        });

        // Submit on Enter
        filenameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                confirmBtn.click();
            }
        });

        // Close on backdrop click
        dialog.addEventListener('click', (e) => {
            if (e.target === dialog) dialog.classList.add('hidden');
        });
    }

    /**
     * Download the PCB file with user-routed traces.
     */
    async function downloadPCB(filename) {
        try {
            const response = await fetch('/api/export');
            if (!response.ok) throw new Error('Export failed');

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename || 'modified.kicad_pcb';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Download failed:', error);
            alert('Failed to export PCB: ' + error.message);
        }
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
                if (routingSession) {
                    // Cancel routing - remove all traces from this session
                    cancelRoutingSession();
                } else if (selectedSegments.length > 0) {
                    // Clear segment selection
                    clearSegmentSelection();
                } else {
                    // Clear net selection
                    clearSelection();
                }
            } else if (e.key === 'Backspace' || e.key === 'Delete') {
                // Delete selected segments
                if (selectedSegments.length > 0) {
                    e.preventDefault();
                    deleteSelectedSegments();
                }
            } else if (routingSession && layerMap[e.key]) {
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
