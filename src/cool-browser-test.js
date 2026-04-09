/**
 * This simple test loads a document in Collabora Online in the
 * browser
 */

import http from 'k6/http';
import { browser } from 'k6/browser';
import { sleep, check, fail } from 'k6';
import { Trend } from 'k6/metrics';

import { checkWopi, getWopiClientUrl, getWopiSrc } from '../lib/wopi_discovery.js';
import { screenshotPage, setWopiClientAndFile, startCool, watchPostMessages, waitForMessage } from '../lib/test_utils.js';
import { wopiHost, wopiUrl } from './config.js';

export const options = {
    insecureSkipTLSVerify: true,
    scenarios: {
        ui: {
            executor: 'shared-iterations',
            vus: 1,
            iterations: 1,
            options: {
                browser: {
                    type: 'chromium',
                },
            },
        },
    },
};

const browserOptions = {
    ignoreHTTPSErrors: true,
}

// Time to go to the page. From initial request.
const pageLoadingTime = new Trend('page_loading_time', true);
// Time to load the UI. From initial request.
const frameLoadingTime = new Trend('frame_loading_time', true);

export function setup() {
    checkWopi(wopiHost, wopiUrl);
}

export default async function () {
    let context = await browser.newContext(browserOptions);
    const page = await context.newPage();
    try {
        page.on('console', (msg) => {
            let text = msg.text();
            if (text.startsWith("DEBUG")) {
                console.log(`page log: ${msg.type()} - ${text}`);
            }
        });

        let start = Date.now();
        frameLoadingTime.add(0);
        pageLoadingTime.add(0);
        await page.goto(wopiHost);
        pageLoadingTime.add(Date.now() - start);

        await setWopiClientAndFile(page, wopiUrl.toString(), 2);
        await watchPostMessages(page, [ "App_LoadingStatus" ]);
        await startCool(page);

        await screenshotPage(page);

        let ready = false;
        do {
            let message = await waitForMessage(page, "App_LoadingStatus");
            console.log(`message2: ${JSON.stringify(message)}`);
            if (message) {
                ready = (message.Values.Status == "Frame_Ready");
            }
        } while (!ready);
        check(ready, {
            "Got Frame Ready": ready => ready
        });
        frameLoadingTime.add(Date.now() - start);
    } catch (error) {
        await screenshotPage(page);
        fail(`Browser iteration failed: ${error}`);
    } finally {
        await page.close();
    }

    sleep(1);
}
