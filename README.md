# What is this?

A K6 based test suite for Collabora Online

## Adding test

Add test to the `src/` directory. Files implementing tests must end in
`-test.js`.

Build the bundles with `npm run build`. The targets are in `dist/`
ready to run. This uses webpack under the hood and the JavaScript
dialect is ES6.

## WOPI Host

A WOPI Host (server) is included in the `server` directory. It's in
pure NodeJS. `npm run server` will start it bound to port 3000.

Running the server require Node 20.10 or later.

### Configuring WOPI files

You can configure files to serve from the WOPI Host. This is done by
adding an entry to the JSON file `./server/routes/files.json`.

It's a dictionary (JS object) where the key is the file id as passed
in the WOPI source URL, and entries contain at least a `path`
(relative to the current working directory or absolute). So for
`https://WOPI_HOST/wopi/files/1` the entry is `"1"`.

There are the various fields for an entry:

- `path`: Path to the file to serve.
- `readonly`: If true the file is served in readonly mode. In absence
of the property, the file is server in editing mode.

A key with an empty object return just a "Hello world" strigs. Asking
a file with an ID that is not found in the `files.json` will return
the HTTP status 404 (not found).

Example:

```JSON
{
    "1": {
    },
    "2": {
        "path": "documents/writer-large.fodt",
        "readonly": false,
        "wopi": {
            "EnableInsertRemoteImage": true,
            "DisableInsertLocalImage": true,
            "HidePrintOption": true,
            "HideSaveOption": false
        }
    }
}
```

### Configuring static files

You can configure the server to serve static files from
`https://WOPI_HOST/static/`. This is done by adding an entry to the JSON
file `./server/routes/static_files.json`.

Static files are used for tests like "inserting an image" or any other
that would require an URL. It's like for WOPI files. The keys are the
file names. So for `https://WOPI_HOST/static/image.png`, the entry is
`"image.png"`.

Each entry need:
- `path`: Path to the file to serve.
- `type`: An optional MIME type. If missing `application/octet-stream`
  will be used.

Example:

```JSON
{
    "image.png": {
        "path": "documents/image.png",
        "type": "image/png"
    }
}
```

### Default values

By default the WOPI file server will set the following properties with
values:

- `UserId`: 1
- `UserCanWrite`: true
- `IsAdminUser`: false

## Running the tests

We default to use the Docker image for k6 since it's not carried by
most distributions. But you can adapt this to other methods.

This is currently tested with k6 version 1.5.x.

### Environment

There are two required environment variables used by the K6 tests.

- `WOPI_URL=https://<your_cool_host>:9980/`: `WOPI_URL` is set to the
WOPI client (Collabora Online) URL. `your_cool_host` is the host on
which Collabora Online is running. Remember if you run K6 in a Docker
container, it's unlikely to be localhost.

- `WOPI_HOST=https://<your_wopi_host>:3000/`: `WOPI_HOST` is set to
the WOPI host (see above). `your_wopi_host` is the host on which you
run the WOPI host started with `npm run server`. Remember if you run
K6 in a Docker container, it's unlikely to be localhost.

The test will use default values, unlikely to be what you want.

You can also optionnaly set the following:

- `COOL_K6_SCREENSHOT_DIR`: This  is set to the directory  in which to
write the screenshot  in case of failure in browser  tests. If running
K6 in Docker, then care should be taken to ensure the directory can be
written bu k6 user from inside docker. `k6-wrap` takes care of it.

### Running

```shell
npm run build
docker run -v $PWD:/app:Z \
       -w /app --rm -i \
       -e WOPI_URL=$WOPI_URL \
       -e WOPI_HOST=$WOPI_HOST \
       -e COOL_K6_SCREENSHOT_DIR=$COOL_K6_SCREENSHOT_DIR \
       grafana/k6:master-with-browser -v run --vus 1 \
       --summary-mode=compact \
       "$@"
```

`k6-wrap` is a convenient wrapper to run k6 using docker.

`k6-run` uses `k6-wrap` to perform the `run` command from k6. You can
use it as a base to learn how to use the wrapper for other purposes.

The tests are webpacked into the `dist/` directory. To run a test
using `k6-wrap`, use the following command:

```shell
./k6-run dist/cool-test.js
```

### Other options

`--insecure-skip-tls-verify` is necessary if you use self-signed
certificates. Make sure the Collabora Online server also accept
them. Or use proper certificates everywhere.

The `k6-run` wrapper will detect `NODE_TLS_REJECT_UNAUTHORIZED` as
used by Node. If it is setp to `0`, the script will add the above
options accordingly.

### Diagnostics

Existing browser tests will save a  screenshot of the page if the test
fail.  This  allow having  an overview  if the page  in an  attempt to
figure out  what is happening. Each  screenshot file name will  have a
timestamp.

## License

This code is licensed under [MPL-2.0](COPYING) license.

Contributing is subject to the [Code of Conduct](CODE_OF_CONDUCT.md).
