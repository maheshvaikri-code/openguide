import "@testing-library/jest-dom/vitest";

// jsdom has no canvas. Return null (as real browsers do when a context is unavailable) so
// components fall back to their text equivalents without noisy "not implemented" warnings.
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];
