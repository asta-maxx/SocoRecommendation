# Event row contract — v1

**Status: agreed, and verified against the generated dataset on 11 September.**
Every field name, event type and conditional rule below was checked against the
6,361 rows the generator actually produced. Three things were corrected in the
process and are marked **[corrected]**.

The contract is enforced in code, not just here: both sides validate against
[`reco/domain/event_contract.py`](reco/domain/event_contract.py). A field renamed
on one side fails the other side's tests immediately, rather than on demo day.

---

## One row in `ml_demo_events`

```json
{
  "user_id":               "U01",
  "event_type":            "product_view",
  "categories":            ["Fashion & Apparel"],
  "timestamp":             "2026-09-10T16:22:58.409339+00:00",
  "weight":                2,
  "view_duration_seconds": 6
}
```

### The five every row carries

| Field | Type | Notes |
|---|---|---|
| `user_id` | string | Text form, not ObjectId |
| `event_type` | string | One of: `product_view`, `keyword_search`, `product_click`, `add_to_cart`, `purchase`, `purchase_reversal` **[corrected]** |
| `categories` | **array** of string | **Any string.** The engine maps or drops; it does not validate at read **[corrected]** |
| `timestamp` | date | UTC, timezone-aware. **A missing one is an explicit `null`, not an absent key** **[corrected]** |
| `weight` | number | Written by the generator. **Never read by the engine** |

### The two that appear only where they apply

| Field | On | Notes |
|---|---|---|
| `view_duration_seconds` | `product_view` rows only | P-02 is applied to it by the method, not the generator |
| `order_id` | `purchase` and `purchase_reversal` rows | Required on both |

### The three corrections

**Event types are the long names.** The generator emits `product_view`, not
`view`. `postevents` uses a third vocabulary again (`view`, `like`, `comment`,
`share`, `save`, `add_to_cart`, `purchase`), and `purchase_reversal` does not
exist there at all — on live data it has to be derived from an order reaching
Cancelled or Rejected. That asymmetry between the two readers is real and is
stated here rather than discovered later.

**Categories are not validated.** They arrive title case — `"Fashion & Apparel"` —
and the dataset deliberately contains legacy spellings (`home & decor`), an
underscore variant (`home_&_living`) and values with no canonical equivalent
(`Casual Sneakers`). U06 and U08 exist to demonstrate mapping and dropping, so a
validator here would delete what they prove. Only a blank string is refused.

**A missing timestamp is `null`, not absent.** `if "timestamp" not in row` misses
every one of U10's rows. Check the value. Two of the drop-and-count cases depend
on catching this.

### One thing the row cannot tell you

**"Future" is measured against `ml_demo_meta.reference_date`, not the clock.**
U10's rows sit just ahead of it. An engine comparing against its own clock and
running a day late stops treating them as future, starts counting them, inflates
U10 and breaks the check.

Five on every row, seven in total. Both counts are correct and describe the same
contract.

---

## Three points that need explicit agreement

### 1. `categories` is plural, and an array

The task list says "category". It has to be `categories`, an array.

A post carrying several categories contributes **full weight to each**, not a
divided share — that is U03's entire purpose, and it's one of the narrated demo
users. A singular `category` field cannot express it. If the generator emits
singular, U03 needs a second code path, and a special case built to make a
demonstration work is a finding about the build, not a shortcut.

The array holds one element in the ordinary case, so this costs nothing.

### 2. A reversal is an `event_type`, not a flag

`purchase_reversal` is its own event type rather than a boolean on a purchase
row. That keeps the contract at seven fields, makes a row self-describing when
someone reads it in Atlas, and means the reversal cannot be created by accident
through a defaulted flag.

Its weight is the purchase weight **negated**, and it is aged from the **original
order's creation**, never from the cancellation — which is why `order_id` is
mandatory on it. A cancellation is always more recent than the order it cancels,
so it decays less, so it is always larger; aged from the cancellation the user
ends up below someone who never ordered and the raw goes negative.

The reversal is **not** P-07 negative feedback. P-07 is hide/report/skip and is 0
at launch; multiplying the reversal by it would zero the reversal silently.

### 3. `weight` is written and never read

The generator writes it so the data checks can do arithmetic a reader can follow.
The engine derives every weight from **P-06 keyed on `event_type`** and ignores
the field — `domain/events.Event` has nowhere to put it and forbids extra fields,
so an adapter cannot carry one through even by mistake.

If the engine read it, P-06 would stop being configuration: retuning a weight
would change no score, the config layer would be decorative, and nothing would
fail loudly to say so.

The one legitimate use is a check asserting the generator's belief matches P-06:
`DemoEventRow.expected_weight(tunables)` exists for exactly that.

---

## What must never appear in this collection

**A declared interest.** Signup picks are a statement of preference, not an
action. They carry no timestamp, contribute a constant floor of 10 (P-25), and
must never be written to the event stream — where Method A's decay term would
consume them. They live on the user record's `interest` array and nowhere else.

This is the single easiest thing in the build to get wrong (G6), so the generator
carries a test for it and `event_contract.is_declared_interest_row()` is there to
make the assertion cheap.

---

## The two sibling collections

The same profile switch moves the sources together. The generator writes three
collections -- there is no posts collection, because a generated event carries its
own categories and nothing is ever joined:

| Collection | Carries |
|---|---|
| `ml_demo_events` | This contract |
| `ml_demo_users` | `user_id`, `declared_interests` (array) — the P-25 floor source |
| `ml_demo_orders` | `order_id`, `placed_at`, `cancelled_at`, `status` — `placed_at` is the timestamp a reversal is aged from |
