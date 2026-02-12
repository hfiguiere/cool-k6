import express from 'express';
import * as fs from 'node:fs/promises';
import path from 'node:path';

let router = express.Router();
export default router;

import files from './files.json' with { type: 'json' };

/* *
 *  wopi CheckFileInfo endpoint
 *
 *  Returns info about the file with the given document id.
 *  The response has to be in JSON format and at a minimum it needs to include
 *  the file name and the file size.
 *  The CheckFileInfo wopi endpoint is triggered by a GET request at
 *  https://HOSTNAME/wopi/files/<document_id>
 */
router.get('/files/:fileId', async (req, res) => {
    console.log('file id: ' + req.params.fileId);
    let fileEntry = files[req.params.fileId];
    if (fileEntry?.path) {
        let filename = fileEntry.path;
        let stats = await fs.stat(filename);

	res.json({
	    BaseFileName: path.basename(filename),
	    Size: stats.size,
	    UserId: 1,
	    UserCanWrite: !fileEntry.readonly,
	    EnableInsertRemoteImage: true,
	});

        return;
    }
    console.log(`file ${req.params.fileId} not found`);
    // test.txt is just a fake text file
    // the Size property is the length of the string
    // returned by the wopi GetFile endpoint
    res.json({
	BaseFileName: 'test.txt',
	Size: 11,
	UserId: 1,
	UserCanWrite: true,
	EnableInsertRemoteImage: true,
    });
});

/* *
 *  wopi GetFile endpoint
 *
 *  Given a request access token and a document id, sends back the contents of the file.
 *  The GetFile wopi endpoint is triggered by a request with a GET verb at
 *  https://HOSTNAME/wopi/files/<document_id>/contents
 */
router.get('/files/:fileId/contents', async (req, res) => {
    let fileEntry = files[req.params.fileId];
    if (fileEntry?.path) {
        let filename = fileEntry.path;

        let fileContent = await fs.readFile(filename);
        res.send(fileContent);
        return;
    }

    // we just return the content of a fake text file
    // in a real case you should use the file id
    // for retrieving the file from the storage and
    // send back the file content as response
    const fileContent = 'Hello world!';
    res.send(fileContent);
});

/* *
 *  wopi PutFile endpoint
 *
 *  Given a request access token and a document id, replaces the files with the POST request body.
 *  The PutFile wopi endpoint is triggered by a request with a POST verb at
 *  https://HOSTNAME/wopi/files/<document_id>/contents
 */
router.post('/files/:fileId/contents', (req, res) => {
	// we log to the console so that is possible
	// to check that saving has triggered this wopi endpoint
	console.log('wopi PutFile endpoint');
	if (req.body) {
		console.dir(req.body);
		console.log(req.body.toString());
		res.sendStatus(200);
	} else {
		console.log('Not possible to get the file content.');
		res.sendStatus(404);
	}
});
