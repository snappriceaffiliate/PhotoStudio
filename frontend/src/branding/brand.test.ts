import { describe, expect, it } from 'vitest';
import { brandStyle, contrastWithWhite, isHexColour } from './brand';

describe('branding colours', () => {
  it('matches the server contrast rule', () => {
    expect(contrastWithWhite('#0E5E5A')).toBeGreaterThan(4.5);
    expect(contrastWithWhite('#E89A1C')).toBeLessThan(4.5);
    expect(contrastWithWhite('#000000')).toBeCloseTo(21, 0);
  });

  it('only passes real hex colours to the stylesheet', () => {
    expect(isHexColour('#8a1c3b')).toBe(true);
    expect(isHexColour('red')).toBe(false);
    expect(brandStyle('#8A1C3B')).toEqual({ '--brand-accent': '#8A1C3B' });
    expect(brandStyle('url(x)')).toBeUndefined();
    expect(brandStyle(null)).toBeUndefined();
  });
});
