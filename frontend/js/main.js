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

    // Trace mode state
    let appMode = 'select';  // 'select' | 'trace'
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
    const ROUTE_DEBOUNCE_MS = 50;     // Minimum delay between route requests

    // Companion mode state - routes multiple traces following a reference
    let companionMode = null;
    // {
    //   referenceRoute: {           // The reference trace to follow
    //     segments: [{path, layer, width}],  // Full path data
    //     netId: number,
    //     routeId: string|null      // If user-created route
    //   },
    //   companions: [               // Array of companion traces (ordered by selection)
    //     {
    //       netId: number,          // Net ID of this companion
    //       startPoint: {x, y},     // Start point (from clicked pad)
    //       offsetIndex: number,    // Position in stack (1, 2, 3...)
    //       currentSegmentIndex: number,  // Which reference segment we're on
    //       pendingPath: array|null,      // Current preview path
    //       routeSuccess: boolean,        // Whether last route succeeded
    //       sessionSegments: [],          // Committed segments for this companion
    //       sessionVias: [],              // Committed vias for this companion
    //       routeId: string               // Unique route ID for this companion
    //     }
    //   ],
    //   baseSpacing: number,        // Base offset distance (multiplied by offsetIndex)
    //   currentLayer: string        // Current routing layer (follows reference)
    // }

    // Expose state for debugging/testing
    window.getRoutingState = () => ({
        isRouting,
        routingSession,
        companionMode,
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

        // Mouse move: continuous routing preview (for both normal routing and companion mode)
        container.addEventListener('mousemove', (e) => {
            if (appMode === 'trace' && (routingSession || companionMode)) {
                handleTraceMouseMove(e);
            }
            handleNetHover(e);
        });

        container.addEventListener('mouseleave', () => {
            viewer.highlightHoverNet(null);
            lastHoveredNetId = null;
        });

        // Single click: commit segment, make click point the new start
        container.addEventListener('click', (e) => {
            const match = findBestMatchAtPoint(e.clientX, e.clientY);

            if (appMode === 'trace') {
                // In trace mode, pass the element (or null) for routing
                const element = match ? match.element : null;
                handleTraceClick(e, element);
            } else {
                // In select mode, handle segment selection or net selection
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

        // Double-click: commit and end routing, or select full route
        container.addEventListener('dblclick', (e) => {
            if (appMode === 'trace' && companionMode && companionMode.companions.length > 0) {
                // Finish companion routing on double-click
                e.preventDefault();
                e.stopPropagation();
                finishCompanionSession();
            } else if (appMode === 'trace') {
                e.preventDefault();
                e.stopPropagation();
                handleTraceDoubleClick(e);
            } else if (appMode === 'select') {
                // In select mode, double-click on user trace/via selects full route
                const match = findBestMatchAtPoint(e.clientX, e.clientY);
                if (match && (match.type === 'user-trace' || match.type === 'user-via')) {
                    const routeId = match.element.dataset.traceId;
                    if (routeId) {
                        e.preventDefault();
                        e.stopPropagation();
                        selectFullRoute(routeId);
                    }
                }
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
     * Continuously routes to cursor position (debounced).
     */
    function handleTraceMouseMove(e) {
        const svgPoint = viewer.screenToSVG(e.clientX, e.clientY);

        // Handle companion mode
        if (companionMode && companionMode.companions.length > 0) {
            companionMode.cursorPoint = { x: svgPoint.x, y: svgPoint.y };

            if (isRouting) {
                pendingCursorUpdate = true;
                return;
            }

            if (routeDebounceTimer) {
                clearTimeout(routeDebounceTimer);
            }
            routeDebounceTimer = setTimeout(() => {
                routeDebounceTimer = null;
                routeCompanionsToCursor();
            }, ROUTE_DEBOUNCE_MS);
            return;
        }

        // Handle normal routing session
        if (!routingSession) return;

        routingSession.cursorPoint = { x: svgPoint.x, y: svgPoint.y };

        // If currently routing, mark that we have a pending update
        if (isRouting) {
            pendingCursorUpdate = true;
            return;
        }

        // Debounce route requests to prevent overwhelming the server
        if (routeDebounceTimer) {
            clearTimeout(routeDebounceTimer);
        }
        routeDebounceTimer = setTimeout(() => {
            routeDebounceTimer = null;
            routeToCursor();
        }, ROUTE_DEBOUNCE_MS);
    }

    /**
     * Handle mouse hovering over elements to highlight same-net items.
     */
    function handleNetHover(e) {
        // Only hover highlight in select mode or trace mode when not actively routing
        if (appMode === 'trace' && routingSession) {
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
    async function routeToCursor() {
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
                }),
                signal: routeAbortController.signal
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

                    // Show error message if routing failed due to different net
                    if (data.message && data.message.toLowerCase().includes('different net')) {
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

            // If cursor moved while we were routing, start another route (debounced)
            if (pendingCursorUpdate && routingSession) {
                pendingCursorUpdate = false;
                // Use debounce instead of immediate call to prevent flooding
                if (routeDebounceTimer) {
                    clearTimeout(routeDebounceTimer);
                }
                routeDebounceTimer = setTimeout(() => {
                    routeDebounceTimer = null;
                    routeToCursor();
                }, ROUTE_DEBOUNCE_MS);
            }
        }
    }

    /**
     * Handle single click in trace mode.
     * - Ctrl+Click on pad with reference selected: add companion
     * - Click on trace with no session: select as reference
     * - First click on pad: start normal routing session
     * - Subsequent clicks: commits current segment, click point becomes new start
     */
    async function handleTraceClick(e, clickedElement) {
        const layer = document.getElementById('trace-layer').value;
        const width = parseFloat(document.getElementById('trace-width').value);
        const target = getTargetCoordinates(e, clickedElement);
        const match = findBestMatchAtPoint(e.clientX, e.clientY);

        // Handle companion mode: Alt+Click on pad/via/trace adds companion
        if (e.altKey && companionMode && companionMode.referenceRoute) {
            if (match && (match.type === 'pad' || match.type === 'via' || match.type === 'trace' ||
                          match.type === 'user-trace' || match.type === 'user-via')) {
                const netId = parseInt(match.element.dataset.net, 10);
                if (netId > 0) {
                    addCompanionTrace(match.element, target);
                    return;
                }
            }
            // Alt+Click on element without net - show error
            showTraceError('Alt+Click on a pad, via, or trace to add a companion');
            return;
        }

        // Handle companion mode: regular click commits segments
        if (companionMode && companionMode.companions.length > 0) {
            await commitCompanionSegments();
            return;
        }

        // Handle clicking on a trace (no active session)
        if (!routingSession && !companionMode && match) {
            if (match.type === 'user-trace' || match.type === 'user-via') {
                // User-created segment: Shift+click for selection, regular click for reference
                const routeId = match.element.dataset.traceId;
                const segmentIndex = parseInt(match.element.dataset.segmentIndex, 10);
                if (routeId && !isNaN(segmentIndex)) {
                    if (e.shiftKey) {
                        toggleSegmentSelection(routeId, segmentIndex);
                        updateTraceStatus('Segment selected. Backspace to delete', 'routing');
                        return;
                    } else {
                        // Try to select as reference for companion mode
                        if (selectReferenceTrace(match)) {
                            return;
                        }
                        // Fall back to segment selection if reference selection fails
                        selectSegment(routeId, segmentIndex);
                        updateTraceStatus('Segment selected. Backspace to delete, or click pad to route', 'routing');
                        return;
                    }
                }
            } else if (match.type === 'trace') {
                // PCB board trace: select as reference for companion mode
                if (selectReferenceTrace(match)) {
                    return;
                }
            }
        }

        // Normal routing mode
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
    /**
     * Commits current segment and ends routing.
     */
    async function handleTraceDoubleClick(e) {
        if (!routingSession) {
            // If not routing, double-click can select reference for companion mode
            const match = findBestMatchAtPoint(e.clientX, e.clientY);
            if (match && (match.type === 'user-trace' || match.type === 'user-via' || match.type === 'trace')) {
                if (selectReferenceTrace(match)) {
                    e.preventDefault();
                    e.stopPropagation();
                }
            }
            return;
        }

        const bestMatch = findBestMatchAtPoint(e.clientX, e.clientY);
        const target = getTargetCoordinates(e, bestMatch ? bestMatch.element : null);

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
        updateTraceStatus('Click a pad to start', '');
    }

    // ==================== COMPANION MODE FUNCTIONS ====================

    /**
     * Select a trace as the reference for companion routing.
     * @param {Object} match - The match object from findBestMatchAtPoint
     * @returns {boolean} True if reference was selected
     */
    function selectReferenceTrace(match) {
        if (!match) return false;

        let referenceRoute = null;

        if (match.type === 'user-trace' || match.type === 'user-via') {
            // User-created route - extract from userRoutes
            const routeId = match.element.dataset.traceId;
            const route = userRoutes.find(r => r.id === routeId);
            if (!route || route.segments.length === 0) {
                showTraceError('Route has no segments');
                return false;
            }
            referenceRoute = {
                segments: route.segments,
                netId: route.netId,
                routeId: routeId
            };
        } else if (match.type === 'trace') {
            // PCB board trace - need to fetch connected path from backend
            const netId = parseInt(match.element.dataset.net, 10);
            const layer = match.element.dataset.layer;

            // Get approximate click position from the trace
            const pathData = match.element.getAttribute('d');
            const firstPoint = extractFirstPointFromPath(pathData);

            if (!firstPoint) {
                showTraceError('Could not determine trace start');
                return false;
            }

            // For PCB traces, we'll fetch the full path asynchronously
            fetchTracePathAndStartCompanion(netId, layer, firstPoint.x, firstPoint.y);
            return true;
        } else {
            return false;
        }

        // Initialize companion mode with this reference
        initCompanionMode(referenceRoute);
        return true;
    }

    /**
     * Extract the first point from an SVG path data string.
     */
    function extractFirstPointFromPath(pathData) {
        if (!pathData) return null;
        const match = pathData.match(/M\s*([\d.-]+)[,\s]+([\d.-]+)/i);
        if (match) {
            return { x: parseFloat(match[1]), y: parseFloat(match[2]) };
        }
        return null;
    }

    /**
     * Fetch connected trace path from backend and start companion mode.
     */
    async function fetchTracePathAndStartCompanion(netId, layer, x, y) {
        try {
            const response = await fetch(`/api/trace-path/${netId}?layer=${encodeURIComponent(layer)}&x=${x}&y=${y}`);
            const data = await response.json();

            if (!data.success || !data.path || data.path.length < 2) {
                showTraceError('Could not reconstruct trace path');
                return;
            }

            // Build reference route from path
            const width = parseFloat(document.getElementById('trace-width').value);
            const referenceRoute = {
                segments: [{
                    path: data.path,
                    layer: layer,
                    width: data.width || width
                }],
                netId: netId,
                routeId: null
            };

            initCompanionMode(referenceRoute);
        } catch (error) {
            console.error('Failed to fetch trace path:', error);
            showTraceError('Failed to fetch trace path');
        }
    }

    /**
     * Initialize companion mode with a reference route.
     */
    function initCompanionMode(referenceRoute) {
        const spacing = parseFloat(document.getElementById('companion-spacing')?.value || '0.4');

        companionMode = {
            referenceRoute: referenceRoute,
            companions: [],
            baseSpacing: spacing,
            currentLayer: referenceRoute.segments[0]?.layer || 'F.Cu'
        };

        // Highlight the reference trace
        if (referenceRoute.routeId) {
            viewer.highlightReferenceTrace(referenceRoute.routeId);
        } else if (referenceRoute.netId) {
            // For PCB traces, highlight by net ID
            viewer.highlightReferenceByNet(referenceRoute.netId, referenceRoute.segments[0]?.layer);
        }

        console.log('Reference selected:', {
            netId: referenceRoute.netId,
            segments: referenceRoute.segments.length,
            firstSegmentPath: referenceRoute.segments[0]?.path?.length || 0,
            layer: companionMode.currentLayer
        });

        updateCompanionStatus();
        updateTraceStatus('Reference selected. Alt+Click pad/via/trace to add companions', 'routing');
    }

    /**
     * Add a companion trace from a clicked element (pad, via, or trace).
     * @param {Element} clickedElement - The element that was Alt+clicked
     * @param {Object} clickTarget - The click target coordinates {x, y}
     */
    function addCompanionTrace(clickedElement, clickTarget) {
        if (!companionMode) return;

        const netId = parseInt(clickedElement.dataset.net, 10);

        // Prevent duplicate nets
        if (companionMode.companions.some(c => c.netId === netId)) {
            showTraceError('This net is already a companion');
            return;
        }

        // Prevent same net as reference
        if (netId === companionMode.referenceRoute.netId) {
            showTraceError('Cannot add reference net as companion');
            return;
        }

        // Get coordinates - try element attributes first, then use click position
        let startX = parseFloat(clickedElement.dataset.x || clickedElement.getAttribute('cx'));
        let startY = parseFloat(clickedElement.dataset.y || clickedElement.getAttribute('cy'));

        // For traces or if element coords unavailable, use click target position
        if (isNaN(startX) || isNaN(startY)) {
            if (clickTarget) {
                startX = clickTarget.x;
                startY = clickTarget.y;
            } else {
                showTraceError('Could not determine start position');
                return;
            }
        }

        const width = parseFloat(document.getElementById('trace-width').value);

        companionMode.companions.push({
            netId: netId,
            startPoint: { x: startX, y: startY },
            offsetIndex: companionMode.companions.length + 1,  // 1-based
            currentSegmentIndex: 0,
            pendingPath: null,
            routeSuccess: true,
            sessionSegments: [],
            sessionVias: [],
            routeId: generateRouteId(),
            width: width
        });

        // Show start marker for this companion
        viewer.showCompanionStartMarker(startX, startY, companionMode.companions.length);

        console.log(`Added companion ${companionMode.companions.length}: net=${netId}, start=(${startX.toFixed(2)}, ${startY.toFixed(2)})`);

        updateCompanionStatus();
        hideTraceError();

        // Show trace actions if we have companions
        if (companionMode.companions.length > 0) {
            document.getElementById('trace-actions').classList.remove('hidden');
        }
    }

    /**
     * Update the companion status display.
     */
    function updateCompanionStatus() {
        const statusEl = document.getElementById('companion-status');
        const refEl = document.getElementById('reference-net');
        const listEl = document.getElementById('companion-net-list');

        if (!statusEl) return;

        if (!companionMode) {
            statusEl.classList.add('hidden');
            return;
        }

        statusEl.classList.remove('hidden');

        if (refEl) {
            const refNetName = companionMode.referenceRoute.netId ?
                `Net ${companionMode.referenceRoute.netId}` : 'Unknown';
            refEl.textContent = refNetName;
        }

        if (listEl) {
            if (companionMode.companions.length === 0) {
                listEl.innerHTML = '<span class="hint">(none)</span>';
            } else {
                const badges = companionMode.companions.map((c, i) =>
                    `<span class="companion-net-badge">${i + 1}. Net ${c.netId}</span>`
                ).join('');
                listEl.innerHTML = badges;
            }
        }
    }

    /**
     * Route all companions to the current cursor position.
     * Calculates offset positions along the reference path.
     */
    async function routeCompanionsToCursor() {
        if (!companionMode || companionMode.companions.length === 0) return;
        if (isRouting) {
            pendingCursorUpdate = true;
            return;
        }
        if (viewer.isZooming) return;

        isRouting = true;
        pendingCursorUpdate = false;

        try {
            // Get reference path for the current segment
            const refSegment = companionMode.referenceRoute.segments[0];
            if (!refSegment || !refSegment.path || refSegment.path.length < 2) {
                return;
            }

            const cursorPoint = companionMode.cursorPoint;
            if (!cursorPoint) return;

            // Find closest point on reference path to cursor
            const { point: refPoint, direction } = findClosestPointOnPath(refSegment.path, cursorPoint);

            // Calculate perpendicular direction for offsets
            const perpX = -direction.y;
            const perpY = direction.x;

            // Route each companion
            const routePromises = companionMode.companions.map(async (companion, index) => {
                // Determine which side of the reference the companion's start point is on
                // by computing the cross product: (start - refPoint) × direction
                const toStartX = companion.startPoint.x - refPoint.x;
                const toStartY = companion.startPoint.y - refPoint.y;
                const crossProduct = toStartX * direction.y - toStartY * direction.x;

                // If cross product > 0, start is on the "positive perpendicular" side
                // If cross product < 0, start is on the "negative perpendicular" side
                // Use the same side for offset to avoid crossing the reference
                const offsetSign = crossProduct >= 0 ? 1 : -1;

                // Calculate offset target point on the same side as start point
                const offset = companionMode.baseSpacing * companion.offsetIndex * offsetSign;
                const targetX = refPoint.x + perpX * offset;
                const targetY = refPoint.y + perpY * offset;

                console.log(`Companion ${index}: routing from (${companion.startPoint.x.toFixed(2)}, ${companion.startPoint.y.toFixed(2)}) to (${targetX.toFixed(2)}, ${targetY.toFixed(2)}), net=${companion.netId}, layer=${companionMode.currentLayer}`);

                try {
                    const response = await fetch('/api/route', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            start_x: companion.startPoint.x,
                            start_y: companion.startPoint.y,
                            end_x: targetX,
                            end_y: targetY,
                            layer: companionMode.currentLayer,
                            width: companion.width,
                            net_id: companion.netId,
                            skip_endpoint_check: true  // Companion routing to arbitrary offset points
                        })
                    });

                    const data = await response.json();

                    if (data.success && data.path.length > 0) {
                        companion.pendingPath = data.path;
                        companion.routeSuccess = true;
                        console.log(`Companion ${index}: route SUCCESS, ${data.path.length} waypoints`);
                    } else {
                        companion.pendingPath = null;
                        companion.routeSuccess = false;
                        console.log(`Companion ${index}: route FAILED - ${data.message || 'no path found'}`);
                    }
                } catch (error) {
                    if (error.name !== 'AbortError') {
                        console.error(`Companion ${index} routing error:`, error);
                    }
                    companion.pendingPath = null;
                    companion.routeSuccess = false;
                }
            });

            await Promise.all(routePromises);

            // Render all companion previews
            if (companionMode) {
                viewer.clearCompanionPreviews();
                for (const companion of companionMode.companions) {
                    if (companion.pendingPath) {
                        viewer.renderCompanionPreview(
                            companion.pendingPath,
                            companionMode.currentLayer,
                            companion.width,
                            companion.routeSuccess
                        );
                    }
                }
            }

        } finally {
            isRouting = false;

            // Chain next request if cursor moved
            if (pendingCursorUpdate && companionMode) {
                pendingCursorUpdate = false;
                if (routeDebounceTimer) {
                    clearTimeout(routeDebounceTimer);
                }
                routeDebounceTimer = setTimeout(() => {
                    routeDebounceTimer = null;
                    routeCompanionsToCursor();
                }, ROUTE_DEBOUNCE_MS);
            }
        }
    }

    /**
     * Find the closest point on a path to a target point.
     * Returns the point and the direction vector at that point.
     */
    function findClosestPointOnPath(path, target) {
        let closestPoint = { x: path[0][0], y: path[0][1] };
        let closestDist = Infinity;
        let direction = { x: 1, y: 0 };

        for (let i = 0; i < path.length - 1; i++) {
            const p1 = { x: path[i][0], y: path[i][1] };
            const p2 = { x: path[i + 1][0], y: path[i + 1][1] };

            // Find closest point on segment
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const lengthSq = dx * dx + dy * dy;

            if (lengthSq < 0.0001) continue;

            const t = Math.max(0, Math.min(1,
                ((target.x - p1.x) * dx + (target.y - p1.y) * dy) / lengthSq
            ));

            const projX = p1.x + t * dx;
            const projY = p1.y + t * dy;
            const dist = Math.sqrt((target.x - projX) ** 2 + (target.y - projY) ** 2);

            if (dist < closestDist) {
                closestDist = dist;
                closestPoint = { x: projX, y: projY };
                // Normalize direction
                const length = Math.sqrt(lengthSq);
                direction = { x: dx / length, y: dy / length };
            }
        }

        return { point: closestPoint, direction };
    }

    /**
     * Commit current segments for all companions.
     */
    async function commitCompanionSegments() {
        if (!companionMode || companionMode.companions.length === 0) return;

        for (const companion of companionMode.companions) {
            if (companion.pendingPath && companion.routeSuccess) {
                const segmentIndex = companion.sessionSegments.length;

                const segment = {
                    path: companion.pendingPath,
                    layer: companionMode.currentLayer,
                    width: companion.width
                };
                companion.sessionSegments.push(segment);

                // Render as confirmed
                viewer.confirmPendingTrace(
                    segment.path,
                    segment.layer,
                    segment.width,
                    companion.routeId,
                    segmentIndex,
                    companion.netId
                );

                // Update start point to end of committed path
                const lastPoint = companion.pendingPath[companion.pendingPath.length - 1];
                companion.startPoint = { x: lastPoint[0], y: lastPoint[1] };
                companion.pendingPath = null;
            }
        }

        viewer.clearCompanionPreviews();
        updateTraceStatus('Companion segments committed', 'success');
    }

    /**
     * Handle layer switch for all companions - place vias and switch layer.
     */
    async function handleCompanionLayerSwitch(newLayer) {
        if (!companionMode || companionMode.companions.length === 0) return;
        if (newLayer === companionMode.currentLayer) return;

        const viaSize = 0.8;

        // First commit any pending paths
        await commitCompanionSegments();

        // Place vias for all companions at their current positions
        for (const companion of companionMode.companions) {
            const { x, y } = companion.startPoint;

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
                        net_id: companion.netId
                    })
                });

                const data = await response.json();

                if (!data.valid) {
                    showTraceError(`Via blocked for companion ${companion.offsetIndex}: ${data.message}`);
                    continue;
                }

                // Get segment index for the via
                const viaSegmentIndex = companion.sessionSegments.length - 1;

                // Place via
                companion.sessionVias.push({ x, y, size: viaSize });
                viewer.renderUserVia(x, y, viaSize, false, companion.routeId, viaSegmentIndex, companion.netId);

            } catch (error) {
                console.error('Via check error for companion:', error);
            }
        }

        // Switch layer for all companions
        companionMode.currentLayer = newLayer;
        document.getElementById('trace-layer').value = newLayer;

        updateTraceStatus(`Vias placed, now on ${newLayer}`, 'success');
        hideTraceError();
    }

    /**
     * Finish companion routing session - keep all committed traces.
     */
    function finishCompanionSession() {
        if (!companionMode) return;

        viewer.clearCompanionPreviews();
        viewer.clearReferenceHighlight();

        let totalSegments = 0;
        let totalVias = 0;

        // Create route entries for each companion
        for (const companion of companionMode.companions) {
            if (companion.sessionSegments.length > 0) {
                const route = {
                    id: companion.routeId,
                    segments: companion.sessionSegments,
                    netId: companion.netId,
                    visible: true
                };
                userRoutes.push(route);
                addRouteToList(route);
                totalSegments += companion.sessionSegments.length;
                totalVias += companion.sessionVias.length;
            }
        }

        updateTraceStatus(`Done: ${companionMode.companions.length} companions, ${totalSegments} segments, ${totalVias} vias`, 'success');

        companionMode = null;
        updateCompanionStatus();
        document.getElementById('trace-actions').classList.add('hidden');
    }

    /**
     * Cancel companion routing session - remove all traces.
     */
    function cancelCompanionSession() {
        if (!companionMode) return;

        // Remove all SVG elements for each companion
        for (const companion of companionMode.companions) {
            if (companion.sessionSegments.length > 0 || companion.sessionVias.length > 0) {
                viewer.removeTraceById(companion.routeId);
            }
        }

        viewer.clearCompanionPreviews();
        viewer.clearReferenceHighlight();
        viewer.clearPendingElements();

        updateTraceStatus('Companion routing cancelled', '');

        companionMode = null;
        updateCompanionStatus();
        document.getElementById('trace-actions').classList.add('hidden');
    }

    // ==================== END COMPANION MODE FUNCTIONS ====================

    /**
     * Confirm button: finish routing and keep traces.
     */
    function confirmTrace() {
        if (companionMode) {
            finishCompanionSession();
        } else {
            finishRoutingSession();
        }
    }

    /**
     * Cancel button: undo all traces from this session.
     */
    function cancelTrace() {
        if (companionMode) {
            cancelCompanionSession();
        } else {
            cancelRoutingSession();
        }
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
        document.getElementById('clear-all-routes').addEventListener('click', clearAllRoutes);

        // Zoom controls
        document.getElementById('zoom-in').addEventListener('click', () => viewer.zoomBy(0.8));
        document.getElementById('zoom-out').addEventListener('click', () => viewer.zoomBy(1.25));

        setupDownloadControls();
    }

    /**
     * Setup download controls.
     */
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
                if (appMode === 'trace' && companionMode) {
                    // Cancel companion routing
                    cancelCompanionSession();
                } else if (appMode === 'trace' && routingSession) {
                    // Cancel routing - remove all traces from this session
                    cancelRoutingSession();
                } else if (appMode === 'trace') {
                    toggleTraceMode();
                } else {
                    // In select mode, clear segment selection first, then net selection
                    if (selectedSegments.length > 0) {
                        clearSegmentSelection();
                    } else {
                        clearSelection();
                    }
                }
            } else if (e.key === 'Backspace' || e.key === 'Delete') {
                // Delete selected segments
                if (selectedSegments.length > 0) {
                    e.preventDefault();
                    deleteSelectedSegments();
                }
            } else if (e.key === 't' || e.key === 'T') {
                toggleTraceMode();
            } else if (appMode === 'trace' && companionMode && companionMode.companions.length > 0 && layerMap[e.key]) {
                // Companion mode layer switching with via
                handleCompanionLayerSwitch(layerMap[e.key]);
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
