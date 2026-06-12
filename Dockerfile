# Cool-K6 test image.
#
# Built test bundles from dist/ are embedded so the container is invoked
# with just the test name on the docker run command line.
#
# Build:  docker build -t cool-k6 .
# Run a single embedded test (via env vars):
#         docker run --rm \
#             -e WOPI_URL=https://collabora-server/cool/ \
#             -e WOPI_HOST=https://wopi-host/ \
#             -v "$PWD/screenshots":/screenshots \
#             cool-k6 cool-test.js
# Same, with the Collabora Online URL on the command line:
#         docker run --rm cool-k6 \
#             --cool-url https://collabora-server/ cool-test.js
# Run several tests in sequence with extra k6 flags:
#         docker run --rm cool-k6 \
#             cool-test.js cool-browser-test.js -- --vus 3 --duration 30s
# Run your own scenarios from a mounted directory, by name:
#         docker run --rm -v "$PWD/scenarios":/tests cool-k6 my-scenario.js
# List the embedded tests (and any mounted scenarios):
#         docker run --rm cool-k6 list
FROM grafana/k6:latest-with-browser

USER root

# Webpack output is self-contained, so dist/ is the only thing the
# tests need at run time.
COPY dist/                /app/dist/
COPY docker-entrypoint.sh /usr/local/bin/cool-k6
RUN chmod +x /usr/local/bin/cool-k6 \
    && mkdir -p /screenshots /tests \
    && chmod 1777 /screenshots

# Screenshots written by the tests land here. Mount a host directory
# to capture them across runs.
ENV COOL_K6_SCREENSHOT_DIR=/screenshots
VOLUME ["/screenshots"]

# Mount a host directory of your own k6 scenarios here to run them by
# name, alongside the bundled tests.
ENV COOL_K6_TESTS_DIR=/tests

ENTRYPOINT ["/usr/local/bin/cool-k6"]
CMD ["list"]
