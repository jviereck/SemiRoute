/**
 * Unit test for routing from C5 pad 1 (GND).
 *
 * Regression test: Previously, rotated pads used a circle approximation
 * in the obstacle map, but allowed cells used rectangular bounds. This
 * caused routes starting from rotated GND pads to fail.
 */
const puppeteer = require('puppeteer');

const { SERVER_URL } = require('./config_test.js');

// C5 pad 1 (GND) coordinates from PCB
const C5_PAD1 = { x: 138.75, y: 99.55 };

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTest() {
    console.log('=== C5 Pad 1 (GND) Routing Test ===\n');

    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Capture console and network for debugging
    const logs = [];
    const apiResponses = [];
    page.on('console', msg => logs.push(msg.text()));
    page.on('response', async response => {
        if (response.url().includes('/api/route')) {
            try {
                const json = await response.json();
                apiResponses.push({ url: response.url(), data: json });
            } catch (e) {}
        }
    });

    try {
        // Step 1: Load page
        console.log('Step 1: Loading page...');
        await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
        await page.waitForSelector('svg', { timeout: 5000 });
        console.log('  ✓ Page loaded');

        // Step 2: Get viewport info and find C5 pad
        console.log('\nStep 2: Finding C5 pad 1...');
        const padInfo = await page.evaluate(() => {
            const pad = document.getElementById('pad-C5_1');
            if (!pad) return { error: 'C5_1 pad not found' };

            const svg = document.querySelector('svg');
            const vb = svg.getAttribute('viewBox').split(' ').map(Number);
            const rect = svg.getBoundingClientRect();

            return {
                padId: pad.id,
                netId: pad.dataset.net,
                netName: pad.dataset.netName,
                dataX: parseFloat(pad.dataset.x),
                dataY: parseFloat(pad.dataset.y),
                vbX: vb[0], vbY: vb[1], vbW: vb[2], vbH: vb[3],
                screenW: rect.width, screenH: rect.height,
                screenX: rect.x, screenY: rect.y
            };
        });

        if (padInfo.error) throw new Error(padInfo.error);
        console.log(`  ✓ Found ${padInfo.padId}`);
        console.log(`  Net: ${padInfo.netName} (ID: ${padInfo.netId})`);
        console.log(`  Position: (${padInfo.dataX}, ${padInfo.dataY})`);

        // Helper to convert SVG coords to screen coords
        function svgToScreen(svgX, svgY) {
            const scaleX = padInfo.screenW / padInfo.vbW;
            const scaleY = padInfo.screenH / padInfo.vbH;
            return {
                x: padInfo.screenX + (svgX - padInfo.vbX) * scaleX,
                y: padInfo.screenY + (svgY - padInfo.vbY) * scaleY
            };
        }

        // Step 3: Enable trace mode
        console.log('\nStep 3: Enabling trace mode...');
        await page.click('#trace-mode-toggle');
        await sleep(300);

        const traceModeActive = await page.evaluate(() =>
            document.body.classList.contains('trace-mode-active')
        );
        if (!traceModeActive) throw new Error('Trace mode not activated');
        console.log('  ✓ Trace mode enabled');

        // Step 4: Click on C5 pad 1 to start routing
        console.log('\nStep 4: Clicking on C5 pad 1 to start routing...');
        const startPos = svgToScreen(C5_PAD1.x, C5_PAD1.y);
        console.log(`  SVG coords: (${C5_PAD1.x}, ${C5_PAD1.y})`);
        console.log(`  Screen coords: (${startPos.x.toFixed(1)}, ${startPos.y.toFixed(1)})`);

        await page.mouse.click(startPos.x, startPos.y);
        await sleep(500);

        const startMarker = await page.evaluate(() => !!document.querySelector('.start-marker'));
        if (!startMarker) throw new Error('Start marker not found after clicking C5 pad 1');
        console.log('  ✓ Start marker appeared');

        // Verify we picked up the GND net
        const sessionInfo = await page.evaluate(() => {
            const statusEl = document.getElementById('trace-status');
            return {
                status: statusEl?.textContent || '',
                statusClass: statusEl?.className || ''
            };
        });
        console.log(`  Status: "${sessionInfo.status}"`);

        // Step 5: Move mouse to create a route
        // Note: Route only 2mm to avoid crossing non-GND obstacles
        console.log('\nStep 5: Moving mouse to route...');
        const endPos = svgToScreen(C5_PAD1.x + 2, C5_PAD1.y);  // 2mm to the right (stays in GND region)
        console.log(`  End SVG coords: (${C5_PAD1.x + 2}, ${C5_PAD1.y})`);
        console.log(`  End screen coords: (${endPos.x.toFixed(1)}, ${endPos.y.toFixed(1)})`);

        await page.mouse.move(endPos.x, endPos.y);

        // Wait for routing to complete (check for pending trace)
        let routeResult = null;
        for (let i = 0; i < 30; i++) {
            await sleep(200);
            routeResult = await page.evaluate(() => ({
                hasPending: !!document.querySelector('.pending-trace'),
                pathData: document.querySelector('.pending-trace')?.getAttribute('d'),
                status: document.getElementById('trace-status')?.textContent,
                statusClass: document.getElementById('trace-status')?.className
            }));
            if (routeResult.hasPending || routeResult.statusClass === 'error') break;
        }

        // Check API responses
        console.log(`\n  API responses received: ${apiResponses.length}`);
        const lastResponse = apiResponses[apiResponses.length - 1];
        if (lastResponse) {
            console.log(`  Last route response: success=${lastResponse.data.success}`);
            if (!lastResponse.data.success) {
                console.log(`  Message: ${lastResponse.data.message}`);
            } else {
                console.log(`  Path points: ${lastResponse.data.path.length}`);
            }
        }

        if (!routeResult.hasPending) {
            console.log('\n  Console logs:');
            logs.slice(-10).forEach(l => console.log('    ' + l));
            throw new Error('No pending trace created - route from C5 pad 1 failed');
        }

        console.log('  ✓ Pending trace created');
        console.log(`  Path: ${routeResult.pathData}`);

        // Step 6: Verify path has valid points
        console.log('\nStep 6: Verifying path...');
        const pathMatches = routeResult.pathData.match(/[ML]\s*[\d.-]+,[\d.-]+/g);
        if (!pathMatches || pathMatches.length < 2) {
            throw new Error('Path has less than 2 points');
        }
        console.log(`  ✓ Path has ${pathMatches.length} points`);

        // Step 7: Click to commit the segment
        console.log('\nStep 7: Committing trace segment...');
        await page.mouse.click(endPos.x, endPos.y);
        await sleep(500);

        const afterCommit = await page.evaluate(() => ({
            hasUserTrace: !!document.querySelector('.user-trace'),
            startMarkerExists: !!document.querySelector('.start-marker')
        }));

        // After committing a segment, start marker should still exist (moved to new position)
        // or we should have a user trace
        console.log(`  User trace exists: ${afterCommit.hasUserTrace}`);
        console.log(`  Start marker exists: ${afterCommit.startMarkerExists}`);

        // Step 8: Double-click to finish
        console.log('\nStep 8: Double-clicking to finish...');
        const finalPos = svgToScreen(C5_PAD1.x + 2.5, C5_PAD1.y);  // Stay in GND region
        await page.mouse.move(finalPos.x, finalPos.y);
        await sleep(300);
        await page.mouse.click(finalPos.x, finalPos.y, { clickCount: 2 });
        await sleep(500);

        const afterFinish = await page.evaluate(() => ({
            hasUserTrace: !!document.querySelector('.user-trace'),
            hasPendingTrace: !!document.querySelector('.pending-trace'),
            hasStartMarker: !!document.querySelector('.start-marker'),
            userTraceCount: document.querySelectorAll('.user-trace').length
        }));

        console.log(`  User traces: ${afterFinish.userTraceCount}`);
        console.log(`  Pending trace cleared: ${!afterFinish.hasPendingTrace}`);
        console.log(`  Start marker cleared: ${!afterFinish.hasStartMarker}`);

        if (afterFinish.userTraceCount === 0) {
            throw new Error('No user trace created after finishing');
        }
        console.log('  ✓ Route from C5 pad 1 completed successfully');

        console.log('\n=== ALL TESTS PASSED ===');
        console.log('Routing from C5 pad 1 (GND) works correctly.');
        await browser.close();
        process.exit(0);

    } catch (err) {
        console.error('\n❌ TEST FAILED:', err.message);
        console.log('\nLast 15 console logs:');
        logs.slice(-15).forEach(l => console.log('  ' + l));
        console.log('\nAPI responses:');
        apiResponses.forEach(r => console.log('  ', JSON.stringify(r.data)));
        await browser.close();
        process.exit(1);
    }
}

runTest().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
