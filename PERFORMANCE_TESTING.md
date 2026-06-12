# Performance testing for integrators

This document is for teams that integrate Collabora Online with their
own WOPI host and want to measure how the combined deployment behaves
under load. It walks through using the bundled k6 test suite from
inside the `cool-k6` Docker image.

The bundled scenarios are examples meant to work with the WOPI host 
included with cool-k6, running with a production WOPI host require 
adapting them to your setup provide the necessary authentication and
flow.

In practice you would bring your own k6 scenario that authenticates
against your host and opens the document you choose from your WOPI host.
This document shows how to run a scenario against a deployment you control,
using the bundled ones as working examples and templates for your own.

If you only want to add new scenarios to the suite, see the developer
notes in `README.md`.


## What the suite measures

Each bundled scenario drives a client against your Collabora Online
server through a WOPI flow. The tests measure end-to-end behaviour as
observed by the client. They are not micro-benchmarks of individual
server components. They are most useful for:

- Smoke checks after a deployment change.
- Capacity tests, by raising the virtual user count and watching how
  document load and edit operations degrade.
- Regression tracking, by recording the metric block over time and
  comparing.

The tests report how long things take. They do not explain why. Look
at server-side logs and metrics when a number moves in a direction you
did not expect.


## Prerequisites

- A reachable Collabora Online server. The image needs to fetch the
  WOPI client iframe from it, and the WOPI host and Collabora Online
  server must use the same protocol (http or https). A coolwsd with
  ssl-termination enabled is supported with a http url for collabora 
  online and an https one for the WOPI Host.
- A reachable WOPI host that you provide. This is the system that
  answers the WOPI endpoints (`CheckFileInfo`, `GetFile`, ...). The
  image does not ship one, so bring your own. (There is an example in
  the cool-k6 repository in server directory, than can be used for
  testing and that can work with provided scenarios)
- A document for each scenario to open, served by your WOPI host. The
  bundled scenarios reference fixed IDs, listed in the scenarios
  section below, so your WOPI host must expose documents under those
  IDs.
- A k6 scenario script suited to your WOPI host. The bundled scenarios
  are examples meant to work with the WOPI host included with cool-k6, 
  running with a production WOPI host require adapting them to your setup
  provide the necessary authentication and flow. See the section on
  your own documents below.
- Docker on the machine that will generate the load. Run the load
  generator on a host separate from Collabora Online and the WOPI
  host so the two are not competing for CPU.
- The `cool-k6` image built from the git repository:

```
cd cool-k6
npm install     # install the build dependencies
npm run build   # produce dist/ (gitignored); the image embeds it
docker build -t cool-k6 .
```

`dist/` is not in git, so `npm run build` has to run before
`docker build` to produce the bundles the image embeds. Once the image
is built, the runner only needs Docker to use it.


## Built-in scenarios

The image carries the following bundled scripts under `/app/dist/`.
Each script reads the document IDs given below from the WOPI host. All
scripts default to one iteration unless stated otherwise.

### Network (synthetic) scenario

- `cool-test.js`. Fetches the WOPI client iframe, opens a WebSocket to
  Collabora through `CoolClientWs`, opens the document at file ID `2`,
  sends a short typing sequence, then closes. No browser, so this is
  the lightest scenario for many virtual users per host. Records
  `frame_loading_time`.

### Browser-based scenarios

- `cool-browser-test.js`. Drives a Chromium through k6-browser against
  file ID `2`. Goes through the WOPI host index page, watches the
  postMessage stream for `App_LoadingStatus`, and records
  `page_loading_time` plus `frame_loading_time`. Saves a screenshot to
  `COOL_K6_SCREENSHOT_DIR` if the iteration throws.

- `cool-browser-insert-image-test.js`. Same browser path as the test
  above, file ID `2`. Once the document canvas is visible it sends
  the `Action_InsertGraphic` postMessage with a sample image URL and
  holds the page open for two seconds while the change propagates.
  Saves a screenshot on failure.

The image lists the bundled scripts when run with no argument:

```
docker run --rm cool-k6
```


## Pointing the tests at your deployment

The two URLs the tests need are surfaced as launcher options. They
override any value in the environment.

```
docker run --rm cool-k6 \
    --cool-url  https://collabora.example.com:9980/ \
    --wopi-host https://wopi.example.com/ \
    cool-test.js
```

- `--cool-url` is the URL of the Collabora Online server. The tests
  use it to fetch the WOPI client iframe.
- `--wopi-host` is the URL of your WOPI host. The tests embed it into
  the `WOPISrc` parameter so Collabora Online calls back to your
  host.

The equivalent environment variables `WOPI_URL` and `WOPI_HOST` are
still honoured. They are the right choice when you want to bake the
URLs into a shell wrapper or a CI job definition. The launcher
options take precedence when both are set.

If either URL uses a self-signed certificate, add `--insecure` so the
runner passes `--insecure-skip-tls-verify` to k6.

```
docker run --rm cool-k6 --insecure \
    --cool-url  https://collabora.example.com:9980/ \
    --wopi-host https://wopi.example.com/ \
    cool-test.js
```

The aliases `--insecure-skip-tls-verify` and `-k` work the same way.
Setting `NODE_TLS_REJECT_UNAUTHORIZED=0` in the container env also
has the same effect.


## A first run

For a deployment you can already reach, the smallest useful command
is:

```
docker run --rm cool-k6 \
    --cool-url  https://collabora.example.com:9980/ \
    --wopi-host https://wopi.example.com/ \
    cool-test.js
```

Launcher options (`--cool-url`, `--wopi-host`, `--insecure`) belong
after the image name and before the test reference. Docker flags
(`--rm`, `-v`, `-e`, ...) belong before the image name.

This runs the lightest scenario, with one virtual user, one
iteration. Expected output, abbreviated:

```
======================================================================
=== cool-k6 sequence start: 2026-06-12T...
=== WOPI_URL:  https://collabora.example.com:9980/
=== WOPI_HOST: https://wopi.example.com/
=== tests: cool-test.js
=== k6 flags:
======================================================================

=== START cool-test.js ...

      execution: local
      script: /app/dist/cool-test.js
      ...
      http_req_duration..............: avg=...   min=... med=... max=... p(90)=... p(95)=...
      iteration_duration.............: avg=...
      iterations.....................: 1
      vus............................: 1
      data_received..................: ...
      data_sent......................: ...

=== END cool-test.js rc=0 duration=Xs ...

per-test summary:
    cool-test.js                                       PASS         Xs
```

If the test exits with a non-zero status, the per-test summary will
show `FAIL(N)` and the runner returns that exit code.


## Reading the metrics

For each test k6 prints a metrics block. The entries that matter
most to an integrator are:

- `http_req_duration`. End-to-end time of every HTTP request the
  scenario issued. The `p(95)` value is what to track as a
  user-visible latency target.
- `http_reqs`. Total request count and per-second rate.
- `iteration_duration`. Wall clock per scenario iteration.
- `data_sent` and `data_received`. Total bytes for the scenario.
- `checks`. Pass and fail counts for the in-script assertions. Any
  failure here means the scenario did not behave as expected, so the
  timings from that iteration should be discarded.
- `frame_loading_time` and `page_loading_time`. Custom trends emitted
  by the scripts. `frame_loading_time` is the headline number for
  "how long until the editor is usable".
- Browser scenarios additionally emit `browser_*` metrics, in
  particular `browser_http_req_duration` and `browser_web_vital_*`.
  These cover the full editor load. The plain `http_*` metrics in a
  browser scenario only describe the iframe shell.

The runner forces `--summary-mode=full` so the metric block is
emitted for every test. Keep it in your CI logs.


## Tuning the load

The launcher passes any flag placed after `--` straight to `k6 run`,
once per test in the sequence. The flags most integrators reach for:

- `--vus N`. Number of virtual users in parallel. Start at 1, double
  until you see `http_req_duration p(95)` cross your target.
- `--duration 1m`. Run for one minute. Use this for capacity work
  instead of a fixed iteration count.
- `--iterations N`. Total iterations across all virtual users. Use
  this for repeatable smoke checks.
- `--rps N`. Cap the request rate.
- `--stage` blocks. For ramp scenarios. See the k6 documentation.

Example, ten virtual users for five minutes:

```
docker run --rm cool-k6 \
    --cool-url  https://collabora.example.com:9980/ \
    --wopi-host https://wopi.example.com/ \
    cool-browser-test.js \
    -- --vus 10 --duration 5m
```


## Running several scenarios at once

Pass multiple test names. The runner runs them in order. The first
one to fail stops the sequence and the launcher returns that test's
exit code.

```
docker run --rm cool-k6 \
    --cool-url  https://collabora.example.com:9980/ \
    --wopi-host https://wopi.example.com/ \
    cool-test.js cool-browser-test.js cool-browser-insert-image-test.js
```

Per-test banners frame START / END with wall-clock timing, and a
roll-up table at the end of the run shows the result of each test:

```
per-test summary:
    cool-test.js                                       PASS         3s
    cool-browser-test.js                               PASS         12s
    cool-browser-insert-image-test.js                  FAIL(99)     47s
```

If you need the same k6 flags applied to every test, place them after
`--`. The runner forwards them to each `k6 run` invocation.

```
docker run --rm cool-k6 cool-test.js cool-browser-test.js \
    -- --vus 5 --duration 2m
```


## Testing with your own documents

Point the tests at your WOPI host with `--wopi-host`. The bundled
scenarios address files by fixed IDs and do not authenticate, so on
their own they only work against a WOPI host that exposes those IDs
without a login. The IDs are at the top of each script under `src/`.
Change them and run `npm run build` to refresh the bundles, then
rebuild the image.

A production WOPI host usually requires authentication and decides
which document to open through its own access tokens. 

The bundled scenarios are examples meant to work with the WOPI host 
included with cool-k6, running with a production WOPI host require 
adapting them to your setup providing the necessary authentication and flow.

For that, make your own k6 scenario: have it authenticate against your host,
build the `WOPISrc` URL for the document you want, and open it. Start from a
bundled script under `src/` as a template, then run it with the mount
described in "Running your own scenarios".


## Running your own scenarios

To run scenarios that are not bundled in the image, mount the local
directory that holds them at `/tests` and refer to them by name, the
same way as the bundled tests:

```
docker run --rm \
    -v "$PWD/scenarios":/tests \
    --cool-url  https://collabora.example.com:9980/ \
    --wopi-host https://wopi.example.com/ \
    cool-k6 my-scenario.js -- --vus 3
```

Here `$PWD/scenarios` is your local folder of k6 scripts. A bare test
name is resolved to a `.js` file, looked up first among the bundled
tests in `/app/dist` and then in the mounted directory. Mounting a
whole directory rather than a single file lets a scenario import helper
modules that sit next to it, since k6 resolves those imports relative
to the script. `docker run cool-k6 list` shows the bundled tests and
any mounted scenarios.

A scenario can still be given by its in-container path directly: any
argument that contains a slash is used verbatim, so
`-v "$PWD/my-scenario.js":/tests/my-scenario.js cool-k6 /tests/my-scenario.js`
also works. Use whichever fits how you iterate locally.

The mount point is `/tests` by default. Set `COOL_K6_TESTS_DIR` to look
names up somewhere else.


## Screenshots on failure

The `cool-browser-test.js` and `cool-browser-insert-image-test.js`
scripts call the `screenshotPage` helper from their catch handlers,
so the failing browser state is captured to disk. Mount a host
directory to keep the screenshots across runs:

```
docker run --rm \
    -v "$PWD/screenshots":/screenshots \
    cool-k6 cool-browser-test.js
```

The image declares `/screenshots` as a volume and exports the path as
`COOL_K6_SCREENSHOT_DIR`, which the helper reads. The other bundled
scripts do not currently call the helper, so they leave nothing in
the volume.


## Limitations and caveats

- Load comes from a single Docker host. For loads above what one
  host can drive, run k6 in cluster mode. The same image works on
  every worker.
- Browser scenarios use a bundled Chromium, which is heavier than a
  plain HTTP client. Expect fewer virtual users per host than
  `cool-test.js` can drive.
- `cool-test.js` records the fetch of the editor shell as
  `frame_loading_time`. Use a browser-driven test if you want
  time-to-interactive.
- The runner stops at the first failing test. To run the remaining
  tests regardless, invoke `docker run` once per test instead of
  listing them together.


## Going further

For a full reference of k6 flags and output formats, see the k6
documentation. For Collabora Online server settings that affect
performance, see the operator handbook for your version. For the
WOPI protocol specifics that the tests rely on, see the WOPI
documentation from the protocol owner.
