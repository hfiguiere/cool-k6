
import { screenshotDir } from '../src/config.js';

/// Screenshot the page for debugging purpose
/// Will save the PNG in the set directory `screenshotDir`.
export function screenshotPage(page) {
    let now = new Date();
    page.screenshot({
        fullPage: true,
        path: `${screenshotDir}/screenshot-${now.toISOString()}.png`,
    });
}

/// Send a PostMessage `msg` to the window (no embedding).
export function postMessageWindow(page, msg) {
    return page.evaluate(function(msg) {
        window.postMessage(JSON.stringify(msg), '*');
    }, msg);
}
