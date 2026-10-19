const {test}=require('node:test');
const assert=require('node:assert/strict');
const {activityDateRange}=require('../../src/fravenir/admin/static/activity.js');
test('inclusive local dates convert to a half-open UTC interval',()=>{
  const result=activityDateRange('2026-10-15','2026-10-16');
  assert.equal(new Date(result.start).getTime(),new Date(2026,9,15).getTime());
  assert.equal(new Date(result.end).getTime(),new Date(2026,9,17).getTime());
});
test('empty and single-ended dates stay open; reversed dates fail',()=>{
  assert.deepEqual(activityDateRange('',''),{});
  assert.equal(Object.keys(activityDateRange('2026-10-15','')).length,1);
  assert.throws(()=>activityDateRange('2026-10-16','2026-10-15'));
});
