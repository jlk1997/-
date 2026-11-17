# dsp-playbooks

Shared upload + harvest playbooks for the creator connector and browser farm.

```
health(code)
upload(code, { audio, cover, title, artist, isrc })
harvest(doc, code) → rows[]
runHarvest(doc, code) → { ok, reason, rows }
harvestSteps(code) → statsUrls / wait / export / paginate
confirmLive(url, code) → store_ref
```

`runner.js` is the executable harvest host (login wall, wait selectors, CSV hrefs, merge pages). Extension copies it to `runner-core.js`; farm injects the same file. Partner APIs are out of scope.
