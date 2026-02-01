/**
 * Regression tests for net highlighting in normal (select) mode.
 *
 * These tests verify that clicking on pads, traces, and vias in normal mode
 * correctly highlights all elements of the same net.
 */
const puppeteer = require('puppeteer');

const { SERVER_URL } = require('./config_test.js');

// Test results
const results = {
    passed: 0,
    failed: 0,
    tests: []
};

function pass(testName, details = '') {
    results.passed++;
    results.tests.push({ name: testName, status: 'PASS', details });
    console.log(`  \u2713 PASS: ${testName}${details ? ' - ' + details : ''}`);
}

function fail(testName, details = '') {
    results.failed++;
    results.tests.push({ name: testName, status: 'FAIL', details });
    console.log(`  \u2717 FAIL: ${testName}${details ? ' - ' + details : ''}`);
}

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function clearHighlights(page) {
    await page.evaluate(() => {
        document.querySelectorAll('.highlighted').forEach(el => el.classList.remove('highlighted'));
    });
    await sleep(100);
}

async function runTests() {
    console.log('=== Net Highlighting Tests ===\n');

    const browser = await puppeteer.launch({ headless: true });
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    try {
        // Load page
        await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
        await page.waitForSelector('svg');

        // Ensure we're in select mode (not trace mode)
        const isTraceMode = await page.evaluate(() => {
            return document.body.classList.contains('trace-mode-active');
        });
        if (isTraceMode) {
            await page.keyboard.press('t');
            await sleep(200);
        }

        // ========== TEST 1: Clicking on a pad highlights the net ==========
        console.log('--- Test 1: Pad click highlights net ---');

        await clearHighlights(page);

        // Find a pad with a net that has other elements
        const padInfo = await page.evaluate(() => {
            const pads = document.querySelectorAll('.pad[data-net]');
            for (const pad of pads) {
                const netId = pad.dataset.net;
                if (netId && netId !== '0') {
                    const sameNetPads = document.querySelectorAll(`.pad[data-net="${netId}"]`);
                    if (sameNetPads.length > 1) {
                        const rect = pad.getBoundingClientRect();
                        return {
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2,
                            netId: netId,
                            totalPadsOnNet: sameNetPads.length
                        };
                    }
                }
            }
            return null;
        });

        if (padInfo) {
            await page.mouse.click(padInfo.x, padInfo.y);
            await sleep(300);

            const afterPadClick = await page.evaluate((netId) => {
                return {
                    padsHighlighted: document.querySelectorAll(`.pad[data-net="${netId}"].highlighted`).length,
                    tracesHighlighted: document.querySelectorAll(`.trace[data-net="${netId}"].highlighted`).length,
                    viasHighlighted: document.querySelectorAll(`.via[data-net="${netId}"].highlighted`).length,
                    totalPads: document.querySelectorAll(`.pad[data-net="${netId}"]`).length
                };
            }, padInfo.netId);

            if (afterPadClick.padsHighlighted > 0) {
                pass('Pad click highlights pads', `${afterPadClick.padsHighlighted} pads highlighted`);
            } else {
                fail('Pad click highlights pads', 'No pads highlighted');
            }

            if (afterPadClick.padsHighlighted === afterPadClick.totalPads) {
                pass('All pads on net highlighted', `${afterPadClick.padsHighlighted}/${afterPadClick.totalPads}`);
            } else {
                fail('All pads on net highlighted', `Only ${afterPadClick.padsHighlighted}/${afterPadClick.totalPads}`);
            }
        } else {
            fail('Pad click highlights pads', 'Could not find suitable pad for test');
            fail('All pads on net highlighted', 'Could not find suitable pad for test');
        }

        // ========== TEST 2: Clicking on a trace highlights the net ==========
        console.log('\n--- Test 2: Trace click highlights net (regression test) ---');

        await clearHighlights(page);

        // Find a trace that's visible and clickable
        // Traces are line elements, so we need to check points along the line
        const traceInfo = await page.evaluate(() => {
            const traces = document.querySelectorAll('.trace[data-net]');
            for (const trace of traces) {
                const netId = trace.dataset.net;
                if (netId && netId !== '0') {
                    // For line elements, get x1,y1,x2,y2 and convert to screen coords
                    const svg = trace.closest('svg');
                    if (!svg) continue;

                    const x1 = parseFloat(trace.getAttribute('x1'));
                    const y1 = parseFloat(trace.getAttribute('y1'));
                    const x2 = parseFloat(trace.getAttribute('x2'));
                    const y2 = parseFloat(trace.getAttribute('y2'));

                    // Get midpoint in SVG coordinates
                    const midX = (x1 + x2) / 2;
                    const midY = (y1 + y2) / 2;

                    // Convert SVG coords to screen coords using CTM
                    const point = svg.createSVGPoint();
                    point.x = midX;
                    point.y = midY;
                    const ctm = svg.getScreenCTM();
                    if (!ctm) continue;

                    const screenPoint = point.matrixTransform(ctm);

                    // Verify trace is actually at this point using elementsFromPoint
                    const elemsAtPoint = document.elementsFromPoint(screenPoint.x, screenPoint.y);
                    const traceAtPoint = elemsAtPoint.find(el => el.classList.contains('trace'));
                    if (traceAtPoint) {
                        return {
                            x: screenPoint.x,
                            y: screenPoint.y,
                            netId: netId,
                            netName: trace.dataset.netName
                        };
                    }
                }
            }
            return null;
        });

        if (traceInfo) {
            await page.mouse.click(traceInfo.x, traceInfo.y);
            await sleep(300);

            const afterTraceClick = await page.evaluate((netId) => {
                return {
                    padsHighlighted: document.querySelectorAll(`.pad[data-net="${netId}"].highlighted`).length,
                    tracesHighlighted: document.querySelectorAll(`.trace[data-net="${netId}"].highlighted`).length,
                    viasHighlighted: document.querySelectorAll(`.via[data-net="${netId}"].highlighted`).length,
                    totalPads: document.querySelectorAll(`.pad[data-net="${netId}"]`).length,
                    totalTraces: document.querySelectorAll(`.trace[data-net="${netId}"]`).length
                };
            }, traceInfo.netId);

            if (afterTraceClick.tracesHighlighted > 0) {
                pass('Trace click highlights traces', `${afterTraceClick.tracesHighlighted} traces highlighted`);
            } else {
                fail('Trace click highlights traces', 'No traces highlighted after clicking trace');
            }

            if (afterTraceClick.padsHighlighted > 0) {
                pass('Trace click also highlights pads', `${afterTraceClick.padsHighlighted} pads highlighted`);
            } else {
                fail('Trace click also highlights pads', 'Pads not highlighted when trace clicked');
            }

            if (afterTraceClick.tracesHighlighted === afterTraceClick.totalTraces) {
                pass('All traces on net highlighted', `${afterTraceClick.tracesHighlighted}/${afterTraceClick.totalTraces}`);
            } else {
                fail('All traces on net highlighted', `Only ${afterTraceClick.tracesHighlighted}/${afterTraceClick.totalTraces}`);
            }
        } else {
            fail('Trace click highlights traces', 'Could not find clickable trace for test');
            fail('Trace click also highlights pads', 'Could not find clickable trace for test');
            fail('All traces on net highlighted', 'Could not find clickable trace for test');
        }

        // ========== TEST 3: Clicking on a via highlights the net ==========
        console.log('\n--- Test 3: Via click highlights net ---');

        await clearHighlights(page);

        const viaInfo = await page.evaluate(() => {
            const vias = document.querySelectorAll('.via[data-net]');
            for (const via of vias) {
                const netId = via.dataset.net;
                if (netId && netId !== '0') {
                    const rect = via.getBoundingClientRect();
                    return {
                        x: rect.x + rect.width / 2,
                        y: rect.y + rect.height / 2,
                        netId: netId
                    };
                }
            }
            return null;
        });

        if (viaInfo) {
            await page.mouse.click(viaInfo.x, viaInfo.y);
            await sleep(300);

            const afterViaClick = await page.evaluate((netId) => {
                return {
                    padsHighlighted: document.querySelectorAll(`.pad[data-net="${netId}"].highlighted`).length,
                    tracesHighlighted: document.querySelectorAll(`.trace[data-net="${netId}"].highlighted`).length,
                    viasHighlighted: document.querySelectorAll(`.via[data-net="${netId}"].highlighted`).length,
                    totalVias: document.querySelectorAll(`.via[data-net="${netId}"]`).length
                };
            }, viaInfo.netId);

            if (afterViaClick.viasHighlighted > 0) {
                pass('Via click highlights vias', `${afterViaClick.viasHighlighted} vias highlighted`);
            } else {
                fail('Via click highlights vias', 'No vias highlighted');
            }

            if (afterViaClick.padsHighlighted > 0 || afterViaClick.tracesHighlighted > 0) {
                pass('Via click highlights related elements',
                    `${afterViaClick.padsHighlighted} pads, ${afterViaClick.tracesHighlighted} traces`);
            } else {
                fail('Via click highlights related elements', 'No pads or traces highlighted');
            }
        } else {
            fail('Via click highlights vias', 'No vias found for test');
            fail('Via click highlights related elements', 'No vias found for test');
        }

        // ========== TEST 4: Clicking empty space clears highlights ==========
        console.log('\n--- Test 4: Empty space click clears highlights ---');

        // First, ensure something is highlighted
        if (padInfo) {
            await page.mouse.click(padInfo.x, padInfo.y);
            await sleep(300);
        }

        const beforeClear = await page.evaluate(() => {
            return document.querySelectorAll('.highlighted').length;
        });

        // Click on an empty area (far corner of the SVG container)
        await page.evaluate(() => {
            const container = document.getElementById('svg-container');
            const rect = container.getBoundingClientRect();
            // Click near top-left corner of container where there shouldn't be any PCB elements
            return { x: rect.x + 10, y: rect.y + 10 };
        }).then(async (pos) => {
            await page.mouse.click(pos.x, pos.y);
        });
        await sleep(300);

        const afterClear = await page.evaluate(() => {
            return document.querySelectorAll('.highlighted').length;
        });

        if (beforeClear > 0 && afterClear === 0) {
            pass('Empty space click clears highlights', `${beforeClear} -> ${afterClear}`);
        } else if (beforeClear === 0) {
            fail('Empty space click clears highlights', 'No highlights to clear');
        } else {
            fail('Empty space click clears highlights', `Still have ${afterClear} highlights`);
        }

        // Print summary
        console.log('\n=== Summary ===');
        console.log(`Passed: ${results.passed}`);
        console.log(`Failed: ${results.failed}`);

    } catch (error) {
        console.error('Test error:', error);
        fail('Test execution', error.message);
    } finally {
        await browser.close();
    }

    // Exit with appropriate code
    process.exit(results.failed > 0 ? 1 : 0);
}

runTests();
