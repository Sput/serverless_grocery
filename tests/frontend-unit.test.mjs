import test from 'node:test';
import assert from 'node:assert/strict';
import { batches, costcoGroups, utcToday } from '../frontend/logic.js';

test('Costco includes all active impromptu rows and retains duplicates', () => {
  const groups = costcoGroups([{ name: 'Eggs', zone: 3 }], [{ items: 'Eggs' }], [{ name: 'Eggs' }, { name: 'New food' }]);
  assert.deepEqual(groups.get(3), ['Eggs', 'Eggs']);
  assert.deepEqual(groups.get('Impromptu'), ['New food']);
});
test('large selections are bounded to DynamoDB transaction limits', () => {
  const values = Array.from({ length: 181 }, (_, i) => i);
  assert.deepEqual(batches(values).map(batch => batch.length), [90, 90, 1]);
  assert.deepEqual(batches(values).flat(), values);
});
test('meal today preserves source UTC date behavior', () => {
  assert.equal(utcToday(), new Date().toISOString().slice(0, 10));
});
