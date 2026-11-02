import { describe, expect, it } from 'vitest';
import { buildGroupPinHtml, buildPlacePinHtml } from './mapPinHtml';

const base = {
  sequence: 2,
  entityId: 'visit-1',
  markerKind: 'visit_stop',
  mode: 'walk',
  color: '#D65F3D',
  endpoint: false,
  size: 30,
  content: '2',
  boxShadow: '0 3px 10px rgba(0,0,0,.22)',
  transform: 'scale(1)',
};

describe('buildPlacePinHtml', () => {
  it('renders the expected marker dataset and text', () => {
    const html = buildPlacePinHtml(base);
    expect(html).toContain('data-bundle-map-marker="2"');
    expect(html).toContain('data-bundle-map-entity="visit-1"');
    expect(html).toContain('data-bundle-map-kind="visit_stop"');
    expect(html).toContain('>2</span>');
  });

  it('escapes every interpolated value', () => {
    const html = buildPlacePinHtml({
      ...base,
      entityId: 'x" onmouseover="alert(1)',
      markerKind: '<b>kind</b>',
      mode: 'walk" onfocus="x',
      color: '#fff" onload="x',
      content: '<script>alert(1)</script>',
    });
    expect(html).not.toContain('data-bundle-map-entity="x" onmouseover=');
    expect(html).not.toContain('<b>');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&quot;');
    expect(html).toContain('&lt;');
  });
});

describe('buildGroupPinHtml', () => {
  it('escapes the group id and renders the count', () => {
    const html = buildGroupPinHtml({ groupId: 'g" onmouseover="x', color: '#D65F3D', count: 3 });
    expect(html).toContain('data-bundle-map-group="g&quot; onmouseover=&quot;x"');
    expect(html).toContain('>3</span>');
  });
});
