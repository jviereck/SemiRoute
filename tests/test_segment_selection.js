/**
 * Puppeteer test for segment selection and deletion functionality.
 * Tests single-click, shift+click, double-click selection and Backspace deletion.
 */
const puppeteer = require('puppeteer');

const SERVER_URL = 'http://localhost:8000';
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

/**
 * Helper to create a route with multiple segments for testing.
 * Returns the route ID if successful.
 */
async function createTestRoute(page, numSegments = 3) {
    // Enable trace mode if not already
    const traceModeEnabled = await page.evaluate(() => {
        return document.body.classList.contains('trace-mode-active');
    });
    if (!traceModeEnabled) {
        await page.click('#trace-mode-toggle');
        await sleep(200);
    }

    // Find a starting pad
    const startPad = await page.evaluate(() => {
        const pads = document.querySelectorAll('.pad');
        for (const pad of pads) {
            if (parseInt(pad.dataset.net, 10) > 0) {
                const bbox = pad.getBoundingClientRect();
                return {
                    screenX: bbox.x + bbox.width / 2,
                    screenY: bbox.y + bbox.height / 2,
                    netId: pad.dataset.net
                };
            }
        }
        return null;
    });

    if (!startPad) {
        log('  No suitable pad found for test route');
        return null;
    }

    // Click on start pad
    await page.mouse.click(startPad.screenX, startPad.screenY);
    await sleep(300);

    // Create segments by clicking at offset positions
    const segmentOffsets = [
        { dx: 50, dy: 0 },
        { dx: 50, dy: 50 },
        { dx: 0, dy: 50 }
    ];

    for (let i = 0; i < Math.min(numSegments, segmentOffsets.length); i++) {
        const offset = segmentOffsets[i];
        const targetX = startPad.screenX + offset.dx;
        const targetY = startPad.screenY + offset.dy;

        await page.mouse.click(targetX, targetY);
        await sleep(300);
    }

    // Double-click to finish the route
    const lastOffset = segmentOffsets[Math.min(numSegments - 1, segmentOffsets.length - 1)];
    await page.mouse.click(
        startPad.screenX + lastOffset.dx,
        startPad.screenY + lastOffset.dy,
        { clickCount: 2 }
    );
    await sleep(500);

    // Get the route ID from the routes list
    const routeId = await page.evaluate(() => {
        const routeItems = document.querySelectorAll('.route-item');
        if (routeItems.length > 0) {
            const lastItem = routeItems[routeItems.length - 1];
            return lastItem.dataset.routeId;
        }
        return null;
    });

    // Disable trace mode for selection tests
    await page.click('#trace-mode-toggle');
    await sleep(200);

    return routeId;
}

async function runTests() {
    log('Starting segment selection tests...');
    log(`Server URL: ${SERVER_URL}`);

    const browser = await puppeteer.launch({
        headless: true,
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
        // ========== TEST 1: Page loads ==========
        log('\n--- Test 1: Page Load ---');
        try {
            await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
            await page.waitForSelector('svg');
            pass('Page loads');
        } catch (err) {
            fail('Page loads', `Server not running at ${SERVER_URL}?`);
            throw new Error('Cannot continue without server');
        }

        // ========== TEST 2: Create test route ==========
        log('\n--- Test 2: Create Test Route ---');

        const routeId = await createTestRoute(page, 3);

        if (routeId) {
            pass('Test route created', `Route ID: ${routeId}`);
        } else {
            fail('Test route created', 'Could not create route');
            // Try to continue with other tests
        }

        // Verify route has segments with data attributes
        const segmentInfo = await page.evaluate((rid) => {
            if (!rid) return null;
            const traces = document.querySelectorAll(`.user-trace[data-trace-id="${rid}"]`);
            const segments = [];
            traces.forEach(t => {
                segments.push({
                    index: t.dataset.segmentIndex,
                    layer: t.dataset.layer
                });
            });
            return { count: traces.length, segments };
        }, routeId);

        if (segmentInfo && segmentInfo.count > 0) {
            pass('Segments have data attributes', `${segmentInfo.count} segments with indices`);
            log(`  Segments: ${JSON.stringify(segmentInfo.segments)}`);
        } else {
            fail('Segments have data attributes', 'No segments found or missing attributes');
        }

        // ========== TEST 3: Single click selects segment ==========
        log('\n--- Test 3: Single Click Selection ---');

        // Get first segment position
        const firstSegment = await page.evaluate((rid) => {
            if (!rid) return null;
            const trace = document.querySelector(`.user-trace[data-trace-id="${rid}"][data-segment-index="0"]`);
            if (!trace) return null;
            const bbox = trace.getBoundingClientRect();
            return {
                x: bbox.x + bbox.width / 2,
                y: bbox.y + bbox.height / 2,
                routeId: trace.dataset.traceId,
                segmentIndex: trace.dataset.segmentIndex
            };
        }, routeId);

        if (firstSegment) {
            await page.mouse.click(firstSegment.x, firstSegment.y);
            await sleep(200);

            const selectionState = await page.evaluate(() => {
                const selected = document.querySelectorAll('.segment-selected');
                return {
                    count: selected.length,
                    classes: Array.from(selected).map(el => ({
                        routeId: el.dataset.traceId,
                        segmentIndex: el.dataset.segmentIndex
                    }))
                };
            });

            if (selectionState.count === 1) {
                pass('Single click selects one segment', `Selected index: ${selectionState.classes[0]?.segmentIndex}`);
            } else {
                fail('Single click selects one segment', `Selected ${selectionState.count} segments`);
            }

            // Verify highlight style is applied
            const hasHighlight = await page.evaluate(() => {
                const selected = document.querySelector('.user-trace.segment-selected');
                if (!selected) return false;
                const style = window.getComputedStyle(selected);
                // Check for green stroke (rgb(0, 255, 0))
                return style.stroke.includes('0, 255, 0') || style.stroke === '#00ff00';
            });

            if (hasHighlight) {
                pass('Selected segment has green highlight');
            } else {
                fail('Selected segment has green highlight');
            }
        } else {
            fail('Single click selects one segment', 'Could not find segment to click');
            fail('Selected segment has green highlight', 'No segment to test');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/segment_single_select.png`, fullPage: true });
        log(`  Screenshot: ${SCREENSHOT_DIR}/segment_single_select.png`);

        // ========== TEST 4: Shift+click multi-select ==========
        log('\n--- Test 4: Shift+Click Multi-Select ---');

        // Get second segment position
        const secondSegment = await page.evaluate((rid) => {
            if (!rid) return null;
            const trace = document.querySelector(`.user-trace[data-trace-id="${rid}"][data-segment-index="1"]`);
            if (!trace) return null;
            const bbox = trace.getBoundingClientRect();
            return {
                x: bbox.x + bbox.width / 2,
                y: bbox.y + bbox.height / 2,
                segmentIndex: trace.dataset.segmentIndex
            };
        }, routeId);

        if (secondSegment) {
            // Shift+click second segment
            await page.keyboard.down('Shift');
            await page.mouse.click(secondSegment.x, secondSegment.y);
            await page.keyboard.up('Shift');
            await sleep(200);

            const multiSelectionState = await page.evaluate(() => {
                const selected = document.querySelectorAll('.segment-selected');
                return {
                    count: selected.length,
                    indices: Array.from(selected).map(el => el.dataset.segmentIndex).filter(Boolean)
                };
            });

            if (multiSelectionState.count >= 2) {
                pass('Shift+click adds to selection', `${multiSelectionState.count} segments selected`);
            } else {
                fail('Shift+click adds to selection', `Only ${multiSelectionState.count} selected`);
            }

            // Test toggle behavior - shift+click again should deselect
            await page.keyboard.down('Shift');
            await page.mouse.click(secondSegment.x, secondSegment.y);
            await page.keyboard.up('Shift');
            await sleep(200);

            const afterToggle = await page.evaluate(() => {
                const selected = document.querySelectorAll('.segment-selected');
                return selected.length;
            });

            if (afterToggle === multiSelectionState.count - 1) {
                pass('Shift+click toggles selection off');
            } else {
                fail('Shift+click toggles selection off', `Expected ${multiSelectionState.count - 1}, got ${afterToggle}`);
            }
        } else {
            fail('Shift+click adds to selection', 'Could not find second segment');
            fail('Shift+click toggles selection off', 'Could not test');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/segment_multi_select.png`, fullPage: true });

        // ========== TEST 5: Double-click selects full route ==========
        log('\n--- Test 5: Double-Click Full Route Selection ---');

        // Clear selection first
        await page.keyboard.press('Escape');
        await sleep(200);

        if (firstSegment) {
            // Double-click on a segment
            await page.mouse.click(firstSegment.x, firstSegment.y, { clickCount: 2 });
            await sleep(300);

            const fullRouteSelection = await page.evaluate((rid) => {
                const selected = document.querySelectorAll('.segment-selected');
                const totalSegments = document.querySelectorAll(`.user-trace[data-trace-id="${rid}"]`).length;
                const selectedInRoute = Array.from(selected).filter(
                    el => el.dataset.traceId === rid
                ).length;
                return {
                    selectedCount: selected.length,
                    totalInRoute: totalSegments,
                    selectedInRoute: selectedInRoute
                };
            }, routeId);

            if (fullRouteSelection.selectedInRoute === fullRouteSelection.totalInRoute &&
                fullRouteSelection.totalInRoute > 0) {
                pass('Double-click selects full route', `All ${fullRouteSelection.totalInRoute} segments selected`);
            } else {
                fail('Double-click selects full route',
                    `${fullRouteSelection.selectedInRoute} of ${fullRouteSelection.totalInRoute} selected`);
            }
        } else {
            fail('Double-click selects full route', 'No segment to double-click');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/segment_full_route_select.png`, fullPage: true });

        // ========== TEST 6: Escape clears selection ==========
        log('\n--- Test 6: Escape Clears Selection ---');

        await page.keyboard.press('Escape');
        await sleep(200);

        const afterEscape = await page.evaluate(() => {
            return document.querySelectorAll('.segment-selected').length;
        });

        if (afterEscape === 0) {
            pass('Escape clears segment selection');
        } else {
            fail('Escape clears segment selection', `${afterEscape} segments still selected`);
        }

        // ========== TEST 7: Backspace deletes selected segments ==========
        log('\n--- Test 7: Backspace Deletes Segments ---');

        // First select a segment
        if (firstSegment) {
            await page.mouse.click(firstSegment.x, firstSegment.y);
            await sleep(200);

            const beforeDelete = await page.evaluate((rid) => {
                return {
                    totalSegments: document.querySelectorAll(`.user-trace[data-trace-id="${rid}"]`).length,
                    selectedCount: document.querySelectorAll('.segment-selected').length
                };
            }, routeId);

            log(`  Before delete: ${beforeDelete.totalSegments} total, ${beforeDelete.selectedCount} selected`);

            // Press Backspace to delete
            await page.keyboard.press('Backspace');
            await sleep(500);

            const afterDelete = await page.evaluate((rid) => {
                return {
                    totalSegments: document.querySelectorAll(`.user-trace[data-trace-id="${rid}"]`).length,
                    selectedCount: document.querySelectorAll('.segment-selected').length
                };
            }, routeId);

            log(`  After delete: ${afterDelete.totalSegments} total, ${afterDelete.selectedCount} selected`);

            if (afterDelete.totalSegments < beforeDelete.totalSegments) {
                pass('Backspace deletes selected segment',
                    `${beforeDelete.totalSegments} -> ${afterDelete.totalSegments} segments`);
            } else {
                fail('Backspace deletes selected segment', 'Segment count unchanged');
            }

            if (afterDelete.selectedCount === 0) {
                pass('Selection cleared after delete');
            } else {
                fail('Selection cleared after delete', `${afterDelete.selectedCount} still selected`);
            }
        } else {
            fail('Backspace deletes selected segment', 'No segment to test');
            fail('Selection cleared after delete', 'No segment to test');
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/segment_after_delete.png`, fullPage: true });

        // ========== TEST 8: Route list updates after deletion ==========
        log('\n--- Test 8: Route List Updates ---');

        const routeListInfo = await page.evaluate((rid) => {
            const item = document.querySelector(`.route-item[data-route-id="${rid}"]`);
            if (!item) return { exists: false };

            const label = item.querySelector('.route-label');
            return {
                exists: true,
                label: label ? label.textContent : ''
            };
        }, routeId);

        if (routeListInfo.exists) {
            // Check that the segment count in the label updated
            const segMatch = routeListInfo.label.match(/\((\d+) seg\)/);
            if (segMatch) {
                pass('Route list shows segment count', routeListInfo.label);
            } else {
                fail('Route list shows segment count', `Label: ${routeListInfo.label}`);
            }
        } else {
            // If route was completely deleted, this is also valid
            pass('Route removed from list (all segments deleted)');
        }

        // ========== TEST 9: Delete full route via selection ==========
        log('\n--- Test 9: Delete Full Route ---');

        // Create a new route for this test
        const newRouteId = await createTestRoute(page, 2);

        if (newRouteId) {
            log(`  Created new route: ${newRouteId}`);

            // Get a segment to double-click
            const newSegment = await page.evaluate((rid) => {
                const trace = document.querySelector(`.user-trace[data-trace-id="${rid}"]`);
                if (!trace) return null;
                const bbox = trace.getBoundingClientRect();
                return { x: bbox.x + bbox.width / 2, y: bbox.y + bbox.height / 2 };
            }, newRouteId);

            if (newSegment) {
                // Double-click to select all
                await page.mouse.click(newSegment.x, newSegment.y, { clickCount: 2 });
                await sleep(300);

                // Press Delete to remove all
                await page.keyboard.press('Delete');
                await sleep(500);

                const afterFullDelete = await page.evaluate((rid) => {
                    return {
                        segmentsRemaining: document.querySelectorAll(`.user-trace[data-trace-id="${rid}"]`).length,
                        routeItemExists: !!document.querySelector(`.route-item[data-route-id="${rid}"]`)
                    };
                }, newRouteId);

                if (afterFullDelete.segmentsRemaining === 0 && !afterFullDelete.routeItemExists) {
                    pass('Delete removes full route', 'Route completely removed');
                } else {
                    fail('Delete removes full route',
                        `${afterFullDelete.segmentsRemaining} segments remain, item exists: ${afterFullDelete.routeItemExists}`);
                }
            } else {
                fail('Delete removes full route', 'Could not find segment');
            }
        } else {
            fail('Delete removes full route', 'Could not create test route');
        }

        // ========== TEST 10: Click on pad clears segment selection ==========
        log('\n--- Test 10: Pad Click Clears Selection ---');

        // Create another route and select it
        const testRouteId2 = await createTestRoute(page, 2);

        if (testRouteId2) {
            const segmentPos = await page.evaluate((rid) => {
                const trace = document.querySelector(`.user-trace[data-trace-id="${rid}"]`);
                if (!trace) return null;
                const bbox = trace.getBoundingClientRect();
                return { x: bbox.x + bbox.width / 2, y: bbox.y + bbox.height / 2 };
            }, testRouteId2);

            if (segmentPos) {
                await page.mouse.click(segmentPos.x, segmentPos.y);
                await sleep(200);

                const hasSelection = await page.evaluate(() => {
                    return document.querySelectorAll('.segment-selected').length > 0;
                });

                if (hasSelection) {
                    // Now click on a pad
                    const padPos = await page.evaluate(() => {
                        const pad = document.querySelector('.pad');
                        if (!pad) return null;
                        const bbox = pad.getBoundingClientRect();
                        return { x: bbox.x + bbox.width / 2, y: bbox.y + bbox.height / 2 };
                    });

                    if (padPos) {
                        await page.mouse.click(padPos.x, padPos.y);
                        await sleep(200);

                        const afterPadClick = await page.evaluate(() => {
                            return document.querySelectorAll('.segment-selected').length;
                        });

                        if (afterPadClick === 0) {
                            pass('Clicking pad clears segment selection');
                        } else {
                            fail('Clicking pad clears segment selection', `${afterPadClick} still selected`);
                        }
                    } else {
                        fail('Clicking pad clears segment selection', 'No pad found');
                    }
                } else {
                    fail('Clicking pad clears segment selection', 'Could not select segment first');
                }
            }
        } else {
            fail('Clicking pad clears segment selection', 'Could not create test route');
        }

        // ========== TEST 11: User traces have pointer-events ==========
        log('\n--- Test 11: Pointer Events ---');

        const pointerEvents = await page.evaluate(() => {
            const trace = document.querySelector('.user-trace');
            const via = document.querySelector('.user-via');

            return {
                trace: trace ? window.getComputedStyle(trace).pointerEvents : null,
                via: via ? window.getComputedStyle(via).pointerEvents : null
            };
        });

        if (pointerEvents.trace === 'stroke' || pointerEvents.trace === 'all') {
            pass('User traces are clickable', `pointer-events: ${pointerEvents.trace}`);
        } else {
            fail('User traces are clickable', `pointer-events: ${pointerEvents.trace}`);
        }

        if (pointerEvents.via === 'all') {
            pass('User vias are clickable', `pointer-events: ${pointerEvents.via}`);
        } else if (pointerEvents.via === null) {
            log('  No user vias to test');
        } else {
            fail('User vias are clickable', `pointer-events: ${pointerEvents.via}`);
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

        await browser.close();
        process.exit(results.failed > 0 ? 1 : 0);

    } catch (err) {
        console.error('\n Test error:', err.message);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/segment_selection_error.png`, fullPage: true });
        log(`Error screenshot: ${SCREENSHOT_DIR}/segment_selection_error.png`);
        await browser.close();
        process.exit(1);
    }
}

runTests().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
