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

/// Set the WOPI client
export async function setWopiClientAndFile(page, clientUrl, fileId) {
    let server = page.locator('#collabora-online-server');
    let value = await server.inputValue();
    await server.fill(clientUrl, { timeout: 1000 });
    value = await server.inputValue();

    let file = page.locator('#wopi-file-id');
    value = await file.inputValue();
    await file.fill(fileId, { timeout: 1000 });
}

/// Start COOL when run in the frame. `setWopiClientAndFile` need to
/// have been called.
export async function startCool(page) {
    let button = await page.locator('#load-button');
    await button.click();
}

/// Send a PostMessage `msg` to the window (no embedding).
export function postMessageWindow(page, msg) {
    return page.evaluate(function(msg) {
        window.postMessage(JSON.stringify(msg), '*');
    }, msg);
}

/// Send a PostMessage `msg` to the COOL frame that has the id `collabora-online`.
export function postMessageFrame(page, msg) {
    return page.evaluate(function(msg) {
        let frame = document.querySelector('#collabora-online-viewer');
        frame.postMessage(JSON.stringify(msg), '*');
    }, msg);
}


/// Watch for a list a postmessages
export function watchPostMessages(page, messages) {
    console.log(`DEBUG watch message, ${typeof messages}`);
    if (!Array.isArray(messages)) {
        console.log("DEBUG watch message, not an array");
        messages = [ messages ];
    }
    return page.evaluate(function(messages) {
        if (typeof window._k6cool == "undefined" || window._k6cool == null) {
            window._k6cool = {};
        }
        window._k6cool.messages = [];
        window.addEventListener("message", function(event) {
            let msg;
            try {
                msg = JSON.parse(event.data);
                if (!msg) {
                    console.log("DEBUG error decoding message");
                    return;
                }
            } catch (error) {
                console.error(error);
                return;
            }

            if (messages.includes(msg.MessageId)) {
                window._k6cool.messages.push(msg);
            }
        });
    }, messages);
}

/// Wait for the message `msgid`.
export async function waitForMessage(page, msgid) {
    let result = null;
    do {
        result = await page.evaluate(msgid => {
            const idx = window._k6cool.messages.findIndex(message => message.MessageId == msgid);
            if (idx >= 0) {
                let message = window._k6cool.messages[idx];
                window._k6cool.messages.splice(idx, 1);
                return message;
            }
            return null;
        }, msgid)
    } while(result == null);
    return result;
}


/// Get the first postmessage with id `msgid`.
export function getPostMessage(page, msgid) {
    return page.evaluate(function(msgid) {
        let idx = window._k6cool.messages.findIndex(message => message.MessageId == msgid);
        if (idx >= 0) {
            let message = window._k6cool.messages[idx];
            window._k6cool.messages.splice(idx, 1);
            return message;
        }
        return null;
    }, msgid);
}
