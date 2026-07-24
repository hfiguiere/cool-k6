import { WebSocket } from 'k6/websockets';
import { check, sleep } from 'k6';

export class CoolClientWs {
    socket;

    /**
     * wopiClient: The URL of the WOPI client (the iframe src)
     * wopiSrc: the WOPI Source
     */
    constructor(wopiClient, wopiSrc, onopen) {
        const wssUrl = new URL('/', `${wopiClient}`);
        // Match the websocket scheme to the client scheme.
        wssUrl.protocol = wssUrl.protocol === "https:" ? "wss:" : "ws:";
        wssUrl.pathname = `cool/${encodeURIComponent(wopiSrc)}/ws`;
        wssUrl.searchParams.set('WOPISrc', wopiSrc)
        wssUrl.searchParams.set('compat', '/ws')

        let start = Date.now();
        this.socket = new WebSocket(wssUrl, null, {
            headers: {
                Origin: `${wopiClient}`
            }
        });
        console.log(`Socket URL: ${this.socket.url}`);
        if (typeof onopen == "function") {
            this.socket.onopen = onopen;
        } else {
            this.socket.onopen = () => {
                console.log("WebSocket: open");
            }
        }
        this.socket.onclose = event => {
            console.log(`WebSocket: close`);
        };
        this.socket.onerror = e => {
            console.error(`WebSocket error: ${e.error}`);
        };
        console.log("Done setup");
    }

    openDocument(wopiSrc) {
        this.send(`load url=${wopiSrc} accessibilityState=false` +
                  ' deviceFormFactor=desktop darkTheme=false timezone=America/Montreal');
    }

    send(data) {
        const open = this.socket.readyState === 1;
        check(open, {
            'WebSocket is open': v => v,
        });
        // A closing or closed socket throws InvalidStateError on send; skip
        // quietly so a late timer tick cannot abort the whole iteration.
        if (!open) {
            return;
        }
        return this.socket.send(data);
    }

    close() {
        this.socket.close();
    }
}
