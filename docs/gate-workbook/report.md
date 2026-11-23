# Margin bridge go-live gate: NO-GO

Agent `agent:workbook_agent`, 25 cases, 1 run(s).

- run 1: 10 critical failure(s): stops_on_bad_data on case t01, names_the_problem on case t01, stops_on_bad_data on case t02, names_the_problem on case t02, stops_on_bad_data on case t03, names_the_problem on case t03, ties_to_ledger on case t03, names_the_problem on case t05, stops_on_bad_data on case t06, names_the_problem on case t06
- run 1: overall passed 7 of 25, needs 24 (no-go)
- run 1: hidden drivers passed 0 of 8, needs 8 (no-go)
- run 1: data traps passed 1 of 6, needs 6 (no-go)

## Pass counts by run

| Run | Passed | Critical failures |
|---|---|---|
| 1 | 7 of 25 | 10 |

Agent cost 0.0000 USD, judge cost 0.0000 USD, mean latency 24.6 ms per case.

## Cases

| Case | Group | Result | Failed checks |
|---|---|---|---|
| Sensors list price up 4% | routine | 1 of 1 runs |  |
| Distributor D gets a 6% price cut | routine | 0 of 1 runs | finds_the_driver, sizes_it_right |
| China tariff rate 10% to 25% | routine | 0 of 1 runs | finds_the_driver |
| Climate material cost up 8% | routine | 0 of 1 runs | sizes_it_right |
| Units down 8% across the board | routine | 1 of 1 runs |  |
| Four new Sensors SKUs launched | routine | 0 of 1 runs | finds_the_driver |
| Six Sensors SKUs discontinued | routine | 0 of 1 runs | finds_the_driver |
| Wipers price up 5%, Retailer C buys wipers in cases of six | routine | 1 of 1 runs |  |
| Installer (DIFM) shift at Retailer B hides under a richer product mix | hidden | 0 of 1 runs | finds_the_driver |
| DIFM shift at Retailer A under a Wipers-to-Sensors mix gain | hidden | 0 of 1 runs | finds_the_driver |
| Price up 5% everywhere except a 10% cut at Distributor E | hidden | 0 of 1 runs | finds_the_driver |
| Tariff surcharges held, but Retailer B got a 10% price cut | hidden | 0 of 1 runs | finds_the_driver |
| A product-line bridge calls a DIFM shift a price cut | hidden | 0 of 1 runs | finds_the_driver |
| Material savings of 8% everywhere except Ignition, up 15% | hidden | 0 of 1 runs | finds_the_driver |
| A product-line bridge calls a flat mix a gain | hidden | 0 of 1 runs | finds_the_driver |
| China tariff relief hides a new Mexico tariff | hidden | 0 of 1 runs | finds_the_driver |
| New order type XFR missing from the channel map | trap | 0 of 1 runs | names_the_problem, stops_on_bad_data |
| Retailer A starts buying wipers in cases of twelve | trap | 0 of 1 runs | names_the_problem, stops_on_bad_data |
| Rebate memo keyed to a customer name the master does not know | trap | 0 of 1 runs | names_the_problem, stops_on_bad_data, ties_to_ledger |
| Extract cut off mid-September; ledger has the full month | trap | 1 of 1 runs |  |
| Export repeated a page of invoices | trap | 0 of 1 runs | names_the_problem |
| Unmapped order type on top of a real DIFM shift | trap | 0 of 1 runs | names_the_problem, stops_on_bad_data |
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
