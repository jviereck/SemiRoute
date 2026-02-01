/**
 * Test for companion routing bug: routing fails from pad in companion mode
 * but works in normal routing mode.
 *
 * Steps to reproduce:
 * 1. Create a short trace from U4 pad 2 towards the right
 * 2. Finish the trace (double-click)
 * 3. Select the trace as reference
 * 4. Alt+Click on U4 pad 3 to add as companion
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
    log('Starting companion routing bug test (U4 pads 2 and 3)...');
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
        if (text.includes('Companion') || text.includes('route') || text.includes('Route')) {
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

        // ========== TEST 2: Find U4 pads 2 and 3 ==========
        log('\n--- Test 2: Find U4 Pads 2 and 3 ---');

        const u4Pads = await page.evaluate(() => {
            // Find pads with data-footprint="U4" and pad numbers 2, 3
            const pads = Array.from(document.querySelectorAll('.pad[data-footprint="U4"]'));
            const targetPads = {};

            for (const pad of pads) {
                const padNum = pad.dataset.pad || '';
                if (['2', '3'].includes(padNum)) {
                    const x = parseFloat(pad.dataset.x || pad.getAttribute('cx'));
                    const y = parseFloat(pad.dataset.y || pad.getAttribute('cy'));
                    const net = parseInt(pad.dataset.net, 10);
                    targetPads[padNum] = { x, y, net, padNum };
                }
            }

            return targetPads;
        });

        const pad2 = u4Pads['2'];
        const pad3 = u4Pads['3'];

        if (pad2 && pad3) {
            pass('Found U4 pads 2 and 3');
            log(`  Pad 2: (${pad2.x.toFixed(2)}, ${pad2.y.toFixed(2)}) net ${pad2.net}`);
            log(`  Pad 3: (${pad3.x.toFixed(2)}, ${pad3.y.toFixed(2)}) net ${pad3.net}`);
        } else {
            fail('Found U4 pads 2 and 3', `Missing pads: 2=${!!pad2}, 3=${!!pad3}`);
            throw new Error('Cannot continue without U4 pads');
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

        // Use F.Cu layer (default)
        pass('Trace mode enabled (F.Cu layer)');

        // ========== TEST 4: Create trace from U4 pad 2 ==========
        log('\n--- Test 4: Create Reference Trace from U4 Pad 2 ---');

        const pad2Screen = await svgToScreen(pad2.x, pad2.y);
        log(`  Clicking pad 2 at screen (${pad2Screen.x.toFixed(1)}, ${pad2Screen.y.toFixed(1)})`);

        // Click to start routing
        await page.mouse.click(pad2Screen.x, pad2Screen.y);
        await sleep(300);

        // Move mouse to the right (create a short trace)
        const endPoint = { x: pad2.x + 3.0, y: pad2.y };  // 3mm to the right
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
            fail('Reference trace created', 'No .user-trace element found');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/u4_companion_bug_1_trace_created.png` });

        // ========== TEST 5: Select trace as reference ==========
        log('\n--- Test 5: Select Trace as Reference ---');

        // Click on the trace we just created
        const tracePos = { x: pad2.x + 1.5, y: pad2.y };  // Middle of the trace
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
            fail('Reference trace selected', 'companion-status not visible');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/u4_companion_bug_2_reference_selected.png` });

        // ========== TEST 6: Add U4 pad 3 as companion ==========
        log('\n--- Test 6: Add U4 Pad 3 as Companion ---');

        const pad3Screen = await svgToScreen(pad3.x, pad3.y);
        log(`  Alt+Clicking pad 3 at screen (${pad3Screen.x.toFixed(1)}, ${pad3Screen.y.toFixed(1)})`);
        log(`  Pad 3 net: ${pad3.net}`);

        // Alt+Click to add companion
        await page.keyboard.down('Alt');
        await page.mouse.click(pad3Screen.x, pad3Screen.y);
        await page.keyboard.up('Alt');
        await sleep(500);

        // Check if companion was added
        const companionAdded = await page.evaluate(() => {
            const listEl = document.getElementById('companion-net-list');
            return listEl && !listEl.innerHTML.includes('(none)');
        });

        if (companionAdded) {
            pass('Companion (pad 3) added');
        } else {
            fail('Companion (pad 3) added', 'companion-net-list still shows (none)');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/u4_companion_bug_3_companion_added.png` });

        // ========== TEST 7: Test companion routing (BUG: may fail) ==========
        log('\n--- Test 7: Test Companion Routing from Pad 3 ---');

        // Move mouse to trigger companion routing
        consoleLogs.length = 0;  // Clear logs

        // Move along the reference trace direction
        const companionTarget = { x: pad2.x + 2.0, y: pad2.y };
        const companionTargetScreen = await svgToScreen(companionTarget.x, companionTarget.y);

        log(`  Moving mouse to (${companionTarget.x.toFixed(2)}, ${companionTarget.y.toFixed(2)}) to trigger companion routing...`);
        await page.mouse.move(companionTargetScreen.x, companionTargetScreen.y);
        await sleep(1000);  // Wait for debounced routing

        await page.screenshot({ path: `${SCREENSHOT_DIR}/u4_companion_bug_4_companion_routing.png` });

        // Check console for companion routing results
        const companion0Success = consoleLogs.some(l =>
            l.text.includes('Companion 0: route SUCCESS')
        );
        const companion0Failed = consoleLogs.some(l =>
            l.text.includes('Companion 0: route FAILED')
        );

        // Check for previews
        const previewCount = await page.evaluate(() => {
            const previews = document.querySelectorAll('.companion-preview');
            return previews.length;
        });

        log(`  Companion 0 (pad 3): ${companion0Success ? 'SUCCESS' : companion0Failed ? 'FAILED' : 'unknown'}`);
        log(`  Preview traces shown: ${previewCount}`);

        // Report results - THE BUG: companion routing fails
        if (companion0Success) {
            pass('Companion route succeeded');
        } else if (companion0Failed) {
            fail('Companion routing failed (THIS IS THE BUG)', 'Normal routing works but companion fails');
        } else {
            fail('Companion routing status unknown', `Previews: ${previewCount}`);
        }

        // ========== TEST 8: Verify normal routing works from same pad ==========
        log('\n--- Test 8: Verify Normal Routing from Pad 3 Works ---');

        // Cancel companion mode
        await page.keyboard.press('Escape');
        await sleep(300);

        // Start a normal route from pad 3
        await page.mouse.click(pad3Screen.x, pad3Screen.y);
        await sleep(300);

        // Move mouse to the right
        const normalEndPoint = { x: pad3.x + 2.0, y: pad3.y };
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
            pass('Normal routing from pad 3 works', 'This proves the bug - companion mode fails but normal routing works');
        } else {
            // Extract just the message part if possible
            let errorMsg = 'No preview shown';
            if (normalRouteFailLog) {
                const match = normalRouteFailLog.text.match(/message['":\s]+([^}]+)/);
                errorMsg = match ? match[1] : normalRouteFailLog.text.substring(0, 100);
            }
            fail('Normal routing from pad 3 works', errorMsg);
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/u4_companion_bug_5_normal_routing.png` });

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

        // This test is designed to FAIL on Test 7 (companion routing) while PASSING on Test 8 (normal routing)
        // That demonstrates the bug: same pad, same direction, but companion mode fails

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
