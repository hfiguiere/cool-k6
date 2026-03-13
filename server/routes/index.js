import express from 'express';
import http from 'http';
import https from 'https';
import {DOMParser as Dom} from '@xmldom/xmldom';
import * as fs from 'node:fs/promises';

import xpath from 'xpath';

import files from './static_files.json' with { type: 'json' };

let router = express.Router();
export default router;

router.get('/', (req, res) => {
    res.render('index');
});

router.get('/static/:fileName', async (req, res) => {
    // serve static files.
    let fileName = req.params.fileName;
    if (fileName && typeof files[fileName] !== "undefined") {
        let file = files[fileName];
        if (file?.path) {
            let stats = await fs.stat(file.path);

            if (file?.type) {
                res.set('Content-Type', file.type);
            }

            let fileContent = await fs.readFile(file.path);
            res.send(fileContent);
            return;
        }
    }

    let err = `File ${fileName} not found.`;
    res.status(404).send(err);
    console.log(err);
});

router.get('/collaboraUrl', (req, res) => {
    let collaboraOnlineHost = req.query.server;
    let httpClient = collaboraOnlineHost.startsWith('https') ? https : http;
    let data = '';
    let request = httpClient.get(collaboraOnlineHost + '/hosting/discovery', (response) => {
        response.on('data', (chunk) => data += chunk.toString());
        response.on('end', () => {
            if (response.statusCode !== 200) {
                let err = 'Request failed. Satus Code: ' + response.statusCode;
                response.resume();
                res.status(response.statusCode).send(err);
                console.log(err)
                return;
            }
            if (!response.complete) {
                let err = 'No able to retrieve the discovery.xml file from the Collabora Online server with the submitted address.';
                res.status(404).send(err);
                console.log(err);
                return;
            }
            let doc = new Dom().parseFromString(data);
            if (!doc) {
                let err = 'The retrieved discovery.xml file is not a valid XML file'
                res.status(404).send(err)
                console.log(err);
                return;
            }
            let mimeType = 'text/plain';
            let nodes = xpath.select("/wopi-discovery/net-zone/app[@name='" + mimeType + "']/action", doc);
            if (!nodes || nodes.length < 1) {
                let err = 'The requested mime type is not handled'
                res.status(404).send(err);
                console.log(err);
                return;
            }
            let onlineUrl = nodes[0].getAttribute('urlsrc');
            res.json({
                url: onlineUrl,
                token: 'test'
            });
        });
        response.on('error', (err) => {
            res.status(404).send('Request error: ' + err);
            console.log('Request error: ' + err.message);
        });
    }).on('error', err => {
        res.status(404).send('Request error: ' + err);
    });
});
