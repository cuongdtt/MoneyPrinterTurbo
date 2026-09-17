# Feature guide (local HTML)

The feature guide lives at [`index.html`](./index.html). It is standalone: it
does not need a build step, dependencies, or an internet connection.

## Quickest option: open the file

Open `docs/features/index.html` directly in any browser.

## Run a local server

From the repository root, run:

```sh
./docs/features/serve.sh
```

Then open either:

- [Feature guide](http://localhost:8080/features/)
- [OFox, WaveSpeed, and fal comparison](http://localhost:8080/ofx-wavespeed-fal-comparison.html)

Stop the server with `Ctrl+C`.

The script uses Python's built-in HTTP server. If port 8080 is already in use,
pass another port:

```sh
./docs/features/serve.sh 4173
```
