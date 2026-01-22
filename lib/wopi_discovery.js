import http from 'http';
import https from 'https';
import {DOMParser as Dom} from '@xmldom/xmldom';
import xpath from 'xpath';

// get the wopi client URL for the wopiUrl.
// This use WOPI discovery.
// XXX allow passing a mime or extension
export function getWopiClientUrl(wopiUrl) {
    let collaboraOnlineHost = wopiUrl;
    let httpClient = collaboraOnlineHost.startsWith('https') ? https : http;
    let data = '';

    return new Promise((resolve, reject) => {
        httpClient.get(collaboraOnlineHost + '/hosting/discovery', (response) => {
            response.on('data', (chunk) => data += chunk.toString());
            response.on('end', () => {
                if (response.statusCode !== 200) {
                    let err = 'Request failed. Satus Code: ' + response.statusCode;
                    response.resume();
                    reject(err);
                    return;
                }
                if (!response.complete) {
                    let err = 'No able to retrieve the discovery.xml file from the Collabora Online server with the submitted address.';
                    reject(err);
                    return;
                }
                let doc = new Dom().parseFromString(data);
                if (!doc) {
                    let err = 'The retrieved discovery.xml file is not a valid XML file';
                    reject(err);
                    return;
                }
                let mimeType = 'text/plain';
                let nodes = xpath.select("/wopi-discovery/net-zone/app[@name='" + mimeType + "']/action", doc);
                if (!nodes || nodes.length < 1) {
                    let err = 'The requested mime type is not handled'
                    reject(err);
                    return;
                }
                let onlineUrl = nodes[0].getAttribute('urlsrc');
                resolve({
                    url: onlineUrl,
                });
            });
            response.on('error', (err) => {
                reject('Request error: ' + err);
            });
        });
    });
}
