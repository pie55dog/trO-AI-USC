import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView. Welcome scrolls to the first
// invalid field in a requestAnimationFrame, which can fire after a test ends
// and fail the run, so give it a no-op here.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
