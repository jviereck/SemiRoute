/**
 * Test zoom centering and highlight sizing.
 */
const puppeteer = require('puppeteer');

(async () => {
    const browser = await puppeteer.launch({ headless: false, args: ['--window-size=1400,900'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });
    await page.goto('http://localhost:8000', { waitUntil: 'networkidle0' });
    await page.waitForSelector('svg .pad');

    console.log('=== Testing Zoom and Highlight ===\n');

    // Get a pad's position
    const padInfo = await page.evaluate(() => {
        const pad = document.getElementById('pad-C5_1');
        const bbox = pad.getBoundingClientRect();
        return {
            id: pad.id,
            centerX: bbox.x + bbox.width / 2,
            centerY: bbox.y + bbox.height / 2,
            width: bbox.width,
            height: bbox.height
        };
    });
    console.log('Initial pad C5_1 position:', padInfo);

    // Take screenshot before zoom
    await page.screenshot({ path: '/tmp/pcb_zoom_before.png' });
    console.log('Screenshot: /tmp/pcb_zoom_before.png');

    // Zoom in at the pad position
    console.log('\nZooming in at pad position...');
    for (let i = 0; i < 5; i++) {
        await page.mouse.move(padInfo.centerX, padInfo.centerY);
        await page.mouse.wheel({ deltaY: -100 });
        await new Promise(r => setTimeout(r, 100));
    }

    // Get pad position after zoom
    const afterZoom = await page.evaluate(() => {
        const pad = document.getElementById('pad-C5_1');
        const bbox = pad.getBoundingClientRect();
        const container = document.getElementById('svg-container').getBoundingClientRect();
        return {
            centerX: bbox.x + bbox.width / 2,
            centerY: bbox.y + bbox.height / 2,
            width: bbox.width,
            height: bbox.height,
            // Check if pad is still roughly centered where we zoomed
            containerCenterX: container.x + container.width / 2,
            containerCenterY: container.y + container.height / 2
        };
    });
    console.log('After zoom pad position:', afterZoom);

    // Check if the pad stayed near where we were zooming (cursor position)
    const driftX = Math.abs(afterZoom.centerX - padInfo.centerX);
    const driftY = Math.abs(afterZoom.centerY - padInfo.centerY);
    console.log(`Zoom drift: X=${driftX.toFixed(1)}px, Y=${driftY.toFixed(1)}px`);

    if (driftX < 50 && driftY < 50) {
        console.log('✓ Zoom centering is working - pad stayed near cursor');
    } else {
        console.log('✗ Zoom centering may not be working - pad drifted significantly');
    }

    await page.screenshot({ path: '/tmp/pcb_zoom_after.png' });
    console.log('Screenshot: /tmp/pcb_zoom_after.png');

    // Test highlighting
    console.log('\n--- Testing Highlight Size ---');

    // Get pad size before highlight
    const beforeHighlight = await page.evaluate(() => {
        const pad = document.getElementById('pad-C5_1');
        const bbox = pad.getBoundingClientRect();
        return { width: bbox.width, height: bbox.height };
    });
    console.log('Pad size before highlight:', beforeHighlight);

    // Click to highlight
    const currentPos = await page.evaluate(() => {
        const pad = document.getElementById('pad-C5_1');
        const bbox = pad.getBoundingClientRect();
        return { x: bbox.x + bbox.width / 2, y: bbox.y + bbox.height / 2 };
    });
    await page.mouse.click(currentPos.x, currentPos.y);
    await new Promise(r => setTimeout(r, 300));

    // Get pad size after highlight
    const afterHighlight = await page.evaluate(() => {
        const pad = document.getElementById('pad-C5_1');
        const bbox = pad.getBoundingClientRect();
        const style = window.getComputedStyle(pad);
        return {
            width: bbox.width,
            height: bbox.height,
            fill: style.fill,
            stroke: style.stroke,
            strokeWidth: style.strokeWidth
        };
    });
    console.log('Pad size after highlight:', afterHighlight);

    const widthDiff = Math.abs(afterHighlight.width - beforeHighlight.width);
    const heightDiff = Math.abs(afterHighlight.height - beforeHighlight.height);
    console.log(`Size difference: width=${widthDiff.toFixed(2)}px, height=${heightDiff.toFixed(2)}px`);

    if (widthDiff < 1 && heightDiff < 1) {
        console.log('✓ Highlight does not change pad size');
    } else {
        console.log('✗ Highlight is changing pad size');
    }

    await page.screenshot({ path: '/tmp/pcb_highlight.png' });
    console.log('Screenshot: /tmp/pcb_highlight.png');

    console.log('\nTest complete. Browser staying open for inspection.');
    console.log('Press Ctrl+C to close.');

    await new Promise(() => {});
})();
