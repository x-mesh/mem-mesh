/**
 * Simple Test Runner for Web Components
 * Lightweight testing framework for client-side component testing
 */

export class TestRunner {
  constructor() {
    this.tests = [];
    this.suites = new Map();
    this.results = {
      passed: 0,
      failed: 0,
      skipped: 0,
      total: 0
    };
    this.currentSuite = null;
  }
  
  /**
   * Create a test suite
   */
  describe(name, callback) {
    const suite = {
      name,
      tests: [],
      beforeEach: null,
      afterEach: null,
      beforeAll: null,
      afterAll: null
    };
    
    this.suites.set(name, suite);
    this.currentSuite = suite;
    
    // Execute suite definition
    callback();
    
    this.currentSuite = null;
    return suite;
  }
  
  /**
   * Define a test case
   */
  it(description, testFn, options = {}) {
    const test = {
      description,
      testFn,
      suite: this.currentSuite?.name || 'default',
      skip: options.skip || false,
      timeout: options.timeout || 5000,
      status: 'pending',
      error: null,
      duration: 0
    };
    
    if (this.currentSuite) {
      this.currentSuite.tests.push(test);
    } else {
      this.tests.push(test);
    }
    
    return test;
  }
  
  /**
   * Skip a test
   */
  xit(description, testFn, options = {}) {
    return this.it(description, testFn, { ...options, skip: true });
  }
  
  /**
   * Setup before each test in suite
   */
  beforeEach(callback) {
    if (this.currentSuite) {
      this.currentSuite.beforeEach = callback;
    }
  }
  
  /**
   * Setup after each test in suite
   */
  afterEach(callback) {
    if (this.currentSuite) {
      this.currentSuite.afterEach = callback;
    }
  }
  
  /**
   * Setup before all tests in suite
   */
  beforeAll(callback) {
    if (this.currentSuite) {
      this.currentSuite.beforeAll = callback;
    }
  }
  
  /**
   * Setup after all tests in suite
   */
  afterAll(callback) {
    if (this.currentSuite) {
      this.currentSuite.afterAll = callback;
    }
  }
  
  /**
   * Run all tests
   */
  async run() {
    console.log('🧪 Starting test run...\n');
    
    this.results = { passed: 0, failed: 0, skipped: 0, total: 0 };
    
    // Run standalone tests
    if (this.tests.length > 0) {
      await this.runTests(this.tests, 'Standalone Tests');
    }
    
    // Run test suites
    for (const [suiteName, suite] of this.suites) {
      await this.runSuite(suite);
    }
    
    this.printSummary();
    return this.results;
  }
  
  /**
   * Run a test suite
   */
  async runSuite(suite) {
    console.log(`📁 ${suite.name}`);
    
    // Run beforeAll
    if (suite.beforeAll) {
      try {
        await suite.beforeAll();
      } catch (error) {
        console.error(`❌ beforeAll failed in ${suite.name}:`, error);
        return;
      }
    }
    
    // Run tests
    await this.runTests(suite.tests, suite.name, suite);
    
    // Run afterAll
    if (suite.afterAll) {
      try {
        await suite.afterAll();
      } catch (error) {
        console.error(`❌ afterAll failed in ${suite.name}:`, error);
      }
    }
    
    console.log('');
  }
  
  /**
   * Run a list of tests
   */
  async runTests(tests, suiteName, suite = null) {
    for (const test of tests) {
      await this.runTest(test, suite);
    }
  }
  
  /**
   * Run a single test
   */
  async runTest(test, suite = null) {
    this.results.total++;
    
    if (test.skip) {
      test.status = 'skipped';
      this.results.skipped++;
      console.log(`  ⏭️  ${test.description} (skipped)`);
      return;
    }
    
    const startTime = performance.now();
    
    try {
      // Run beforeEach
      if (suite?.beforeEach) {
        await suite.beforeEach();
      }
      
      // Run test with timeout
      await this.runWithTimeout(test.testFn, test.timeout);
      
      // Run afterEach
      if (suite?.afterEach) {
        await suite.afterEach();
      }
      
      test.status = 'passed';
      test.duration = performance.now() - startTime;
      this.results.passed++;
      
      console.log(`  ✅ ${test.description} (${Math.round(test.duration)}ms)`);
      
    } catch (error) {
      test.status = 'failed';
      test.error = error;
      test.duration = performance.now() - startTime;
      this.results.failed++;
      
      console.log(`  ❌ ${test.description}`);
      console.log(`     ${error.message}`);
      if (error.stack) {
        console.log(`     ${error.stack.split('\n')[1]?.trim()}`);
      }
    }
  }
  
  /**
   * Run function with timeout
   */
  async runWithTimeout(fn, timeout) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`Test timed out after ${timeout}ms`));
      }, timeout);
      
      Promise.resolve(fn())
        .then(resolve)
        .catch(reject)
        .finally(() => clearTimeout(timer));
    });
  }
  
  /**
   * Print test summary
   */
  printSummary() {
    console.log('📊 Test Results:');
    console.log(`   Total: ${this.results.total}`);
    console.log(`   ✅ Passed: ${this.results.passed}`);
    console.log(`   ❌ Failed: ${this.results.failed}`);
    console.log(`   ⏭️  Skipped: ${this.results.skipped}`);
    
    const successRate = this.results.total > 0 
      ? Math.round((this.results.passed / this.results.total) * 100)
      : 0;
    
    console.log(`   📈 Success Rate: ${successRate}%`);
    
    if (this.results.failed === 0) {
      console.log('\n🎉 All tests passed!');
    } else {
      console.log(`\n💥 ${this.results.failed} test(s) failed`);
    }
  }
}

/**
 * Assertion utilities
 */
export class Expect {
  constructor(actual) {
    this.actual = actual;
    this.isNot = false;
  }
  
  get not() {
    this.isNot = true;
    return this;
  }
  
  toBe(expected) {
    const result = Object.is(this.actual, expected);
    if (this.isNot ? result : !result) {
      throw new Error(`Expected ${this.actual} ${this.isNot ? 'not ' : ''}to be ${expected}`);
    }
    return this;
  }
  
  toEqual(expected) {
    const result = JSON.stringify(this.actual) === JSON.stringify(expected);
    if (this.isNot ? result : !result) {
      throw new Error(`Expected ${JSON.stringify(this.actual)} ${this.isNot ? 'not ' : ''}to equal ${JSON.stringify(expected)}`);
    }
    return this;
  }
  
  toBeTruthy() {
    const result = Boolean(this.actual);
    if (this.isNot ? result : !result) {
      throw new Error(`Expected ${this.actual} ${this.isNot ? 'not ' : ''}to be truthy`);
    }
    return this;
  }
  
  toBeFalsy() {
    const result = !Boolean(this.actual);
    if (this.isNot ? result : !result) {
      throw new Error(`Expected ${this.actual} ${this.isNot ? 'not ' : ''}to be falsy`);
    }
    return this;
  }
  
  toContain(expected) {
    const result = this.actual && this.actual.includes && this.actual.includes(expected);
    if (this.isNot ? result : !result) {
      throw new Error(`Expected ${this.actual} ${this.isNot ? 'not ' : ''}to contain ${expected}`);
    }
    return this;
  }
  
  toHaveLength(expected) {
    const result = this.actual && this.actual.length === expected;
    if (this.isNot ? result : !result) {
      throw new Error(`Expected ${this.actual} ${this.isNot ? 'not ' : ''}to have length ${expected}, but got ${this.actual?.length}`);
    }
    return this;
  }
  
  toBeInstanceOf(expected) {
    const result = this.actual instanceof expected;
    if (this.isNot ? result : !result) {
      throw new Error(`Expected ${this.actual} ${this.isNot ? 'not ' : ''}to be instance of ${expected.name}`);
    }
    return this;
  }
  
  toThrow(expectedError) {
    let threw = false;
    let error = null;
    
    try {
      if (typeof this.actual === 'function') {
        this.actual();
      }
    } catch (e) {
      threw = true;
      error = e;
    }
    
    if (this.isNot) {
      if (threw) {
        throw new Error(`Expected function not to throw, but it threw: ${error.message}`);
      }
    } else {
      if (!threw) {
        throw new Error('Expected function to throw, but it did not');
      }
      
      if (expectedError && !error.message.includes(expectedError)) {
        throw new Error(`Expected function to throw "${expectedError}", but it threw: ${error.message}`);
      }
    }
    
    return this;
  }
}

/**
 * Global test functions
 */
export function expect(actual) {
  return new Expect(actual);
}

/**
 * Mock utilities
 */
export class Mock {
  constructor(implementation) {
    this.calls = [];
    this.results = [];
    this.implementation = implementation;
  }
  
  mockImplementation(fn) {
    this.implementation = fn;
    return this;
  }
  
  mockReturnValue(value) {
    this.implementation = () => value;
    return this;
  }
  
  mockResolvedValue(value) {
    this.implementation = () => Promise.resolve(value);
    return this;
  }
  
  mockRejectedValue(error) {
    this.implementation = () => Promise.reject(error);
    return this;
  }
  
  __call(...args) {
    this.calls.push(args);
    
    try {
      const result = this.implementation ? this.implementation(...args) : undefined;
      this.results.push({ type: 'return', value: result });
      return result;
    } catch (error) {
      this.results.push({ type: 'throw', value: error });
      throw error;
    }
  }
  
  toHaveBeenCalled() {
    if (this.calls.length === 0) {
      throw new Error('Expected mock to have been called, but it was not called');
    }
    return this;
  }
  
  toHaveBeenCalledTimes(times) {
    if (this.calls.length !== times) {
      throw new Error(`Expected mock to have been called ${times} times, but it was called ${this.calls.length} times`);
    }
    return this;
  }
  
  toHaveBeenCalledWith(...args) {
    const found = this.calls.some(call => 
      call.length === args.length && 
      call.every((arg, index) => Object.is(arg, args[index]))
    );
    
    if (!found) {
      throw new Error(`Expected mock to have been called with ${JSON.stringify(args)}, but it was not`);
    }
    return this;
  }
  
  clear() {
    this.calls = [];
    this.results = [];
    return this;
  }
}

export function createMock(implementation) {
  const mock = new Mock(implementation);
  const mockFn = (...args) => mock.__call(...args);
  
  // Copy mock methods to function
  Object.setPrototypeOf(mockFn, mock);
  Object.assign(mockFn, mock);
  
  return mockFn;
}

/**
 * DOM testing utilities
 */
export class DOMTestUtils {
  static createElement(tagName, attributes = {}, textContent = '') {
    const element = document.createElement(tagName);
    
    Object.entries(attributes).forEach(([key, value]) => {
      element.setAttribute(key, value);
    });
    
    if (textContent) {
      element.textContent = textContent;
    }
    
    return element;
  }
  
  static createComponent(tagName, attributes = {}) {
    const element = document.createElement(tagName);
    
    Object.entries(attributes).forEach(([key, value]) => {
      element.setAttribute(key, value);
    });
    
    document.body.appendChild(element);
    
    // Wait for component to initialize
    return new Promise(resolve => {
      if (element.connectedCallback) {
        setTimeout(() => resolve(element), 0);
      } else {
        resolve(element);
      }
    });
  }
  
  static cleanup() {
    // Remove all test elements
    const testElements = document.querySelectorAll('[data-test]');
    testElements.forEach(el => el.remove());
    
    // Clear any test containers
    const containers = document.querySelectorAll('.test-container');
    containers.forEach(container => container.remove());
  }
  
  static fireEvent(element, eventType, eventInit = {}) {
    const event = new Event(eventType, { bubbles: true, cancelable: true, ...eventInit });
    element.dispatchEvent(event);
    return event;
  }
  
  static async waitFor(callback, options = {}) {
    const { timeout = 1000, interval = 50 } = options;
    const startTime = Date.now();
    
    while (Date.now() - startTime < timeout) {
      try {
        const result = callback();
        if (result) return result;
      } catch (error) {
        // Continue waiting
      }
      
      await new Promise(resolve => setTimeout(resolve, interval));
    }
    
    throw new Error(`waitFor timed out after ${timeout}ms`);
  }
}

// Create global test runner instance
export const testRunner = new TestRunner();

// Export global functions
export const { describe, it, xit, beforeEach, afterEach, beforeAll, afterAll } = testRunner;