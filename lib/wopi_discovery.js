import http from 'k6/http';
import {DOMParser as Dom} from '@xmldom/xmldom';
import xpath from 'xpath';

// get the wopi client URL for the wopiUrl.
// This use WOPI discovery.
// XXX allow passing a mime or extension
export function getWopiClientUrl(wopiUrl) {
    let collaboraOnlineHost = wopiUrl;
    let data = '';

    return new Promise((resolve, reject) => {
        let response = http.get(collaboraOnlineHost + '/hosting/discovery');
        if (response.status !== 200) {
            let err = 'Request failed. Satus Code: ' + response.status;
            reject(err);
            return;
        }
        let data = response.body;
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
}

export function getWopiSrc(wopiHost, fileId) {
    return `${wopiHost}/wopi/files/${fileId}`;
}
