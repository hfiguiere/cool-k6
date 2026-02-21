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
        wssUrl.protocol = "wss:";
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
        check(this.socket.readyState, {
            'WebSocket is open': r => r == 1,
        });
        return this.socket.send(data);
    }

    close() {
        this.socket.close();
    }
}
