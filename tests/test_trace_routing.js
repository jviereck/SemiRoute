/**
 * Unit test for trace routing: click on pad, route to another point.
 * Tests that routing works and paths use 45° angle increments.
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config');

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTest() {
    console.log('=== Trace Routing Unit Test ===\n');

    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Capture console for debugging
    const logs = [];
    page.on('console', msg => logs.push(msg.text()));

    try {
        // Step 1: Load page
        console.log('Step 1: Loading page...');
        await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
        await page.waitForSelector('svg', { timeout: 5000 });
        console.log('  ✓ Page loaded');

        // Step 2: Get viewport info for coordinate conversion
        console.log('\nStep 2: Getting viewport info...');
        const viewInfo = await page.evaluate(() => {
            const svg = document.querySelector('svg');
            const vb = svg.getAttribute('viewBox').split(' ').map(Number);
            const rect = svg.getBoundingClientRect();
            return {
                vbX: vb[0], vbY: vb[1], vbW: vb[2], vbH: vb[3],
                screenW: rect.width, screenH: rect.height,
                screenX: rect.x, screenY: rect.y
            };
        });

        // Helper to convert SVG coords to screen coords
        function svgToScreen(svgX, svgY) {
            const scaleX = viewInfo.screenW / viewInfo.vbW;
            const scaleY = viewInfo.screenH / viewInfo.vbH;
            return {
                x: viewInfo.screenX + (svgX - viewInfo.vbX) * scaleX,
                y: viewInfo.screenY + (svgY - viewInfo.vbY) * scaleY
            };
        }
        console.log('  ✓ Viewport info obtained');

        // Step 3: Double-click start point to begin routing (known clear area)
        console.log('\nStep 3: Double-clicking start point...');
        const startSvg = { x: 135, y: 55 };
        const start = svgToScreen(startSvg.x, startSvg.y);
        console.log(`  SVG coords: (${startSvg.x}, ${startSvg.y})`);
        console.log(`  Screen coords: (${start.x.toFixed(1)}, ${start.y.toFixed(1)})`);

        await page.mouse.click(start.x, start.y, { clickCount: 2 });
        await sleep(500);

        const startMarker = await page.evaluate(() => !!document.querySelector('.start-marker'));
        if (!startMarker) throw new Error('Start marker not found');
        console.log('  ✓ Start marker appeared');

        // Step 4: Click end point to trigger routing
        console.log('\nStep 4: Clicking end point to route...');
        const endSvg = { x: 145, y: 60 };
        const end = svgToScreen(endSvg.x, endSvg.y);
        console.log(`  SVG coords: (${endSvg.x}, ${endSvg.y})`);
        console.log(`  Screen coords: (${end.x.toFixed(1)}, ${end.y.toFixed(1)})`);

        await page.mouse.click(end.x, end.y);

        // Wait for routing to complete
        let result;
        for (let i = 0; i < 30; i++) {
            await sleep(200);
            result = await page.evaluate(() => ({
                status: document.getElementById('trace-status')?.textContent,
                statusClass: document.getElementById('trace-status')?.className,
                hasPending: !!document.querySelector('.pending-trace'),
                pathData: document.querySelector('.pending-trace')?.getAttribute('d')
            }));
            if (result.statusClass === 'success' || result.statusClass === 'error') break;
        }

        console.log(`  Status: "${result.status}" (${result.statusClass})`);

        if (!result.hasPending) {
            console.log('\n  Console logs:');
            logs.forEach(l => console.log('    ' + l));
            throw new Error('No pending trace created');
        }
        console.log('  ✓ Pending trace created');
        console.log(`  Path: ${result.pathData}`);

        // Step 5: Verify 45-degree angles
        console.log('\nStep 5: Verifying 45° angle constraint...');
        const pathMatches = result.pathData.match(/[ML]\s*[\d.-]+,[\d.-]+/g);
        if (!pathMatches || pathMatches.length < 2) {
            throw new Error('Invalid path data');
        }

        const points = pathMatches.map(p => {
            const coords = p.substring(1).trim().split(',');
            return { x: parseFloat(coords[0]), y: parseFloat(coords[1]) };
        });

        let allAnglesValid = true;
        for (let i = 0; i < points.length - 1; i++) {
            const dx = points[i + 1].x - points[i].x;
            const dy = points[i + 1].y - points[i].y;

            if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) continue;

            const angle = Math.atan2(dy, dx) * 180 / Math.PI;
            const normalized = ((angle % 360) + 360) % 360;
            const remainder = normalized % 45;

            if (remainder > 1 && remainder < 44) {
                console.log(`  ✗ Invalid angle: ${normalized.toFixed(1)}°`);
                allAnglesValid = false;
            }
        }

        if (!allAnglesValid) throw new Error('Path has invalid angles');
        console.log('  ✓ All path segments use 45° angle increments');

        // Step 6: Confirm the trace
        console.log('\nStep 6: Confirming trace...');
        await page.click('#trace-confirm');
        await sleep(300);

        const afterConfirm = await page.evaluate(() => ({
            hasUserTrace: !!document.querySelector('.user-trace'),
            hasPendingTrace: !!document.querySelector('.pending-trace'),
            hasStartMarker: !!document.querySelector('.start-marker')
        }));

        if (!afterConfirm.hasUserTrace) throw new Error('User trace not created after confirm');
        if (afterConfirm.hasPendingTrace) throw new Error('Pending trace not cleared after confirm');
        if (afterConfirm.hasStartMarker) throw new Error('Start marker not cleared after confirm');

        console.log('  ✓ Trace confirmed and added to user traces');
        console.log('  ✓ Pending elements cleared');

        console.log('\n=== ALL TESTS PASSED ===');
        await browser.close();
        process.exit(0);

    } catch (err) {
        console.error('\n❌ TEST FAILED:', err.message);
        console.log('\nConsole logs:');
        logs.slice(-20).forEach(l => console.log('  ' + l));
        await browser.close();
        process.exit(1);
    }
}

runTest().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
