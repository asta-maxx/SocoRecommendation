/**
 * SOCO M1 — score store setup.  RE-02.
 *
 * Creates ml_user_interest_scores, its two indexes, and a schema validator that
 * enforces the four metadata fields at the DATABASE level — so a write from any
 * client, not only from the Python engine, is rejected without them.
 *
 * Idempotent. Safe to run more than once.
 *
 *   mongosh "<connection string>" scripts/setup_ml_collections.js
 *
 * The collection name is a parameter, matching the Python side where it is
 * configuration rather than a constant. Override it for the demo store:
 *
 *   mongosh "<uri>" --eval 'var SCORES_COLLECTION="ml_demo_user_interest_scores"' \
 *           scripts/setup_ml_collections.js
 *
 * Creating the ml_-scoped write user is a SEPARATE step and is not done here,
 * because it needs admin privileges this script should not assume. See HANDOFF.md.
 */

const COLLECTION =
  typeof SCORES_COLLECTION !== "undefined" ? SCORES_COLLECTION : "ml_user_interest_scores";

if (!COLLECTION.startsWith("ml_")) {
  throw new Error(
    `refusing to create ${COLLECTION}: scores live only in the ml_ namespace`
  );
}

const METHODS = ["A_recency_decay", "B_time_windows"];
const WINDOWS = ["all", "90d"];

const validator = {
  $jsonSchema: {
    bsonType: "object",
    title: "M1 interest score — one document per user per category",
    required: [
      "user_id",
      "category",
      "raw",
      "share",
      "event_count",
      // The four metadata fields. Not optional. Without them two methods
      // writing to one store are indistinguishable and no comparison between
      // them can be reconstructed afterwards.
      "method",
      "model_version",
      "window",
      "computed_at",
    ],
    additionalProperties: false,
    properties: {
      _id: {},
      user_id: {
        bsonType: "string",
        description: "SOCO user id, as text. Text form so it round-trips through JSON.",
      },
      category: {
        bsonType: "string",
        description:
          "A toCategoryKey() key: lowercase, trimmed, spaces preserved, no underscores. " +
          "e.g. 'fashion & apparel'. Not constrained to the canonical 23 here — the " +
          "vocabulary lives in categories.js and must not be duplicated into a validator.",
      },
      raw: {
        bsonType: "double",
        minimum: 0,
        description:
          "The weighted sum. Unbounded and not comparable between users; diagnostics only. " +
          "Cannot be negative: a purchase reversal aged from the original order exactly " +
          "cancels the purchase. If a negative appears, the reversal is being aged from " +
          "the cancellation instead.",
      },
      share: {
        bsonType: "double",
        minimum: 0,
        maximum: 1,
        description:
          "raw divided by the user's total raw across all categories. Sums to 1 per " +
          "(user, method, model_version). THIS is what downstream consumers read.",
      },
      event_count: {
        bsonType: "int",
        minimum: 0,
        description: "How many qualifying events contributed. Diagnostics.",
      },
      method: {
        enum: METHODS,
        description:
          "Which method produced this score. Part of the unique key, so both methods " +
          "coexist for the same user and category rather than overwriting each other.",
      },
      model_version: {
        bsonType: "string",
        description:
          "Configuration/model generation. Part of the unique key, so a rerun after a " +
          "parameter change creates a new generation rather than destroying the old one.",
      },
      window: {
        enum: WINDOWS,
        description:
          "The window the score was computed over. 'all' for Method A, whose decay has " +
          "no hard cutoff; '90d' for Method B, which discards anything older.",
      },
      computed_at: {
        bsonType: "date",
        description:
          "UTC. Drives the P-08 staleness check on rung 4 of the fallback ladder.",
      },
    },
  },
};

const existing = db.getCollectionNames();

if (existing.indexOf(COLLECTION) === -1) {
  db.createCollection(COLLECTION, { validator, validationLevel: "strict", validationAction: "error" });
  print(`created ${COLLECTION} with schema validation`);
} else {
  db.runCommand({
    collMod: COLLECTION,
    validator,
    validationLevel: "strict",
    validationAction: "error",
  });
  print(`${COLLECTION} already existed — validator updated`);
}

// Unique identity of a score. Method and model_version are part of it on purpose.
db.getCollection(COLLECTION).createIndex(
  { user_id: 1, category: 1, method: 1, model_version: 1 },
  { unique: true, name: "uniq_user_category_method_version" }
);

// The read path filters by user and method, then needs computed_at for P-08.
db.getCollection(COLLECTION).createIndex(
  { user_id: 1, method: 1, computed_at: -1 },
  { name: "user_method_recency" }
);

print("indexes:");
db.getCollection(COLLECTION)
  .getIndexes()
  .forEach((ix) => print(`  ${ix.name}  ${JSON.stringify(ix.key)}${ix.unique ? "  UNIQUE" : ""}`));

print("");
print("Done. Next: create the ml_-scoped write user — see HANDOFF.md §3.");
