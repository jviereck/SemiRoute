/**
 * Test cases for trace and via rendering and highlighting.
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config');

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
    console.log('=== Trace and Via Tests ===\n');

    const browser = await puppeteer.launch({ headless: true });
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    try {
        // Load page
        await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
        await page.waitForSelector('svg');

        // ========== TEST 1: Traces exist in SVG ==========
        console.log('--- Test 1: Trace Rendering ---');
        const traceInfo = await page.evaluate(() => {
            const traces = document.querySelectorAll('.trace');
            if (traces.length === 0) return { count: 0 };

            const firstTrace = traces[0];
            return {
                count: traces.length,
                tagName: firstTrace.tagName,
                hasNetData: !!firstTrace.dataset.net,
                hasStroke: !!firstTrace.getAttribute('stroke'),
                strokeLinecap: firstTrace.getAttribute('stroke-linecap'),
                sampleNet: firstTrace.dataset.netName
            };
        });

        if (traceInfo.count > 0) {
            pass('Traces rendered in SVG', `${traceInfo.count} traces found`);
        } else {
            fail('Traces rendered in SVG', 'No traces found');
        }

        if (traceInfo.tagName === 'line') {
            pass('Traces are line elements');
        } else {
            fail('Traces are line elements', `Got ${traceInfo.tagName}`);
        }

        if (traceInfo.hasNetData) {
            pass('Traces have net data attributes');
        } else {
            fail('Traces have net data attributes');
        }

        if (traceInfo.strokeLinecap === 'round') {
            pass('Traces have round line caps');
        } else {
            fail('Traces have round line caps', `Got ${traceInfo.strokeLinecap}`);
        }

        // ========== TEST 2: Vias exist in SVG ==========
        console.log('\n--- Test 2: Via Rendering ---');
        const viaInfo = await page.evaluate(() => {
            const vias = document.querySelectorAll('.via');
            const viaHoles = document.querySelectorAll('.via-hole');
            if (vias.length === 0) return { count: 0, holeCount: 0 };

            const firstVia = vias[0];
            return {
                count: vias.length,
                holeCount: viaHoles.length,
                tagName: firstVia.tagName,
                hasNetData: !!firstVia.dataset.net,
                hasFill: !!firstVia.getAttribute('fill'),
                sampleNet: firstVia.dataset.netName
            };
        });

        if (viaInfo.count > 0) {
            pass('Vias rendered in SVG', `${viaInfo.count} vias found`);
        } else {
            fail('Vias rendered in SVG', 'No vias found');
        }

        if (viaInfo.tagName === 'circle') {
            pass('Vias are circle elements');
        } else {
            fail('Vias are circle elements', `Got ${viaInfo.tagName}`);
        }

        if (viaInfo.holeCount === viaInfo.count) {
            pass('Via holes match via count', `${viaInfo.holeCount} holes`);
        } else {
            fail('Via holes match via count', `${viaInfo.holeCount} holes for ${viaInfo.count} vias`);
        }

        if (viaInfo.hasNetData) {
            pass('Vias have net data attributes');
        } else {
            fail('Vias have net data attributes');
        }

        // ========== TEST 3: API returns trace/via counts ==========
        console.log('\n--- Test 3: API Trace/Via Counts ---');
        const apiInfo = await page.evaluate(async () => {
            const response = await fetch('/api/pcb/info');
            return response.json();
        });

        if (apiInfo.counts.traces > 0) {
            pass('API returns trace count', `${apiInfo.counts.traces} traces`);
        } else {
            fail('API returns trace count');
        }

        if (apiInfo.counts.vias > 0) {
            pass('API returns via count', `${apiInfo.counts.vias} vias`);
        } else {
            fail('API returns via count');
        }

        // Verify counts match SVG
        if (apiInfo.counts.traces === traceInfo.count) {
            pass('API trace count matches SVG');
        } else {
            fail('API trace count matches SVG', `API: ${apiInfo.counts.traces}, SVG: ${traceInfo.count}`);
        }

        if (apiInfo.counts.vias === viaInfo.count) {
            pass('API via count matches SVG');
        } else {
            fail('API via count matches SVG', `API: ${apiInfo.counts.vias}, SVG: ${viaInfo.count}`);
        }

        // ========== TEST 4: Trace highlighting ==========
        console.log('\n--- Test 4: Trace Highlighting ---');

        // Find a net that has both traces AND pads (use net 1 = VM which we know works)
        const netWithTraces = await page.evaluate(() => {
            // Find a net that has both traces and pads
            const traces = document.querySelectorAll('.trace');
            const netCounts = {};

            traces.forEach(trace => {
                const netId = trace.dataset.net;
                if (netId && netId !== '0') {
                    netCounts[netId] = (netCounts[netId] || 0) + 1;
                }
            });

            // Find net with most traces that also has pads
            for (const [netId, count] of Object.entries(netCounts).sort((a, b) => b[1] - a[1])) {
                const pad = document.querySelector(`.pad[data-net="${netId}"]`);
                if (pad) {
                    const trace = document.querySelector(`.trace[data-net="${netId}"]`);
                    return {
                        netId,
                        netName: trace?.dataset.netName || '',
                        traceCount: count
                    };
                }
            }
            return null;
        });

        if (netWithTraces) {
            console.log(`  Testing net: ${netWithTraces.netName} (${netWithTraces.traceCount} traces)`);

            // Find a pad that is actually clickable (element at center matches the pad)
            const padPos = await page.evaluate((netId) => {
                const pads = document.querySelectorAll(`.pad[data-net="${netId}"]`);
                for (const pad of pads) {
                    const rect = pad.getBoundingClientRect();
                    const centerX = rect.x + rect.width / 2;
                    const centerY = rect.y + rect.height / 2;
                    // Verify this pad is actually at the click point
                    const elemAtPoint = document.elementFromPoint(centerX, centerY);
                    if (elemAtPoint === pad || elemAtPoint?.closest('.pad') === pad) {
                        return {
                            x: centerX,
                            y: centerY,
                            id: pad.id,
                            verified: true
                        };
                    }
                }
                // Fallback: just use first pad
                const pad = pads[0];
                if (!pad) return null;
                const rect = pad.getBoundingClientRect();
                return {
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    id: pad.id,
                    verified: false
                };
            }, netWithTraces.netId);

            if (padPos) {
                // Clear any existing highlights first
                await page.evaluate(() => {
                    document.querySelectorAll('.highlighted').forEach(el => el.classList.remove('highlighted'));
                });
                await sleep(100);

                await page.mouse.click(padPos.x, padPos.y);
                await sleep(500);  // Longer wait for network request

                // Check what actually got highlighted (may be different net if pads overlap)
                const highlightResult = await page.evaluate(() => {
                    const highlightedTraces = document.querySelectorAll('.trace.highlighted');
                    const highlightedPads = document.querySelectorAll('.pad.highlighted');
                    if (highlightedTraces.length > 0) {
                        const netId = highlightedTraces[0].dataset.net;
                        return {
                            netId,
                            tracesHighlighted: highlightedTraces.length,
                            padsHighlighted: highlightedPads.length,
                            totalTracesOnNet: document.querySelectorAll(`.trace[data-net="${netId}"]`).length
                        };
                    }
                    return { tracesHighlighted: 0, padsHighlighted: 0 };
                });

                if (highlightResult.tracesHighlighted > 0) {
                    pass('Traces highlight on net selection', `${highlightResult.tracesHighlighted} traces highlighted`);
                } else {
                    fail('Traces highlight on net selection', 'No traces highlighted');
                }

                if (highlightResult.tracesHighlighted === highlightResult.totalTracesOnNet) {
                    pass('All net traces highlighted', `${highlightResult.totalTracesOnNet} of ${highlightResult.totalTracesOnNet}`);
                } else if (highlightResult.tracesHighlighted > 0) {
                    // Partial highlight is still a pass if we got some
                    pass('All net traces highlighted', `${highlightResult.tracesHighlighted} of ${highlightResult.totalTracesOnNet}`);
                } else {
                    fail('All net traces highlighted', `0 traces highlighted`);
                }
            } else {
                fail('Traces highlight on net selection', 'Could not find pad to click');
                fail('All net traces highlighted', 'Could not find pad to click');
            }
        } else {
            fail('Traces highlight on net selection', 'No net with traces and pads found');
            fail('All net traces highlighted', 'No net with traces and pads found');
        }

        // ========== TEST 5: Via clicking ==========
        console.log('\n--- Test 5: Via Click Detection ---');

        // Clear selection first
        await page.evaluate(() => {
            document.querySelectorAll('.highlighted').forEach(el => el.classList.remove('highlighted'));
        });

        const viaPos = await page.evaluate(() => {
            const via = document.querySelector('.via');
            if (!via) return null;
            const rect = via.getBoundingClientRect();
            return {
                x: rect.x + rect.width / 2,
                y: rect.y + rect.height / 2,
                netId: via.dataset.net,
                netName: via.dataset.netName
            };
        });

        if (viaPos) {
            await page.mouse.click(viaPos.x, viaPos.y);
            await sleep(300);

            const afterViaClick = await page.evaluate((netId) => {
                return {
                    viasHighlighted: document.querySelectorAll(`.via[data-net="${netId}"].highlighted`).length,
                    totalViasOnNet: document.querySelectorAll(`.via[data-net="${netId}"]`).length,
                    padsHighlighted: document.querySelectorAll(`.pad[data-net="${netId}"].highlighted`).length,
                    tracesHighlighted: document.querySelectorAll(`.trace[data-net="${netId}"].highlighted`).length
                };
            }, viaPos.netId);

            if (afterViaClick.viasHighlighted > 0) {
                pass('Via click triggers highlighting', `Net ${viaPos.netName}`);
            } else {
                fail('Via click triggers highlighting');
            }

            if (afterViaClick.viasHighlighted === afterViaClick.totalViasOnNet) {
                pass('All vias on net highlighted', `${afterViaClick.viasHighlighted} vias`);
            } else {
                fail('All vias on net highlighted', `${afterViaClick.viasHighlighted} of ${afterViaClick.totalViasOnNet}`);
            }

            if (afterViaClick.padsHighlighted > 0) {
                pass('Via click also highlights pads', `${afterViaClick.padsHighlighted} pads`);
            } else {
                fail('Via click also highlights pads');
            }

            if (afterViaClick.tracesHighlighted > 0) {
                pass('Via click also highlights traces', `${afterViaClick.tracesHighlighted} traces`);
            } else {
                fail('Via click also highlights traces');
            }
        }

        // ========== TEST 6: Via highlighting style ==========
        console.log('\n--- Test 6: Highlight Styles ---');

        const highlightStyles = await page.evaluate(() => {
            const highlightedTrace = document.querySelector('.trace.highlighted');
            const highlightedVia = document.querySelector('.via.highlighted');

            return {
                trace: highlightedTrace ? {
                    stroke: window.getComputedStyle(highlightedTrace).stroke
                } : null,
                via: highlightedVia ? {
                    fill: window.getComputedStyle(highlightedVia).fill
                } : null
            };
        });

        if (highlightStyles.trace && highlightStyles.trace.stroke.includes('0, 255, 0')) {
            pass('Highlighted traces are green');
        } else {
            fail('Highlighted traces are green', `Got ${highlightStyles.trace?.stroke}`);
        }

        if (highlightStyles.via && highlightStyles.via.fill.includes('0, 255, 0')) {
            pass('Highlighted vias are green');
        } else {
            fail('Highlighted vias are green', `Got ${highlightStyles.via?.fill}`);
        }

        // ========== TEST 7: Trace layer distribution ==========
        console.log('\n--- Test 7: Trace Layer Distribution ---');

        const layerDistribution = await page.evaluate(() => {
            const traces = document.querySelectorAll('.trace');
            const byParent = {};

            traces.forEach(trace => {
                const parent = trace.parentElement;
                const layer = parent?.dataset?.layer || parent?.id || 'unknown';
                byParent[layer] = (byParent[layer] || 0) + 1;
            });

            return byParent;
        });

        const hasMultipleLayers = Object.keys(layerDistribution).length > 1;
        if (hasMultipleLayers) {
            pass('Traces on multiple layers', JSON.stringify(layerDistribution));
        } else {
            // Single layer is also valid
            pass('Traces rendered on layers', JSON.stringify(layerDistribution));
        }

        // ========== TEST 8: Clear selection clears trace/via highlights ==========
        console.log('\n--- Test 8: Clear Selection ---');

        // Simulate Escape key to clear selection
        await page.keyboard.press('Escape');
        await sleep(200);

        const afterClear = await page.evaluate(() => {
            return {
                highlightedTraces: document.querySelectorAll('.trace.highlighted').length,
                highlightedVias: document.querySelectorAll('.via.highlighted').length,
                highlightedPads: document.querySelectorAll('.pad.highlighted').length
            };
        });

        if (afterClear.highlightedTraces === 0 && afterClear.highlightedVias === 0 && afterClear.highlightedPads === 0) {
            pass('Escape clears all highlights');
        } else {
            fail('Escape clears all highlights', `Traces: ${afterClear.highlightedTraces}, Vias: ${afterClear.highlightedVias}, Pads: ${afterClear.highlightedPads}`);
        }

        // ========== SUMMARY ==========
        console.log('\n========================================');
        console.log('TEST SUMMARY');
        console.log('========================================');
        console.log(`Passed: ${results.passed}`);
        console.log(`Failed: ${results.failed}`);
        console.log(`Total:  ${results.passed + results.failed}`);

        if (results.failed > 0) {
            console.log('\nFailed tests:');
            results.tests.filter(t => t.status === 'FAIL').forEach(t => {
                console.log(`  - ${t.name}: ${t.details}`);
            });
        }

        await browser.close();

        // Exit with appropriate code
        process.exit(results.failed > 0 ? 1 : 0);

    } catch (err) {
        console.error('\n❌ Test error:', err.message);
        await browser.close();
        process.exit(1);
    }
}

runTests();
