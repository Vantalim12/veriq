# Synthetic procurement procedure

This is demonstration data, not a customer policy or a real approval system.

1. Intake accepts an order with `body.amount` expressed as a finite numeric PHP value.
2. Purchases above PHP 10,000 must cross the reviewed blocking approval waypoint before the fulfillment waypoint.
3. The high-value IF comparison is strictly `body.amount > 10000`; its true output is index 0.
4. The low-value route must not reach the review-request waypoint.
5. An actual deployment must authenticate the approver and enforce approval outside this static model. The synthetic Wait node does not establish who resumed it.

`purchase-v1.json` preserves the modeled route. `purchase-v2.json` intentionally rewires the high-value output directly to fulfillment. The approved example rules are hand-authored; SOP extraction and citation validation belong to P1.

