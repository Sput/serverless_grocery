// Pure helpers shared by UI and tests. Source duplicate rows remain duplicate rows.
export function costcoGroups(items, costco, impromptu) {
  const zoneByName = new Map(items.map(item => [item.name.trim(), item.zone]));
  const groups = new Map([[1, []], [2, []], [3, []], [4, []], ['Impromptu', []]]);
  for (const name of [...costco.map(row => row.items.trim()), ...impromptu.map(row => row.name.trim())]) {
    const zone = zoneByName.get(name);
    groups.get([1, 2, 3, 4].includes(zone) ? zone : 'Impromptu').push(name);
  }
  return groups;
}

export function batches(values, size = 90) {
  const result = [];
  for (let i = 0; i < values.length; i += size) result.push(values.slice(i, i + size));
  return result;
}

export function utcToday() {
  return new Date().toISOString().slice(0, 10);
}
