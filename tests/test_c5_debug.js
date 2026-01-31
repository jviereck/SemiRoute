/**
 * Detailed debug test for C5 pad 1 routing issues.
 */
const puppeteer = require('puppeteer');

const SERVER_URL = 'http://localhost:8000';
const C5_PAD1 = { x: 138.75, y: 99.55 };

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTest() {
    console.log('=== C5 Pad 1 Debug Test ===\n');

    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Capture all console messages
    page.on('console', msg => console.log('[BROWSER]', msg.text()));

    // Capture all network requests/responses for /api/route
    page.on('requestfinished', async request => {
        if (request.url().includes('/api/route')) {
            const response = request.response();
            try {
                const body = await response.json();
                console.log('[API ROUTE]', JSON.stringify(body));
            } catch (e) {}
        }
    });

    try {
        console.log('Loading page...');
        await page.goto(SERVER_URL, { waitUntil: 'networkidle0', timeout: 10000 });
        await page.waitForSelector('svg', { timeout: 5000 });

        // Get viewport info
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

        function svgToScreen(svgX, svgY) {
            const scaleX = viewInfo.screenW / viewInfo.vbW;
            const scaleY = viewInfo.screenH / viewInfo.vbH;
            return {
                x: viewInfo.screenX + (svgX - viewInfo.vbX) * scaleX,
                y: viewInfo.screenY + (svgY - viewInfo.vbY) * scaleY
            };
        }

        // Check if C5 pad is visible
        const padVisible = await page.evaluate(() => {
            const pad = document.getElementById('pad-C5_1');
            if (!pad) return { error: 'pad not found' };
            const rect = pad.getBoundingClientRect();
            return {
                visible: rect.width > 0 && rect.height > 0,
                inViewport: rect.top >= 0 && rect.left >= 0 &&
                           rect.bottom <= window.innerHeight &&
                           rect.right <= window.innerWidth,
                rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height }
            };
        });
        console.log('\nC5 pad visibility:', JSON.stringify(padVisible, null, 2));

        // Enable trace mode
        console.log('\nEnabling trace mode...');
        await page.click('#trace-mode-toggle');
        await sleep(500);

        // Check what element is at C5 position
        const c5Screen = svgToScreen(C5_PAD1.x, C5_PAD1.y);
        console.log(`\nC5 screen position: (${c5Screen.x.toFixed(1)}, ${c5Screen.y.toFixed(1)})`);

        const elementAtC5 = await page.evaluate((x, y) => {
            const elements = document.elementsFromPoint(x, y);
            return elements.slice(0, 5).map(e => ({
                tag: e.tagName,
                id: e.id,
                class: e.className,
                dataset: { ...e.dataset }
            }));
        }, c5Screen.x, c5Screen.y);
        console.log('Elements at C5 position:', JSON.stringify(elementAtC5, null, 2));

        // Click on C5
        console.log('\nClicking on C5 pad...');
        await page.mouse.click(c5Screen.x, c5Screen.y);
        await sleep(500);

        // Check routing session state
        const sessionState = await page.evaluate(() => {
            const statusEl = document.getElementById('trace-status');
            const startMarker = document.querySelector('.start-marker');
            return {
                status: statusEl?.textContent,
                statusClass: statusEl?.className,
                hasStartMarker: !!startMarker,
                startMarkerPos: startMarker ? {
                    cx: startMarker.getAttribute('cx'),
                    cy: startMarker.getAttribute('cy')
                } : null
            };
        });
        console.log('After click:', JSON.stringify(sessionState, null, 2));

        if (!sessionState.hasStartMarker) {
            console.log('\n*** NO START MARKER - Click did not start routing! ***');

            // Try clicking directly on the pad element
            console.log('\nTrying to click pad element directly...');
            await page.click('#pad-C5_1');
            await sleep(500);

            const retryState = await page.evaluate(() => {
                const startMarker = document.querySelector('.start-marker');
                return { hasStartMarker: !!startMarker };
            });
            console.log('After direct click:', retryState);
        }

        // Move mouse and check for route
        const endScreen = svgToScreen(C5_PAD1.x + 2, C5_PAD1.y);
        console.log(`\nMoving to: (${endScreen.x.toFixed(1)}, ${endScreen.y.toFixed(1)})`);
        await page.mouse.move(endScreen.x, endScreen.y);

        // Wait longer and check multiple times
        for (let i = 0; i < 10; i++) {
            await sleep(300);
            const traceState = await page.evaluate(() => {
                const pending = document.querySelector('.pending-trace');
                const statusEl = document.getElementById('trace-status');
                return {
                    hasPending: !!pending,
                    pathData: pending?.getAttribute('d'),
                    status: statusEl?.textContent,
                    statusClass: statusEl?.className
                };
            });
            console.log(`Check ${i + 1}:`, JSON.stringify(traceState));
            if (traceState.hasPending) break;
        }

        console.log('\n=== Test complete ===');

    } catch (err) {
        console.error('Error:', err);
    } finally {
        await browser.close();
    }
}

runTest();
