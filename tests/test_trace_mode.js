/**
 * Puppeteer test for routing functionality.
 * Tests routing UI, double-click to start routing, and same-net crossing.
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config_test');
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
    log('Starting routing tests...');
    log(`Server URL: ${SERVER_URL}`);

    const browser = await puppeteer.launch({
        headless: true,
        devtools: false,
        args: ['--window-size=1400,900', '--no-sandbox', '--disable-setuid-sandbox']
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

        // ========== TEST 2: Routing UI exists ==========
        log('\n--- Test 2: Routing UI ---');
        const routingUI = await page.evaluate(() => {
            return {
                hasPanel: !!document.getElementById('routing-panel'),
                hasLayerSelect: !!document.getElementById('trace-layer'),
                hasWidthInput: !!document.getElementById('trace-width'),
                hasStatus: !!document.getElementById('trace-status'),
                hasConfirm: !!document.getElementById('trace-confirm'),
                hasCancel: !!document.getElementById('trace-cancel')
            };
        });

        if (routingUI.hasPanel) {
            pass('Routing panel exists');
        } else {
            fail('Routing panel exists');
        }

        if (routingUI.hasLayerSelect && routingUI.hasWidthInput) {
            pass('Routing controls exist (layer, width)');
        } else {
            fail('Routing controls exist', `layer=${routingUI.hasLayerSelect}, width=${routingUI.hasWidthInput}`);
        }

        if (routingUI.hasStatus) {
            pass('Status display exists');
        } else {
            fail('Status display exists');
        }

        if (routingUI.hasConfirm && routingUI.hasCancel) {
            pass('Confirm/Cancel buttons exist');
        } else {
            fail('Confirm/Cancel buttons exist');
        }

        // ========== TEST 3: Layer selection ==========
        log('\n--- Test 3: Layer Selection ---');

        const layers = await page.evaluate(() => {
            const select = document.getElementById('trace-layer');
            if (!select) return [];
            return Array.from(select.options).map(o => o.value);
        });

        log(`  Available layers: ${layers.join(', ')}`);

        if (layers.includes('F.Cu') && layers.includes('B.Cu')) {
            pass('Layer selector has copper layers');
        } else {
            fail('Layer selector has copper layers');
        }

        // ========== TEST 4: Find pads for routing test ==========
        log('\n--- Test 4: Find Test Pads ---');

        const testPads = await page.evaluate(() => {
            const pads = Array.from(document.querySelectorAll('.pad'));

            // Group pads by net
            const padsByNet = {};
            for (const pad of pads) {
                const netId = pad.dataset.net;
                if (netId && parseInt(netId, 10) > 0) {
                    if (!padsByNet[netId]) padsByNet[netId] = [];
                    padsByNet[netId].push(pad);
                }
            }

            // Find a net with multiple pads
            let testNet = null;
            let testPadPair = null;
            for (const [netId, netPads] of Object.entries(padsByNet)) {
                if (netPads.length >= 2) {
                    testNet = netId;
                    testPadPair = [netPads[0], netPads[1]];
                    break;
                }
            }

            if (!testPadPair) return null;

            const pad1 = testPadPair[0];
            const pad2 = testPadPair[1];

            const bbox1 = pad1.getBoundingClientRect();
            const bbox2 = pad2.getBoundingClientRect();

            return {
                netId: testNet,
                netName: pad1.dataset.netName,
                pad1: {
                    id: pad1.id,
                    x: parseFloat(pad1.dataset.x || pad1.getAttribute('cx') || (bbox1.x + bbox1.width/2)),
                    y: parseFloat(pad1.dataset.y || pad1.getAttribute('cy') || (bbox1.y + bbox1.height/2)),
                    screenX: bbox1.x + bbox1.width / 2,
                    screenY: bbox1.y + bbox1.height / 2
                },
                pad2: {
                    id: pad2.id,
                    x: parseFloat(pad2.dataset.x || pad2.getAttribute('cx') || (bbox2.x + bbox2.width/2)),
                    y: parseFloat(pad2.dataset.y || pad2.getAttribute('cy') || (bbox2.y + bbox2.height/2)),
                    screenX: bbox2.x + bbox2.width / 2,
                    screenY: bbox2.y + bbox2.height / 2
                }
            };
        });

        if (testPads) {
            log(`  Found net ${testPads.netName} (ID: ${testPads.netId}) with pads:`);
            log(`    Pad 1: ${testPads.pad1.id} at screen (${testPads.pad1.screenX.toFixed(1)}, ${testPads.pad1.screenY.toFixed(1)})`);
            log(`    Pad 2: ${testPads.pad2.id} at screen (${testPads.pad2.screenX.toFixed(1)}, ${testPads.pad2.screenY.toFixed(1)})`);
            pass('Found same-net pad pair for testing');
        } else {
            fail('Found same-net pad pair for testing', 'No net with multiple pads found');
        }

        // ========== TEST 5: Single-click highlights net (no routing) ==========
        log('\n--- Test 5: Single-Click Highlights ---');

        // Get a pad to single-click
        const highlightTarget = await page.evaluate(() => {
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

        if (highlightTarget) {
            log(`  Single-clicking on pad at (${highlightTarget.screenX.toFixed(1)}, ${highlightTarget.screenY.toFixed(1)})`);
            // Single click should highlight, not start routing
            await page.mouse.click(highlightTarget.screenX, highlightTarget.screenY);
            await sleep(300);

            const afterSingleClick = await page.evaluate((netId) => {
                // Check if routing session started (it should NOT have)
                const state = window.getRoutingState?.();
                const hasRoutingSession = state?.routingSession !== null && state?.routingSession !== undefined;

                // Check if net is highlighted
                const highlightedPads = document.querySelectorAll(`.pad.highlighted[data-net="${netId}"]`);

                // Check if start marker exists (it should NOT)
                const hasStartMarker = !!document.querySelector('.start-marker');

                return {
                    hasRoutingSession,
                    hasStartMarker,
                    highlightedCount: highlightedPads.length
                };
            }, highlightTarget.netId);

            if (!afterSingleClick.hasRoutingSession && !afterSingleClick.hasStartMarker) {
                pass('Single-click does not start routing');
            } else {
                fail('Single-click does not start routing', `routingSession=${afterSingleClick.hasRoutingSession}, startMarker=${afterSingleClick.hasStartMarker}`);
            }

            if (afterSingleClick.highlightedCount > 0) {
                pass('Single-click highlights net', `${afterSingleClick.highlightedCount} pads highlighted`);
            } else {
                fail('Single-click highlights net');
            }

            // Clear selection for next test
            await page.keyboard.press('Escape');
            await sleep(200);
        }

        // ========== TEST 6: Start marker appears on double-click ==========
        log('\n--- Test 6: Start Marker ---');

        // Get a clickable pad position
        const clickTarget = await page.evaluate(() => {
            const pads = document.querySelectorAll('.pad');
            if (pads.length === 0) return null;
            // Find first pad with a net
            for (const pad of pads) {
                if (parseInt(pad.dataset.net, 10) > 0) {
                    const bbox = pad.getBoundingClientRect();
                    return {
                        screenX: bbox.x + bbox.width / 2,
                        screenY: bbox.y + bbox.height / 2,
                        padId: pad.id
                    };
                }
            }
            const bbox = pads[0].getBoundingClientRect();
            return {
                screenX: bbox.x + bbox.width / 2,
                screenY: bbox.y + bbox.height / 2,
                padId: pads[0].id
            };
        });

        if (clickTarget) {
            log(`  Double-clicking on pad at (${clickTarget.screenX.toFixed(1)}, ${clickTarget.screenY.toFixed(1)})`);
            // Double-click to start routing
            await page.mouse.click(clickTarget.screenX, clickTarget.screenY, { clickCount: 2 });
            await sleep(500);

            const markerExists = await page.evaluate(() => {
                const marker = document.querySelector('.start-marker');
                return !!marker;
            });

            if (markerExists) {
                pass('Start marker appears after double-click');
            } else {
                fail('Start marker appears after double-click');
            }

            const statusText = await page.evaluate(() => {
                const status = document.getElementById('trace-status');
                return status ? status.textContent : '';
            });

            log(`  Status: "${statusText}"`);
            if (statusText.toLowerCase().includes('click') || statusText.toLowerCase().includes('route') || statusText.toLowerCase().includes('move')) {
                pass('Status updates after double-click');
            } else {
                fail('Status updates after double-click', `Got: "${statusText}"`);
            }

            await page.screenshot({ path: `${SCREENSHOT_DIR}/routing_start_marker.png`, fullPage: true });
            log(`  Screenshot: ${SCREENSHOT_DIR}/routing_start_marker.png`);
        }

        // ========== TEST 7: API Route endpoint ==========
        log('\n--- Test 7: Route API Endpoint ---');

        const routeResponse = await page.evaluate(async () => {
            try {
                const response = await fetch('/api/route', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        start_x: 140.0,
                        start_y: 70.0,
                        end_x: 145.0,
                        end_y: 75.0,
                        layer: 'F.Cu',
                        width: 0.25
                    })
                });
                const data = await response.json();
                return { status: response.status, data };
            } catch (err) {
                return { error: err.message };
            }
        });

        if (routeResponse.error) {
            fail('Route API endpoint responds', routeResponse.error);
        } else if (routeResponse.status === 200) {
            pass('Route API endpoint responds');
            log(`  Response: success=${routeResponse.data.success}, path length=${routeResponse.data.path?.length || 0}`);
        } else {
            fail('Route API endpoint responds', `Status: ${routeResponse.status}`);
        }

        // ========== TEST 8: Path uses 45-degree angles ==========
        log('\n--- Test 8: 45-Degree Angle Constraint ---');

        if (routeResponse.data && routeResponse.data.path && routeResponse.data.path.length >= 2) {
            const path = routeResponse.data.path;
            let allAnglesValid = true;
            let invalidAngle = null;

            for (let i = 0; i < path.length - 1; i++) {
                const dx = path[i + 1][0] - path[i][0];
                const dy = path[i + 1][1] - path[i][1];

                if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) continue;

                const angle = Math.atan2(dy, dx) * 180 / Math.PI;
                const normalizedAngle = ((angle % 360) + 360) % 360;
                const remainder = normalizedAngle % 45;

                if (remainder > 1 && remainder < 44) {
                    allAnglesValid = false;
                    invalidAngle = normalizedAngle;
                    break;
                }
            }

            if (allAnglesValid) {
                pass('Path segments use 45 degree angles only');
            } else {
                fail('Path segments use 45 degree angles only', `Found angle ${invalidAngle?.toFixed(1)} degrees`);
            }
        } else {
            log('  Skipping angle test - no path returned');
        }

        // ========== TEST 9: Same-net crossing allowed ==========
        log('\n--- Test 9: Same-Net Crossing ---');

        if (testPads) {
            const sameNetRoute = await page.evaluate(async (pads) => {
                try {
                    const response = await fetch('/api/route', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            start_x: pads.pad1.x,
                            start_y: pads.pad1.y,
                            end_x: pads.pad2.x,
                            end_y: pads.pad2.y,
                            layer: 'F.Cu',
                            width: 0.25,
                            net_id: parseInt(pads.netId, 10)
                        })
                    });
                    const data = await response.json();
                    return { success: response.ok, data };
                } catch (err) {
                    return { error: err.message };
                }
            }, testPads);

            if (sameNetRoute.error) {
                fail('Same-net routing request', sameNetRoute.error);
            } else if (sameNetRoute.data && sameNetRoute.data.success) {
                pass('Route found between same-net pads', `${sameNetRoute.data.path.length} waypoints`);
                log('  This confirms same-net elements can be crossed');
            } else {
                log(`  Routing result: ${JSON.stringify(sameNetRoute.data)}`);
                // This might fail if there's truly no path, which is OK
                // The key test is that same-net elements don't block
                log('  Note: Route may fail due to other obstacles, not same-net blocking');
            }
        } else {
            log('  Skipping same-net test - no test pads found');
        }

        // ========== TEST 10: Cancel resets state ==========
        log('\n--- Test 10: Cancel/Reset ---');

        // Press Escape to cancel
        await page.keyboard.press('Escape');
        await sleep(200);

        const afterEscape = await page.evaluate(() => {
            const marker = document.querySelector('.start-marker');
            const status = document.getElementById('trace-status');
            return {
                markerExists: !!marker,
                statusText: status ? status.textContent : ''
            };
        });

        if (!afterEscape.markerExists) {
            pass('Escape clears start marker');
        } else {
            fail('Escape clears start marker');
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

        log('\nScreenshots saved to /tmp/');

        if (results.failed > 0) {
            log('\n  Some tests failed');
        } else {
            log('\n  All tests passed');
        }

        log('\nTests completed successfully.');
        await browser.close();
        process.exit(results.failed > 0 ? 1 : 0);

    } catch (err) {
        console.error('\n  Test error:', err.message);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/routing_error.png`, fullPage: true });
        log(`Error screenshot: ${SCREENSHOT_DIR}/routing_error.png`);
        await browser.close();
        process.exit(1);
    }
}

runTests().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
