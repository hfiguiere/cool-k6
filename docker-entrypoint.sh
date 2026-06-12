#!/bin/sh
#
# Launcher for the cool-k6 image.
#
# Accepts one or more test references, optionally followed by extra k6
# flags after a `--` separator. Each test reference can be:
#   - a bare base name such as "cool-test", resolved to a .js file. It is
#     looked up first among the bundled tests in /app/dist, then in the
#     mounted scenarios directory (COOL_K6_TESTS_DIR, default /tests).
#   - a file name such as "cool-test.js", same lookup.
#   - any path containing a slash, used verbatim.
#
# To run your own scenarios, mount a local directory of k6 scripts at
# /tests and refer to them by name, the same way as the bundled tests:
#   -v "$PWD/scenarios":/tests cool-k6 my-scenario.js
#
# Options recognised by this launcher itself (must come before the test
# names):
#   --cool-url <url>        Collabora Online server URL, forwarded to the
#                           bundles as WOPI_URL. Takes precedence over
#                           the env var of the same effect.
#   --wopi-host <url>       URL of the WOPI host, forwarded as WOPI_HOST.
#   --insecure              Avoid verifying tls cerficates
#
# Special commands:
#   list | ls | --list      print the bundled tests in /app/dist and exit
#
# Each test runs with k6's full summary mode so the metric block (HTTP
# timings, iterations, checks, data sent/received) is always printed.
# Per-test banners frame START / END with wall-clock timing, and after
# the whole sequence a roll-up table shows pass / fail and duration for
# every test that ran. The sequence stops at the first failing test and
# the entrypoint returns that test's exit code.
#
# Examples:
#   docker run cool-k6 list
#   docker run cool-k6 cool-test.js
#   docker run cool-k6 --cool-url https://collabora-server/ cool-test.js
#   docker run cool-k6 cool-test.js cool-browser-test.js
#   docker run cool-k6 cool-test.js cool-browser-test.js -- --vus 3 --duration 30s
#   docker run -v "$PWD/scenarios":/tests cool-k6 my-scenario.js
#
# Environment variables honoured:
#   WOPI_URL                              the Collabora Online server URL
#                                         (same as --cool-url; the CLI
#                                         option wins when both are set)
#   WOPI_HOST                             the WOPI host URL (same as
#                                         --wopi-host)
#   NODE_TLS_REJECT_UNAUTHORIZED=0        maps to k6's --insecure-skip-tls-verify
#   COOL_K6_SCREENSHOT_DIR                where the tests write screenshots
#                                         (defaults to /screenshots, declared
#                                         as a VOLUME in the image)
#   COOL_K6_TESTS_DIR                     where mounted scenarios are looked
#                                         up by name (defaults to /tests)

: "${COOL_K6_SCREENSHOT_DIR:=/screenshots}"
export COOL_K6_SCREENSHOT_DIR
mkdir -p "$COOL_K6_SCREENSHOT_DIR"

# Where mounted scenarios are looked up by name. Mount a host folder of
# your own k6 scripts here and run them by base name, the same way as the
# bundled tests. Bundled tests in /app/dist take precedence on a name
# clash; pass a full path to force a particular file.
: "${COOL_K6_TESTS_DIR:=/tests}"
export COOL_K6_TESTS_DIR

skip_tls_verify=0

iso_now() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

print_banner() {
    echo "======================================================================"
    for line in "$@"; do
        echo "=== $line"
    done
    echo "======================================================================"
}

print_usage() {
    cat >&2 <<EOF
usage: docker run cool-k6 list
       docker run cool-k6 <test>[.js] [<test>[.js] ...] [-- <k6 flags>]
available tests in /app/dist/:
EOF
    ls /app/dist/ | sed 's/^/    /' >&2
}

if [ "$#" -eq 0 ]; then
    print_usage
    exit 2
fi

# Pull launcher-level options off the front of the arg list before we
# treat the rest as test names. Anything we do not recognise is left in
# place and handled by the test/flag splitter further down.
while [ "$#" -gt 0 ]; do
    case "$1" in
        --cool-url|--wopi-url)
            [ "$#" -ge 2 ] || { echo "$1 needs a URL" >&2; exit 2; }
            WOPI_URL="$2"
            export WOPI_URL
            shift 2
            ;;
        --cool-url=*|--wopi-url=*)
            WOPI_URL="${1#*=}"
            export WOPI_URL
            shift
            ;;
        --wopi-host)
            [ "$#" -ge 2 ] || { echo "$1 needs a URL" >&2; exit 2; }
            WOPI_HOST="$2"
            export WOPI_HOST
            shift 2
            ;;
        --wopi-host=*)
            WOPI_HOST="${1#*=}"
            export WOPI_HOST
            shift
            ;;
        --insecure|--insecure-skip-tls-verify|-k)
            skip_tls_verify=1
            shift
            ;;
        *)
            break
            ;;
    esac
done

if [ "$#" -eq 0 ]; then
    print_usage
    exit 2
fi

case "$1" in
    list|ls|--list)
        echo "available tests in /app/dist/:"
        ls /app/dist/ | sed 's/^/    /'
        if [ -d "$COOL_K6_TESTS_DIR" ] && [ -n "$(ls -A "$COOL_K6_TESTS_DIR" 2>/dev/null)" ]; then
            echo "mounted scenarios in $COOL_K6_TESTS_DIR/:"
            ls "$COOL_K6_TESTS_DIR/" | sed 's/^/    /'
        fi
        exit 0
        ;;
esac

# Split positional args into the test list (everything before `--`) and
# the k6-flags list (everything after `--`). Without `--` every arg is a
# test.
tests=""
saw_separator=0
for arg in "$@"; do
    if [ "$saw_separator" -eq 0 ] && [ "$arg" = "--" ]; then
        saw_separator=1
        continue
    fi
    if [ "$saw_separator" -eq 0 ]; then
        tests="$tests $arg"
    fi
done

while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
    shift
done
[ "$#" -gt 0 ] && shift

if [ -z "$tests" ]; then
    echo "no tests requested" >&2
    print_usage
    exit 2
fi

extra_flags=
if [ "$skip_tls_verify" -eq 1 ] || [ "$NODE_TLS_REJECT_UNAUTHORIZED" = "0" ]; then
    extra_flags="--insecure-skip-tls-verify"
    # --insecure-skip-tls-verify only covers k6's own http and websocket
    # clients, which is what the network scenarios use. The browser
    # scenarios drive a separate Chromium process that never sees that
    # flag, so it has to be told to ignore certificate errors through its
    # own argument. Append it, keeping any value the caller already set.
    if [ -n "$K6_BROWSER_ARGS" ]; then
        K6_BROWSER_ARGS="$K6_BROWSER_ARGS,ignore-certificate-errors"
    else
        K6_BROWSER_ARGS="ignore-certificate-errors"
    fi
    export K6_BROWSER_ARGS
fi

resolve_test() {
    # A path (anything with a slash) is used verbatim.
    case "$1" in
        /*|*/*) printf '%s\n' "$1"; return ;;
    esac

    # A bare name resolves to a .js file. Look it up first among the
    # bundled tests, then in the mounted scenarios directory. If it is in
    # neither, return the bundled path so the missing-file message names a
    # concrete location.
    name="$1"
    case "$name" in
        *.js) ;;
        *)    name="$name.js" ;;
    esac

    if [ -f "/app/dist/$name" ]; then
        printf '/app/dist/%s\n' "$name"
    elif [ -f "$COOL_K6_TESTS_DIR/$name" ]; then
        printf '%s/%s\n' "$COOL_K6_TESTS_DIR" "$name"
    else
        printf '/app/dist/%s\n' "$name"
    fi
}

sequence_start=$(date +%s)
sequence_started_at=$(iso_now)
print_banner \
    "cool-k6 sequence start: $sequence_started_at" \
    "WOPI_URL:  ${WOPI_URL:-<unset, bundles will default>}" \
    "WOPI_HOST: ${WOPI_HOST:-<unset, bundles will default>}" \
    "tests:$tests" \
    "k6 flags:${extra_flags:+ }$extra_flags $*"

results=""
final_rc=0
for t in $tests; do
    test_path=$(resolve_test "$t")
    test_name=$(basename "$test_path")
    if [ ! -f "$test_path" ]; then
        echo "no such test: $test_path" >&2
        results="${results}
${test_name}|MISSING|0"
        final_rc=2
        break
    fi

    test_start=$(date +%s)
    started_at=$(iso_now)
    echo
    print_banner \
        "START $test_name" \
        "path:  $test_path" \
        "begin: $started_at"

    k6 run --vus 1 --summary-mode=full $extra_flags "$@" "$test_path"
    test_rc=$?

    test_end=$(date +%s)
    ended_at=$(iso_now)
    duration=$((test_end - test_start))

    print_banner \
        "END   $test_name" \
        "rc:       $test_rc" \
        "duration: ${duration}s" \
        "end:      $ended_at"

    results="${results}
${test_name}|${test_rc}|${duration}"

    if [ "$test_rc" -ne 0 ]; then
        final_rc=$test_rc
        echo "stopping after first failure" >&2
        break
    fi
done

sequence_end=$(date +%s)
sequence_duration=$((sequence_end - sequence_start))

echo
print_banner \
    "cool-k6 sequence end: $(iso_now)" \
    "total duration: ${sequence_duration}s" \
    "overall rc:     $final_rc"

echo
echo "per-test summary:"
printf '%s\n' "$results" \
    | awk -F'|' 'NF==3 {
        if ($2 == "0")        { status = "PASS" }
        else if ($2 == "MISSING") { status = "MISSING" }
        else                  { status = "FAIL(" $2 ")" }
        printf "    %-50s %-12s %ss\n", $1, status, $3
    }'

exit "$final_rc"
