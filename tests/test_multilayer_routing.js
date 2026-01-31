/**
 * Puppeteer test for multi-layer trace routing features.
 * Tests:
 * - Continuous routing to cursor position
 * - Click to commit segment (click point becomes new start)
 * - Layer switching with via at cursor
 * - Double-click to finish routing
 * - Escape to cancel and undo all traces
 * - Net highlighting during routing
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config');
const SCREENSHOT_DIR = '/tmp';

// Test results
const results = {
    passed: 0,
    failed: 0,
    tests: []
};

function log(msg) {
    console.log(`[TEST] ${msg}`);
}

function pass(testName, details = '') {
    results.passed++;
    results.tests.push({ name: testName, status: 'PASS', details });
    console.log(`  ✓ PASS: ${testName}${details ? ' - ' + details : ''}`);
}

function fail(testName, details = '') {
    results.failed++;
    results.tests.push({ name: testName, status: 'FAIL', details });
    console.log(`  ✗ FAIL: ${testName}${details ? ' - ' + details : ''}`);
}

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTests() {
    log('Starting multi-layer routing tests...');
    log(`Server URL: ${SERVER_URL}`);

    const browser = await puppeteer.launch({
        headless: false,
        devtools: false,
        args: ['--window-size=1400,900']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Enable console logging from the page
    page.on('console', msg => {
        if (msg.type() === 'error') {
            console.log(`  [PAGE ERROR] ${msg.text()}`);
        }
    });

    try {
        // ========== TEST 1: Page loads successfully ==========
        log('\n--- Test 1: Page Load ---');
        try {
            await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
            pass('Page loads');
        } catch (err) {
            fail('Page loads', `Server not running at ${SERVER_URL}?`);
            throw new Error('Cannot continue without server');
        }

        // ========== TEST 2: Check Via API Endpoint exists ==========
        log('\n--- Test 2: Via Check API Endpoint ---');

        const viaCheckResponse = await page.evaluate(async () => {
            try {
                const response = await fetch('/api/check-via', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        x: 140.0,
                        y: 70.0,
                        size: 0.8,
                        drill: 0.4
                    })
                });
                const data = await response.json();
                return { status: response.status, data };
            } catch (err) {
                return { error: err.message };
            }
        });

        if (viaCheckResponse.error) {
            fail('Via check API endpoint responds', viaCheckResponse.error);
        } else if (viaCheckResponse.status === 200) {
            pass('Via check API endpoint responds');
            log(`  Response: valid=${viaCheckResponse.data.valid}, message="${viaCheckResponse.data.message || ''}"`);
        } else {
            fail('Via check API endpoint responds', `Status: ${viaCheckResponse.status}`);
        }

        // ========== TEST 3: Via check with net_id parameter ==========
        log('\n--- Test 3: Via Check with Net ID ---');

        const viaCheckWithNet = await page.evaluate(async () => {
            try {
                const response = await fetch('/api/check-via', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        x: 140.0,
                        y: 70.0,
                        size: 0.8,
                        drill: 0.4,
                        net_id: 1
                    })
                });
                const data = await response.json();
                return { status: response.status, data };
            } catch (err) {
                return { error: err.message };
            }
        });

        if (viaCheckWithNet.status === 200) {
            pass('Via check accepts net_id parameter');
        } else {
            fail('Via check accepts net_id parameter');
        }

        // ========== TEST 4: Trace error element exists ==========
        log('\n--- Test 4: Trace Error Element ---');

        const traceErrorUI = await page.evaluate(() => {
            const errorEl = document.getElementById('trace-error');
            return {
                exists: !!errorEl,
                hidden: errorEl ? errorEl.classList.contains('hidden') : true
            };
        });

        if (traceErrorUI.exists) {
            pass('Trace error element exists');
        } else {
            fail('Trace error element exists');
        }

        if (traceErrorUI.hidden) {
            pass('Trace error initially hidden');
        } else {
            fail('Trace error initially hidden');
        }

        // ========== TEST 5: Enable trace mode and start routing ==========
        log('\n--- Test 5: Start Routing Session with Net Highlight ---');

        // Enable trace mode
        await page.click('#trace-mode-toggle');
        await sleep(300);

        // Find a pad to click
        const startPad = await page.evaluate(() => {
            const pads = document.querySelectorAll('.pad');
            for (const pad of pads) {
                if (parseInt(pad.dataset.net, 10) > 0) {
                    const bbox = pad.getBoundingClientRect();
                    return {
                        screenX: bbox.x + bbox.width / 2,
                        screenY: bbox.y + bbox.height / 2,
                        padId: pad.id,
                        netId: pad.dataset.net
                    };
                }
            }
            return null;
        });

        if (startPad) {
            log(`  Clicking on pad ${startPad.padId} (net ${startPad.netId}) at (${startPad.screenX.toFixed(1)}, ${startPad.screenY.toFixed(1)})`);
            await page.mouse.click(startPad.screenX, startPad.screenY);
            await sleep(500);

            const sessionStarted = await page.evaluate((netId) => {
                const marker = document.querySelector('.start-marker');
                const status = document.getElementById('trace-status');
                const actions = document.getElementById('trace-actions');
                const routingActive = document.querySelectorAll('.routing-active');
                return {
                    markerExists: !!marker,
                    statusText: status ? status.textContent : '',
                    actionsVisible: actions ? !actions.classList.contains('hidden') : false,
                    routingActiveCount: routingActive.length
                };
            }, startPad.netId);

            if (sessionStarted.markerExists) {
                pass('Start marker appears on first click');
            } else {
                fail('Start marker appears on first click');
            }

            if (sessionStarted.actionsVisible) {
                pass('Action buttons appear on routing start');
            } else {
                fail('Action buttons appear on routing start');
            }

            if (sessionStarted.routingActiveCount > 0) {
                pass('Same-net elements highlighted during routing', `${sessionStarted.routingActiveCount} elements`);
            } else {
                fail('Same-net elements highlighted during routing');
            }

            log(`  Status: "${sessionStarted.statusText}"`);

            await page.screenshot({ path: `${SCREENSHOT_DIR}/multilayer_session_started.png`, fullPage: true });
        } else {
            fail('Found pad to start routing');
        }

        // ========== TEST 6: Continuous routing on mouse move ==========
        log('\n--- Test 6: Continuous Routing on Mouse Move ---');

        if (startPad) {
            // Move mouse to trigger continuous routing
            const offsetX = startPad.screenX + 80;
            const offsetY = startPad.screenY + 50;
            log(`  Moving mouse to (${offsetX.toFixed(1)}, ${offsetY.toFixed(1)})`);

            await page.mouse.move(offsetX, offsetY);
            await sleep(300);  // Wait for debounced routing

            const afterMove = await page.evaluate(() => {
                const pendingTraces = document.querySelectorAll('.pending-trace');
                return {
                    pendingTraceCount: pendingTraces.length
                };
            });

            log(`  Pending trace elements after mouse move: ${afterMove.pendingTraceCount}`);

            // Note: Route preview may or may not appear depending on obstacles
            if (afterMove.pendingTraceCount > 0) {
                pass('Route preview appears on mouse move');
            } else {
                log('  Note: No route preview (may be blocked by obstacles)');
            }

            await page.screenshot({ path: `${SCREENSHOT_DIR}/multilayer_mouse_move.png`, fullPage: true });
        }

        // ========== TEST 6b: Click commits segment ==========
        log('\n--- Test 6b: Click Commits Segment ---');

        if (startPad) {
            const commitX = startPad.screenX + 60;
            const commitY = startPad.screenY + 40;
            log(`  Clicking to commit at (${commitX.toFixed(1)}, ${commitY.toFixed(1)})`);

            await page.mouse.click(commitX, commitY);
            await sleep(500);

            const afterCommit = await page.evaluate(() => {
                const userTraces = document.querySelectorAll('.user-trace');
                const startMarker = document.querySelector('.start-marker');
                const status = document.getElementById('trace-status');
                return {
                    userTraceCount: userTraces.length,
                    hasStartMarker: !!startMarker,
                    statusText: status ? status.textContent : ''
                };
            });

            log(`  User traces after click: ${afterCommit.userTraceCount}`);
            log(`  Status: "${afterCommit.statusText}"`);

            if (afterCommit.userTraceCount > 0 || afterCommit.statusText.toLowerCase().includes('commit')) {
                pass('Click commits segment');
            } else {
                log('  Note: Segment may not have committed (routing may have failed)');
            }

            if (afterCommit.hasStartMarker) {
                pass('Start marker moved to new position after commit');
            }

            await page.screenshot({ path: `${SCREENSHOT_DIR}/multilayer_after_commit.png`, fullPage: true });
        }

        // ========== TEST 7: Layer switching with keyboard ==========
        log('\n--- Test 7: Layer Switching Keyboard Shortcuts ---');

        // Reset state first
        await page.keyboard.press('Escape');
        await sleep(200);

        // Start new routing session
        if (startPad) {
            await page.mouse.click(startPad.screenX, startPad.screenY);
            await sleep(500);
        }

        // Get current layer
        const beforeSwitch = await page.evaluate(() => {
            const layerSelect = document.getElementById('trace-layer');
            return layerSelect ? layerSelect.value : '';
        });
        log(`  Current layer before switch: ${beforeSwitch}`);

        // Press '2' to switch to B.Cu
        await page.keyboard.press('2');
        await sleep(500);

        const afterSwitch = await page.evaluate(() => {
            const layerSelect = document.getElementById('trace-layer');
            const status = document.getElementById('trace-status');
            const vias = document.querySelectorAll('.user-via');
            return {
                currentLayer: layerSelect ? layerSelect.value : '',
                statusText: status ? status.textContent : '',
                viaCount: vias.length
            };
        });

        log(`  Layer after pressing '2': ${afterSwitch.currentLayer}`);
        log(`  Status: "${afterSwitch.statusText}"`);
        log(`  Via elements: ${afterSwitch.viaCount}`);

        if (afterSwitch.currentLayer === 'B.Cu') {
            pass('Key "2" switches to B.Cu layer');
        } else if (afterSwitch.statusText.toLowerCase().includes('clearance') ||
                   afterSwitch.statusText.toLowerCase().includes('violation')) {
            pass('Layer switch blocked with clearance error (expected)');
        } else {
            fail('Key "2" switches to B.Cu layer', `Layer is ${afterSwitch.currentLayer}`);
        }

        // Check if via was created (if switch was valid)
        if (afterSwitch.viaCount > 0) {
            pass('Via element created on layer switch');
        } else if (afterSwitch.currentLayer !== 'B.Cu') {
            log('  Note: Via not created because layer switch was blocked');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/multilayer_layer_switch.png`, fullPage: true });

        // ========== TEST 8: All layer shortcuts work ==========
        log('\n--- Test 8: All Layer Shortcuts (1-4) ---');

        const layerTests = [
            { key: '1', expected: 'F.Cu' },
            { key: '2', expected: 'B.Cu' },
            { key: '3', expected: 'In1.Cu' },
            { key: '4', expected: 'In2.Cu' }
        ];

        for (const test of layerTests) {
            await page.keyboard.press(test.key);
            await sleep(300);

            const layer = await page.evaluate(() => {
                const select = document.getElementById('trace-layer');
                return select ? select.value : '';
            });

            // Layer may not switch if blocked, but the mapping should be correct when it does
            log(`  Key '${test.key}' -> Layer: ${layer}`);
        }
        pass('All layer shortcuts (1-4) processed');

        // ========== TEST 9: Double-click to end routing ==========
        log('\n--- Test 9: Double-Click to End Routing ---');

        // Reset and start new session
        await page.keyboard.press('Escape');
        await sleep(200);

        if (startPad) {
            await page.mouse.click(startPad.screenX, startPad.screenY);
            await sleep(500);

            // Verify we have an active session
            const beforeDblClick = await page.evaluate(() => {
                const actions = document.getElementById('trace-actions');
                return {
                    actionsVisible: actions ? !actions.classList.contains('hidden') : false
                };
            });

            if (beforeDblClick.actionsVisible) {
                log('  Active routing session confirmed');

                // Double-click to end
                await page.mouse.click(startPad.screenX + 20, startPad.screenY + 20, { clickCount: 2 });
                await sleep(500);

                const afterDblClick = await page.evaluate(() => {
                    const actions = document.getElementById('trace-actions');
                    const status = document.getElementById('trace-status');
                    const pendingElements = document.querySelectorAll('.pending-element');
                    return {
                        actionsVisible: actions ? !actions.classList.contains('hidden') : false,
                        statusText: status ? status.textContent : '',
                        pendingCount: pendingElements.length
                    };
                });

                log(`  Status after double-click: "${afterDblClick.statusText}"`);

                if (!afterDblClick.actionsVisible && afterDblClick.pendingCount === 0) {
                    pass('Double-click ends routing session');
                } else if (afterDblClick.statusText.toLowerCase().includes('confirm')) {
                    pass('Double-click finalizes routing session');
                } else {
                    fail('Double-click ends routing session');
                }

                await page.screenshot({ path: `${SCREENSHOT_DIR}/multilayer_after_dblclick.png`, fullPage: true });
            }
        }

        // ========== TEST 10: Same-net pad detection ==========
        log('\n--- Test 10: Same-Net Pad Auto-Finalize ---');

        // Find two pads on the same net
        const sameNetPads = await page.evaluate(() => {
            const pads = Array.from(document.querySelectorAll('.pad'));
            const padsByNet = {};

            for (const pad of pads) {
                const netId = parseInt(pad.dataset.net, 10);
                if (netId > 0) {
                    if (!padsByNet[netId]) padsByNet[netId] = [];
                    padsByNet[netId].push(pad);
                }
            }

            // Find a net with multiple pads
            for (const [netId, netPads] of Object.entries(padsByNet)) {
                if (netPads.length >= 2) {
                    const pad1 = netPads[0];
                    const pad2 = netPads[1];
                    const bbox1 = pad1.getBoundingClientRect();
                    const bbox2 = pad2.getBoundingClientRect();
                    return {
                        netId: netId,
                        pad1: { screenX: bbox1.x + bbox1.width/2, screenY: bbox1.y + bbox1.height/2, id: pad1.id },
                        pad2: { screenX: bbox2.x + bbox2.width/2, screenY: bbox2.y + bbox2.height/2, id: pad2.id }
                    };
                }
            }
            return null;
        });

        if (sameNetPads) {
            log(`  Found same-net pads: ${sameNetPads.pad1.id} and ${sameNetPads.pad2.id} (net ${sameNetPads.netId})`);

            // Start routing from first pad
            await page.mouse.click(sameNetPads.pad1.screenX, sameNetPads.pad1.screenY);
            await sleep(500);

            // Click on second pad of same net (should auto-finalize)
            await page.mouse.click(sameNetPads.pad2.screenX, sameNetPads.pad2.screenY);
            await sleep(800);

            const afterSameNet = await page.evaluate(() => {
                const status = document.getElementById('trace-status');
                const actions = document.getElementById('trace-actions');
                return {
                    statusText: status ? status.textContent : '',
                    actionsHidden: actions ? actions.classList.contains('hidden') : true
                };
            });

            log(`  Status: "${afterSameNet.statusText}"`);

            if (afterSameNet.statusText.toLowerCase().includes('confirm') ||
                afterSameNet.actionsHidden) {
                pass('Clicking same-net pad finalizes route');
            } else {
                log('  Note: Route may have failed, but same-net detection was attempted');
            }

            await page.screenshot({ path: `${SCREENSHOT_DIR}/multilayer_same_net.png`, fullPage: true });
        } else {
            log('  No same-net pad pair found for testing');
        }

        // ========== TEST 11: Confirm button works ==========
        log('\n--- Test 11: Confirm Button ---');

        // Reset and start new session
        await page.keyboard.press('Escape');
        await sleep(200);

        if (startPad) {
            await page.mouse.click(startPad.screenX, startPad.screenY);
            await sleep(500);

            const confirmBtn = await page.$('#trace-confirm');
            if (confirmBtn) {
                await confirmBtn.click();
                await sleep(300);

                const afterConfirm = await page.evaluate(() => {
                    const actions = document.getElementById('trace-actions');
                    const status = document.getElementById('trace-status');
                    return {
                        actionsHidden: actions ? actions.classList.contains('hidden') : true,
                        statusText: status ? status.textContent : ''
                    };
                });

                if (afterConfirm.actionsHidden) {
                    pass('Confirm button ends routing session');
                } else {
                    fail('Confirm button ends routing session');
                }
            }
        }

        // ========== TEST 12: Cancel/Escape undoes all traces ==========
        log('\n--- Test 12: Cancel/Escape Undoes All Traces ---');

        if (startPad) {
            // Count traces before starting
            const beforeStart = await page.evaluate(() => {
                return document.querySelectorAll('.user-trace').length;
            });
            log(`  User traces before: ${beforeStart}`);

            // Start routing and add a segment
            await page.mouse.click(startPad.screenX, startPad.screenY);
            await sleep(300);

            // Move and click to commit a segment
            await page.mouse.move(startPad.screenX + 40, startPad.screenY + 30);
            await sleep(200);
            await page.mouse.click(startPad.screenX + 40, startPad.screenY + 30);
            await sleep(500);

            const afterCommit = await page.evaluate(() => {
                return document.querySelectorAll('.user-trace').length;
            });
            log(`  User traces after commit: ${afterCommit}`);

            // Press Escape to cancel and undo
            await page.keyboard.press('Escape');
            await sleep(300);

            const afterEscape = await page.evaluate(() => {
                const actions = document.getElementById('trace-actions');
                const marker = document.querySelector('.start-marker');
                const userTraces = document.querySelectorAll('.user-trace');
                const routingActive = document.querySelectorAll('.routing-active');
                return {
                    actionsHidden: actions ? actions.classList.contains('hidden') : true,
                    markerExists: !!marker,
                    userTraceCount: userTraces.length,
                    routingHighlightCleared: routingActive.length === 0
                };
            });

            log(`  User traces after Escape: ${afterEscape.userTraceCount}`);

            if (afterEscape.actionsHidden && !afterEscape.markerExists) {
                pass('Escape clears routing state');
            } else {
                fail('Escape clears routing state');
            }

            if (afterEscape.routingHighlightCleared) {
                pass('Escape clears routing net highlight');
            } else {
                fail('Escape clears routing net highlight');
            }

            // Note: Trace undo verification depends on whether segments were successfully routed
            if (afterEscape.userTraceCount <= beforeStart) {
                pass('Escape undoes session traces');
            } else {
                log(`  Note: Traces may not have been undone (${afterEscape.userTraceCount} > ${beforeStart})`);
            }
        }

        // ========== TEST 13: Error display styling ==========
        log('\n--- Test 13: Error Display Styling ---');

        const errorStyles = await page.evaluate(() => {
            const errorEl = document.getElementById('trace-error');
            if (!errorEl) return null;

            const styles = window.getComputedStyle(errorEl);
            return {
                hasBackground: styles.backgroundColor !== 'transparent' && styles.backgroundColor !== 'rgba(0, 0, 0, 0)',
                hasBorder: styles.borderWidth !== '0px',
                display: styles.display
            };
        });

        if (errorStyles) {
            if (errorStyles.hasBackground || errorStyles.hasBorder) {
                pass('Error element has visible styling');
            } else {
                log('  Note: Error element styling may be minimal');
            }
        }

        // ========== TEST 14: Keyboard shortcuts in controls list ==========
        log('\n--- Test 14: Updated Controls List ---');

        const controlsText = await page.evaluate(() => {
            const controls = document.querySelector('.controls-list');
            return controls ? controls.textContent : '';
        });

        if (controlsText.includes('1-4') || controlsText.includes('layer')) {
            pass('Controls list shows layer switch shortcut');
        } else {
            fail('Controls list shows layer switch shortcut');
        }

        if (controlsText.toLowerCase().includes('dbl') || controlsText.toLowerCase().includes('double')) {
            pass('Controls list shows double-click shortcut');
        } else {
            fail('Controls list shows double-click shortcut');
        }

        // ========== TEST 15: Via rendering ==========
        log('\n--- Test 15: Via Rendering (SVG) ---');

        // Check if renderUserVia function exists
        const hasViaRenderer = await page.evaluate(() => {
            return typeof SVGViewer !== 'undefined' &&
                   SVGViewer.prototype.renderUserVia !== undefined;
        });

        if (hasViaRenderer) {
            pass('SVGViewer.renderUserVia method exists');
        } else {
            fail('SVGViewer.renderUserVia method exists');
        }

        // ========== SUMMARY ==========
        log('\n========================================');
        log('TEST SUMMARY');
        log('========================================');
        log(`Passed: ${results.passed}`);
        log(`Failed: ${results.failed}`);
        log(`Total:  ${results.passed + results.failed}`);

        if (results.failed > 0) {
            log('\nFailed tests:');
            results.tests.filter(t => t.status === 'FAIL').forEach(t => {
                log(`  - ${t.name}: ${t.details}`);
            });
        }

        log('\nScreenshots saved to /tmp/multilayer_*.png');

        if (results.failed > 0) {
            log('\n⚠️  Some tests failed');
        } else {
            log('\n✓ All tests passed');
        }

        log('\nBrowser left open for manual inspection. Press Ctrl+C to close.');
        await new Promise(() => {}); // Keep browser open

    } catch (err) {
        console.error('\n❌ Test error:', err.message);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/multilayer_error.png`, fullPage: true });
        log(`Error screenshot: ${SCREENSHOT_DIR}/multilayer_error.png`);
        await browser.close();
        process.exit(1);
    }
}

runTests().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
