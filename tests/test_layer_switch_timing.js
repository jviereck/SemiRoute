/**
 * Test to investigate layer switching delay.
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config');

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTest() {
    console.log('Starting layer switch timing test...');

    const browser = await puppeteer.launch({
        headless: false,
        devtools: true,
        args: ['--window-size=1400,900']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Enable console logging from the page
    page.on('console', msg => {
        console.log(`[PAGE] ${msg.text()}`);
    });

    try {
        await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
        console.log('Page loaded');

        // Enable trace mode
        await page.click('#trace-mode-toggle');
        await sleep(300);
        console.log('Trace mode enabled');

        // Find a pad to click
        const startPad = await page.evaluate(() => {
            const pads = document.querySelectorAll('.pad');
            for (const pad of pads) {
                if (parseInt(pad.dataset.net, 10) > 0) {
                    const bbox = pad.getBoundingClientRect();
                    return {
                        screenX: bbox.x + bbox.width / 2,
                        screenY: bbox.y + bbox.height / 2,
                        padId: pad.id,
                        netId: pad.dataset.net
                    };
                }
            }
            return null;
        });

        if (!startPad) {
            console.log('No pad found');
            return;
        }

        console.log(`Clicking pad ${startPad.padId} at (${startPad.screenX}, ${startPad.screenY})`);
        await page.mouse.click(startPad.screenX, startPad.screenY);
        await sleep(500);

        // Move mouse to trigger routing
        const targetX = startPad.screenX + 50;
        const targetY = startPad.screenY + 30;
        console.log(`Moving mouse to (${targetX}, ${targetY})`);
        await page.mouse.move(targetX, targetY);
        await sleep(500);

        // Check current state
        const beforeSwitch = await page.evaluate(() => {
            const state = window.getRoutingState ? window.getRoutingState() : null;
            return {
                layer: document.getElementById('trace-layer').value,
                hasState: !!state,
                appMode: state?.appMode,
                hasSession: !!state?.routingSession,
                isRouting: state?.isRouting,
                hasPendingPath: !!(state?.routingSession?.pendingPath),
                cursorPoint: state?.routingSession?.cursorPoint
            };
        });
        console.log('Before switch:', beforeSwitch);

        // Add timing instrumentation to the page
        await page.evaluate(() => {
            window.originalHandleLayerSwitch = window.handleLayerSwitch;
            window.layerSwitchTimings = [];
        });

        // Time the layer switch
        console.log('\n--- Pressing "2" to switch to B.Cu ---');
        const startTime = Date.now();

        await page.keyboard.press('2');

        // Wait for the switch to complete
        await page.waitForFunction(() => {
            const layer = document.getElementById('trace-layer').value;
            return layer === 'B.Cu';
        }, { timeout: 10000 }).catch(() => {
            console.log('Layer did not switch to B.Cu within timeout');
        });

        const endTime = Date.now();
        console.log(`Layer switch took: ${endTime - startTime}ms`);

        // Check final state
        const afterSwitch = await page.evaluate(() => {
            return {
                layer: document.getElementById('trace-layer').value,
                viaCount: document.querySelectorAll('.user-via').length
            };
        });
        console.log('After switch:', afterSwitch);

        // Now let's test the API directly
        console.log('\n--- Testing /api/check-via directly ---');
        const apiTiming = await page.evaluate(async () => {
            const start = performance.now();
            const response = await fetch('/api/check-via', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    x: 140.0,
                    y: 70.0,
                    size: 0.8,
                    drill: 0.4,
                    net_id: 1
                })
            });
            const data = await response.json();
            const end = performance.now();
            return {
                duration: end - start,
                valid: data.valid,
                message: data.message
            };
        });
        console.log(`Via check API took: ${apiTiming.duration.toFixed(2)}ms, valid: ${apiTiming.valid}`);

        // Test routing API timing
        console.log('\n--- Testing /api/route directly ---');
        const routeTiming = await page.evaluate(async () => {
            const start = performance.now();
            const response = await fetch('/api/route', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_x: 140.0,
                    start_y: 70.0,
                    end_x: 145.0,
                    end_y: 75.0,
                    layer: 'F.Cu',
                    width: 0.25
                })
            });
            const data = await response.json();
            const end = performance.now();
            return {
                duration: end - start,
                success: data.success,
                pathLength: data.path ? data.path.length : 0
            };
        });
        console.log(`Route API took: ${routeTiming.duration.toFixed(2)}ms, success: ${routeTiming.success}`);

        console.log('\nTest complete. Browser left open for inspection.');
        console.log('Press Ctrl+C to close.');

        // Keep browser open
        await new Promise(() => {});

    } catch (err) {
        console.error('Test error:', err);
        await browser.close();
        process.exit(1);
    }
}

runTest();
