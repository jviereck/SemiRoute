
const puppeteer = require('puppeteer');

const { SERVER_URL } = require('./config_test.js');
const SCREENSHOT_DIR = '/tmp';

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTest() {
    console.log('Starting delete trace test...');
    const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1200, height: 800 });

    try {
        await page.goto(SERVER_URL, { waitUntil: 'networkidle0' });
        await page.waitForSelector('svg');
        console.log('Page loaded.');

        // 1. Create a new trace
        await page.click('#trace-mode-toggle');
        await page.waitForSelector('body.trace-mode-active');
        console.log('Trace mode activated.');

        // Click on a pad to ensure we have a net
        const startPadPos = await page.evaluate(() => {
            const pad = document.querySelector('.pad[data-net="1"]');
            if (!pad) return { x: 400, y: 300 };
            const bbox = pad.getBoundingClientRect();
            return { x: bbox.x + bbox.width / 2, y: bbox.y + bbox.height / 2 };
        });

        // Click to start trace
        await page.mouse.click(startPadPos.x, startPadPos.y);
        await sleep(500);

        // Click to end trace
        const endPos = { x: startPadPos.x + 50, y: startPadPos.y + 50 };
        await page.mouse.click(endPos.x, endPos.y);
        await sleep(500);

        // Double click to finish
        await page.mouse.click(endPos.x, endPos.y, { clickCount: 2 });
        await sleep(500);
        console.log('Trace created.');

        const traceExists = await page.evaluate(() => document.querySelector('.user-trace') !== null);
        if (!traceExists) {
            throw new Error('Trace was not created successfully.');
        }

        // 2. Select the trace
        // Toggle off trace mode
        await page.keyboard.press('t');
        await sleep(500);
        
        // Click on the trace
        const tracePos = { x: startPadPos.x + 25, y: startPadPos.y + 25 };
        await page.mouse.click(tracePos.x, tracePos.y);
        await sleep(500);

        const isSelected = await page.evaluate(() => document.querySelector('.segment-selected') !== null);
        if (!isSelected) {
            await page.screenshot({ path: `${SCREENSHOT_DIR}/delete_test_not_selected.png` });
            throw new Error('Trace segment was not selected.');
        }
        console.log('Trace selected.');

        // 3. Press Backspace
        await page.keyboard.press('Backspace');
        await sleep(500);
        console.log('Backspace key pressed.');

        // 4. Check that the trace is gone
        const traceDeleted = await page.evaluate(() => document.querySelector('.user-trace') === null);

        if (traceDeleted) {
            console.log('✓ PASS: Trace was deleted successfully.');
        } else {
            await page.screenshot({ path: `${SCREENSHOT_DIR}/delete_test_fail.png` });
            console.error('✗ FAIL: Trace was not deleted.');
            throw new Error('Trace deletion failed. See screenshot for details.');
        }

    } catch (error) {
        console.error('Test failed:', error.message);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/delete_test_error.png` });
        process.exit(1);
    } finally {
        await browser.close();
    }
}

runTest();
