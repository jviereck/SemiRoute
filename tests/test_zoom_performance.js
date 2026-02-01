/**
 * Puppeteer test for zoom performance in trace mode.
 * Tests that scrolling/zooming is not laggy while routing.
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config');

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

async function runTests() {
    log('Starting zoom performance tests...');
    log(`Server URL: ${SERVER_URL}`);

    const browser = await puppeteer.launch({
        headless: true,
        args: ['--window-size=1400,900']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Collect console errors (ignore 404 errors for static resources)
    const consoleErrors = [];
    page.on('console', msg => {
        const text = msg.text();
        if (msg.type() === 'error' && !text.includes('404') && !text.includes('Failed to load resource')) {
            consoleErrors.push(text);
        }
    });

    try {
        // Load page
        log('\n--- Setup: Load page and enter trace mode ---');
        try {
            await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
            pass('Page loads');
        } catch (err) {
            fail('Page loads', `Server not running at ${SERVER_URL}?`);
            throw new Error('Cannot continue without server');
        }

        // Wait for SVG to be fully loaded
        await page.waitForSelector('#svg-container svg', { timeout: 5000 });
        await sleep(500);

        // ========== TEST 1: Zoom performance outside trace mode ==========
        log('\n--- Test 1: Baseline zoom performance (not in trace mode) ---');

        const baselinePerf = await page.evaluate(async () => {
            const container = document.getElementById('svg-container');
            const rect = container.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;

            const wheelTimes = [];
            const numWheelEvents = 20;

            for (let i = 0; i < numWheelEvents; i++) {
                const start = performance.now();

                const wheelEvent = new WheelEvent('wheel', {
                    clientX: centerX,
                    clientY: centerY,
                    deltaY: i % 2 === 0 ? 100 : -100,
                    bubbles: true,
                    cancelable: true
                });
                container.dispatchEvent(wheelEvent);

                // Wait for next frame to measure render time
                await new Promise(r => requestAnimationFrame(r));

                const elapsed = performance.now() - start;
                wheelTimes.push(elapsed);
            }

            return {
                times: wheelTimes,
                avg: wheelTimes.reduce((a, b) => a + b, 0) / wheelTimes.length,
                max: Math.max(...wheelTimes)
            };
        });

        log(`  Baseline: avg=${baselinePerf.avg.toFixed(2)}ms, max=${baselinePerf.max.toFixed(2)}ms`);

        if (baselinePerf.avg < 50) {
            pass('Baseline zoom performance', `avg ${baselinePerf.avg.toFixed(2)}ms < 50ms`);
        } else {
            fail('Baseline zoom performance', `avg ${baselinePerf.avg.toFixed(2)}ms >= 50ms`);
        }

        // ========== TEST 2: Enter trace mode and start routing ==========
        log('\n--- Test 2: Enter trace mode and start routing ---');

        // Click the trace mode toggle
        await page.click('#trace-mode-toggle');
        await sleep(200);

        const traceModeActive = await page.evaluate(() => {
            const toggle = document.getElementById('trace-mode-toggle');
            return toggle && toggle.classList.contains('active');
        });

        if (traceModeActive) {
            pass('Trace mode activated');
        } else {
            fail('Trace mode activated');
        }

        // Find a pad to click on to start routing
        const padInfo = await page.evaluate(() => {
            const pads = document.querySelectorAll('.pad[data-net]');
            if (pads.length === 0) return null;

            const pad = pads[0];
            const rect = pad.getBoundingClientRect();
            return {
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2,
                netId: pad.getAttribute('data-net')
            };
        });

        if (padInfo) {
            await page.mouse.click(padInfo.x, padInfo.y);
            await sleep(300);
            pass('Clicked on pad to start routing', `net ${padInfo.netId}`);
        } else {
            fail('Could not find pad to click');
        }

        // Move mouse to trigger routing
        const container = await page.$('#svg-container');
        const box = await container.boundingBox();
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await sleep(200);

        // ========== TEST 3: Zoom performance while routing ==========
        log('\n--- Test 3: Zoom performance while routing ---');

        const traceModePerf = await page.evaluate(async () => {
            const container = document.getElementById('svg-container');
            const rect = container.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;

            const wheelTimes = [];
            const numWheelEvents = 20;

            for (let i = 0; i < numWheelEvents; i++) {
                const start = performance.now();

                const wheelEvent = new WheelEvent('wheel', {
                    clientX: centerX,
                    clientY: centerY,
                    deltaY: i % 2 === 0 ? 100 : -100,
                    bubbles: true,
                    cancelable: true
                });
                container.dispatchEvent(wheelEvent);

                // Wait for next frame
                await new Promise(r => requestAnimationFrame(r));

                const elapsed = performance.now() - start;
                wheelTimes.push(elapsed);
            }

            return {
                times: wheelTimes,
                avg: wheelTimes.reduce((a, b) => a + b, 0) / wheelTimes.length,
                max: Math.max(...wheelTimes)
            };
        });

        log(`  Trace mode: avg=${traceModePerf.avg.toFixed(2)}ms, max=${traceModePerf.max.toFixed(2)}ms`);

        // Check absolute performance
        if (traceModePerf.avg < 50) {
            pass('Trace mode zoom performance', `avg ${traceModePerf.avg.toFixed(2)}ms < 50ms`);
        } else {
            fail('Trace mode zoom performance', `avg ${traceModePerf.avg.toFixed(2)}ms >= 50ms`);
        }

        // ========== TEST 4: Compare trace mode to baseline ==========
        log('\n--- Test 4: Compare trace mode performance to baseline ---');

        const slowdownRatio = traceModePerf.avg / baselinePerf.avg;
        log(`  Slowdown ratio: ${slowdownRatio.toFixed(2)}x`);

        if (slowdownRatio < 3.0) {
            pass('Trace mode slowdown acceptable', `${slowdownRatio.toFixed(2)}x < 3x baseline`);
        } else {
            fail('Trace mode slowdown too high', `${slowdownRatio.toFixed(2)}x >= 3x baseline`);
        }

        // ========== TEST 5: Zoom while actively routing (interleaved) ==========
        log('\n--- Test 5: Zoom while actively routing (mousemove + wheel interleaved) ---');

        const interleavedPerf = await page.evaluate(async () => {
            const container = document.getElementById('svg-container');
            const rect = container.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;

            const wheelTimes = [];
            const numIterations = 10;

            for (let i = 0; i < numIterations; i++) {
                // Move mouse to trigger routing request
                const moveEvent = new MouseEvent('mousemove', {
                    clientX: centerX + (i * 10),
                    clientY: centerY + (i * 5),
                    bubbles: true
                });
                container.dispatchEvent(moveEvent);

                // Immediately zoom (simulates user scrolling while cursor moves)
                const start = performance.now();

                const wheelEvent = new WheelEvent('wheel', {
                    clientX: centerX,
                    clientY: centerY,
                    deltaY: i % 2 === 0 ? 100 : -100,
                    bubbles: true,
                    cancelable: true
                });
                container.dispatchEvent(wheelEvent);

                // Wait for frame
                await new Promise(r => requestAnimationFrame(r));

                const elapsed = performance.now() - start;
                wheelTimes.push(elapsed);

                // Small delay to let routing requests fire
                await new Promise(r => setTimeout(r, 20));
            }

            return {
                times: wheelTimes,
                avg: wheelTimes.reduce((a, b) => a + b, 0) / wheelTimes.length,
                max: Math.max(...wheelTimes)
            };
        });

        log(`  Interleaved: avg=${interleavedPerf.avg.toFixed(2)}ms, max=${interleavedPerf.max.toFixed(2)}ms`);

        if (interleavedPerf.avg < 50) {
            pass('Interleaved zoom+move performance', `avg ${interleavedPerf.avg.toFixed(2)}ms < 50ms`);
        } else {
            fail('Interleaved zoom+move performance', `avg ${interleavedPerf.avg.toFixed(2)}ms >= 50ms`);
        }

        // ========== TEST 6: No console errors ==========
        log('\n--- Test 6: No console errors ---');
        if (consoleErrors.length === 0) {
            pass('No console errors');
        } else {
            fail('Console errors detected', consoleErrors.join('; '));
        }

    } catch (err) {
        console.error(`\nTest error: ${err.message}`);
        fail('Test execution', err.message);
    } finally {
        await browser.close();
    }

    // Print summary
    console.log('\n=== Summary ===');
    console.log(`Passed: ${results.passed}`);
    console.log(`Failed: ${results.failed}`);

    process.exit(results.failed > 0 ? 1 : 0);
}

runTests();
