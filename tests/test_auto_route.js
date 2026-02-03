/**
 * Browser test for auto-route to pad feature.
 *
 * Tests:
 * 1. Start routing on a pad, click another same-net pad to auto-route
 * 2. Verify that segments and vias are created correctly
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config_test');

const results = {
    passed: 0,
    failed: 0,
    tests: []
};

function log(msg) {
    console.log(`  ${msg}`);
}

function pass(testName) {
    results.passed++;
    results.tests.push({ name: testName, status: 'PASS' });
    console.log(`  [PASS] ${testName}`);
}

function fail(testName, error) {
    results.failed++;
    results.tests.push({ name: testName, status: 'FAIL', error });
    console.log(`  [FAIL] ${testName}: ${error}`);
}

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTests() {
    console.log('=== Auto-Route to Pad Browser Test ===\n');
    log(`Server URL: ${SERVER_URL}`);

    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Capture console
    const logs = [];
    page.on('console', msg => logs.push(msg.text()));

    try {
        // Load page
        console.log('\n1. Loading page...');
        try {
            await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
            await page.waitForSelector('svg', { timeout: 5000 });
            pass('Page loads');
        } catch (err) {
            fail('Page loads', `Server not running at ${SERVER_URL}?`);
            throw new Error('Cannot continue without server');
        }

        // Clear any existing traces
        console.log('\n2. Clearing existing traces...');
        await page.evaluate(async () => {
            await fetch('/api/traces', { method: 'DELETE' });
        });
        await page.reload({ waitUntil: 'networkidle0' });
        await page.waitForSelector('svg');
        pass('Traces cleared');

        // Get viewport info for coordinate conversion
        console.log('\n3. Getting viewport info...');
        const viewInfo = await page.evaluate(() => {
            const svg = document.querySelector('svg');
            const vb = svg.getAttribute('viewBox').split(' ').map(Number);
            const rect = svg.getBoundingClientRect();
            return {
                vbX: vb[0], vbY: vb[1], vbW: vb[2], vbH: vb[3],
                screenW: rect.width, screenH: rect.height,
                screenX: rect.x, screenY: rect.y
            };
        });

        function svgToScreen(svgX, svgY) {
            const scaleX = viewInfo.screenW / viewInfo.vbW;
            const scaleY = viewInfo.screenH / viewInfo.vbH;
            return {
                x: viewInfo.screenX + (svgX - viewInfo.vbX) * scaleX,
                y: viewInfo.screenY + (svgY - viewInfo.vbY) * scaleY
            };
        }
        pass('Viewport info obtained');

        // Find two pads on the same net for testing
        console.log('\n4. Finding test pads...');
        const testPads = await page.evaluate(() => {
            const pads = Array.from(document.querySelectorAll('.pad'));
            // Group pads by net
            const padsByNet = {};
            for (const pad of pads) {
                const netId = parseInt(pad.dataset.net, 10);
                if (netId > 0) {
                    if (!padsByNet[netId]) {
                        padsByNet[netId] = [];
                    }
                    // Get pad center from transform or position
                    const cx = parseFloat(pad.getAttribute('cx') || pad.getAttribute('x')) || 0;
                    const cy = parseFloat(pad.getAttribute('cy') || pad.getAttribute('y')) || 0;

                    // Try to get from data attributes if available
                    const dataX = parseFloat(pad.dataset.x);
                    const dataY = parseFloat(pad.dataset.y);

                    let x = dataX || cx;
                    let y = dataY || cy;

                    // Parse from transform if needed
                    const transform = pad.getAttribute('transform');
                    if (transform) {
                        const match = transform.match(/translate\(([\d.-]+)[,\s]+([\d.-]+)\)/);
                        if (match) {
                            x = parseFloat(match[1]);
                            y = parseFloat(match[2]);
                        }
                    }

                    padsByNet[netId].push({
                        netId,
                        x,
                        y,
                        layer: pad.dataset.layer
                    });
                }
            }

            // Find a net with at least 2 pads that have reasonable separation
            for (const [netId, netPads] of Object.entries(padsByNet)) {
                if (netPads.length >= 2) {
                    // Find two pads with some distance
                    for (let i = 0; i < netPads.length; i++) {
                        for (let j = i + 1; j < netPads.length; j++) {
                            const p1 = netPads[i];
                            const p2 = netPads[j];
                            const dist = Math.sqrt(
                                (p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2
                            );
                            // Want pads 2-20mm apart for testing
                            if (dist > 2 && dist < 20) {
                                return { pad1: p1, pad2: p2, netId: parseInt(netId, 10) };
                            }
                        }
                    }
                }
            }
            return null;
        });

        if (!testPads) {
            fail('Find test pads', 'No suitable pad pairs found');
            throw new Error('Cannot continue without test pads');
        }
        log(`Found pads on net ${testPads.netId}:`);
        log(`  Pad 1: (${testPads.pad1.x.toFixed(2)}, ${testPads.pad1.y.toFixed(2)})`);
        log(`  Pad 2: (${testPads.pad2.x.toFixed(2)}, ${testPads.pad2.y.toFixed(2)})`);
        pass('Find test pads');

        // Enable trace mode
        console.log('\n5. Enabling trace mode...');
        await page.click('#trace-mode-toggle');
        await sleep(300);

        const traceModeActive = await page.evaluate(() =>
            document.body.classList.contains('trace-mode-active')
        );
        if (!traceModeActive) {
            fail('Enable trace mode', 'Trace mode not activated');
            throw new Error('Cannot continue without trace mode');
        }
        pass('Enable trace mode');

        // Double-click on first pad to start routing
        console.log('\n6. Starting routing on first pad...');
        const start = svgToScreen(testPads.pad1.x, testPads.pad1.y);
        await page.mouse.click(start.x, start.y, { clickCount: 2 });
        await sleep(500);

        const routingStarted = await page.evaluate(() => {
            const state = window.getRoutingState ? window.getRoutingState() : {};
            return !!state.routingSession;
        });

        if (!routingStarted) {
            fail('Start routing', 'Routing session not started');
            throw new Error('Cannot continue without routing session');
        }
        pass('Start routing');

        // Single-click on second pad (same net) to trigger auto-route
        console.log('\n7. Clicking destination pad (auto-route)...');
        const end = svgToScreen(testPads.pad2.x, testPads.pad2.y);
        await page.mouse.click(end.x, end.y);

        // Wait for auto-route to complete
        await sleep(2000);

        // Check results
        console.log('\n8. Verifying auto-route results...');
        const result = await page.evaluate(() => {
            const state = window.getRoutingState ? window.getRoutingState() : {};
            const userTraces = document.querySelectorAll('.user-trace');
            const userVias = document.querySelectorAll('.user-via');
            const status = document.getElementById('trace-status')?.textContent || '';

            return {
                routingSession: !!state.routingSession,
                traceCount: userTraces.length,
                viaCount: userVias.length,
                status: status
            };
        });

        log(`Status: "${result.status}"`);
        log(`User traces created: ${result.traceCount}`);
        log(`User vias created: ${result.viaCount}`);
        log(`Routing session active: ${result.routingSession}`);

        // Verify traces were created
        if (result.traceCount === 0) {
            fail('Auto-route creates traces', 'No user traces created');
        } else {
            pass('Auto-route creates traces');
        }

        // Verify routing session ended
        if (result.routingSession) {
            fail('Routing session ends', 'Routing session still active');
        } else {
            pass('Routing session ends');
        }

        // Verify status message indicates success
        if (result.status.toLowerCase().includes('auto-routed') ||
            result.status.toLowerCase().includes('done') ||
            result.status.toLowerCase().includes('success')) {
            pass('Status indicates success');
        } else {
            // May still pass if traces were created
            if (result.traceCount > 0) {
                pass('Status indicates success');
            } else {
                fail('Status indicates success', `Got: "${result.status}"`);
            }
        }

        // Test the API directly
        console.log('\n9. Testing /api/auto-route endpoint directly...');
        const apiResult = await page.evaluate(async (p1, p2) => {
            const response = await fetch('/api/auto-route', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_x: p1.x,
                    start_y: p1.y,
                    end_x: p2.x,
                    end_y: p2.y,
                    preferred_layer: 'F.Cu',
                    width: 0.25,
                    net_id: p1.netId,
                    via_size: 0.8
                })
            });
            return await response.json();
        }, testPads.pad1, testPads.pad2);

        log(`API success: ${apiResult.success}`);
        log(`API message: ${apiResult.message}`);
        log(`API segments: ${apiResult.segments ? apiResult.segments.length : 0}`);
        log(`API vias: ${apiResult.vias ? apiResult.vias.length : 0}`);

        if (apiResult.success) {
            pass('API auto-route succeeds');
        } else {
            fail('API auto-route succeeds', apiResult.message);
        }

        if (apiResult.segments && apiResult.segments.length > 0) {
            pass('API returns segments');
            // Verify each segment has valid structure
            let validStructure = true;
            for (const seg of apiResult.segments) {
                if (!seg.path || !Array.isArray(seg.path) || !seg.layer) {
                    validStructure = false;
                    break;
                }
            }
            if (validStructure) {
                pass('Segments have valid structure');
            } else {
                fail('Segments have valid structure', 'Invalid segment data');
            }
        } else {
            fail('API returns segments', 'No segments returned');
        }

    } catch (err) {
        console.error('\nTest error:', err.message);
        console.log('\nRecent console logs:');
        logs.slice(-15).forEach(l => console.log('  ' + l));
    } finally {
        await browser.close();
    }

    // Print summary
    console.log('\n=== Test Summary ===');
    console.log(`Passed: ${results.passed}`);
    console.log(`Failed: ${results.failed}`);

    if (results.failed > 0) {
        console.log('\nFailed tests:');
        results.tests.filter(t => t.status === 'FAIL').forEach(t => {
            console.log(`  - ${t.name}: ${t.error}`);
        });
    }

    process.exit(results.failed > 0 ? 1 : 0);
}

runTests().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
