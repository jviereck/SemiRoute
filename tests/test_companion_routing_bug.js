/**
 * Test for companion routing bug: routing fails from pad in companion mode
 * but works in normal routing mode.
 *
 * Steps to reproduce:
 * 1. Create a short trace from U3 pad 38 towards the right
 * 2. Finish the trace (double-click)
 * 3. Select the trace as reference
 * 4. Alt+Click on U3 pad 39 and 40 to add as companions
 * 5. Move mouse - companion routing should work but fails
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config_test');
const SCREENSHOT_DIR = '/tmp';

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
    log('Starting companion routing bug test (U3 pads 38, 39, 40)...');
    log(`Server URL: ${SERVER_URL}`);

    const browser = await puppeteer.launch({
        headless: true,
        devtools: false,
        args: ['--window-size=1400,900', '--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Collect console messages
    const consoleLogs = [];
    page.on('console', msg => {
        const text = msg.text();
        consoleLogs.push({ type: msg.type(), text });
        if (text.includes('Companion') || text.includes('route')) {
            console.log(`  [CONSOLE] ${text}`);
        }
        if (msg.type() === 'error') {
            console.log(`  [PAGE ERROR] ${text}`);
        }
    });

    try {
        // ========== TEST 1: Page loads ==========
        log('\n--- Test 1: Page Load ---');
        await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
        await page.waitForSelector('svg', { timeout: 5000 });
        await sleep(500);
        pass('Page loads');

        // ========== TEST 2: Find U3 pads 38, 39, 40 ==========
        log('\n--- Test 2: Find U3 Pads 38, 39, 40 ---');

        const u3Pads = await page.evaluate(() => {
            // Find pads with data-footprint="U3" and pad numbers 38, 39, 40
            const pads = Array.from(document.querySelectorAll('.pad[data-footprint="U3"]'));
            const targetPads = {};

            for (const pad of pads) {
                const padNum = pad.dataset.pad || '';
                if (['38', '39', '40'].includes(padNum)) {
                    const x = parseFloat(pad.dataset.x || pad.getAttribute('cx'));
                    const y = parseFloat(pad.dataset.y || pad.getAttribute('cy'));
                    const net = parseInt(pad.dataset.net, 10);
                    targetPads[padNum] = { x, y, net, padNum };
                }
            }

            return targetPads;
        });

        const pad38 = u3Pads['38'];
        const pad39 = u3Pads['39'];
        const pad40 = u3Pads['40'];

        if (pad38 && pad39 && pad40) {
            pass('Found U3 pads 38, 39, 40');
            log(`  Pad 38: (${pad38.x.toFixed(2)}, ${pad38.y.toFixed(2)}) net ${pad38.net}`);
            log(`  Pad 39: (${pad39.x.toFixed(2)}, ${pad39.y.toFixed(2)}) net ${pad39.net}`);
            log(`  Pad 40: (${pad40.x.toFixed(2)}, ${pad40.y.toFixed(2)}) net ${pad40.net}`);
        } else {
            fail('Found U3 pads 38, 39, 40', `Missing pads: 38=${!!pad38}, 39=${!!pad39}, 40=${!!pad40}`);
            throw new Error('Cannot continue without U3 pads');
        }

        // Helper to convert SVG coords to screen coords
        async function svgToScreen(svgX, svgY) {
            return await page.evaluate((x, y) => {
                const container = document.getElementById('svg-container');
                const svg = container.querySelector('svg');
                const rect = container.getBoundingClientRect();
                const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
                const svgWidth = svg.clientWidth;
                const svgHeight = svg.clientHeight;
                const scaleX = svgWidth / viewBox[2];
                const scaleY = svgHeight / viewBox[3];
                return {
                    x: rect.left + (x - viewBox[0]) * scaleX,
                    y: rect.top + (y - viewBox[1]) * scaleY
                };
            }, svgX, svgY);
        }

        // ========== TEST 3: Enable trace mode ==========
        log('\n--- Test 3: Enable Trace Mode ---');
        await page.click('#trace-mode-toggle');
        await sleep(300);

        // Switch to B.Cu layer (F.Cu is blocked in this area)
        await page.select('#trace-layer', 'B.Cu');
        await sleep(100);

        pass('Trace mode enabled (B.Cu layer)');

        // ========== TEST 4: Create trace from U3 pad 38 ==========
        log('\n--- Test 4: Create Reference Trace from U3 Pad 38 ---');

        const pad38Screen = await svgToScreen(pad38.x, pad38.y);
        log(`  Clicking pad 38 at screen (${pad38Screen.x.toFixed(1)}, ${pad38Screen.y.toFixed(1)})`);

        // Click to start routing
        await page.mouse.click(pad38Screen.x, pad38Screen.y);
        await sleep(300);

        // Move mouse to the right (create a short trace)
        const endPoint = { x: pad38.x + 3.0, y: pad38.y };  // 3mm to the right
        const endScreen = await svgToScreen(endPoint.x, endPoint.y);
        log(`  Moving to (${endPoint.x.toFixed(2)}, ${endPoint.y.toFixed(2)})`);

        await page.mouse.move(endScreen.x, endScreen.y);
        await sleep(500);

        // Double-click to finish
        await page.mouse.click(endScreen.x, endScreen.y, { clickCount: 2 });
        await sleep(500);

        // Check if trace was created
        const routeCreated = await page.evaluate(() => {
            const traces = document.querySelectorAll('.user-trace');
            return traces.length > 0;
        });

        if (routeCreated) {
            pass('Reference trace created');
        } else {
            fail('Reference trace created');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/companion_bug_1_trace_created.png` });

        // ========== TEST 5: Select trace as reference ==========
        log('\n--- Test 5: Select Trace as Reference ---');

        // Click on the trace we just created
        const tracePos = { x: pad38.x + 1.5, y: pad38.y };  // Middle of the trace
        const traceScreen = await svgToScreen(tracePos.x, tracePos.y);
        log(`  Clicking trace at (${tracePos.x.toFixed(2)}, ${tracePos.y.toFixed(2)})`);

        await page.mouse.click(traceScreen.x, traceScreen.y);
        await sleep(500);

        // Check if companion mode started (reference selected)
        const companionModeStarted = await page.evaluate(() => {
            const statusEl = document.getElementById('companion-status');
            return statusEl && !statusEl.classList.contains('hidden');
        });

        if (companionModeStarted) {
            pass('Reference trace selected');
        } else {
            fail('Reference trace selected');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/companion_bug_2_reference_selected.png` });

        // ========== TEST 6: Add U3 pad 39 as companion ==========
        log('\n--- Test 6: Add U3 Pad 39 as Companion ---');

        const pad39Screen = await svgToScreen(pad39.x, pad39.y);
        log(`  Alt+Clicking pad 39 at screen (${pad39Screen.x.toFixed(1)}, ${pad39Screen.y.toFixed(1)})`);
        log(`  Pad 39 net: ${pad39.net}`);

        // Alt+Click to add companion
        await page.keyboard.down('Alt');
        await page.mouse.click(pad39Screen.x, pad39Screen.y);
        await page.keyboard.up('Alt');
        await sleep(500);

        // Check if companion was added
        const companion1Added = await page.evaluate(() => {
            const listEl = document.getElementById('companion-net-list');
            return listEl && !listEl.innerHTML.includes('(none)');
        });

        if (companion1Added) {
            pass('Companion 1 (pad 39) added');
        } else {
            fail('Companion 1 (pad 39) added');
        }

        // ========== TEST 7: Add U3 pad 40 as companion ==========
        log('\n--- Test 7: Add U3 Pad 40 as Companion ---');

        const pad40Screen = await svgToScreen(pad40.x, pad40.y);
        log(`  Alt+Clicking pad 40 at screen (${pad40Screen.x.toFixed(1)}, ${pad40Screen.y.toFixed(1)})`);
        log(`  Pad 40 net: ${pad40.net}`);

        // Alt+Click to add companion
        await page.keyboard.down('Alt');
        await page.mouse.click(pad40Screen.x, pad40Screen.y);
        await page.keyboard.up('Alt');
        await sleep(500);

        await page.screenshot({ path: `${SCREENSHOT_DIR}/companion_bug_3_companions_added.png` });

        const companionCount = await page.evaluate(() => {
            const listEl = document.getElementById('companion-net-list');
            if (!listEl) return 0;
            const badges = listEl.querySelectorAll('.companion-net-badge');
            return badges.length;
        });

        if (companionCount >= 2) {
            pass('Companion 2 (pad 40) added', `${companionCount} companions total`);
        } else {
            fail('Companion 2 (pad 40) added', `Only ${companionCount} companions`);
        }

        // ========== TEST 8: Test companion routing (BUG: may fail) ==========
        log('\n--- Test 8: Test Companion Routing from Pads 39 & 40 ---');

        // Move mouse to trigger companion routing
        consoleLogs.length = 0;  // Clear logs

        // Move along the reference trace direction
        const companionTarget = { x: pad38.x + 2.0, y: pad38.y };
        const companionTargetScreen = await svgToScreen(companionTarget.x, companionTarget.y);

        log(`  Moving mouse to (${companionTarget.x.toFixed(2)}, ${companionTarget.y.toFixed(2)}) to trigger companion routing...`);
        await page.mouse.move(companionTargetScreen.x, companionTargetScreen.y);
        await sleep(1000);  // Wait for debounced routing

        await page.screenshot({ path: `${SCREENSHOT_DIR}/companion_bug_4_companion_routing.png` });

        // Check console for companion routing results
        const companion0Success = consoleLogs.some(l =>
            l.text.includes('Companion 0: route SUCCESS')
        );
        const companion1Success = consoleLogs.some(l =>
            l.text.includes('Companion 1: route SUCCESS')
        );
        const companion0Failed = consoleLogs.some(l =>
            l.text.includes('Companion 0: route FAILED')
        );
        const companion1Failed = consoleLogs.some(l =>
            l.text.includes('Companion 1: route FAILED')
        );

        // Check for previews
        const previewCount = await page.evaluate(() => {
            const previews = document.querySelectorAll('.companion-preview');
            return previews.length;
        });

        log(`  Companion 0 (pad 39): ${companion0Success ? 'SUCCESS' : companion0Failed ? 'FAILED' : 'unknown'}`);
        log(`  Companion 1 (pad 40): ${companion1Success ? 'SUCCESS' : companion1Failed ? 'FAILED' : 'unknown'}`);
        log(`  Preview traces shown: ${previewCount}`);

        // Report results
        if (companion0Success && companion1Success) {
            pass('Both companion routes succeeded');
        } else if (companion0Failed || companion1Failed) {
            const failedCompanions = [];
            if (companion0Failed) failedCompanions.push('Companion 0 (pad 39)');
            if (companion1Failed) failedCompanions.push('Companion 1 (pad 40)');
            fail('Companion routing failed', failedCompanions.join(', '));
        } else {
            fail('Companion routing status unknown', `Previews: ${previewCount}`);
        }

        // ========== TEST 9: Verify normal routing works from same pads ==========
        log('\n--- Test 9: Verify Normal Routing from Pad 39 Works ---');

        // Cancel companion mode
        await page.keyboard.press('Escape');
        await sleep(300);

        // Start a normal route from pad 39
        await page.mouse.click(pad39Screen.x, pad39Screen.y);
        await sleep(300);

        // Move mouse to the right
        const normalEndPoint = { x: pad39.x + 2.0, y: pad39.y };
        const normalEndScreen = await svgToScreen(normalEndPoint.x, normalEndPoint.y);

        consoleLogs.length = 0;
        await page.mouse.move(normalEndScreen.x, normalEndScreen.y);
        await sleep(600);

        // Check for successful route
        const normalRouteSuccess = await page.evaluate(() => {
            const preview = document.querySelector('.pending-trace');
            return !!preview;
        });

        const normalRouteFailLog = consoleLogs.find(l =>
            l.text.includes('Route failed') || l.text.includes('FAILED')
        );

        if (normalRouteSuccess && !normalRouteFailLog) {
            pass('Normal routing from pad 39 works');
        } else {
            // Extract just the message part if possible
            let errorMsg = 'No preview shown';
            if (normalRouteFailLog) {
                const match = normalRouteFailLog.text.match(/message['":\s]+([^}]+)/);
                errorMsg = match ? match[1] : normalRouteFailLog.text.substring(0, 100);
            }
            fail('Normal routing from pad 39 works', errorMsg);
        }

        // ========== Summary ==========
        log('\n========================================');
        log('TEST SUMMARY');
        log('========================================');
        log(`Passed: ${results.passed}`);
        log(`Failed: ${results.failed}`);
        log(`Total:  ${results.passed + results.failed}`);

        if (results.failed > 0) {
            log('\nFailed tests:');
            results.tests
                .filter(t => t.status === 'FAIL')
                .forEach(t => log(`  - ${t.name}: ${t.details}`));
        }

    } catch (err) {
        console.error('Test error:', err);
    } finally {
        await browser.close();
    }

    log(`\nScreenshots saved to ${SCREENSHOT_DIR}/`);

    if (results.failed > 0) {
        log('\n✗ Test failures detected');
        process.exit(1);
    } else {
        log('\n✓ All tests passed');
        process.exit(0);
    }
}

runTests();
