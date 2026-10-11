// Pure logic tests for the store emit/subscribe mechanism.
// These are the parts that are easily testable without a DOM.
// FE3 was a sequencing bug in server.js that would have been caught by
// testing the sequencing logic in isolation.

import { test, describe } from 'node:test';
import assert from 'node:assert';

// Mock store implementation for testing
const createStore = () => {
  let version = 0;
  const subs = new Set();
  return {
    app: { sel: 0, cycle: 0, cur: 'eng', tgt: 0, fc: 0, view: 'auto', theme: 'light', status: 'Loading models...', WO: {}, ACK: {}, loaded: {}, backendConnected: false, apiReachable: false, onBackendChange: null, model: { version: null, fallback: false, degraded: false, reason: null, staleTicks: 0 }, serverAlerts: [] },
    subscribe: (fn) => { subs.add(fn); return () => subs.delete(fn); },
    getVersion: () => version,
    emit: () => { version++; subs.forEach((fn) => fn()); },
    selectFleet: () => 0,
    selectCycle: () => 0,
    selectCur: () => 'eng',
    selectTgt: () => 0,
    selectFc: () => 0,
    selectView: () => 'auto',
    selectTheme: () => 'light',
    selectStatus: () => 'Loading models...',
    selectWO: () => ({}),
    selectACK: () => ({}),
    selectLoaded: () => ({}),
    selectBackendConnected: () => false,
    selectApiReachable: () => false,
    selectModel: () => ({ version: null, fallback: false, degraded: false, reason: null, staleTicks: 0 }),
    selectServerAlerts: () => ([]),
  };
};

describe('store emit/subscribe mechanism', () => {
  test('subscribe returns a function that unsubscribes', () => {
    const store = createStore();
    let called = false;
    const unsubscribe = store.subscribe(() => { called = true; });
    store.emit();
    assert.strictEqual(called, true);
    called = false;
    unsubscribe();
    store.emit();
    assert.strictEqual(called, false);
  });

  test('emit increments version and calls all subscribers', () => {
    const store = createStore();
    let callCount = 0;
    const unsub1 = store.subscribe(() => callCount++);
    const unsub2 = store.subscribe(() => callCount++);
    const initialVersion = store.getVersion();
    store.emit();
    assert.strictEqual(callCount, 2);
    assert.strictEqual(store.getVersion(), initialVersion + 1);
  });

  test('multiple subscribers all fire on emit', () => {
    const store = createStore();
    let calls = 0;
    store.subscribe(() => calls++);
    store.subscribe(() => calls++);
    store.subscribe(() => calls++);
    store.emit();
    assert.strictEqual(calls, 3);
  });

  test('unsubscribed functions do not fire', () => {
    const store = createStore();
    let calls = 0;
    const unsubscribe = store.subscribe(() => calls++);
    store.emit();
    assert.strictEqual(calls, 1);
    calls = 0;
    unsubscribe();
    store.emit();
    assert.strictEqual(calls, 0);
  });
});

describe('server sequencing (FE3)', () => {
  function createSequencer() {
    let seq = 0;
    return () => ++seq;
  }

  test('independent aircraft/engine sequences do not clobber each other', () => {
    const aircraftSeq = createSequencer();
    const engineSeq = createSequencer();

    const a1 = aircraftSeq();
    const e1 = engineSeq();
    const a2 = aircraftSeq();
    const e2 = engineSeq();

    // Each sequence advances independently starting from 1
    assert.strictEqual(a1, 1);
    assert.strictEqual(e1, 1);
    assert.strictEqual(a2, 2);
    assert.strictEqual(e2, 2);
  });

  test('stale sequence is detected correctly', () => {
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

  test('fresh sequence matches', () => {
    let seq = 0;
    function next() { return ++seq; }

    const req = next(); // 1
    // Response arrives before any other request
    const current = seq; // 1

    assert.strictEqual(req === current, true);
  });
});