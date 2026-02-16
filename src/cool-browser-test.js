import http from 'k6/http';
import exec from 'k6/execution';
import { browser } from 'k6/browser';
import { sleep, check, fail } from 'k6';

import { getWopiClientUrl, getWopiSrc } from '../lib/wopi_discovery.js';
import { Trend } from 'k6/metrics';

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

let wopiUrl = new URL(__ENV['WOPI_URL'] ? __ENV['WOPI_URL'] : 'https://localhost:9980/');
let wopiHost = new URL(__ENV['WOPI_HOST'] ? __ENV['WOPI_HOST'] : 'https://localhost:3000/');
// Time to go to the page. From initial request.
const pageLoadingTime = new Trend('page_loading_time', true);
// Time to load the UI. From initial request.
const frameLoadingTime = new Trend('frame_loading_time', true);

export function setup() {

    let res = http.get(wopiUrl.toString());
    if (res.status !== 200) {
        exec.test.abort(`Got unexpected status code ${res.status} when trying to setup. Exiting.`);
    }
}

export default async function () {
    let wopiClient = await getWopiClientUrl(wopiUrl);
    let wopiSrc = getWopiSrc(wopiHost, 2);

    let wopiClientUrl = new URL(wopiClient);
    wopiClientUrl.searchParams.set("WOPISrc", wopiSrc);

    let context = await browser.newContext(browserOptions);
    const page = await context.newPage();
    try {
        let start = Date.now();
        frameLoadingTime.add(0);
        pageLoadingTime.add(0);
        let resp = await page.goto(wopiClientUrl.toString());
        pageLoadingTime.add(Date.now() - start);

        const locator = page.locator('ul#main-menu');
        await locator.waitFor({state: 'visible'});
        frameLoadingTime.add(Date.now() - start);
        let content = await locator.textContent();
        check(content, {
            "Menu is visible": content => content.startsWith('File'),
        });
    } catch (error) {
        fail(`Browser iteration failed: ${error}`);
    } finally {
        await page.close();
    }

    sleep(1);
}
