/**
 * Puppeteer test for via center snapping during routing.
 *
 * Verifies that when routing, moving the mouse over a via
 * snaps the cursor to the via's center coordinates.
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config_test');

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
    log('Starting via snap tests...');
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

        // Wait for SVG to load
        await page.waitForSelector('svg', { timeout: 5000 });
        await sleep(500);

        // ========== TEST 2: Find a via and a nearby pad ==========
        log('\n--- Test 2: Find Via and Pad ---');

        const elements = await page.evaluate(() => {
            const vias = document.querySelectorAll('.via[data-net]');
            const pads = document.querySelectorAll('.pad[data-net]');

            // Find a via with a valid net
            let targetVia = null;
            for (const via of vias) {
                const netId = via.dataset.net;
                if (netId && netId !== '0') {
                    const rect = via.getBoundingClientRect();
                    const cx = parseFloat(via.getAttribute('cx'));
                    const cy = parseFloat(via.getAttribute('cy'));
                    targetVia = {
                        screenX: rect.x + rect.width / 2,
                        screenY: rect.y + rect.height / 2,
                        pcbX: cx,
                        pcbY: cy,
                        netId: netId
                    };
                    break;
                }
            }

            // Find a pad (any pad to start routing from)
            let startPad = null;
            for (const pad of pads) {
                const netId = pad.dataset.net;
                if (netId && netId !== '0') {
                    const rect = pad.getBoundingClientRect();
                    const dataX = pad.dataset.x;
                    const dataY = pad.dataset.y;
                    const cx = pad.getAttribute('cx');
                    const cy = pad.getAttribute('cy');
                    startPad = {
                        screenX: rect.x + rect.width / 2,
                        screenY: rect.y + rect.height / 2,
                        pcbX: parseFloat(dataX || cx),
                        pcbY: parseFloat(dataY || cy),
                        netId: netId
                    };
                    break;
                }
            }

            return { via: targetVia, pad: startPad };
        });

        if (!elements.via) {
            fail('Find via', 'No vias found on board');
            throw new Error('Cannot continue without via');
        }
        pass('Find via', `Via at PCB (${elements.via.pcbX.toFixed(2)}, ${elements.via.pcbY.toFixed(2)})`);

        if (!elements.pad) {
            fail('Find pad', 'No pads found on board');
            throw new Error('Cannot continue without pad');
        }
        pass('Find pad', `Pad at PCB (${elements.pad.pcbX.toFixed(2)}, ${elements.pad.pcbY.toFixed(2)})`);

        // ========== TEST 3: Switch to trace mode ==========
        log('\n--- Test 3: Enter Trace Mode ---');

        // Click on "Trace" mode toggle
        await page.click('#trace-mode-toggle');
        await sleep(300);

        const isTraceMode = await page.evaluate(() => {
            return document.body.classList.contains('trace-mode-active');
        });

        if (isTraceMode) {
            pass('Enter trace mode');
        } else {
            fail('Enter trace mode');
        }

        // ========== TEST 4: Start routing session ==========
        log('\n--- Test 4: Start Routing Session ---');

        // Double-click on the pad to start routing (single click just highlights)
        await page.mouse.click(elements.pad.screenX, elements.pad.screenY, { clickCount: 2 });
        await sleep(300);

        const sessionStarted = await page.evaluate(() => {
            const state = window.getRoutingState?.();
            return state?.routingSession !== null && state?.routingSession !== undefined;
        });

        if (sessionStarted) {
            pass('Routing session started');
        } else {
            fail('Routing session started');
            throw new Error('Cannot continue without routing session');
        }

        // ========== TEST 5: Move mouse over via and check snapping ==========
        log('\n--- Test 5: Via Center Snapping ---');

        // Move mouse to the via
        await page.mouse.move(elements.via.screenX, elements.via.screenY);
        await sleep(300);  // Wait for debounced routing

        const cursorInfo = await page.evaluate((expectedX, expectedY) => {
            const state = window.getRoutingState?.();
            const session = state?.routingSession;
            if (!session || !session.cursorPoint) {
                return { error: 'No cursor point in session' };
            }

            const cursorX = session.cursorPoint.x;
            const cursorY = session.cursorPoint.y;
            const tolerance = 0.01;  // 0.01mm tolerance

            const snappedToViaX = Math.abs(cursorX - expectedX) < tolerance;
            const snappedToViaY = Math.abs(cursorY - expectedY) < tolerance;

            return {
                cursorX: cursorX,
                cursorY: cursorY,
                expectedX: expectedX,
                expectedY: expectedY,
                snappedToViaX: snappedToViaX,
                snappedToViaY: snappedToViaY,
                snapped: snappedToViaX && snappedToViaY,
                deltaX: Math.abs(cursorX - expectedX),
                deltaY: Math.abs(cursorY - expectedY)
            };
        }, elements.via.pcbX, elements.via.pcbY);

        if (cursorInfo.error) {
            fail('Via center snapping', cursorInfo.error);
        } else if (cursorInfo.snapped) {
            pass('Via center snapping',
                `Cursor at (${cursorInfo.cursorX.toFixed(4)}, ${cursorInfo.cursorY.toFixed(4)}) ` +
                `matches via center (${cursorInfo.expectedX.toFixed(4)}, ${cursorInfo.expectedY.toFixed(4)})`);
        } else {
            fail('Via center snapping',
                `Cursor at (${cursorInfo.cursorX.toFixed(4)}, ${cursorInfo.cursorY.toFixed(4)}) ` +
                `does not match via center (${cursorInfo.expectedX.toFixed(4)}, ${cursorInfo.expectedY.toFixed(4)}). ` +
                `Delta: (${cursorInfo.deltaX.toFixed(4)}, ${cursorInfo.deltaY.toFixed(4)})`);
        }

        // ========== TEST 6: Compare with pad snapping ==========
        log('\n--- Test 6: Pad Snapping (for comparison) ---');

        // Find another pad to move over
        const anotherPad = await page.evaluate(() => {
            const pads = document.querySelectorAll('.pad[data-net]');
            for (const pad of Array.from(pads).slice(1)) {  // Skip first pad
                const netId = pad.dataset.net;
                if (netId && netId !== '0') {
                    const rect = pad.getBoundingClientRect();
                    const dataX = pad.dataset.x;
                    const dataY = pad.dataset.y;
                    const cx = pad.getAttribute('cx');
                    const cy = pad.getAttribute('cy');
                    return {
                        screenX: rect.x + rect.width / 2,
                        screenY: rect.y + rect.height / 2,
                        pcbX: parseFloat(dataX || cx),
                        pcbY: parseFloat(dataY || cy)
                    };
                }
            }
            return null;
        });

        if (anotherPad) {
            await page.mouse.move(anotherPad.screenX, anotherPad.screenY);
            await sleep(300);

            const padCursorInfo = await page.evaluate((expectedX, expectedY) => {
                const state = window.getRoutingState?.();
                const session = state?.routingSession;
                if (!session || !session.cursorPoint) {
                    return { error: 'No cursor point' };
                }

                const cursorX = session.cursorPoint.x;
                const cursorY = session.cursorPoint.y;
                const tolerance = 0.01;

                return {
                    snapped: Math.abs(cursorX - expectedX) < tolerance &&
                             Math.abs(cursorY - expectedY) < tolerance,
                    cursorX: cursorX,
                    cursorY: cursorY,
                    expectedX: expectedX,
                    expectedY: expectedY
                };
            }, anotherPad.pcbX, anotherPad.pcbY);

            if (padCursorInfo.snapped) {
                pass('Pad snapping works',
                    `Cursor snapped to pad center (${padCursorInfo.expectedX.toFixed(4)}, ${padCursorInfo.expectedY.toFixed(4)})`);
            } else {
                fail('Pad snapping works',
                    `Cursor at (${padCursorInfo.cursorX.toFixed(4)}, ${padCursorInfo.cursorY.toFixed(4)}) ` +
                    `expected (${padCursorInfo.expectedX.toFixed(4)}, ${padCursorInfo.expectedY.toFixed(4)})`);
            }
        } else {
            log('  Skipped: No second pad found');
        }

        // ========== TEST 7: Cancel routing session ==========
        log('\n--- Test 7: Cleanup ---');
        await page.keyboard.press('Escape');
        await sleep(200);

        const sessionEnded = await page.evaluate(() => {
            const state = window.getRoutingState?.();
            return state?.routingSession === null;
        });

        if (sessionEnded) {
            pass('Routing session cancelled');
        } else {
            fail('Routing session cancelled');
        }

    } catch (err) {
        console.error(`\n[ERROR] Test execution failed: ${err.message}`);
        console.error(err.stack);
    } finally {
        await browser.close();
    }

    // ========== SUMMARY ==========
    console.log('\n========================================');
    console.log('           TEST SUMMARY');
    console.log('========================================');
    console.log(`  Passed: ${results.passed}`);
    console.log(`  Failed: ${results.failed}`);
    console.log(`  Total:  ${results.passed + results.failed}`);
    console.log('========================================\n');

    process.exit(results.failed > 0 ? 1 : 0);
}

runTests().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
