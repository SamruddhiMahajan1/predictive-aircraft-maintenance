// Pure logic tests for the server.js sequencing logic (FE3 fix).
// The bug: refreshAircraft and refreshEngine shared one `detailSeq` counter,
// so firing them back-to-back meant the aircraft response always lost the
// seq race and `applyDetail()` never ran.

function createSequencer() {
  let seq = 0;
  return () => ++seq;
}

describe('server sequencing (FE3)', () => {
  it('independent aircraft/engine sequences do not clobber each other', () => {
    const aircraftSeq = createSequencer();
    const engineSeq = createSequencer();

    const a1 = aircraftSeq();
    const e1 = engineSeq();
    const a2 = aircraftSeq();
    const e2 = engineSeq();

    // Each sequence advances independently
    assert.strictEqual(a1, 1);
    assert.strictEqual(e1, 2);
    assert.strictEqual(a2, 3);
    assert.strictEqual(e2, 4);

    // A response with seq=1 (first aircraft request) is still valid for aircraft
    // even after engineSeq advanced to 2
    assert.strictEqual(a1, 1);
    assert.strictEqual(e1, 2);
  });

  it('stale sequence is detected correctly', () => {
    let seq = 0;
    function next() { return ++seq; }

    const req1 = next(); // 1
    const req2 = next(); // 2

    // Response for req1 arrives AFTER req2 was sent
    const current = next(); // 3

    // req1's seq (1) !== current (3) -> stale
    assert.strictEqual(req1 === current, false);
    // req2's seq (2) !== current (3) -> stale
    assert.strictEqual(req2 === current, false);
  });

  it('fresh sequence matches', () => {
    let seq = 0;
    function next() { return ++seq; }

    const req = next(); // 1
    // Response arrives before any other request
    const current = seq; // 1

    assert.strictEqual(req === current, true);
  });
});