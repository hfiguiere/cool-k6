import http from 'k6/http';
import { sleep } from 'k6';
import { Trend } from 'k6/metrics';

import { getWopiClientUrl, getWopiSrc } from '../lib/wopi_discovery.js';
import { CoolClientWs } from '../lib/cool_client_ws.js';

export const options = {
  iterations: 1,
};

const frameLoadingTime = new Trend('frame_loading_time', true);

// The default exported function is gonna be picked up by k6 as the
// entry point for the test script. It will be executed repeatedly in
// "iterations" for the whole duration of the test.
export default async function () {
    let wopiUrl = __ENV['WOPI_URL'] || 'https://localhost:9980/';
    let wopiHost = __ENV['WOPI_HOST'] || 'https://localhost:3000/';

    let wopiClient = await getWopiClientUrl(wopiUrl);
    let wopiSrc = getWopiSrc(wopiHost, 2);

    let wopiClientUrl = new URL(wopiClient);
    wopiClientUrl.searchParams.set("WOPISrc", wopiSrc);

    // Get the Collabora Online iframe.
    console.log(`loading iframe ${wopiClient}?WOPISrc=${encodeURIComponent(wopiSrc)}`);
    let request = http.get(http.url`${wopiClient}?WOPISrc=${encodeURIComponent(wopiSrc)}`);

    frameLoadingTime.add(request.timings.waiting);

    // Sleep for 1 second to simulate real-world usage
    sleep(1);

    // connect the websocket.

    let client = new CoolClientWs(wopiClient, wopiSrc, () => {
        console.log("ready");
        client.openDocument(wopiSrc);

        // Perform some changes
        const changes = [
            'textinput id=0 text=H',
            'textinput id=0 text=e',
            'textinput id=0 text=l',
            'textinput id=0 text=l',
            'textinput id=0 text=o',
            'key type=input char=32 key=0',
            'textinput id=0 text=w',
            'textinput id=0 text=o',
            'textinput id=0 text=r',
            'textinput id=0 text=l',
            'textinput id=0 text=d',
            'key type=input char=33 key=0'
        ];
        changes.forEach(change => {
            client.send(change);
        });
        sleep(1);
        client.close();
    });
}
