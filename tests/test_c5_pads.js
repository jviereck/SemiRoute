/**
 * Test clicking specifically on C5 pads.
 */
const puppeteer = require('puppeteer');
const { SERVER_URL } = require('./config');

(async () => {
    const browser = await puppeteer.launch({ headless: true });
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });
    await page.goto(SERVER_URL, { waitUntil: 'networkidle0' });
    await page.waitForSelector('svg .pad');

    // Check both C5 pads
    const c5Info = await page.evaluate(() => {
        const pad1 = document.getElementById('pad-C5_1');
        const pad2 = document.getElementById('pad-C5_2');

        function getPadInfo(pad, name) {
            if (!pad) return { error: name + ' not found' };
            const bbox = pad.getBoundingClientRect();
            return {
                id: pad.id,
                tagName: pad.tagName,
                netId: pad.dataset.net,
                netName: pad.dataset.netName,
                bbox: {
                    x: bbox.x,
                    y: bbox.y,
                    width: bbox.width,
                    height: bbox.height,
                    centerX: bbox.x + bbox.width / 2,
                    centerY: bbox.y + bbox.height / 2
                },
                isVisible: bbox.width > 0 && bbox.height > 0,
                pointerEvents: window.getComputedStyle(pad).pointerEvents
            };
        }

        return {
            pad1: getPadInfo(pad1, 'C5_1'),
            pad2: getPadInfo(pad2, 'C5_2')
        };
    });

    console.log('=== C5 Pad Information ===');
    console.log('\nPad C5_1:', JSON.stringify(c5Info.pad1, null, 2));
    console.log('\nPad C5_2:', JSON.stringify(c5Info.pad2, null, 2));

    // Test clicking on each pad
    const pads = [['C5_1', c5Info.pad1], ['C5_2', c5Info.pad2]];

    for (const [name, info] of pads) {
        if (info.error) {
            console.log('\n' + name + ': ' + info.error);
            continue;
        }

        // Clear highlights
        await page.evaluate(() => {
            document.querySelectorAll('.pad.highlighted').forEach(p => p.classList.remove('highlighted'));
        });

        // Check element at click point
        const clickX = info.bbox.centerX;
        const clickY = info.bbox.centerY;

        const elemAtPoint = await page.evaluate((x, y) => {
            const elem = document.elementFromPoint(x, y);
            if (!elem) return { error: 'No element' };
            const closestPad = elem.closest('.pad');
            return {
                tagName: elem.tagName,
                id: elem.id,
                isPad: elem.classList.contains('pad'),
                closestPadId: closestPad ? closestPad.id : null
            };
        }, clickX, clickY);

        console.log('\n--- Testing ' + name + ' ---');
        console.log('Click position: (' + clickX.toFixed(1) + ', ' + clickY.toFixed(1) + ')');
        console.log('Element at point: ' + elemAtPoint.tagName + '#' + (elemAtPoint.id || '(no id)'));
        console.log('Is pad: ' + elemAtPoint.isPad);
        console.log('Closest pad: ' + elemAtPoint.closestPadId);

        // Click and check
        await page.mouse.click(clickX, clickY);
        await new Promise(r => setTimeout(r, 300));

        const result = await page.evaluate((padId) => {
            const pad = document.getElementById(padId);
            const highlighted = document.querySelectorAll('.pad.highlighted');
            return {
                padHighlighted: pad ? pad.classList.contains('highlighted') : false,
                totalHighlighted: highlighted.length,
                highlightedIds: Array.from(highlighted).map(p => p.id)
            };
        }, 'pad-' + name);

        console.log('Pad highlighted after click: ' + result.padHighlighted);
        console.log('Total highlighted: ' + result.totalHighlighted);
        if (result.totalHighlighted > 0) {
            console.log('Highlighted pads: ' + result.highlightedIds.join(', '));
        }

        if (!result.padHighlighted) {
            console.log('*** CLICK FAILED FOR ' + name + ' ***');
        } else {
            console.log('✓ CLICK SUCCEEDED FOR ' + name);
        }
    }

    // Also check what's covering the pads
    console.log('\n=== Element Stack Analysis ===');
    for (const [name, info] of pads) {
        if (info.error) continue;

        const stack = await page.evaluate((x, y) => {
            const elements = document.elementsFromPoint(x, y);
            return elements.slice(0, 8).map(e => ({
                tagName: e.tagName,
                id: e.id,
                classList: Array.from(e.classList || [])
            }));
        }, info.bbox.centerX, info.bbox.centerY);

        console.log('\n' + name + ' element stack (top to bottom):');
        stack.forEach((e, i) => {
            const classes = e.classList.length > 0 ? ' [' + e.classList.join(',') + ']' : '';
            console.log('  ' + (i + 1) + '. ' + e.tagName + '#' + (e.id || '(no id)') + classes);
        });
    }

    await browser.close();
    console.log('\nTest complete.');
})();
