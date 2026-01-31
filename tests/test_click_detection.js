/**
 * Comprehensive Puppeteer test for click detection on PCB viewer.
 * Tests pad clicking, highlighting, and event propagation.
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
    log('Starting click detection tests...');
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

        // ========== TEST 2: SVG loads with pads ==========
        log('\n--- Test 2: SVG Content ---');
        try {
            await page.waitForSelector('svg', { timeout: 5000 });
            pass('SVG element exists');
        } catch (err) {
            fail('SVG element exists');
        }

        const svgInfo = await page.evaluate(() => {
            const svg = document.querySelector('svg');
            const pads = document.querySelectorAll('.pad');
            const container = document.getElementById('svg-container');
            return {
                hasSvg: !!svg,
                padCount: pads.length,
                hasContainer: !!container,
                svgWidth: svg ? svg.getBoundingClientRect().width : 0,
                svgHeight: svg ? svg.getBoundingClientRect().height : 0,
                viewBox: svg ? svg.getAttribute('viewBox') : null,
                // Check first few pads
                samplePads: Array.from(pads).slice(0, 3).map(p => ({
                    id: p.id,
                    tagName: p.tagName,
                    classList: Array.from(p.classList),
                    hasNetData: !!p.dataset.net,
                    netName: p.dataset.netName
                }))
            };
        });

        log(`  SVG size: ${svgInfo.svgWidth.toFixed(0)}x${svgInfo.svgHeight.toFixed(0)}`);
        log(`  ViewBox: ${svgInfo.viewBox}`);
        log(`  Total pads found: ${svgInfo.padCount}`);

        if (svgInfo.padCount > 0) {
            pass('Pads exist in SVG', `${svgInfo.padCount} pads found`);
            log('  Sample pads:');
            svgInfo.samplePads.forEach(p => {
                log(`    - ${p.id}: ${p.tagName}, classes=[${p.classList.join(',')}], net=${p.netName}`);
            });
        } else {
            fail('Pads exist in SVG', 'No elements with .pad class found');
        }

        // ========== TEST 3: Find a specific pad to test ==========
        log('\n--- Test 3: Locate Test Pad ---');
        const testPadInfo = await page.evaluate(() => {
            // Try to find a pad that's likely to be clickable
            const pads = document.querySelectorAll('.pad');
            if (pads.length === 0) return null;

            // Find a pad with a net (not net 0)
            let testPad = null;
            for (const pad of pads) {
                const netId = parseInt(pad.dataset.net, 10);
                if (netId > 0) {
                    testPad = pad;
                    break;
                }
            }
            if (!testPad) testPad = pads[0];

            const bbox = testPad.getBoundingClientRect();
            const svg = testPad.ownerSVGElement;
            const svgRect = svg ? svg.getBoundingClientRect() : null;

            return {
                id: testPad.id,
                tagName: testPad.tagName,
                netId: testPad.dataset.net,
                netName: testPad.dataset.netName,
                bbox: {
                    x: bbox.x,
                    y: bbox.y,
                    width: bbox.width,
                    height: bbox.height,
                    centerX: bbox.x + bbox.width / 2,
                    centerY: bbox.y + bbox.height / 2
                },
                svgBbox: svgRect ? {
                    x: svgRect.x,
                    y: svgRect.y,
                    width: svgRect.width,
                    height: svgRect.height
                } : null,
                isVisible: bbox.width > 0 && bbox.height > 0,
                // Check computed styles
                computedStyle: {
                    pointerEvents: window.getComputedStyle(testPad).pointerEvents,
                    visibility: window.getComputedStyle(testPad).visibility,
                    display: window.getComputedStyle(testPad).display,
                    opacity: window.getComputedStyle(testPad).opacity
                }
            };
        });

        if (testPadInfo) {
            log(`  Test pad: ${testPadInfo.id} (${testPadInfo.tagName})`);
            log(`  Net: ${testPadInfo.netName} (ID: ${testPadInfo.netId})`);
            log(`  Bounding box: (${testPadInfo.bbox.x.toFixed(1)}, ${testPadInfo.bbox.y.toFixed(1)}) ` +
                `${testPadInfo.bbox.width.toFixed(1)}x${testPadInfo.bbox.height.toFixed(1)}`);
            log(`  Center: (${testPadInfo.bbox.centerX.toFixed(1)}, ${testPadInfo.bbox.centerY.toFixed(1)})`);
            log(`  Computed styles: pointerEvents=${testPadInfo.computedStyle.pointerEvents}, ` +
                `visibility=${testPadInfo.computedStyle.visibility}, opacity=${testPadInfo.computedStyle.opacity}`);

            if (testPadInfo.isVisible) {
                pass('Test pad is visible');
            } else {
                fail('Test pad is visible', 'Pad has zero size');
            }

            if (testPadInfo.computedStyle.pointerEvents !== 'none') {
                pass('Pad accepts pointer events');
            } else {
                fail('Pad accepts pointer events', 'pointer-events: none');
            }
        } else {
            fail('Locate test pad', 'Could not find any pad');
            throw new Error('No pad to test');
        }

        // Take initial screenshot
        await page.screenshot({ path: `${SCREENSHOT_DIR}/pcb_test_initial.png`, fullPage: true });
        log(`  Screenshot: ${SCREENSHOT_DIR}/pcb_test_initial.png`);

        // ========== TEST 4: Element detection at click position ==========
        log('\n--- Test 4: Element Detection ---');
        const clickX = testPadInfo.bbox.centerX;
        const clickY = testPadInfo.bbox.centerY;

        const elementAtPoint = await page.evaluate((x, y) => {
            const elem = document.elementFromPoint(x, y);
            if (!elem) return { error: 'No element at point' };

            // Walk up to find if we're inside a pad
            let current = elem;
            let path = [];
            while (current && current !== document.body) {
                path.push({
                    tagName: current.tagName,
                    id: current.id,
                    classList: Array.from(current.classList || [])
                });
                current = current.parentElement;
            }

            const closestPad = elem.closest('.pad');

            return {
                element: {
                    tagName: elem.tagName,
                    id: elem.id,
                    classList: Array.from(elem.classList || []),
                    isPad: elem.classList.contains('pad'),
                    dataset: elem.dataset ? Object.fromEntries(Object.entries(elem.dataset)) : {}
                },
                closestPad: closestPad ? {
                    id: closestPad.id,
                    tagName: closestPad.tagName,
                    netName: closestPad.dataset.netName
                } : null,
                domPath: path.slice(0, 5) // First 5 ancestors
            };
        }, clickX, clickY);

        log(`  Element at (${clickX.toFixed(1)}, ${clickY.toFixed(1)}):`);
        log(`    Direct element: ${elementAtPoint.element.tagName}#${elementAtPoint.element.id || '(no id)'}`);
        log(`    Classes: [${elementAtPoint.element.classList.join(', ')}]`);
        log(`    Is pad: ${elementAtPoint.element.isPad}`);
        log(`    Closest pad: ${elementAtPoint.closestPad ? elementAtPoint.closestPad.id : 'NONE'}`);

        if (elementAtPoint.closestPad) {
            pass('Element at click point is/contains pad');
        } else {
            fail('Element at click point is/contains pad',
                `Got ${elementAtPoint.element.tagName}#${elementAtPoint.element.id}`);
            log('  DOM path:');
            elementAtPoint.domPath.forEach((p, i) => {
                log(`    ${'  '.repeat(i)}${p.tagName}#${p.id || '(no id)'} [${p.classList.join(',')}]`);
            });
        }

        // ========== TEST 5: Click and check highlighting ==========
        log('\n--- Test 5: Click Detection ---');

        // Clear any existing highlights first
        await page.evaluate(() => {
            document.querySelectorAll('.pad.highlighted').forEach(p => p.classList.remove('highlighted'));
        });

        // Get state before click
        const beforeClick = await page.evaluate((padId) => {
            const pad = document.getElementById(padId);
            return {
                isHighlighted: pad ? pad.classList.contains('highlighted') : false,
                totalHighlighted: document.querySelectorAll('.pad.highlighted').length
            };
        }, testPadInfo.id);

        log(`  Before click: highlighted=${beforeClick.isHighlighted}, total=${beforeClick.totalHighlighted}`);

        // Perform click
        log(`  Clicking at (${clickX.toFixed(1)}, ${clickY.toFixed(1)})...`);
        await page.mouse.click(clickX, clickY);
        await sleep(500);

        // Check state after click
        const afterClick = await page.evaluate((padId, netId) => {
            const pad = document.getElementById(padId);
            const allHighlighted = document.querySelectorAll('.pad.highlighted');
            const sameNetPads = document.querySelectorAll(`.pad[data-net="${netId}"]`);
            const sameNetHighlighted = document.querySelectorAll(`.pad[data-net="${netId}"].highlighted`);

            return {
                padHighlighted: pad ? pad.classList.contains('highlighted') : false,
                totalHighlighted: allHighlighted.length,
                highlightedIds: Array.from(allHighlighted).slice(0, 5).map(p => p.id),
                sameNetCount: sameNetPads.length,
                sameNetHighlightedCount: sameNetHighlighted.length
            };
        }, testPadInfo.id, testPadInfo.netId);

        log(`  After click: padHighlighted=${afterClick.padHighlighted}, total=${afterClick.totalHighlighted}`);
        log(`  Same net pads: ${afterClick.sameNetCount}, highlighted: ${afterClick.sameNetHighlightedCount}`);

        if (afterClick.padHighlighted) {
            pass('Clicked pad is highlighted');
        } else {
            fail('Clicked pad is highlighted');
        }

        if (afterClick.totalHighlighted > 0) {
            pass('Highlighting triggered', `${afterClick.totalHighlighted} pads highlighted`);
        } else {
            fail('Highlighting triggered', 'No pads highlighted after click');
        }

        // Take screenshot after click
        await page.screenshot({ path: `${SCREENSHOT_DIR}/pcb_test_after_click.png`, fullPage: true });
        log(`  Screenshot: ${SCREENSHOT_DIR}/pcb_test_after_click.png`);

        // ========== TEST 6: Event listener check ==========
        log('\n--- Test 6: Event Listeners ---');
        const eventInfo = await page.evaluate(() => {
            const container = document.getElementById('svg-container');
            const svg = container ? container.querySelector('svg') : null;

            // Try to dispatch a synthetic click and see if it's caught
            let clickCaught = false;
            const testHandler = () => { clickCaught = true; };

            if (container) {
                container.addEventListener('click', testHandler, { once: true });
                container.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            }

            return {
                hasContainer: !!container,
                hasSvg: !!svg,
                clickCaught
            };
        });

        if (eventInfo.clickCaught) {
            pass('Container receives click events');
        } else {
            fail('Container receives click events');
        }

        // ========== TEST 7: Test multiple click positions ==========
        log('\n--- Test 7: Multiple Click Positions ---');
        const testPositions = [
            { name: 'center', x: testPadInfo.bbox.centerX, y: testPadInfo.bbox.centerY },
            { name: 'top-left', x: testPadInfo.bbox.x + 2, y: testPadInfo.bbox.y + 2 },
            { name: 'bottom-right', x: testPadInfo.bbox.x + testPadInfo.bbox.width - 2, y: testPadInfo.bbox.y + testPadInfo.bbox.height - 2 }
        ];

        for (const pos of testPositions) {
            // Clear highlights
            await page.evaluate(() => {
                document.querySelectorAll('.pad.highlighted').forEach(p => p.classList.remove('highlighted'));
            });
            await sleep(100);

            // Check what element is at this position
            const elemCheck = await page.evaluate((x, y) => {
                const elem = document.elementFromPoint(x, y);
                return {
                    tagName: elem ? elem.tagName : 'NONE',
                    id: elem ? elem.id : '',
                    isPad: elem ? elem.classList.contains('pad') : false,
                    hasPadAncestor: elem ? !!elem.closest('.pad') : false
                };
            }, pos.x, pos.y);

            log(`  ${pos.name} (${pos.x.toFixed(1)}, ${pos.y.toFixed(1)}): ` +
                `${elemCheck.tagName}#${elemCheck.id || '(no id)'}, isPad=${elemCheck.isPad}, hasPadAncestor=${elemCheck.hasPadAncestor}`);

            // Click and check
            await page.mouse.click(pos.x, pos.y);
            await sleep(300);

            const result = await page.evaluate((padId) => {
                const pad = document.getElementById(padId);
                return pad ? pad.classList.contains('highlighted') : false;
            }, testPadInfo.id);

            if (result) {
                pass(`Click at ${pos.name} highlights pad`);
            } else {
                fail(`Click at ${pos.name} highlights pad`, `Element at point: ${elemCheck.tagName}`);
            }
        }

        // ========== TEST 8: Check for overlapping elements ==========
        log('\n--- Test 8: Z-Index / Overlap Check ---');
        const overlapCheck = await page.evaluate((x, y) => {
            const elements = document.elementsFromPoint(x, y);
            return elements.slice(0, 10).map(e => ({
                tagName: e.tagName,
                id: e.id,
                classList: Array.from(e.classList || []),
                zIndex: window.getComputedStyle(e).zIndex
            }));
        }, clickX, clickY);

        log('  Elements at click point (top to bottom):');
        overlapCheck.forEach((e, i) => {
            const classes = e.classList.length > 0 ? ` [${e.classList.join(',')}]` : '';
            log(`    ${i + 1}. ${e.tagName}#${e.id || '(no id)'}${classes} z-index=${e.zIndex}`);
        });

        // Check if pad is the topmost clickable element
        const padIndex = overlapCheck.findIndex(e => e.classList.includes('pad'));
        if (padIndex === 0) {
            pass('Pad is topmost element at click point');
        } else if (padIndex > 0) {
            fail('Pad is topmost element at click point',
                `Pad is at position ${padIndex + 1}, covered by ${overlapCheck[0].tagName}`);
        } else {
            fail('Pad is topmost element at click point', 'Pad not found in element stack');
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

        log('\nScreenshots saved to:');
        log(`  - ${SCREENSHOT_DIR}/pcb_test_initial.png`);
        log(`  - ${SCREENSHOT_DIR}/pcb_test_after_click.png`);

        if (results.failed > 0) {
            log('\n⚠️  Some tests failed - click detection may not be working correctly');
        } else {
            log('\n✓ All tests passed - click detection is working');
        }

        log('\nBrowser left open for manual inspection. Press Ctrl+C to close.');
        await new Promise(() => {}); // Keep browser open

    } catch (err) {
        console.error('\n❌ Test error:', err.message);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/pcb_test_error.png`, fullPage: true });
        log(`Error screenshot: ${SCREENSHOT_DIR}/pcb_test_error.png`);
        await browser.close();
        process.exit(1);
    }
}

runTests().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
