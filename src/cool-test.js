import http from 'k6/http';
import { sleep } from 'k6';

import { getWopiClientUrl, getWopiSrc } from '../lib/wopi_discovery.js';

export const options = {
  iterations: 10,
};

// The default exported function is gonna be picked up by k6 as the
// entry point for the test script. It will be executed repeatedly in
// "iterations" for the whole duration of the test.
export default async function () {
    let wopiUrl = __ENV['WOPI_URL'] || 'https://localhost:9980/';
    let wopiHost = __ENV['WOPI_HOST'] || 'https://localhost:3000/';

    let wopiClient = await getWopiClientUrl(wopiUrl);
    let wopiSrc = getWopiSrc(wopiClient);

    // Get the Collabora Online iframe.
    // XXX this is wrong.
    http.get(http.url`${wopiClient.url}?WOPISrc=${encodeURIComponent(wopiSrc)}`);

    // Sleep for 1 second to simulate real-world usage
    sleep(1);
}
