# G1 product definition — proposed

Status: proposed for Human G1 review. This file is not an approval.

## Product

A small demonstration application that imports a synthetic monthly building-energy CSV and presents monthly totals, month-over-month change, and highlighted anomalies.

## Intended users

- a facilities analyst learning the sample workflow;
- a reviewer evaluating whether the synthetic product definition is clear enough to proceed to detailed requirements.

## Intended value

- make a synthetic monthly energy dataset easy to inspect;
- show how totals, changes, and anomalies could be presented;
- provide a bounded example for the Factory S4 acceptance exercise.

## Boundary

- synthetic data only;
- no connection to meters, sensors, production devices, or real customer systems;
- no real credentials, private data, billing action, control action, or automated operational decision;
- no Control adoption or production task binding;
- detailed fields, calculations, validation rules, thresholds, persistence behavior, and acceptance cases remain for G2 and are not decided by this proposal.

## G1 question

Should this bounded synthetic monthly-energy analysis definition be accepted as the basis for preparing G2 requirements?
