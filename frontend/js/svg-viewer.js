/**
 * SVG Viewer with pan and zoom functionality.
 */
class SVGViewer {
    constructor(container) {
        this.container = container;
        this.svg = null;

        // ViewBox state (in SVG coordinates)
        this.viewBox = { x: 0, y: 0, width: 100, height: 100 };

        // Interaction state
        this.isPanning = false;
        this.lastMouseX = 0;
        this.lastMouseY = 0;

        // Zoom limits
        this.minScale = 0.1;
        this.maxScale = 50;

        // Pending viewBox update (for requestAnimationFrame batching)
        this._pendingViewBox = null;
        this._rafId = null;

        // Zooming state (for pausing routing during zoom)
        this.isZooming = false;
        this._zoomEndTimer = null;

        // CSS transform state for smooth zooming
        // We use CSS transforms during zoom for GPU acceleration,
        // then commit to viewBox when zooming ends for sharp rendering
        this._cssScale = 1;
        this._cssTranslateX = 0;
        this._cssTranslateY = 0;
        this._baseViewBox = null;  // viewBox at start of zoom gesture

        // Bind event handlers
        this._onMouseDown = this._onMouseDown.bind(this);
        this._onMouseMove = this._onMouseMove.bind(this);
        this._onMouseUp = this._onMouseUp.bind(this);
        this._onWheel = this._onWheel.bind(this);
        this._onKeyDown = this._onKeyDown.bind(this);
    }

    /**
     * Load SVG content into the container.
     */
    loadSVG(svgContent) {
        this.container.innerHTML = svgContent;
        this.svg = this.container.querySelector('svg');

        if (!this.svg) {
            console.error('No SVG element found');
            return;
        }

        // Store original viewBox
        const viewBox = this.svg.getAttribute('viewBox').split(' ').map(Number);
        this.originalViewBox = {
            x: viewBox[0],
            y: viewBox[1],
            width: viewBox[2],
            height: viewBox[3]
        };

        // Initialize current viewBox to original
        this.viewBox = { ...this.originalViewBox };

        // Setup event listeners
        this._setupEventListeners();

        // Initial fit
        this.fitToView();
    }

    /**
     * Setup event listeners for interaction.
     */
    _setupEventListeners() {
        this.container.addEventListener('mousedown', this._onMouseDown);
        this.container.addEventListener('mousemove', this._onMouseMove);
        this.container.addEventListener('mouseup', this._onMouseUp);
        this.container.addEventListener('mouseleave', this._onMouseUp);
        this.container.addEventListener('wheel', this._onWheel, { passive: false });
        document.addEventListener('keydown', this._onKeyDown);
    }

    /**
     * Convert screen coordinates to SVG coordinates.
     */
    _screenToSVG(screenX, screenY) {
        const rect = this.container.getBoundingClientRect();
        const ratioX = this.viewBox.width / rect.width;
        const ratioY = this.viewBox.height / rect.height;
        return {
            x: this.viewBox.x + (screenX - rect.left) * ratioX,
            y: this.viewBox.y + (screenY - rect.top) * ratioY
        };
    }

    /**
     * Handle mouse down for panning.
     */
    _onMouseDown(e) {
        // Only pan with left mouse button + shift key
        if (e.button !== 0) return;
        if (!e.shiftKey) return;  // Require shift for panning

        this.isPanning = true;
        this.lastMouseX = e.clientX;
        this.lastMouseY = e.clientY;
        this.container.classList.add('panning');
    }

    /**
     * Handle mouse move for panning.
     * Uses requestAnimationFrame to batch rapid mouse events for smooth performance.
     */
    _onMouseMove(e) {
        if (!this.isPanning) return;

        const rect = this.container.getBoundingClientRect();
        const dx = (e.clientX - this.lastMouseX) * (this.viewBox.width / rect.width);
        const dy = (e.clientY - this.lastMouseY) * (this.viewBox.height / rect.height);

        this.viewBox.x -= dx;
        this.viewBox.y -= dy;

        this.lastMouseX = e.clientX;
        this.lastMouseY = e.clientY;

        // Batch DOM updates with requestAnimationFrame for smooth performance
        if (!this._rafId) {
            this._rafId = requestAnimationFrame(() => {
                this._rafId = null;
                this._updateTransform();
            });
        }
    }

    /**
     * Handle mouse up to end panning.
     */
    _onMouseUp() {
        this.isPanning = false;
        this.container.classList.remove('panning');
    }

    /**
     * Handle mouse wheel for zooming.
     * Uses CSS transforms during zoom for GPU acceleration (fixes Firefox lag),
     * then commits to viewBox when zooming ends for sharp rendering.
     */
    _onWheel(e) {
        e.preventDefault();

        // Initialize base viewBox at start of zoom gesture
        if (!this._baseViewBox) {
            this._baseViewBox = { ...this.viewBox };
            this._cssScale = 1;
            this._cssTranslateX = 0;
            this._cssTranslateY = 0;
        }

        // Mark as zooming (for pausing routing during zoom)
        this.isZooming = true;
        if (this._zoomEndTimer) {
            clearTimeout(this._zoomEndTimer);
        }
        this._zoomEndTimer = setTimeout(() => {
            this._commitZoom();
        }, 150);  // Commit after 150ms of no scroll

        // Get mouse position in SVG coordinates BEFORE zoom
        const svgPoint = this._screenToSVG(e.clientX, e.clientY);

        // Calculate zoom factor
        const zoomFactor = e.deltaY > 0 ? 1.1 : 0.9;

        // Calculate new dimensions
        const newWidth = this.viewBox.width * zoomFactor;
        const newHeight = this.viewBox.height * zoomFactor;

        // Check zoom limits based on original viewBox
        const newScale = this.originalViewBox.width / newWidth;
        if (newScale < this.minScale || newScale > this.maxScale) {
            return;
        }

        // Adjust viewBox origin to keep mouse position fixed
        const rect = this.container.getBoundingClientRect();
        const mouseRatioX = (e.clientX - rect.left) / rect.width;
        const mouseRatioY = (e.clientY - rect.top) / rect.height;

        // Update viewBox state immediately (for coordinate conversions)
        this.viewBox.x = svgPoint.x - newWidth * mouseRatioX;
        this.viewBox.y = svgPoint.y - newHeight * mouseRatioY;
        this.viewBox.width = newWidth;
        this.viewBox.height = newHeight;

        // Calculate CSS transform relative to base viewBox
        this._cssScale = this._baseViewBox.width / this.viewBox.width;

        // Calculate translation to keep the view centered correctly
        // The transform origin is at the center of the container
        const baseCenterX = this._baseViewBox.x + this._baseViewBox.width / 2;
        const baseCenterY = this._baseViewBox.y + this._baseViewBox.height / 2;
        const viewCenterX = this.viewBox.x + this.viewBox.width / 2;
        const viewCenterY = this.viewBox.y + this.viewBox.height / 2;

        // Convert SVG coordinate difference to screen pixels
        const svgToScreenX = rect.width / this._baseViewBox.width;
        const svgToScreenY = rect.height / this._baseViewBox.height;

        this._cssTranslateX = (baseCenterX - viewCenterX) * svgToScreenX * this._cssScale;
        this._cssTranslateY = (baseCenterY - viewCenterY) * svgToScreenY * this._cssScale;

        // Apply CSS transform (GPU-accelerated, no re-rasterization)
        if (!this._rafId) {
            this._rafId = requestAnimationFrame(() => {
                this._rafId = null;
                this._applyCSSTransform();
            });
        }
    }

    /**
     * Apply CSS transform for smooth zooming.
     */
    _applyCSSTransform() {
        if (!this.svg) return;
        this.svg.style.transform = `translate(${this._cssTranslateX}px, ${this._cssTranslateY}px) scale(${this._cssScale})`;
        this.svg.style.transformOrigin = 'center center';
    }

    /**
     * Commit zoom: update viewBox and reset CSS transform.
     * This gives sharp rendering after zooming ends.
     */
    _commitZoom() {
        this.isZooming = false;
        this._zoomEndTimer = null;

        // Reset CSS transform
        if (this.svg) {
            this.svg.style.transform = '';
            this.svg.style.transformOrigin = '';
        }

        // Update the actual viewBox
        this._updateTransform();

        // Clear base viewBox for next gesture
        this._baseViewBox = null;
        this._cssScale = 1;
        this._cssTranslateX = 0;
        this._cssTranslateY = 0;
    }

    /**
     * Handle keyboard shortcuts.
     */
    _onKeyDown(e) {
        if (e.key === 'r' || e.key === 'R') {
            this.fitToView();
        }
    }

    /**
     * Update the SVG transform.
     */
    _updateTransform() {
        if (!this.svg) return;
        this.svg.setAttribute('viewBox',
            `${this.viewBox.x} ${this.viewBox.y} ${this.viewBox.width} ${this.viewBox.height}`);
    }

    /**
     * Fit the entire board in view.
     */
    fitToView() {
        if (!this.svg) return;

        const containerRect = this.container.getBoundingClientRect();
        const vb = this.originalViewBox;

        // Calculate scale to fit with 90% margin
        const scaleX = containerRect.width / vb.width;
        const scaleY = containerRect.height / vb.height;
        const scale = Math.min(scaleX, scaleY) * 0.9;

        // Calculate viewBox dimensions that fit the container
        const viewWidth = containerRect.width / scale;
        const viewHeight = containerRect.height / scale;

        // Center the original viewBox in the new viewBox
        this.viewBox = {
            x: vb.x + (vb.width - viewWidth) / 2,
            y: vb.y + (vb.height - viewHeight) / 2,
            width: viewWidth,
            height: viewHeight
        };

        this._updateTransform();
    }

    /**
     * Toggle visibility of a layer.
     */
    toggleLayer(layerName, visible) {
        if (!this.svg) return;

        const layerId = `layer-${layerName.replace('.', '-')}`;
        const layer = this.svg.getElementById(layerId);

        if (layer) {
            layer.classList.toggle('hidden', !visible);
        }
    }

    /**
     * Highlight pads, traces, and vias by net ID.
     */
    highlightNet(netId) {
        if (!this.svg) return;

        // Clear existing highlights
        this.svg.querySelectorAll('.pad.highlighted, .trace.highlighted, .via.highlighted').forEach(el => {
            el.classList.remove('highlighted');
        });

        // Highlight new selection
        if (netId !== null) {
            this.svg.querySelectorAll(`.pad[data-net="${netId}"]`).forEach(el => {
                el.classList.add('highlighted');
            });
            this.svg.querySelectorAll(`.trace[data-net="${netId}"]`).forEach(el => {
                el.classList.add('highlighted');
            });
            this.svg.querySelectorAll(`.via[data-net="${netId}"]`).forEach(el => {
                el.classList.add('highlighted');
            });
        }
    }

    /**
     * Highlight all elements of a net during routing (bolder/more visible).
     */
    highlightRoutingNet(netId) {
        if (!this.svg) return;

        // Clear any existing routing highlight
        this.clearRoutingHighlight();

        if (netId === null || netId === 0) return;

        // Add routing-active class to all elements of this net
        this.svg.querySelectorAll(`.pad[data-net="${netId}"]`).forEach(el => {
            el.classList.add('routing-active');
        });
        this.svg.querySelectorAll(`.trace[data-net="${netId}"]`).forEach(el => {
            el.classList.add('routing-active');
        });
        this.svg.querySelectorAll(`.via[data-net="${netId}"]`).forEach(el => {
            el.classList.add('routing-active');
        });
    }

    /**
     * Clear routing net highlight.
     */
    clearRoutingHighlight() {
        if (!this.svg) return;

        this.svg.querySelectorAll('.routing-active').forEach(el => {
            el.classList.remove('routing-active');
        });
    }

    /**
     * Get pads by net ID.
     */
    getPadsByNet(netId) {
        if (!this.svg) return [];

        return Array.from(this.svg.querySelectorAll(`.pad[data-net="${netId}"]`)).map(el => ({
            id: el.id,
            footprint: el.dataset.footprint,
            pad: el.dataset.pad,
            netName: el.dataset.netName
        }));
    }

    /**
     * Convert screen coordinates to SVG coordinates (public version).
     */
    screenToSVG(screenX, screenY) {
        return this._screenToSVG(screenX, screenY);
    }

    /**
     * Show a small "x" marker at the trace start point.
     */
    showStartMarker(x, y) {
        if (!this.svg) return;

        this.clearPendingElements();

        // Create a small "x" using two lines
        const size = 0.4;  // Half-size of the x
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'start-marker pending-element');

        const line1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line1.setAttribute('x1', x - size);
        line1.setAttribute('y1', y - size);
        line1.setAttribute('x2', x + size);
        line1.setAttribute('y2', y + size);
        line1.setAttribute('stroke', '#4caf50');
        line1.setAttribute('stroke-width', '0.15');
        line1.setAttribute('stroke-linecap', 'round');

        const line2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line2.setAttribute('x1', x - size);
        line2.setAttribute('y1', y + size);
        line2.setAttribute('x2', x + size);
        line2.setAttribute('y2', y - size);
        line2.setAttribute('stroke', '#4caf50');
        line2.setAttribute('stroke-width', '0.15');
        line2.setAttribute('stroke-linecap', 'round');

        group.appendChild(line1);
        group.appendChild(line2);
        this.svg.appendChild(group);
    }

    /**
     * Render a pending trace path.
     */
    renderPendingTrace(path, layer, width) {
        if (!this.svg || path.length < 2) return;

        // Remove existing pending trace but keep start marker
        this.svg.querySelectorAll('.pending-trace').forEach(el => el.remove());

        // Layer colors
        const layerColors = {
            'F.Cu': '#C83232',
            'B.Cu': '#3232C8',
            'In1.Cu': '#C8C832',
            'In2.Cu': '#32C8C8'
        };
        const color = layerColors[layer] || '#888888';

        // Create path element
        const pathData = path.map((p, i) =>
            (i === 0 ? 'M' : 'L') + p[0].toFixed(4) + ',' + p[1].toFixed(4)
        ).join(' ');

        const pathEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        pathEl.setAttribute('d', pathData);
        pathEl.setAttribute('stroke', color);
        pathEl.setAttribute('stroke-width', width);
        pathEl.setAttribute('stroke-linecap', 'round');
        pathEl.setAttribute('stroke-linejoin', 'round');
        pathEl.setAttribute('fill', 'none');
        pathEl.setAttribute('stroke-opacity', '0.5');  // Faint/transparent
        pathEl.setAttribute('class', 'pending-trace pending-element');
        this.svg.appendChild(pathEl);
    }

    /**
     * Clear all pending elements (markers, preview traces).
     */
    clearPendingElements() {
        if (!this.svg) return;
        this.svg.querySelectorAll('.pending-element').forEach(el => el.remove());
    }

    /**
     * Clear only the pending trace preview (keeps start marker).
     */
    clearPendingTrace() {
        if (!this.svg) return;
        this.svg.querySelectorAll('.pending-trace').forEach(el => el.remove());
    }

    /**
     * Remove traces and vias added in a session (for undo).
     */
    removeSessionTraces(segments, vias) {
        if (!this.svg) return;

        const userGroup = this.svg.getElementById('user-traces');
        if (!userGroup) return;

        // Remove the last N user-trace elements matching the session count
        const traceEls = userGroup.querySelectorAll('.user-trace');
        const viaEls = userGroup.querySelectorAll('.user-via');
        const holeEls = userGroup.querySelectorAll('.user-via-hole');

        // Remove traces (from the end)
        for (let i = 0; i < segments.length && traceEls.length > 0; i++) {
            const el = traceEls[traceEls.length - 1 - i];
            if (el) el.remove();
        }

        // Remove vias and holes (from the end)
        for (let i = 0; i < vias.length; i++) {
            const via = viaEls[viaEls.length - 1 - i];
            const hole = holeEls[holeEls.length - 1 - i];
            if (via) via.remove();
            if (hole) hole.remove();
        }
    }

    /**
     * Render a user-placed via at the given coordinates.
     * @param {number} x - X coordinate
     * @param {number} y - Y coordinate
     * @param {number} size - Via size in mm
     * @param {boolean} isPending - Whether this is a pending (uncommitted) via
     * @param {string} routeId - Route ID for tracking
     * @param {number} segmentIndex - Segment index within the route
     */
    renderUserVia(x, y, size, isPending = true, routeId = null, segmentIndex = null) {
        if (!this.svg) return;

        // Find or create user traces group
        let userGroup = this.svg.getElementById('user-traces');
        if (!userGroup) {
            userGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            userGroup.setAttribute('id', 'user-traces');
            userGroup.setAttribute('class', 'user-trace-layer');
            this.svg.appendChild(userGroup);
        }

        // Create via outer circle
        const via = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        via.setAttribute('cx', x);
        via.setAttribute('cy', y);
        via.setAttribute('r', size / 2);
        via.setAttribute('fill', '#C8A832');
        via.setAttribute('class', isPending ? 'user-via pending-element' : 'user-via');
        if (routeId) {
            via.setAttribute('data-trace-id', routeId);
        }
        if (segmentIndex !== null) {
            via.setAttribute('data-segment-index', segmentIndex.toString());
        }
        userGroup.appendChild(via);

        // Create drill hole
        const hole = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        hole.setAttribute('cx', x);
        hole.setAttribute('cy', y);
        hole.setAttribute('r', size / 4);  // Drill is typically half the via size
        hole.setAttribute('fill', '#1a1a1a');
        hole.setAttribute('class', isPending ? 'user-via-hole pending-element' : 'user-via-hole');
        if (routeId) {
            hole.setAttribute('data-trace-id', routeId);
        }
        if (segmentIndex !== null) {
            hole.setAttribute('data-segment-index', segmentIndex.toString());
        }
        userGroup.appendChild(hole);
    }

    /**
     * Confirm pending trace and make it permanent.
     * @param {Array} path - Array of [x, y] points
     * @param {string} layer - Layer name (e.g., 'F.Cu')
     * @param {number} width - Trace width in mm
     * @param {string} traceId - Unique trace ID for tracking
     * @param {number} segmentIndex - Segment index within the route
     * @returns {string|null} The trace ID if successful
     */
    confirmPendingTrace(path, layer, width, traceId = null, segmentIndex = null) {
        if (!this.svg || path.length < 2) return null;

        // Layer colors
        const layerColors = {
            'F.Cu': '#C83232',
            'B.Cu': '#3232C8',
            'In1.Cu': '#C8C832',
            'In2.Cu': '#32C8C8'
        };
        const color = layerColors[layer] || '#888888';

        // Find or create user traces group
        let userGroup = this.svg.getElementById('user-traces');
        if (!userGroup) {
            userGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            userGroup.setAttribute('id', 'user-traces');
            userGroup.setAttribute('class', 'user-trace-layer');
            this.svg.appendChild(userGroup);
        }

        // Create permanent path
        const pathData = path.map((p, i) =>
            (i === 0 ? 'M' : 'L') + p[0].toFixed(4) + ',' + p[1].toFixed(4)
        ).join(' ');

        const pathEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        pathEl.setAttribute('d', pathData);
        pathEl.setAttribute('stroke', color);
        pathEl.setAttribute('stroke-width', width);
        pathEl.setAttribute('stroke-linecap', 'round');
        pathEl.setAttribute('stroke-linejoin', 'round');
        pathEl.setAttribute('fill', 'none');
        pathEl.setAttribute('stroke-opacity', '0.9');
        pathEl.setAttribute('class', 'user-trace');
        pathEl.setAttribute('data-layer', layer);
        if (traceId) {
            pathEl.setAttribute('data-trace-id', traceId);
        }
        if (segmentIndex !== null) {
            pathEl.setAttribute('data-segment-index', segmentIndex.toString());
        }
        userGroup.appendChild(pathEl);

        // Clear only the pending trace preview (not the start marker)
        this.clearPendingTrace();

        return traceId;
    }

    /**
     * Set visibility of all traces with the given ID.
     * @param {string} traceId - The trace ID
     * @param {boolean} visible - Whether to show or hide
     */
    setTraceVisible(traceId, visible) {
        if (!this.svg) return;

        const traceEls = this.svg.querySelectorAll(`[data-trace-id="${traceId}"]`);
        traceEls.forEach(el => {
            el.style.display = visible ? '' : 'none';
        });
    }

    /**
     * Remove all traces with the given ID.
     * @param {string} traceId - The trace ID to remove
     * @returns {boolean} True if any traces were found and removed
     */
    removeTraceById(traceId) {
        if (!this.svg) return false;

        const traceEls = this.svg.querySelectorAll(`[data-trace-id="${traceId}"]`);
        if (traceEls.length > 0) {
            traceEls.forEach(el => el.remove());
            return true;
        }
        return false;
    }

    /**
     * Clear all user traces and vias.
     */
    clearAllUserTraces() {
        if (!this.svg) return;

        const userGroup = this.svg.getElementById('user-traces');
        if (userGroup) {
            userGroup.innerHTML = '';
        }
    }

    /**
     * Highlight specific segments by adding the segment-selected class.
     * @param {Array} segments - Array of {routeId, segmentIndex} objects
     */
    highlightSegments(segments) {
        if (!this.svg) return;

        for (const seg of segments) {
            // Highlight traces
            const traces = this.svg.querySelectorAll(
                `.user-trace[data-trace-id="${seg.routeId}"][data-segment-index="${seg.segmentIndex}"]`
            );
            traces.forEach(el => el.classList.add('segment-selected'));

            // Highlight vias (they mark the end of a segment/layer transition)
            const vias = this.svg.querySelectorAll(
                `.user-via[data-trace-id="${seg.routeId}"][data-segment-index="${seg.segmentIndex}"]`
            );
            vias.forEach(el => el.classList.add('segment-selected'));
        }
    }

    /**
     * Clear all segment selection highlights.
     */
    clearSegmentHighlights() {
        if (!this.svg) return;

        this.svg.querySelectorAll('.segment-selected').forEach(el => {
            el.classList.remove('segment-selected');
        });
    }

    /**
     * Remove a specific segment from the SVG.
     * @param {string} routeId - The route ID
     * @param {number} segmentIndex - The segment index to remove
     * @returns {boolean} True if any elements were removed
     */
    removeSegment(routeId, segmentIndex) {
        if (!this.svg) return false;

        let removed = false;

        // Remove trace segments with matching route ID and segment index
        const traces = this.svg.querySelectorAll(
            `.user-trace[data-trace-id="${routeId}"][data-segment-index="${segmentIndex}"]`
        );
        traces.forEach(el => {
            el.remove();
            removed = true;
        });

        // Remove vias with matching route ID and segment index
        const vias = this.svg.querySelectorAll(
            `.user-via[data-trace-id="${routeId}"][data-segment-index="${segmentIndex}"]`
        );
        vias.forEach(el => el.remove());

        // Remove via holes with matching route ID and segment index
        const holes = this.svg.querySelectorAll(
            `.user-via-hole[data-trace-id="${routeId}"][data-segment-index="${segmentIndex}"]`
        );
        holes.forEach(el => el.remove());

        return removed;
    }

    /**
     * Update the segment index attribute for elements.
     * @param {string} routeId - The route ID
     * @param {number} oldIndex - The current segment index
     * @param {number} newIndex - The new segment index
     */
    updateSegmentIndex(routeId, oldIndex, newIndex) {
        if (!this.svg) return;

        const selector = `[data-trace-id="${routeId}"][data-segment-index="${oldIndex}"]`;
        this.svg.querySelectorAll(selector).forEach(el => {
            el.setAttribute('data-segment-index', newIndex.toString());
        });
    }
}
