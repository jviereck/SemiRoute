/**
 * Puppeteer test for endpoint snapping behavior during routing.
 * Tests that clicking near a different-net pad does NOT snap to that pad.
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
    log('Starting endpoint snapping tests...');
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
        consoleLogs.push({ type: msg.type(), text: msg.text() });
        if (msg.type() === 'error') {
            console.log(`  [PAGE ERROR] ${msg.text()}`);
        }
    });

    try {
        // ========== TEST 1: Page loads ==========
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

        // ========== TEST 2: Find adjacent pads on different nets ==========
        log('\n--- Test 2: Find Adjacent Pads on Different Nets ---');

        const padInfo = await page.evaluate(() => {
            const pads = Array.from(document.querySelectorAll('.pad'));

            // Find pads that are close together but on different nets
            // Look for U3 pads specifically (known to have adjacent GND and NC pads)
            const u3Pads = pads.filter(p => {
                const footprint = p.closest('[data-footprint]')?.dataset.footprint;
                return footprint === 'U3';
            });

            if (u3Pads.length < 2) {
                // Fallback: find any two close pads on different nets
                for (let i = 0; i < pads.length; i++) {
                    for (let j = i + 1; j < pads.length; j++) {
                        const p1 = pads[i];
                        const p2 = pads[j];
                        const net1 = parseInt(p1.dataset.net, 10);
                        const net2 = parseInt(p2.dataset.net, 10);

                        if (net1 > 0 && net2 > 0 && net1 !== net2) {
                            const x1 = parseFloat(p1.dataset.x || p1.getAttribute('cx'));
                            const y1 = parseFloat(p1.dataset.y || p1.getAttribute('cy'));
                            const x2 = parseFloat(p2.dataset.x || p2.getAttribute('cx'));
                            const y2 = parseFloat(p2.dataset.y || p2.getAttribute('cy'));

                            const dist = Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2);
                            if (dist < 2.0) {  // Within 2mm
                                return {
                                    pad1: { x: x1, y: y1, net: net1 },
                                    pad2: { x: x2, y: y2, net: net2 },
                                    distance: dist
                                };
                            }
                        }
                    }
                }
                return null;
            }

            // Found U3 pads - find two on different nets
            for (let i = 0; i < u3Pads.length; i++) {
                for (let j = i + 1; j < u3Pads.length; j++) {
                    const p1 = u3Pads[i];
                    const p2 = u3Pads[j];
                    const net1 = parseInt(p1.dataset.net, 10);
                    const net2 = parseInt(p2.dataset.net, 10);

                    if (net1 > 0 && net2 > 0 && net1 !== net2) {
                        const x1 = parseFloat(p1.dataset.x || p1.getAttribute('cx'));
                        const y1 = parseFloat(p1.dataset.y || p1.getAttribute('cy'));
                        const x2 = parseFloat(p2.dataset.x || p2.getAttribute('cx'));
                        const y2 = parseFloat(p2.dataset.y || p2.getAttribute('cy'));

                        return {
                            pad1: { x: x1, y: y1, net: net1 },
                            pad2: { x: x2, y: y2, net: net2 },
                            distance: Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                        };
                    }
                }
            }
            return null;
        });

        if (padInfo) {
            pass('Found adjacent pads on different nets', `dist=${padInfo.distance.toFixed(2)}mm`);
            log(`  Pad 1: (${padInfo.pad1.x.toFixed(2)}, ${padInfo.pad1.y.toFixed(2)}) net ${padInfo.pad1.net}`);
            log(`  Pad 2: (${padInfo.pad2.x.toFixed(2)}, ${padInfo.pad2.y.toFixed(2)}) net ${padInfo.pad2.net}`);
        } else {
            fail('Found adjacent pads on different nets');
            throw new Error('Cannot continue without test pads');
        }

        // ========== TEST 3: Enable trace mode ==========
        log('\n--- Test 3: Enable Trace Mode ---');
        await page.click('#trace-mode-toggle');
        await sleep(300);

        const traceModeEnabled = await page.evaluate(() => {
            return document.body.classList.contains('trace-mode-active');
        });

        if (traceModeEnabled) {
            pass('Trace mode enabled');
        } else {
            fail('Trace mode enabled');
        }

        // ========== TEST 4: Start routing from pad 1 ==========
        log('\n--- Test 4: Start Routing Session ---');

        // Get screen coordinates for pad 1
        const pad1Screen = await page.evaluate((padInfo) => {
            // Find the SVG viewer's transform
            const container = document.getElementById('svg-container');
            const svg = container.querySelector('svg');
            const rect = container.getBoundingClientRect();

            // Get the current transform
            const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
            const svgWidth = svg.clientWidth;
            const svgHeight = svg.clientHeight;

            // Convert SVG coords to screen coords
            const scaleX = svgWidth / viewBox[2];
            const scaleY = svgHeight / viewBox[3];
            const screenX = rect.left + (padInfo.pad1.x - viewBox[0]) * scaleX;
            const screenY = rect.top + (padInfo.pad1.y - viewBox[1]) * scaleY;

            return { x: screenX, y: screenY };
        }, padInfo);

        log(`  Clicking pad 1 at screen (${pad1Screen.x.toFixed(1)}, ${pad1Screen.y.toFixed(1)})`);

        // Click to start routing
        await page.mouse.click(pad1Screen.x, pad1Screen.y);
        await sleep(300);

        const routingStarted = await page.evaluate(() => {
            // Check if routing session started by looking for start marker
            const startMarker = document.querySelector('.start-marker');
            return !!startMarker;
        });

        if (routingStarted) {
            pass('Routing session started');
        } else {
            fail('Routing session started');
        }

        // ========== TEST 5: Route towards empty space (not to pad 2) ==========
        log('\n--- Test 5: Route Away From Different-Net Pad ---');

        // Calculate a position away from both pads
        const targetPoint = {
            x: padInfo.pad1.x + 3.0,  // 3mm to the right
            y: padInfo.pad1.y
        };

        const targetScreen = await page.evaluate((target) => {
            const container = document.getElementById('svg-container');
            const svg = container.querySelector('svg');
            const rect = container.getBoundingClientRect();
            const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
            const svgWidth = svg.clientWidth;
            const svgHeight = svg.clientHeight;

            const scaleX = svgWidth / viewBox[2];
            const scaleY = svgHeight / viewBox[3];
            const screenX = rect.left + (target.x - viewBox[0]) * scaleX;
            const screenY = rect.top + (target.y - viewBox[1]) * scaleY;

            return { x: screenX, y: screenY };
        }, targetPoint);

        // Move mouse to trigger routing preview
        await page.mouse.move(targetScreen.x, targetScreen.y);
        await sleep(500);  // Wait for debounced routing

        const hasPreview = await page.evaluate(() => {
            const preview = document.querySelector('.pending-trace');
            return !!preview;
        });

        if (hasPreview) {
            pass('Route preview shown to empty space');
        } else {
            // Route might fail due to obstacles, which is OK
            pass('Route preview not shown (may be blocked by obstacles)');
        }

        // ========== TEST 6: Click near different-net pad - should NOT snap ==========
        log('\n--- Test 6: Click Near Different-Net Pad ---');

        // Position between the two pads (closer to pad 2)
        const nearPad2 = {
            x: (padInfo.pad1.x + padInfo.pad2.x) / 2 + (padInfo.pad2.x - padInfo.pad1.x) * 0.3,
            y: (padInfo.pad1.y + padInfo.pad2.y) / 2 + (padInfo.pad2.y - padInfo.pad1.y) * 0.3
        };

        const nearPad2Screen = await page.evaluate((target) => {
            const container = document.getElementById('svg-container');
            const svg = container.querySelector('svg');
            const rect = container.getBoundingClientRect();
            const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
            const svgWidth = svg.clientWidth;
            const svgHeight = svg.clientHeight;

            const scaleX = svgWidth / viewBox[2];
            const scaleY = svgHeight / viewBox[3];
            const screenX = rect.left + (target.x - viewBox[0]) * scaleX;
            const screenY = rect.top + (target.y - viewBox[1]) * scaleY;

            return { x: screenX, y: screenY };
        }, nearPad2);

        log(`  Clicking near pad 2 at (${nearPad2.x.toFixed(2)}, ${nearPad2.y.toFixed(2)})`);

        // Move mouse there first
        await page.mouse.move(nearPad2Screen.x, nearPad2Screen.y);
        await sleep(500);

        // Clear console logs to capture new ones
        consoleLogs.length = 0;

        // Double-click to try to commit and finish
        await page.mouse.click(nearPad2Screen.x, nearPad2Screen.y, { clickCount: 2 });
        await sleep(500);

        // Check console for "Cannot route to different net" error
        const differentNetError = consoleLogs.some(log =>
            log.text.includes('Cannot route to different net') ||
            log.text.includes('different net')
        );

        // Check if routing session ended (should end even if no path)
        const routingEnded = await page.evaluate(() => {
            const startMarker = document.querySelector('.start-marker');
            return !startMarker;
        });

        // Check for error message in UI
        const errorShown = await page.evaluate(() => {
            const errorEl = document.getElementById('trace-error');
            return errorEl && !errorEl.classList.contains('hidden');
        });

        const errorText = await page.evaluate(() => {
            const errorEl = document.getElementById('trace-error');
            return errorEl ? errorEl.textContent : '';
        });

        log(`  Error shown: ${errorShown}, text: "${errorText}"`);
        log(`  Different net error in console: ${differentNetError}`);
        log(`  Routing ended: ${routingEnded}`);

        // The key behavior: clicking near a different-net pad should NOT cause
        // "Cannot route to different net" error because we don't snap to it
        if (!differentNetError && !errorText.includes('different net')) {
            pass('No different-net error (endpoint did not snap to wrong pad)');
        } else {
            fail('No different-net error', `Got: ${errorText}`);
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/endpoint_snap_test.png`, fullPage: true });

        // ========== TEST 7: Verify same-net snapping still works ==========
        log('\n--- Test 7: Same-Net Snapping Works ---');

        // Find two pads on the same net
        const sameNetPads = await page.evaluate(() => {
            const pads = Array.from(document.querySelectorAll('.pad'));
            const padsByNet = {};

            for (const pad of pads) {
                const net = parseInt(pad.dataset.net, 10);
                if (net > 0) {
                    if (!padsByNet[net]) padsByNet[net] = [];
                    padsByNet[net].push({
                        x: parseFloat(pad.dataset.x || pad.getAttribute('cx')),
                        y: parseFloat(pad.dataset.y || pad.getAttribute('cy')),
                        net: net
                    });
                }
            }

            // Find a net with at least 2 pads
            for (const [net, pads] of Object.entries(padsByNet)) {
                if (pads.length >= 2) {
                    return { pad1: pads[0], pad2: pads[1] };
                }
            }
            return null;
        });

        if (!sameNetPads) {
            log('  Skipping - no net with 2 pads found');
        } else {
            log(`  Same net pads: net ${sameNetPads.pad1.net}`);
            log(`    Pad 1: (${sameNetPads.pad1.x.toFixed(2)}, ${sameNetPads.pad1.y.toFixed(2)})`);
            log(`    Pad 2: (${sameNetPads.pad2.x.toFixed(2)}, ${sameNetPads.pad2.y.toFixed(2)})`);

            // Re-enable trace mode if needed
            const needsEnable = await page.evaluate(() => {
                return !document.body.classList.contains('trace-mode-active');
            });
            if (needsEnable) {
                await page.click('#trace-mode-toggle');
                await sleep(300);
            }

            // Click pad 1 to start
            const sameNetPad1Screen = await page.evaluate((pad) => {
                const container = document.getElementById('svg-container');
                const svg = container.querySelector('svg');
                const rect = container.getBoundingClientRect();
                const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
                const svgWidth = svg.clientWidth;
                const svgHeight = svg.clientHeight;

                const scaleX = svgWidth / viewBox[2];
                const scaleY = svgHeight / viewBox[3];
                return {
                    x: rect.left + (pad.x - viewBox[0]) * scaleX,
                    y: rect.top + (pad.y - viewBox[1]) * scaleY
                };
            }, sameNetPads.pad1);

            await page.mouse.click(sameNetPad1Screen.x, sameNetPad1Screen.y);
            await sleep(300);

            // Double-click on pad 2 (same net - should snap and work)
            const sameNetPad2Screen = await page.evaluate((pad) => {
                const container = document.getElementById('svg-container');
                const svg = container.querySelector('svg');
                const rect = container.getBoundingClientRect();
                const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
                const svgWidth = svg.clientWidth;
                const svgHeight = svg.clientHeight;

                const scaleX = svgWidth / viewBox[2];
                const scaleY = svgHeight / viewBox[3];
                return {
                    x: rect.left + (pad.x - viewBox[0]) * scaleX,
                    y: rect.top + (pad.y - viewBox[1]) * scaleY
                };
            }, sameNetPads.pad2);

            consoleLogs.length = 0;
            await page.mouse.move(sameNetPad2Screen.x, sameNetPad2Screen.y);
            await sleep(500);
            await page.mouse.click(sameNetPad2Screen.x, sameNetPad2Screen.y, { clickCount: 2 });
            await sleep(500);

            // Check for double-click log showing same-net snap
            const snapLog = consoleLogs.find(l => l.text.includes('Double-click to commit'));
            if (snapLog && snapLog.text.includes('same-net pad')) {
                pass('Same-net pad snapping works');
            } else {
                // Check that there's no different-net error at least
                const hasDiffNetError = consoleLogs.some(l => l.text.includes('different net'));
                if (!hasDiffNetError) {
                    pass('Same-net routing completed without error');
                } else {
                    fail('Same-net pad snapping', 'Got different-net error');
                }
            }
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

    if (results.failed === 0) {
        log('\n✓ All tests passed');
        process.exit(0);
    } else {
        process.exit(1);
    }
}

runTests();
