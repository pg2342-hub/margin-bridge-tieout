# Margin bridge go-live gate: GO

Agent `agent:tieout_agent`, 25 cases, 1 run(s).

- every rule held on all 1 run(s), no critical failures

## Pass counts by run

| Run | Passed | Critical failures |
|---|---|---|
| 1 | 25 of 25 | 0 |

Agent cost 0.0000 USD, judge cost 0.0000 USD, mean latency 38.7 ms per case.

## Cases

| Case | Group | Result | Failed checks |
|---|---|---|---|
| Sensors list price up 4% | routine | 1 of 1 runs |  |
| Distributor D gets a 6% price cut | routine | 1 of 1 runs |  |
| China tariff rate 10% to 25% | routine | 1 of 1 runs |  |
| Climate material cost up 8% | routine | 1 of 1 runs |  |
| Units down 8% across the board | routine | 1 of 1 runs |  |
| Four new Sensors SKUs launched | routine | 1 of 1 runs |  |
| Six Sensors SKUs discontinued | routine | 1 of 1 runs |  |
| Wipers price up 5%, Retailer C buys wipers in cases of six | routine | 1 of 1 runs |  |
| Installer (DIFM) shift at Retailer B hides under a richer product mix | hidden | 1 of 1 runs |  |
| DIFM shift at Retailer A under a Wipers-to-Sensors mix gain | hidden | 1 of 1 runs |  |
| Price up 5% everywhere except a 10% cut at Distributor E | hidden | 1 of 1 runs |  |
| Tariff surcharges held, but Retailer B got a 10% price cut | hidden | 1 of 1 runs |  |
| A product-line bridge calls a DIFM shift a price cut | hidden | 1 of 1 runs |  |
| Material savings of 8% everywhere except Ignition, up 15% | hidden | 1 of 1 runs |  |
| A product-line bridge calls a flat mix a gain | hidden | 1 of 1 runs |  |
| China tariff relief hides a new Mexico tariff | hidden | 1 of 1 runs |  |
| New order type XFR missing from the channel map | trap | 1 of 1 runs |  |
| Retailer A starts buying wipers in cases of twelve | trap | 1 of 1 runs |  |
| Rebate memo keyed to a customer name the master does not know | trap | 1 of 1 runs |  |
| Extract cut off mid-September; ledger has the full month | trap | 1 of 1 runs |  |
| Export repeated a page of invoices | trap | 1 of 1 runs |  |
| Unmapped order type on top of a real DIFM shift | trap | 1 of 1 runs |  |
| Nothing planted (seed 7) | control | 1 of 1 runs |  |
| Nothing planted (seed 31) | control | 1 of 1 runs |  |
| Units up 2%, nothing else | control | 1 of 1 runs |  |

## Checks

| Check | Critical | Text |
|---|---|---|
| stops_on_bad_data | yes | A data problem stops the bridge; clean data publishes one. |
| names_the_problem | yes | The analysis names the planted data problem. |
| ties_to_ledger | yes | A published bridge ties to the ledger, and its effects add up to the ledger's change in gross profit. |
| finds_the_driver |  | The planted driver is in the findings, with the right sign; a hidden one is in the top 3. |
| sizes_it_right |  | The bridge's effect for the planted driver is within 2% of the planted dollars. |
| no_false_alarm |  | With nothing planted, there are no data issues and no masked or reattributed findings. |
