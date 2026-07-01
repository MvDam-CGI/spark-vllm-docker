# DGX Spark Control Room

Run the local dashboard from the project root:

```bash
python -m dashboard.server --host 127.0.0.1 --port 8088
```

Open `http://127.0.0.1:8088`.

The server prints a control token at startup. Paste that token into `Settings` before using `Launch` or `Stop`. Read-only pages do not require the token.

`127.0.0.1` is local-only. Other VPN machines cannot reach this server unless it is bound to `0.0.0.0`, a VPN IP, or exposed through a tunnel or reverse proxy.

By default the token is stored in `dashboard/state/control-token.txt`. You can also set `DASHBOARD_TOKEN` before starting the server.

Launch requests are converted to argument arrays for `./run-recipe.sh`; browser input is never executed as shell text. The default TranslateGemma launch uses solo mode on port `8001`.
