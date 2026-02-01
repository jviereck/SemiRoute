/**
 * Test that pending traces are loaded and rendered on page load.
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config_test');

// Test results
const results = {
    passed: 0,
    failed: 0,
    tests: []
};

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
    console.log('=== Pending Traces Load Test ===\n');

    const browser = await puppeteer.launch({ headless: true });
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Collect console messages for debugging
    page.on('console', msg => {
        if (msg.type() === 'error') {
            console.log(`  [Browser Error] ${msg.text()}`);
        }
    });

    try {
        // ========== SETUP: Clear existing traces and add test traces ==========
        console.log('--- Setup: Preparing test traces ---');

        // Clear all existing traces
        const clearResponse = await fetch(`${SERVER_URL}/api/traces`, {
            method: 'DELETE'
        });
        if (clearResponse.ok) {
            console.log('  Cleared existing traces');
        } else {
            console.log('  Warning: Could not clear traces');
        }

        // Add test trace 1: Simple horizontal trace on F.Cu
        const trace1 = {
            id: 'route-100-seg0',
            segments: [[150.8, 100.75], [153.5, 100.75]],
            width: 0.25,
            layer: 'F.Cu',
            net_id: 57
        };

        const add1Response = await fetch(`${SERVER_URL}/api/traces`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(trace1)
        });
        if (add1Response.ok) {
            console.log('  Added test trace 1');
        } else {
            fail('Setup - add trace 1', await add1Response.text());
        }

        // Add test trace 2: Diagonal trace on B.Cu
        const trace2 = {
            id: 'route-101-seg0',
            segments: [[148.0, 95.0], [150.0, 97.0], [152.0, 97.0]],
            width: 0.25,
            layer: 'B.Cu',
            net_id: 62
        };

        const add2Response = await fetch(`${SERVER_URL}/api/traces`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(trace2)
        });
        if (add2Response.ok) {
            console.log('  Added test trace 2');
        } else {
            fail('Setup - add trace 2', await add2Response.text());
        }

        // Verify traces were added via API
        const listResponse = await fetch(`${SERVER_URL}/api/traces`);
        const tracesData = await listResponse.json();
        console.log(`  API reports ${tracesData.traces.length} traces\n`);

        // ========== TEST 1: Load page and check user-trace elements ==========
        console.log('--- Test 1: User traces rendered on page load ---');

        await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
        await page.waitForSelector('svg');
        await sleep(500);  // Wait for traces to be rendered

        const userTraceInfo = await page.evaluate(() => {
            const userTraces = document.querySelectorAll('.user-trace');
            const traces = [];
            userTraces.forEach(t => {
                traces.push({
                    traceId: t.dataset.traceId,
                    layer: t.dataset.layer,
                    net: t.dataset.net,
                    d: t.getAttribute('d')
                });
            });
            return {
                count: userTraces.length,
                traces: traces
            };
        });

        console.log(`  Found ${userTraceInfo.count} user-trace elements`);
        userTraceInfo.traces.forEach(t => {
            console.log(`    - ${t.traceId} on ${t.layer} (net ${t.net})`);
        });

        if (userTraceInfo.count >= 2) {
            pass('User traces rendered on load', `${userTraceInfo.count} traces found`);
        } else {
            fail('User traces rendered on load', `Expected at least 2, got ${userTraceInfo.count}`);
        }

        // ========== TEST 2: Check routes list UI ==========
        console.log('\n--- Test 2: Routes appear in sidebar list ---');

        const routeListInfo = await page.evaluate(() => {
            const routeItems = document.querySelectorAll('.route-item');
            const routes = [];
            routeItems.forEach(item => {
                routes.push({
                    routeId: item.dataset.routeId,
                    label: item.querySelector('.route-label')?.textContent || ''
                });
            });
            return {
                count: routeItems.length,
                routes: routes
            };
        });

        console.log(`  Found ${routeListInfo.count} route items in list`);
        routeListInfo.routes.forEach(r => {
            console.log(`    - ${r.routeId}: ${r.label}`);
        });

        if (routeListInfo.count >= 2) {
            pass('Routes appear in sidebar', `${routeListInfo.count} routes listed`);
        } else {
            fail('Routes appear in sidebar', `Expected at least 2, got ${routeListInfo.count}`);
        }

        // ========== TEST 3: Check trace has correct path data ==========
        console.log('\n--- Test 3: Trace path data is correct ---');

        const trace1Path = userTraceInfo.traces.find(t => t.traceId === 'route-100');
        if (trace1Path && trace1Path.d) {
            // Path should contain the coordinates we set
            const hasStartPoint = trace1Path.d.includes('150.8') && trace1Path.d.includes('100.75');
            const hasEndPoint = trace1Path.d.includes('153.5');

            if (hasStartPoint && hasEndPoint) {
                pass('Trace 1 path data correct', 'Contains expected coordinates');
            } else {
                fail('Trace 1 path data correct', `Path: ${trace1Path.d}`);
            }
        } else {
            fail('Trace 1 path data correct', `Trace not found. Available: ${userTraceInfo.traces.map(t => t.traceId).join(', ')}`);
        }

        // ========== TEST 4: Traces are on correct layers ==========
        console.log('\n--- Test 4: Traces on correct layers ---');

        const fCuTrace = userTraceInfo.traces.find(t => t.layer === 'F.Cu');
        const bCuTrace = userTraceInfo.traces.find(t => t.layer === 'B.Cu');

        if (fCuTrace) {
            pass('F.Cu trace found', `trace ${fCuTrace.traceId}`);
        } else {
            fail('F.Cu trace found', 'No trace with layer F.Cu');
        }

        if (bCuTrace) {
            pass('B.Cu trace found', `trace ${bCuTrace.traceId}`);
        } else {
            fail('B.Cu trace found', 'No trace with layer B.Cu');
        }

        // ========== TEST 5: Page reload preserves traces ==========
        console.log('\n--- Test 5: Page reload preserves traces ---');

        await page.reload({ waitUntil: 'networkidle0' });
        await page.waitForSelector('svg');
        await sleep(500);

        const afterReloadCount = await page.evaluate(() => {
            return document.querySelectorAll('.user-trace').length;
        });

        if (afterReloadCount >= 2) {
            pass('Traces preserved after reload', `${afterReloadCount} traces`);
        } else {
            fail('Traces preserved after reload', `Expected at least 2, got ${afterReloadCount}`);
        }

        // ========== CLEANUP ==========
        console.log('\n--- Cleanup ---');
        await fetch(`${SERVER_URL}/api/traces`, { method: 'DELETE' });
        console.log('  Cleared test traces');

    } catch (error) {
        console.error('Test error:', error);
        fail('Test execution', error.message);
    } finally {
        await browser.close();
    }

    // Print summary
    console.log('\n=== Test Summary ===');
    console.log(`Passed: ${results.passed}`);
    console.log(`Failed: ${results.failed}`);

    process.exit(results.failed > 0 ? 1 : 0);
}

runTests();
