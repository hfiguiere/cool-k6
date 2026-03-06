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

### Configuring files

You can configure files to serve from the WOPI Host. This is done by
adding an entry to the JSON file `./server/routes/files.json`.

It's a dictionary (JS object) where the key is the file id as passed
in the WOPI source URL, and entries contain at least a `path`
(relative to the current working directory or absolute).

There are the various fields for an entry:

- `path`: Path to the file to serve.
- `readonly`: If true the file is served in readonly mode. In absence
of the property, the file is server in editing mode.

A key with an empty object return just a "Hello world" strigs. Asking
a file with an ID that is not found in the `files.json` will return
the HTTP status 404 (not found).

## Running the tests

We default to use the Docker image for k6 since it's not carried by
most distributions. But you can adapt this to other methods.

This is currently tested with k6 version 1.5.x.

### Environment

There are two environment variables used by the K6 tests.

- `WOPI_URL=https://<your_cool_host>:9980/`: `WOPI_URL` is set to the
WOPI client (Collabora Online) URL. `your_cool_host` is the host on
which Collabora Online is running. Remember if you run K6 in a Docker
container, it's unlikely to be localhost.

- `WOPI_HOST=https://<your_wopi_host>:3000/`: `WOPI_HOST` is set to
the WOPI host (see above). `your_wopi_host` is the host on which you
run the WOPI host started with `npm run server`. Remember if you run
K6 in a Docker container, it's unlikely to be localhost.

The test will use default values, unlikely to be what you want.

### Running

```shell
npm run build
docker run -v $PWD:/app:Z \
       -w /app --rm -i \
       -e WOPI_URL=$WOPI_URL \
       -e WOPI_HOST=$WOPI_HOST \
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

## License

This code is licensed under [MPL-2.0](COPYING) license.

Contributing is subject to the [Code of Conduct](CODE_OF_CONDUCT.md).
