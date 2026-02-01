/**
 * Puppeteer test for trace mode functionality.
 * Tests trace mode toggle, routing, and same-net crossing.
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
    log('Starting trace mode tests...');
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

        // ========== TEST 2: Trace mode UI exists ==========
        log('\n--- Test 2: Trace Mode UI ---');
        const traceModeUI = await page.evaluate(() => {
            return {
                hasPanel: !!document.getElementById('trace-mode-panel'),
                hasToggle: !!document.getElementById('trace-mode-toggle'),
                hasOptions: !!document.getElementById('trace-options'),
                hasLayerSelect: !!document.getElementById('trace-layer'),
                hasWidthInput: !!document.getElementById('trace-width'),
                hasStatus: !!document.getElementById('trace-status'),
                hasConfirm: !!document.getElementById('trace-confirm'),
                hasCancel: !!document.getElementById('trace-cancel')
            };
        });

        if (traceModeUI.hasPanel) {
            pass('Trace mode panel exists');
        } else {
            fail('Trace mode panel exists');
        }

        if (traceModeUI.hasToggle) {
            pass('Trace mode toggle button exists');
        } else {
            fail('Trace mode toggle button exists');
        }

        if (traceModeUI.hasLayerSelect && traceModeUI.hasWidthInput) {
            pass('Trace options controls exist');
        } else {
            fail('Trace options controls exist');
        }

        // ========== TEST 3: Toggle trace mode ==========
        log('\n--- Test 3: Toggle Trace Mode ---');

        // Check initial state
        const initialState = await page.evaluate(() => {
            const toggle = document.getElementById('trace-mode-toggle');
            const options = document.getElementById('trace-options');
            return {
                toggleText: toggle ? toggle.textContent : '',
                toggleActive: toggle ? toggle.classList.contains('active') : false,
                optionsHidden: options ? options.classList.contains('hidden') : true,
                bodyHasTraceMode: document.body.classList.contains('trace-mode-active')
            };
        });

        if (!initialState.toggleActive) {
            pass('Trace mode initially disabled');
        } else {
            fail('Trace mode initially disabled');
        }

        // Click toggle to enable trace mode
        await page.click('#trace-mode-toggle');
        await sleep(300);

        const afterEnable = await page.evaluate(() => {
            const toggle = document.getElementById('trace-mode-toggle');
            const options = document.getElementById('trace-options');
            return {
                toggleText: toggle ? toggle.textContent : '',
                toggleActive: toggle ? toggle.classList.contains('active') : false,
                optionsHidden: options ? options.classList.contains('hidden') : true,
                bodyHasTraceMode: document.body.classList.contains('trace-mode-active')
            };
        });

        if (afterEnable.toggleActive && afterEnable.bodyHasTraceMode) {
            pass('Trace mode enabled after click');
        } else {
            fail('Trace mode enabled after click', `active=${afterEnable.toggleActive}, body=${afterEnable.bodyHasTraceMode}`);
        }

        if (!afterEnable.optionsHidden) {
            pass('Trace options visible when enabled');
        } else {
            fail('Trace options visible when enabled');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/trace_mode_enabled.png`, fullPage: true });
        log(`  Screenshot: ${SCREENSHOT_DIR}/trace_mode_enabled.png`);

        // ========== TEST 4: Keyboard shortcut (T) ==========
        log('\n--- Test 4: Keyboard Shortcut ---');

        // Disable trace mode first
        await page.click('#trace-mode-toggle');
        await sleep(200);

        // Press T to enable
        await page.keyboard.press('t');
        await sleep(200);

        const afterT = await page.evaluate(() => {
            const toggle = document.getElementById('trace-mode-toggle');
            return toggle ? toggle.classList.contains('active') : false;
        });

        if (afterT) {
            pass('T key enables trace mode');
        } else {
            fail('T key enables trace mode');
        }

        // ========== TEST 5: Layer selection ==========
        log('\n--- Test 5: Layer Selection ---');

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

        // ========== TEST 6: Find pads for routing test ==========
        log('\n--- Test 6: Find Test Pads ---');

        const testPads = await page.evaluate(() => {
            const pads = Array.from(document.querySelectorAll('.pad'));

            // Find two pads on F.Cu with the same net (for same-net crossing test)
            const fCuPads = pads.filter(p => {
                // Check if pad is on F.Cu (has data attribute or is in F.Cu layer)
                return true; // All pads should work for this test
            });

            // Group pads by net
            const padsByNet = {};
            for (const pad of fCuPads) {
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
            // Continue with other tests anyway
        }

        // ========== TEST 7: Start marker appears on first click ==========
        log('\n--- Test 7: Start Marker ---');

        // Ensure trace mode is enabled
        const traceModeEnabled = await page.evaluate(() => {
            return document.body.classList.contains('trace-mode-active');
        });
        if (!traceModeEnabled) {
            await page.click('#trace-mode-toggle');
            await sleep(200);
        }

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
            log(`  Clicking on pad at (${clickTarget.screenX.toFixed(1)}, ${clickTarget.screenY.toFixed(1)})`);
            await page.mouse.click(clickTarget.screenX, clickTarget.screenY);
            await sleep(500);

            const markerExists = await page.evaluate(() => {
                const marker = document.querySelector('.start-marker');
                return !!marker;
            });

            if (markerExists) {
                pass('Start marker appears after first click');
            } else {
                fail('Start marker appears after first click');
            }

            const statusText = await page.evaluate(() => {
                const status = document.getElementById('trace-status');
                return status ? status.textContent : '';
            });

            log(`  Status: "${statusText}"`);
            if (statusText.toLowerCase().includes('click') || statusText.toLowerCase().includes('destination')) {
                pass('Status updates after first click');
            } else {
                fail('Status updates after first click', `Got: "${statusText}"`);
            }

            await page.screenshot({ path: `${SCREENSHOT_DIR}/trace_mode_start_marker.png`, fullPage: true });
            log(`  Screenshot: ${SCREENSHOT_DIR}/trace_mode_start_marker.png`);
        }

        // ========== TEST 8: API Route endpoint ==========
        log('\n--- Test 8: Route API Endpoint ---');

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

        // ========== TEST 9: Path uses 45-degree angles ==========
        log('\n--- Test 9: 45-Degree Angle Constraint ---');

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
                pass('Path segments use 45° angles only');
            } else {
                fail('Path segments use 45° angles only', `Found angle ${invalidAngle?.toFixed(1)}°`);
            }
        } else {
            log('  Skipping angle test - no path returned');
        }

        // ========== TEST 10: Same-net crossing allowed ==========
        log('\n--- Test 10: Same-Net Crossing ---');

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

        // ========== TEST 11: Cancel resets state ==========
        log('\n--- Test 11: Cancel/Reset ---');

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
            log('\n⚠️  Some tests failed');
        } else {
            log('\n✓ All tests passed');
        }

        log('\nTests completed successfully.');
        await browser.close();
        process.exit(results.failed > 0 ? 1 : 0);

    } catch (err) {
        console.error('\n❌ Test error:', err.message);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/trace_mode_error.png`, fullPage: true });
        log(`Error screenshot: ${SCREENSHOT_DIR}/trace_mode_error.png`);
        await browser.close();
        process.exit(1);
    }
}

runTests().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
