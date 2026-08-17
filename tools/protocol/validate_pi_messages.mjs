// Validate NeoMind's pi-protocol messages against pi's own TypeBox schemas.
//
// Run from inside a pi-mono clone; the samples file comes from
// `tools/protocol/emit_pi_samples.py`. Both paths are arguments rather than
// constants: the first version of this script carried an absolute path from
// the machine it was written on, which is exactly what the pre-push scan is
// there to catch.
//
//   node --experimental-strip-types validate_pi_messages.mjs <samples.json>
import { Value } from "typebox/value";
import * as S from "./packages/protocol/src/schemas.ts";
import { readFileSync } from "node:fs";

const samplesPath = process.argv[2];
if (!samplesPath) {
  console.error("usage: validate_pi_messages.mjs <samples.json>");
  process.exit(2);
}
const samples = JSON.parse(readFileSync(samplesPath, "utf8"));

const checks = [
  ["ServerHello", S.ServerHelloSchema],
  ["ServerSnapshot", S.ServerSnapshotSchema],
  ["SessionSnapshot", S.SessionSnapshotSchema],
  ["TranscriptProgress_text", S.TranscriptProgressSchema],
  ["TranscriptProgress_thinking", S.TranscriptProgressSchema],
  ["TranscriptProgress_started", S.TranscriptProgressSchema],
  ["TranscriptProgress_running", S.TranscriptProgressSchema],
  ["TranscriptProgress_finished", S.TranscriptProgressSchema],
];

let failed = 0;
for (const [name, schema] of checks) {
  const sample = samples[name];
  if (sample === undefined) {
    console.log(`  ? ${name} — not in samples`);
    failed++;
    continue;
  }
  let ok = false;
  let errors = [];
  try {
    ok = Value.Check(schema, sample);
    if (!ok) errors = [...Value.Errors(schema, sample)].slice(0, 4);
  } catch (e) {
    errors = [{ path: "(validator)", message: e.message }];
  }
  console.log(`  ${ok ? "✓" : "✗"} ${name}`);
  for (const e of errors) console.log(`      ${e.path}: ${e.message}`);
  if (!ok) failed++;
}
process.exit(failed ? 1 : 0);
