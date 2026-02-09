import http from 'k6/http';
import exec from 'k6/execution';
import { browser } from 'k6/browser';
import { sleep, check, fail } from 'k6';

import { getWopiClientUrl, getWopiSrc } from '../lib/wopi_discovery.js';

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

export function setup() {

    let res = http.get(wopiUrl.toString());
    if (res.status !== 200) {
        exec.test.abort(`Got unexpected status code ${res.status} when trying to setup. Exiting.`);
    }
}

export default async function () {
    let wopiClient = await getWopiClientUrl(wopiUrl);
    let wopiSrc = getWopiSrc(wopiHost, 1);

    let wopiClientUrl = new URL(wopiClient);
    wopiClientUrl.searchParams.set("WOPISrc", wopiSrc);

    let context = await browser.newContext(browserOptions);
    const page = await context.newPage();
    try {
        await page.goto(wopiClientUrl.toString());

        const locator = page.locator('ul#main-menu');
        await locator.waitFor({state: 'visible'});
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
