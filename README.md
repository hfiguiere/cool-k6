# What is this?

A K6 based test suite for Collabora Online

## Adding test

Add test to the src directory. File must end in `-test.js`.

Build the bundles with `npm run build`. The targets are in `dist/`
ready to run. This uses webpack under the hood.

## WOPI Host

A WOPI Host (server) is included in the `server` directory. It's in
pure NodeJS. `npm run server` will start it bound to port 3000.

Running the server require Node 20.10

### Configuring files

You can configure files to serve from the WOPI Host. This is done by
adding an entry to the JSON file `./server/routes/files.json`.

It's a dictionary (JS object) where the key is the file id as passed in the WOPI source URL, and entries contain at least a `path` (relative to the current working directory or absolute).

There are the various fields for an entry:

- `path`: Path to the file to serve.
- `readonly`: If true the file is served in readonly mode. In absence
of the property, the file is server in editing mode.

## Running the tests

We default to use the Docker image for k6 since it's not carried by
most distributions. But you can adapt this to other methods.

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
       --insecure-skip-tls-verify \
       --summary-mode=compact \
       "$@"
```

### Other options

`--insecure-skip-tls-verify` is necessary if you use self-signed
certificates. Make sure the Collabora Online server also accept
them. Or use proper certificates everywhere.


## License

This code is licensed under [MPL-2.0](COPYING) license.

Contributing is subject to the [Code of Conduct](CODE_OF_CONDUCT.md).
