import path from "path";

import GlobEntries from "webpack-glob-entries";

export default {
    mode: "development",
    entry: GlobEntries("./src/*-test.js"),
    output: {
        libraryTarget: "commonjs",
        path: path.resolve(import.meta.dirname, "dist"),
        filename: "[name].js"
    },
    externals: /^(k6|https?\:\/\/)(\/.*)?/,
}
