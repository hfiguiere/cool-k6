

/// URL for the WOPI editor: Your Collabora Online server.
export let wopiUrl = new URL(__ENV['WOPI_URL'] ? __ENV['WOPI_URL'] : 'https://localhost:9980/');
/// URL for the WOPI host.
export let wopiHost = new URL(__ENV['WOPI_HOST'] ? __ENV['WOPI_HOST'] : 'https://localhost:3000/');

/// Where to save screenshots.
export let screenshotDir = __ENV['COOL_K6_SCREENSHOT_DIR'];
