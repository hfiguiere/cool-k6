/**
 * Large-document load and render test.
 *
 * One user opens a big mixed-content Writer document (fileId=5,
 * large-mixed-10mb.odt: ~10 MB, text, images, tables and graphs) and then
 * scrolls through it top to bottom, asking for the tiles of each screen as it
 * goes. This drives the heavy kit work we want to profile: the import filter
 * and initial layout when the document opens, then the layout and tile
 * painting of every page as it is scrolled into view.
 *
 * Why a load test rather than a typing test for profiling: the kit's cost here
 * is per document, not per keystroke, so a handful of commands (open, then a
 * paced scroll) keep the kit busy for seconds without flooding the client
 * WebSocket.
 *
 * Everything that talks to the socket is driven from event-loop timers
 * (setTimeout / setInterval), never from a blocking sleep(). In k6's
 * websockets module the socket callbacks and the VU run on one event loop; a
 * blocking sleep in onopen (or a sleep-based keep-alive in the default
 * function) stops queued frames from flushing and incoming tiles from
 * draining, so the sends pile up in the buffer and the load never reaches the
 * kit. Timers hand control back to the loop between steps, which is what lets
 * the frames flush and the replies drain.
 *
 * This speaks the same WebSocket protocol the browser client sends
 * (load, clientvisiblearea, clientzoom, tilecombine), so it reproduces the
 * browser's open-and-scroll traffic without driving a real browser.
 */

import { checkWopi, getWopiClientUrl, getWopiSrc } from '../lib/wopi_discovery.js';
import { CoolClientWs } from '../lib/cool_client_ws.js';
import { wopiHost, wopiUrl } from './config.js';

// The large fixture is fileId 5 in server/routes/files.json.
const FILE_ID = __ENV['LOAD_FILE_ID'] || 5;
// LOAD_PASSES: how many times to scroll the whole document top to bottom. One
// pass renders every page once; raise it to keep the kit on-CPU longer for a
// profiling capture.
const PASSES = Math.max(1, Number(__ENV['LOAD_PASSES'] ?? 4));

// Tile geometry at 100% zoom, matching the browser client: a 256 px tile is
// 3840 twips wide (15 twips per pixel). An A4 page is about 4 tiles across and
// a screen about 6 tiles tall.
const TILE_PX = 256;
const TILE_TWIPS = 3840;
const COLS = 4;
const ROWS = 6;
// visible width in twips
const VIEW_W = COLS * TILE_TWIPS;
// visible (screen) height in twips
const VIEW_H = ROWS * TILE_TWIPS;
// The document is about 41 pages of ~16838 twips; scroll a little past the end.
const PAGE_TWIPS = 16838;
const DOC_END = PAGE_TWIPS * 44;

// let the kit import and lay out before pulling tiles
const IMPORT_WAIT_MS = 5000;
// gap between screens, paces requests and lets tiles drain
const STEP_MS = 120;
// hold open after the last screen so its tiles arrive
const DRAIN_MS = 2500;
// force-close guard, well under the 10m maxDuration
const SAFETY_MS = 540000;

export const options = {
    insecureSkipTLSVerify: true,
    scenarios: {
        load: {
            executor: 'shared-iterations',
            vus: 1,
            iterations: 1,
            maxDuration: '10m',
        },
    },
};

export function setup() {
    checkWopi(wopiHost, wopiUrl);
}

// Ask the server for the tiles of one screen. tileposx/tileposy are parallel
// lists: the i-th tile sits at (tileposx[i], tileposy[i]) in twips, snapped to
// the tile grid so the server can cache and reuse them.
function requestScreen(client, yTop, part) {
    const xs = [];
    const ys = [];
    const yBase = Math.floor(yTop / TILE_TWIPS) * TILE_TWIPS;
    for (let c = 0; c < COLS; c++) {
        for (let r = 0; r < ROWS; r++) {
            xs.push(c * TILE_TWIPS);
            ys.push(yBase + r * TILE_TWIPS);
        }
    }
    client.send(`clientvisiblearea x=0 y=${yBase} width=${VIEW_W} height=${VIEW_H}`);
    client.send(`tilecombine nviewid=0 part=${part} width=${TILE_PX} height=${TILE_PX} `
        + `tileposx=${xs.join(',')} tileposy=${ys.join(',')} `
        + `tilewidth=${TILE_TWIPS} tileheight=${TILE_TWIPS}`);
}

export default async function () {
    const wopiClient = await getWopiClientUrl(wopiUrl);
    const wopiSrc = getWopiSrc(wopiHost, FILE_ID);
    console.log(`loading fileId=${FILE_ID}: open + ${PASSES} full-document render pass(es)`);

    // Scroll state, advanced one screen per interval tick.
    const state = { y: 0, pass: 0, timer: null, safety: null };

    const client = new CoolClientWs(wopiClient, wopiSrc, () => {
        client.openDocument(wopiSrc);
        // Mirror the browser: it fetches the font list right after load.
        client.send('commandvalues command=.uno:CharFontName');
        client.send(`clientzoom tilepixelwidth=${TILE_PX} tilepixelheight=${TILE_PX} `
            + `tiletwipwidth=${TILE_TWIPS} tiletwipheight=${TILE_TWIPS}`);
        // Start scrolling once the kit has had time to import and lay out.
        setTimeout(startScrolling, IMPORT_WAIT_MS);
    });
    // Drain incoming server traffic (tiles, cursors) so it does not pile up.
    // With the timer-driven loop below, onmessage actually runs between ticks.
    client.socket.onmessage = () => {};

    function startScrolling() {
        state.timer = setInterval(tick, STEP_MS);
    }

    function finish() {
        if (state.timer) { clearInterval(state.timer); state.timer = null; }
        if (state.safety) { clearTimeout(state.safety); state.safety = null; }
        // Let the last screen's tiles come back, then close (which ends the
        // iteration, since the open socket is what keeps the VU alive).
        setTimeout(() => client.close(), DRAIN_MS);
    }

    function tick() {
        if (client.socket.readyState !== 1) { finish(); return; }
        if (state.y >= DOC_END) {
            state.pass += 1;
            state.y = 0;
            if (state.pass >= PASSES) {
                console.log(`rendered ${PASSES} pass(es); draining and closing`);
                finish();
                return;
            }
        }
        requestScreen(client, state.y, 0);
        state.y += VIEW_H;
    }

    // Never let a wedged run hold the slot for the whole maxDuration.
    state.safety = setTimeout(() => {
        console.error('safety timeout reached; closing');
        if (state.timer) clearInterval(state.timer);
        client.close();
    }, SAFETY_MS);
}
