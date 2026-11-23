# margin-bridge-tieout

[![CI](https://github.com/pg2342-hub/margin-bridge-tieout/actions/workflows/ci.yml/badge.svg)](https://github.com/pg2342-hub/margin-bridge-tieout/actions/workflows/ci.yml)

Demo page: https://pg2342-hub.github.io/margin-bridge-tieout/ (the showcase quarter, both bridges, every finding and both gate reports; no install needed)

Rebuild a quarter's gross-profit bridge from ERP invoice lines, tie it to the ledger, and find the driver a favorable total hides.

A product-line bridge is how most month-end workbooks explain margin: price, volume, mix and cost by product line. It adds up, it ties, and it can still point the business at the wrong lever. When lower-margin installer (do-it-for-me) business grows inside a product line, the lower program price shows up as a price cut, and a richer product mix can hide a channel mix that is getting worse. This repo does the analysis at the item grain (SKU x customer x channel), and only after the extract passes its data checks and ties to the ledger.

## What it does

1. **Data checks** against one definitions file finance owns (`bridge/definitions.yml`): every order type maps to a channel, every unit of measure converts to eaches, every rebate memo names a customer in the master, no invoice line appears twice. Any failure stops the bridge and says why.
2. **Tie-out**: extract revenue and gross profit against the general ledger, each quarter, within $1. Rebates post as separate customer-level memos, so they are allocated to lines by gross sales within each customer and month.
3. **Bridge** at any grain: price (net of rebates, tariff surcharges included), tariff cost, other cost, volume, mix, new and lost items. The effects add up to the change in gross profit exactly.
4. **Driver finder**: the largest member behind each driver, any member moving against its driver's total ("masked"), any driver that reads differently at the product-line grain ("reattributed"), and mix between the members of each dimension (product line, customer, channel, country of origin). Materiality is $100K of gross profit.

## The eval

`eval/` holds 25 planted scenarios on a made-up aftermarket parts maker (6 product lines, 6 customers, about 5,500 invoice lines across two quarters), scored with [golive-gate](https://github.com/pg2342-hub/golive-gate):

| Group | Cases | What a correct analysis must do |
|---|---|---|
| routine | 8 | Find one visible driver (a price change, a tariff, a cost change, new or lost SKUs) and size price and cost within 2% of the planted dollars |
| hidden | 8 | Put a driver a product-line bridge gets wrong in its top 3 findings |
| trap | 6 | Stop on a bad extract and name the problem |
| control | 3 | Flag nothing when nothing was planted |

The gate: 24 of 25 overall, every hidden and trap case, every control, and zero critical failures. The three critical checks are publishing a bridge on bad data, missing a planted data problem, and publishing a bridge that does not tie to the ledger.

```
golive run eval/golive.yml                                # tie-out + item bridge: GO, 25 of 25
golive run eval/golive.yml --agent agent:workbook_agent   # product-line workbook: NO-GO, 6 of 25
```

The workbook baseline is a careful one: it allocates rebates the same way and ties its totals, but it bridges by product line and has no data checks.

## Run it

```
pip install -e ".[dev]"
pytest -q
golive run eval/golive.yml
python scripts/build_demo.py   # rebuilds docs/ for GitHub Pages
```

CI runs ruff, the tests and the gate on every push, and fails if the workbook baseline ever passes.

## Limits

- All data is synthetic. Customers, SKUs, prices, tariffs and the ledger are made up; the shape (invoice lines, separate rebate memos, order type codes, case packs) follows a typical ERP export.
- Volume and mix use one common method (each continuing item grows at the total rate; mix is share gained or lost at its own prior margin). Other conventions split volume and mix differently but give the same price and cost effects.
- No model calls. This is the deterministic layer an analysis agent's numbers should tie back to.
